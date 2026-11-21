import pytest

from app.services.compliance.forget_person import forget_person
from app.services.compliance.suppression import is_suppressed


class FakeSuppressionStore:
    def __init__(self):
        self.email_hashes: set[str] = set()
        self.domains: set[str] = set()
        self.added_reasons: list[str] = []

    async def add(self, email_hash: str, domain: str | None, reason: str) -> None:
        self.email_hashes.add(email_hash)
        if domain:
            self.domains.add(domain)
        self.added_reasons.append(reason)

    async def find_email(self, email_hash: str) -> bool:
        return email_hash in self.email_hashes

    async def find_domain(self, domain: str) -> bool:
        return domain in self.domains


class FakeLeadStore:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def forget_lead(self, lead_id: str, email: str) -> None:
        self.calls.append((lead_id, email))


async def test_suppression_is_added_before_person_is_wiped():
    suppression_store = FakeSuppressionStore()
    lead_store = FakeLeadStore()

    await forget_person(
        lead_store,
        suppression_store,
        "lead-123",
        "Person@Example.com",
    )

    assert suppression_store.added_reasons == ["forget"]
    assert lead_store.calls == [("lead-123", "Person@Example.com")]
    assert await is_suppressed(suppression_store, "person@example.com")


async def test_suppression_remains_when_lead_email_is_wiped():
    suppression_store = FakeSuppressionStore()
    lead_store = FakeLeadStore()
    await forget_person(
        lead_store,
        suppression_store,
        "lead-123",
        "person@example.com",
    )

    lead_store.calls.clear()
    assert await is_suppressed(suppression_store, "person@example.com")


@pytest.mark.parametrize(
    ("lead_id", "email"),
    [
        ("", "person@example.com"),
        ("   ", "person@example.com"),
        ("lead-123", ""),
        ("lead-123", "   "),
    ],
)
async def test_missing_lead_or_email_is_rejected(lead_id, email):
    with pytest.raises(ValueError):
        await forget_person(FakeLeadStore(), FakeSuppressionStore(), lead_id, email)
