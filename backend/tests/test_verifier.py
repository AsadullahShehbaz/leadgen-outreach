import pytest

from app.services.verify.base import VerifyResult
from app.services.verify.catchall import catchall_reason
from app.services.verify.fake import FakeVerifier
from app.services.verify.syntax import is_role_based_email, is_syntax_valid


def test_syntax_and_role_checks():
    assert is_syntax_valid("person@example.com") is True
    assert is_syntax_valid("not-an-email") is False
    assert is_role_based_email("sales@example.com") is True
    assert is_role_based_email("person@example.com") is False


def test_catch_all_is_risky_evidence():
    assert catchall_reason("catch-all domain") is True
    assert catchall_reason("mailbox confirmed") is False


@pytest.mark.asyncio
async def test_fake_verifier_does_not_touch_network():
    verifier = FakeVerifier(
        results={
            "valid@example.com": VerifyResult(status="valid", reason="confirmed"),
            "bad@example.com": VerifyResult(status="invalid", reason="mailbox missing"),
        }
    )

    valid = await verifier.verify("valid@example.com")
    invalid = await verifier.verify("bad@example.com")

    assert valid.status == "valid"
    assert invalid.status == "invalid"
    assert verifier.calls == ["valid@example.com", "bad@example.com"]
