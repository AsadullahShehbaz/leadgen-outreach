from uuid import uuid4

from app.models import Mailbox
from app.services.mail.base import InboundMessage
from app.services.mail.fake import FakeMailProvider
from app.services.sequencing.inbox_worker import (
    apply_mailbox_penalty,
    is_complaint,
    should_pause_for_complaints,
    should_pause_for_hard_bounce,
)


def mailbox() -> Mailbox:
    return Mailbox(
        id=uuid4(),
        workspace_id=uuid4(),
        domain_id=uuid4(),
        address="sender@example.com",
        status="active",
        health_score=100.0,
    )


def test_hard_bounce_rate_threshold():
    assert should_pause_for_hard_bounce(4, 100)
    assert not should_pause_for_hard_bounce(2, 100)


def test_complaint_rate_threshold():
    assert should_pause_for_complaints(1, 100)
    assert not should_pause_for_complaints(1, 1000)


def test_mailbox_penalty_pauses_after_health_drop():
    mb = mailbox()
    mb.health_score = 75.0
    apply_mailbox_penalty(mb, "hard_bounce")
    assert mb.health_score == 65.0
    assert mb.status == "paused"


def test_complaint_header_is_detected():
    message = InboundMessage(
        message_id="complaint-1",
        headers={"Feedback-Type": "abuse"},
    )
    assert is_complaint(message)


async def test_fake_mail_provider_fetches_inbound_without_network():
    mb = mailbox()
    inbound = InboundMessage(message_id="reply-1", body="Interested")
    provider = FakeMailProvider(inbound_messages=[inbound])

    first = await provider.fetch_new(mb, 0)
    second = await provider.fetch_new(mb, 1)

    assert first == [inbound]
    assert second == []
    assert provider.fetched == [(mb, 0), (mb, 1)]
