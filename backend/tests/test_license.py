import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.services.license.license import (
    InvalidLicense,
    LicenseClaims,
    verify_license_token,
)


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def make_license(now: datetime | None = None, **changes) -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    current = now or datetime.now(timezone.utc)
    payload = {
        "customer": "customer-1",
        "plan": "starter",
        "max_mailboxes": 5,
        "max_leads_per_month": 1000,
        "expires_at": (current + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "features": ["sourcing", "personalization"],
    }
    payload.update(changes)
    header = b64(json.dumps({"alg": "EdDSA"}, separators=(",", ":")).encode())
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = b64(private_key.sign(signing_input))
    return f"{header}.{body}.{signature}", public_key


def test_valid_ed25519_license():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    token, public_key = make_license(now)

    status = verify_license_token(token, public_key, now)

    assert status.valid is True
    assert status.in_grace is False
    assert status.customer == "customer-1"
    assert status.max_mailboxes == 5


def test_tampered_payload_is_invalid():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    token, public_key = make_license(now)
    header, body, signature = token.split(".")
    tampered = f"{header}.{body[:-1]}A.{signature}"

    status = verify_license_token(tampered, public_key, now)

    assert status.valid is False


def test_wrong_public_key_is_invalid():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    token, _ = make_license(now)
    private_key = Ed25519PrivateKey.generate()
    wrong_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    status = verify_license_token(token, wrong_key, now)

    assert status.valid is False


def test_missing_public_key_is_invalid():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    token, _ = make_license(now)

    status = verify_license_token(token, "", now)

    assert status.valid is False
    assert status.reason == "License public key is missing"


def test_expired_license_enters_and_leaves_grace():
    expires = datetime(2026, 11, 1, tzinfo=timezone.utc)
    token, public_key = make_license(expires_at=expires.isoformat().replace("+00:00", "Z"))

    in_grace = verify_license_token(
        token,
        public_key,
        datetime(2026, 11, 14, tzinfo=timezone.utc),
    )
    expired = verify_license_token(
        token,
        public_key,
        datetime(2026, 11, 16, tzinfo=timezone.utc),
    )

    assert in_grace.valid is True
    assert in_grace.in_grace is True
    assert expired.valid is False
    assert expired.reason == "License is expired"


def test_grace_exactly_14_days_is_allowed():
    expires = datetime(2026, 11, 1, tzinfo=timezone.utc)
    token, public_key = make_license(expires_at=expires.isoformat().replace("+00:00", "Z"))

    status = verify_license_token(
        token,
        public_key,
        datetime(2026, 11, 15, tzinfo=timezone.utc),
    )

    assert status.valid is True
    assert status.in_grace is True


def test_wrong_algorithm_is_invalid():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    token, public_key = make_license(now)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    payload = {"alg": "HS256"}
    header = b64(json.dumps(payload).encode())
    parts = token.split(".")
    tampered = f"{header}.{parts[1]}.{parts[2]}"

    status = verify_license_token(tampered, public_key, now)

    assert status.valid is False


def test_claim_model_rejects_boolean_integer():
    with pytest.raises(ValidationError):
        LicenseClaims(
            customer="customer",
            plan="starter",
            max_mailboxes=True,
            max_leads_per_month=10,
            expires_at=datetime.now(timezone.utc),
            features=["sourcing"],
        )


def test_malformed_three_part_token_returns_status_not_valid():
    status = verify_license_token("one.two.three", "not-a-key", datetime.now(timezone.utc))

    assert status.valid is False
