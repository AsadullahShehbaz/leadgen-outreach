import pytest

from app.models import Mailbox
from app.services.mail.base import (
    OutboundMessage,
    PermanentSendError,
    TransientSendError,
)
from app.services.mail.fake import FakeMailProvider


def mailbox() -> Mailbox:
    from uuid import uuid4

    return Mailbox(
        id=uuid4(),
        workspace_id=uuid4(),
        domain_id=uuid4(),
        address="sender@example.com",
        daily_cap=40,
        status="active",
    )


def message() -> OutboundMessage:
    return OutboundMessage(
        from_address="sender@example.com",
        to_address="lead@example.net",
        subject="Hello",
        body="Hello from LeadGen",
        headers={"List-Unsubscribe": "<https://example.com/unsubscribe>"},
    )


async def test_fake_provider_records_no_network_send():
    provider = FakeMailProvider()
    sent_mailbox = mailbox()
    sent_message = message()

    message_id = await provider.send(sent_mailbox, sent_message)

    assert message_id == "fake-message-1"
    assert provider.sent == [(sent_mailbox, sent_message, message_id)]


async def test_fake_provider_records_multiple_sends():
    provider = FakeMailProvider(message_id_prefix="test")

    first = await provider.send(mailbox(), message())
    second = await provider.send(mailbox(), message())

    assert first == "test-1"
    assert second == "test-2"
    assert len(provider.sent) == 2


async def test_fake_provider_can_raise_transient_error():
    provider = FakeMailProvider(transient_failures=1)

    with pytest.raises(TransientSendError):
        await provider.send(mailbox(), message())


async def test_fake_provider_can_raise_permanent_error():
    provider = FakeMailProvider(permanent_failure=True)

    with pytest.raises(PermanentSendError):
        await provider.send(mailbox(), message())
