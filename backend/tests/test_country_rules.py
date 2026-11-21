import pytest

from app.services.compliance.rules_by_country import can_contact


def test_us_allows_without_prior_consent():
    assert can_contact("US", None) == (True, "")
    assert can_contact("US", "legitimate_interest") == (True, "")


def test_germany_requires_consent():
    assert can_contact("DE", "legitimate_interest") == (
        False,
        "Germany requires consent",
    )
    assert can_contact("DE", "consent") == (True, "")


def test_canada_requires_supported_consent_rule():
    assert can_contact("CA", "consent")[0] is False
    assert can_contact("CA", "express_consent") == (True, "")
    assert can_contact("CA", "implied_exception") == (True, "")


@pytest.mark.parametrize("country", ["FR", "GB"])
def test_eu_and_uk_allow_consent_or_legitimate_interest(country):
    assert can_contact(country, "consent") == (True, "")
    assert can_contact(country, "legitimate_interest") == (True, "")
    assert can_contact(country, None)[0] is False


def test_strict_mode_requires_lawful_basis():
    assert can_contact("US", None, "strict") == (
        False,
        "strict mode requires a lawful basis",
    )
    assert can_contact("US", "legitimate_interest", "strict") == (True, "")


def test_unknown_country_requires_lawful_basis():
    assert can_contact(None, None)[0] is False
    assert can_contact(None, "legitimate_interest") == (True, "")


def test_invalid_country_fails_loudly():
    with pytest.raises(ValueError):
        can_contact("USA", "consent")


def test_unknown_lawful_basis_fails_loudly():
    with pytest.raises(ValueError):
        can_contact("US", "guessing")


@pytest.mark.parametrize("mode", ["", "blocked", "STANDARD"])
def test_invalid_compliance_mode_fails_loudly(mode):
    if mode == "STANDARD":
        assert can_contact("US", None, mode) == (True, "")
    else:
        with pytest.raises(ValueError):
            can_contact("US", None, mode)
