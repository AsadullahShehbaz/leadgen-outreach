import base64
import json
import re
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy import func

from app.core.config import settings
from app.models import Lead, LicenseState, Mailbox


GRACE_PERIOD = timedelta(days=14)
BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")


class InvalidLicense(ValueError):
    pass


class LicenseClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: StrictStr = Field(min_length=1)
    plan: StrictStr = Field(min_length=1)
    max_mailboxes: StrictInt = Field(gt=0)
    max_leads_per_month: StrictInt = Field(gt=0)
    expires_at: datetime
    features: list[StrictStr]


class LicenseStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    in_grace: bool = False
    expires_at: datetime | None = None
    reason: str
    customer: str | None = None
    plan: str | None = None
    max_mailboxes: int | None = None
    max_leads_per_month: int | None = None
    features: list[str] = Field(default_factory=list)


def _decode_base64url(value: str) -> bytes:
    if not BASE64URL_RE.fullmatch(value):
        raise InvalidLicense("Invalid base64url encoding")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, base64.binascii.Error) as exc:
        raise InvalidLicense("Invalid base64url encoding") from exc


def _json_object(payload: bytes) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidLicense("Duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except InvalidLicense:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidLicense("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise InvalidLicense("License payload must be a JSON object")
    return value


def _utc_now(value: datetime | None) -> datetime:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_expiry(value: object) -> datetime:
    if not isinstance(value, str):
        raise InvalidLicense("expires_at must be an RFC 3339 UTC timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidLicense("expires_at must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise InvalidLicense("expires_at must use UTC")
    return parsed.astimezone(timezone.utc)


def verify_license_token(
    token: str,
    public_key_pem: str,
    now: datetime | None = None,
) -> LicenseStatus:
    current = _utc_now(now)
    if not isinstance(token, str) or not token.strip():
        return LicenseStatus(valid=False, reason="License is missing")
    if not isinstance(public_key_pem, str) or not public_key_pem.strip():
        return LicenseStatus(valid=False, reason="License public key is missing")

    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise InvalidLicense("License token must have three parts")
        header_bytes = _decode_base64url(parts[0])
        payload_bytes = _decode_base64url(parts[1])
        signature = _decode_base64url(parts[2])

        header = _json_object(header_bytes)
        if header.get("alg") != "EdDSA":
            raise InvalidLicense("License algorithm must be EdDSA")
        if "crit" in header:
            raise InvalidLicense("Critical license headers are not supported")

        payload = _json_object(payload_bytes)
        payload["expires_at"] = _parse_expiry(payload.get("expires_at"))
        claims = LicenseClaims.model_validate(payload)

        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            raise InvalidLicense("License public key must be Ed25519")
        public_key.verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"))
    except InvalidLicense as exc:
        return LicenseStatus(valid=False, reason=str(exc))
    except (InvalidSignature, ValueError, TypeError, UnicodeEncodeError) as exc:
        return LicenseStatus(valid=False, reason="License signature or payload is invalid")

    if current <= claims.expires_at:
        return LicenseStatus(
            valid=True,
            in_grace=False,
            expires_at=claims.expires_at,
            reason="License is valid",
            customer=claims.customer,
            plan=claims.plan,
            max_mailboxes=claims.max_mailboxes,
            max_leads_per_month=claims.max_leads_per_month,
            features=claims.features,
        )

    if current <= claims.expires_at + GRACE_PERIOD:
        return LicenseStatus(
            valid=True,
            in_grace=True,
            expires_at=claims.expires_at,
            reason="License is in the 14-day grace period",
            customer=claims.customer,
            plan=claims.plan,
            max_mailboxes=claims.max_mailboxes,
            max_leads_per_month=claims.max_leads_per_month,
            features=claims.features,
        )

    return LicenseStatus(
        valid=False,
        in_grace=False,
        expires_at=claims.expires_at,
        reason="License is expired",
        customer=claims.customer,
        plan=claims.plan,
        max_mailboxes=claims.max_mailboxes,
        max_leads_per_month=claims.max_leads_per_month,
        features=claims.features,
    )


async def get_license_status(
    db,
    now: datetime | None = None,
    public_key_pem: str | None = None,
) -> LicenseStatus:
    result = await db.exec(
        select(LicenseState).order_by(LicenseState.created_at.desc()).limit(1)
    )
    state = result.first()
    if state is None:
        return LicenseStatus(valid=False, reason="License is missing")
    key = public_key_pem if public_key_pem is not None else settings.LICENSE_PUBLIC_KEY_PEM
    if not key:
        return LicenseStatus(valid=False, reason="License public key is missing")
    try:
        return verify_license_token(state.token, key, now)
    except (InvalidLicense, ValueError):
        return LicenseStatus(valid=False, reason="License is invalid")


async def refresh_license_state(
    db,
    token: str,
    public_key_pem: str,
    now: datetime | None = None,
) -> LicenseStatus:
    try:
        status = verify_license_token(token, public_key_pem, now)
    except InvalidLicense as exc:
        raise

    result = await db.exec(
        select(LicenseState).order_by(LicenseState.created_at.desc()).limit(1)
    )
    state = result.first()
    if state is None:
        state = LicenseState(token=token)
    else:
        state.token = token
    state.valid_until = status.expires_at if status.valid else None
    state.last_checked_at = _utc_now(now)
    db.add(state)
    await db.commit()
    return status


async def license_allows_sending(
    db,
    now: datetime | None = None,
) -> bool:
    status = await get_license_status(db, now=now)
    return status.valid


async def license_allows_sourcing(
    db,
    now: datetime | None = None,
    workspace_id=None,
    additional_leads: int = 0,
) -> bool:
    status = await get_license_status(db, now=now)
    if not status.valid:
        return False
    if workspace_id is None or additional_leads <= 0:
        return True

    current = _utc_now(now)
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.exec(
        select(func.count(Lead.id)).where(
            Lead.workspace_id == workspace_id,
            Lead.collected_at >= month_start,
            Lead.collected_at <= current,
        )
    )
    used = int(result.one())
    return used + additional_leads <= int(status.max_leads_per_month or 0)


async def check_mailbox_limit(
    db,
    workspace_id,
    now: datetime | None = None,
    additional: int = 1,
) -> bool:
    status = await get_license_status(db, now=now)
    if not status.valid:
        return False
    result = await db.exec(
        select(func.count(Mailbox.id)).where(Mailbox.workspace_id == workspace_id)
    )
    current = int(result.one())
    return current + additional <= int(status.max_mailboxes or 0)
