import pytest

from app.services.compliance.suppression import (
    add_suppression,
    domain_from_email,
    hash_email,
    is_suppressed,
    normalize_email,
)


class FakeSuppressionStore:
    def __init__(self):
        self.email_hashes: set[str] = set()
        self.domains: set[str] = set()

    async def add(self, email_hash: str, domain: str | None, reason: str) -> None:
        self.email_hashes.add(email_hash)
        if domain:
            self.domains.add(domain)

    async def find_email(self, email_hash: str) -> bool:
        return email_hash in self.email_hashes

    async def find_domain(self, domain: str) -> bool:
        return domain in self.domains


def test_normalize_email():
    assert normalize_email("  Person@Example.COM  ") == "person@example.com"


@pytest.mark.parametrize(
    "email",
    ["", "person", "@example.com", "person@", "person@example", "a@b@c.com"],
)
def test_invalid_email_is_rejected(email):
    with pytest.raises(ValueError):
        normalize_email(email)


def test_hash_is_stable_sha256_hex():
    result = hash_email(" Person@Example.COM ")
    assert len(result) == 64
    assert result == result.lower()
    assert result == hash_email("person@example.com")


def test_domain_normalization():
    assert domain_from_email("Person@Example.COM") == "example.com"


async def test_exact_address_is_suppressed():
    store = FakeSuppressionStore()
    email_hash = await add_suppression(store, "person@example.com", "unsubscribe")

    assert await is_suppressed(store, "PERSON@example.com")
    assert email_hash not in {"person@example.com"}
    assert "person@example.com" not in store.email_hashes


async def test_domain_suppression_blocks_another_address():
    store = FakeSuppressionStore()
    await add_suppression(store, "person@example.com", "bounce")

    assert await is_suppressed(store, "someone@example.com")


async def test_duplicate_suppression_is_idempotent():
    store = FakeSuppressionStore()
    first = await add_suppression(store, "person@example.com", "unsubscribe")
    second = await add_suppression(store, "person@example.com", "unsubscribe")

    assert first == second
    assert len(store.email_hashes) == 1
    assert len(store.domains) == 1


async def test_different_addresses_and_domains_are_independent():
    store = FakeSuppressionStore()
    await add_suppression(store, "person@one.example", "unsubscribe")

    assert await is_suppressed(store, "other@one.example")
    assert not await is_suppressed(store, "person@two.example")


async def test_invalid_address_fails_closed():
    store = FakeSuppressionStore()
    assert await is_suppressed(store, "not-an-email")


async def test_suppression_reason_is_required():
    store = FakeSuppressionStore()
    with pytest.raises(ValueError):
        await add_suppression(store, "person@example.com", " ")
