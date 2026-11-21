from typing import Protocol

from app.services.compliance.suppression import (
    SuppressionStore,
    add_suppression,
)


class LeadForgetStore(Protocol):
    async def forget_lead(self, lead_id: str, email: str) -> None: ...


async def forget_person(
    store: LeadForgetStore,
    suppression_store: SuppressionStore,
    lead_id: str,
    email: str,
) -> None:
    if not isinstance(lead_id, str) or not lead_id.strip():
        raise ValueError("Lead ID is required")
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Email is required")

    await add_suppression(suppression_store, email, "forget")
    await store.forget_lead(lead_id.strip(), email.strip())
