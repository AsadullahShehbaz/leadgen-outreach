import re


EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

ROLE_PREFIXES = {
    "admin",
    "billing",
    "careers",
    "contact",
    "help",
    "hr",
    "info",
    "jobs",
    "marketing",
    "noreply",
    "sales",
    "support",
}


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("email must be a string")
    return email.strip().lower()


def is_syntax_valid(email: str) -> bool:
    try:
        email = normalize_email(email)
    except ValueError:
        return False
    if len(email) > 254:
        return False
    local, separator, domain = email.rpartition("@")
    return bool(
        separator
        and local
        and len(local) <= 64
        and ".." not in local
        and not local.startswith(".")
        and not local.endswith(".")
        and EMAIL_RE.fullmatch(email)
    )


def is_role_based_email(email: str) -> bool:
    try:
        email = normalize_email(email)
    except ValueError:
        return False
    local = email.partition("@")[0]
    return local in ROLE_PREFIXES


is_valid_syntax = is_syntax_valid
