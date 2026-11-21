from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models import LeadEmail
from app.services.budget.spend_caps import SpendLimits, reserve_usage
from app.services.verify.base import Verifier, VerifyResult
from app.services.verify.catchall import catchall_reason
from app.services.verify.mx import DnsMxLookup, MxLookup
from app.services.verify.syntax import is_role_based_email, is_syntax_valid, normalize_email


def is_risky_eligible(
    risky_count: int,
    total_count: int,
    risky_share_cap: float | None,
) -> bool:
    if risky_share_cap is None:
        return False
    if risky_share_cap <= 0:
        return False
    if total_count <= 0:
        return False
    return (risky_count + 1) / total_count <= risky_share_cap


async def verify_lead_email(
    session,
    lead_email_id,
    verifier: Verifier | None,
    verifier_store,
    mx_lookup: MxLookup | None = None,
) -> dict:
    mx_lookup = mx_lookup or DnsMxLookup()
    email_row = await session.get(LeadEmail, lead_email_id)
    if email_row is None:
        return {"paused": False, "status": "unknown", "reason": "lead_email_not_found"}

    limits = SpendLimits.from_settings()
    check = await reserve_usage(
        verifier_store,
        "verify",
        limits,
        requested_units=1,
        requested_usd=0.0,
    )
    if not check.allowed:
        return {
            "paused": True,
            "status": email_row.verify_status,
            "reason": "verification_spend_cap",
            "used_units": check.used_units,
            "limit_units": check.limit_units,
        }

    await session.commit()
    email = normalize_email(email_row.email)
    role_based = is_role_based_email(email)
    email_row.role_based = role_based

    if not is_syntax_valid(email):
        email_row.verify_status = "invalid"
        email_row.verified_at = datetime.now(timezone.utc)
        await session.commit()
        return {"paused": False, "status": "invalid", "reason": "invalid_syntax"}

    domain = email.rpartition("@")[2]
    try:
        has_mx = await mx_lookup.has_mx(domain)
    except Exception:
        has_mx = False
    if not has_mx:
        email_row.verify_status = "invalid"
        email_row.verified_at = datetime.now(timezone.utc)
        await session.commit()
        return {"paused": False, "status": "invalid", "reason": "mx_lookup_failed"}

    provider_result: VerifyResult | None = None
    if verifier is not None:
        try:
            provider_result = await verifier.verify(email)
        except Exception:
            status = "unknown"
            reason = "verifier_provider_error"
            email_row.verify_status = status
            email_row.verified_at = datetime.now(timezone.utc)
            await session.commit()
            return {
                "paused": False,
                "status": status,
                "reason": reason,
                "role_based": role_based,
            }

    if provider_result is not None and provider_result.status == "invalid":
        status = "invalid"
        reason = provider_result.reason
    elif provider_result is not None and provider_result.status == "valid":
        status = "valid"
        reason = provider_result.reason
    elif provider_result is not None and provider_result.status == "risky":
        status = "risky"
        reason = provider_result.reason
    elif provider_result is not None and catchall_reason(provider_result.reason):
        status = "risky"
        reason = provider_result.reason
    else:
        status = "unknown"
        reason = provider_result.reason if provider_result is not None else "mx_only"

    email_row.verify_status = status
    email_row.verified_at = datetime.now(timezone.utc)
    await session.commit()
    return {
        "paused": False,
        "status": status,
        "reason": reason,
        "role_based": role_based,
    }


async def verify_lead_emails(
    session,
    verifier: Verifier | None,
    lead_email_ids: list,
    verifier_store,
    mx_lookup: MxLookup | None = None,
    risky_share_cap: float | None = None,
) -> dict:
    mx_lookup = mx_lookup or DnsMxLookup()
    results: list[dict[str, Any]] = []
    eligible = 0
    risky_seen = 0

    for lead_email_id in lead_email_ids:
        result = await verify_lead_email(
            session,
            lead_email_id,
            verifier,
            verifier_store,
            mx_lookup,
        )
        results.append(result)
        if result["status"] == "valid":
            eligible += 1
        elif result["status"] == "risky":
            if is_risky_eligible(
                risky_seen,
                len(lead_email_ids),
                risky_share_cap,
            ):
                eligible += 1
                risky_seen += 1
                result["eligible"] = True
            else:
                result["eligible"] = False

    return {
        "paused": any(result.get("paused") for result in results),
        "processed": len(results),
        "eligible": eligible,
        "results": results,
    }
