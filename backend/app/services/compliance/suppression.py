import hashlib
from typing import Protocol


class SuppressionStore(Protocol):
    async def add(self, email_hash: str, domain: str | None, reason: str) -> None: ...

    async def find_email(self, email_hash: str) -> bool: ...

    async def find_domain(self, domain: str) -> bool: ...


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Email must be a string")

    normalized = email.strip().lower()
    if normalized.count("@") != 1:
        raise ValueError("Email must contain exactly one @")

    local, domain = normalized.split("@")
    if not local or not domain:
        raise ValueError("Email must have a local part and domain")
    if "." not in domain:
        raise ValueError("Email domain must contain a dot")

    return f"{local}@{domain.rstrip('.')}"


def hash_email(email: str) -> str:
    normalized = normalize_email(email)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def domain_from_email(email: str) -> str:
    normalized = normalize_email(email)
    return normalized.split("@", 1)[1].lower().rstrip(".").removeprefix("@")


async def add_suppression(
    store: SuppressionStore,
    email: str,
    reason: str,
) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Suppression reason is required")

    email_hash = hash_email(email)
    await store.add(email_hash, domain_from_email(email), reason.strip())
    return email_hash


async def is_suppressed(store: SuppressionStore, email: str) -> bool:
    try:
        normalized = normalize_email(email)
    except (TypeError, ValueError):
        return True

    email_hash = hash_email(normalized)
    if await store.find_email(email_hash):
        return True
    return await store.find_domain(domain_from_email(normalized))
