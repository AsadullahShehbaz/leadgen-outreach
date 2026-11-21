from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.models import Lead, LeadEmail
from app.services.budget.spend_caps import (
    SpendLimits,
    SqlSpendLedgerStore,
    reserve_usage,
)
from app.services.sources.base import LeadSource, RawLead
from app.services.sources.csv_import import normalize_domain, normalize_email


def normalize_person_name(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.strip().lower().split()) or None


def score_icp(raw: RawLead, icp: dict | None = None) -> float:
    icp = icp or {}
    score = 0.0
    if raw.company_domain:
        score += 20.0
    if raw.company_name:
        score += 20.0
    if raw.person_name:
        score += 15.0
    if raw.title:
        score += 15.0
    if raw.email:
        score += 15.0
    if raw.country:
        score += 5.0

    target_domains = icp.get("domains")
    if isinstance(target_domains, list) and raw.company_domain:
        if raw.company_domain.lower() in {str(v).lower() for v in target_domains}:
            score += 10.0
    return min(score, 100.0)


async def persist_raw_leads(
    session,
    workspace_id: UUID,
    raw_leads: list[RawLead],
    icp: dict | None = None,
) -> dict:
    created = 0
    updated = 0
    lead_emails = 0

    for raw in raw_leads:
        domain = normalize_domain(raw.company_domain)
        person_key = normalize_person_name(raw.person_name)
        lead = None
        email = normalize_email(raw.email)

        if domain:
            statement = select(Lead).where(
                Lead.workspace_id == workspace_id,
                Lead.company_domain == domain,
            )
            if person_key:
                candidates = (await session.execute(statement)).scalars().all()
                lead = next(
                    (
                        item
                        for item in candidates
                        if normalize_person_name(item.person_name) == person_key
                    ),
                    None,
                )

        if lead is None and email:
            statement = (
                select(Lead)
                .join(LeadEmail, LeadEmail.lead_id == Lead.id)
                .where(
                    Lead.workspace_id == workspace_id,
                    LeadEmail.email == email,
                )
            )
            lead = (await session.execute(statement)).scalars().first()

        if lead is None and domain and not person_key:
            statement = select(Lead).where(
                Lead.workspace_id == workspace_id,
                Lead.company_domain == domain,
                Lead.person_name.is_(None),
            )
            lead = (await session.execute(statement)).scalars().first()

        if lead is None:
            lead = Lead(
                workspace_id=workspace_id,
                source=raw.source,
                company_domain=domain,
                company_name=raw.company_name,
                person_name=raw.person_name,
                title=raw.title,
                country=raw.country,
                icp_score=score_icp(raw, icp),
                lawful_basis=raw.lawful_basis,
                collected_at=datetime.now(timezone.utc),
                raw=raw.raw,
            )
            session.add(lead)
            await session.flush()
            created += 1
        else:
            changed = False
            for field in ("company_name", "person_name", "title", "country", "lawful_basis"):
                value = getattr(raw, field)
                if value is not None and getattr(lead, field) in (None, ""):
                    setattr(lead, field, value)
                    changed = True
            new_score = score_icp(raw, icp)
            if lead.icp_score is None or new_score > lead.icp_score:
                lead.icp_score = new_score
                changed = True
            if changed:
                updated += 1

        if email:
            statement = select(LeadEmail).where(
                LeadEmail.lead_id == lead.id,
                LeadEmail.email == email,
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is None:
                session.add(
                    LeadEmail(
                        lead_id=lead.id,
                        email=email,
                        verify_status="unknown",
                        role_based=False,
                    )
                )
                lead_emails += 1

    await session.commit()
    return {
        "created": created,
        "updated": updated,
        "lead_emails": lead_emails,
        "processed": len(raw_leads),
    }


async def source_leads(
    session,
    source: LeadSource,
    query: dict,
    workspace_id: UUID,
    limit: int,
    source_store,
    estimated_usd: float = 0.0,
) -> dict:
    limits = SpendLimits.from_settings()
    check = await reserve_usage(
        source_store,
        "source",
        limits,
        requested_units=1,
        requested_usd=estimated_usd,
    )
    if not check.allowed:
        return {
            "paused": True,
            "kind": "source",
            "provider_calls": 0,
            "created": 0,
            "updated": 0,
            "lead_emails": 0,
            "processed": 0,
            "used_units": check.used_units,
            "limit_units": check.limit_units,
        }

    await session.commit()
    raw_leads = await source.fetch(query, limit)
    persisted = await persist_raw_leads(
        session,
        workspace_id,
        raw_leads,
        icp=query.get("icp"),
    )
    return {"paused": False, "kind": "source", "provider_calls": 1, **persisted}
