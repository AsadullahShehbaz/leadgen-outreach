SUPPORTED_LAWFUL_BASES = frozenset(
    {
        "consent",
        "legitimate_interest",
        "express_consent",
        "implied_exception",
    }
)

EU_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)


def normalize_country(country: str | None) -> str | None:
    if country is None:
        return None
    if not isinstance(country, str):
        raise ValueError("Country must be a two-letter code or null")

    normalized = country.strip().upper()
    if not normalized:
        return None
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError("Country must be a two-letter code")
    return normalized


def can_contact(
    country: str | None,
    lawful_basis: str | None,
    compliance_mode: str = "standard",
) -> tuple[bool, str]:
    mode = compliance_mode.strip().lower() if isinstance(compliance_mode, str) else ""
    if mode not in {"standard", "strict"}:
        raise ValueError("Compliance mode must be standard or strict")

    country_code = normalize_country(country)

    if lawful_basis is None:
        basis = None
    elif isinstance(lawful_basis, str) and lawful_basis.strip():
        basis = lawful_basis.strip().lower()
        if basis not in SUPPORTED_LAWFUL_BASES:
            raise ValueError("Unknown lawful basis")
    else:
        basis = None

    if mode == "strict" and basis is None:
        return False, "strict mode requires a lawful basis"

    if country_code == "DE" and basis != "consent":
        return False, "Germany requires consent"

    if country_code == "CA" and basis not in {
        "express_consent",
        "implied_exception",
    }:
        return False, "Canada requires express consent or a narrow implied exception"

    if country_code in EU_COUNTRIES and basis not in {
        "consent",
        "legitimate_interest",
    }:
        return False, "EU countries require consent or legitimate interest"

    if country_code == "GB" and basis not in {
        "consent",
        "legitimate_interest",
    }:
        return False, "UK requires consent or legitimate interest"

    if country_code is None and basis is None:
        return False, "Country is unknown and no lawful basis is recorded"

    if country_code not in {"US", "DE", "CA", "GB"} and country_code not in EU_COUNTRIES:
        if basis is None:
            return False, "Unknown country requires a recorded lawful basis"

    return True, ""
