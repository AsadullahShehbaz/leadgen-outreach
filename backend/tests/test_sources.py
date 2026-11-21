import pytest

from app.services.sources.base import RawLead
from app.services.sources.csv_import import (
    normalize_domain,
    normalize_email,
    parse_csv,
)
from app.services.sources.fake import FakeLeadSource
from app.services.sources.website import is_public_ip, validate_public_url


def test_csv_parsing_normalizes_fields_and_keeps_unknown_columns():
    leads = parse_csv(
        "company_name,company_domain,person_name,title,email,country,lawful_basis,ref\n"
        " Acme ,https://Acme.COM/about, Jane Doe ,CEO, JANE@EXAMPLE.COM ,US,consent,ref-1\n"
    )

    assert len(leads) == 1
    assert leads[0].company_name == "Acme"
    assert leads[0].company_domain == "acme.com"
    assert leads[0].person_name == "Jane Doe"
    assert leads[0].email == "jane@example.com"
    assert leads[0].raw["ref"] == "ref-1"
    assert normalize_domain("https://Example.COM/path") == "example.com"
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_csv_parser_rejects_blank_text():
    with pytest.raises(ValueError, match="empty"):
        parse_csv("")


@pytest.mark.asyncio
async def test_fake_source_respects_limit():
    source = FakeLeadSource(
        [
            RawLead(company_name="A", source="fake"),
            RawLead(company_name="B", source="fake"),
        ]
    )

    leads = await source.fetch({"query": "test"}, 1)

    assert len(leads) == 1
    assert source.calls == [({"query": "test"}, 1)]


@pytest.mark.asyncio
async def test_website_rejects_private_url():
    with pytest.raises(ValueError, match="Private|reserved"):
        await validate_public_url("http://127.0.0.1/")


def test_public_ip_guard_rejects_reserved_ranges():
    assert is_public_ip("127.0.0.1") is False
    assert is_public_ip("10.0.0.1") is False
    assert is_public_ip("169.254.1.1") is False
