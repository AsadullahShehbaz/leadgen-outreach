import csv
import io
from urllib.parse import urlsplit

from app.services.sources.base import LeadSource, RawLead


KNOWN_FIELDS = {
    "company_name",
    "company_domain",
    "person_name",
    "title",
    "email",
    "country",
    "lawful_basis",
}


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_domain(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    if "://" in value:
        value = urlsplit(value).hostname or value
    value = value.strip().lower().strip(".")
    value = value.split("/", 1)[0]
    return value or None


def normalize_email(value: str | None) -> str | None:
    value = clean_text(value)
    return value.lower() if value else None


def parse_csv(text: str, source: str = "csv") -> list[RawLead]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("CSV text is empty")

    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV header row is missing")

    leads: list[RawLead] = []
    for row_number, row in enumerate(reader, start=2):
        if not any(clean_text(value) for value in row.values()):
            continue

        normalized: dict = {}
        for key, value in row.items():
            if key:
                normalized[key.strip().lower()] = value

        unknown = {
            key: clean_text(value)
            for key, value in normalized.items()
            if key not in KNOWN_FIELDS and clean_text(value) is not None
        }
        lead = RawLead(
            company_name=clean_text(normalized.get("company_name")),
            company_domain=normalize_domain(normalized.get("company_domain")),
            person_name=clean_text(normalized.get("person_name")),
            title=clean_text(normalized.get("title")),
            email=normalize_email(normalized.get("email")),
            country=clean_text(normalized.get("country")),
            lawful_basis=clean_text(normalized.get("lawful_basis")),
            source=source,
            raw={"row_number": row_number, **unknown},
        )
        leads.append(lead)
    return leads


parse_csv_leads = parse_csv


class CSVLeadSource:
    name = "csv"

    async def fetch(self, query: dict, limit: int) -> list[RawLead]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        text = query.get("csv_text")
        if not isinstance(text, str):
            raise ValueError("csv_text is required")
        leads = parse_csv(text, source=query.get("source", "csv"))
        return leads[:limit]
