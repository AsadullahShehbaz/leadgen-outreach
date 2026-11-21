import pytest

from app.services.mail.bounce_parser import BounceResult, parse_bounce


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Diagnostic-Code: smtp; 5.1.1 user unknown", "hard"),
        ("Status: 4.2.0", "soft"),
        ("Status: 2.0.0 delivered", "unknown"),
        ("No delivery status is included", "unknown"),
    ],
)
def test_parse_bounce(text: str, kind: str):
    result = parse_bounce(text)
    assert isinstance(result, BounceResult)
    assert result.kind == kind


def test_hard_bounce_status_code_is_preserved():
    assert parse_bounce("5.1.1") == BounceResult("hard", "5.1.1")


def test_ordinary_reply_text_is_not_a_bounce():
    assert parse_bounce("Thanks, let's talk next week").kind == "unknown"
