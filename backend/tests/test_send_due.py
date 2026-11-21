from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models import (
    Campaign,
    Enrollment,
    Lead,
    LeadEmail,
    Mailbox,
    Workspace,
)
from app.services.sequencing.send_due import (
    backoff_enrollment,
    build_message,
    sending_enabled,
)


def enrollment(status: str = "queued") -> Enrollment:
    return Enrollment(
        id=uuid4(),
        campaign_id=uuid4(),
        lead_id=uuid4(),
        lead_email_id=uuid4(),
        status=status,
        step_no=0,
    )


def workspace() -> Workspace:
    return Workspace(
        id=uuid4(),
        name="Example",
        sender_identity="Example Sales",
        postal_address="123 Example Street",
        timezone="UTC",
    )


def mailbox(workspace_id) -> Mailbox:
    return Mailbox(
        id=uuid4(),
        workspace_id=workspace_id,
        domain_id=uuid4(),
        address="sender@example.com",
        daily_cap=40,
        status="active",
    )


def lead(workspace_id) -> Lead:
    return Lead(
        id=uuid4(),
        workspace_id=workspace_id,
        source="csv",
        person_name="Sam",
        country="US",
        lawful_basis="legitimate_interest",
    )


def lead_email(lead_id) -> LeadEmail:
    return LeadEmail(
        id=uuid4(),
        lead_id=lead_id,
        email="sam@example.net",
        verify_status="valid",
    )


def test_build_message_footer_opt_out_and_no_tracking_pixel():
    ws = workspace()
    mb = mailbox(ws.id)
    ld = lead(ws.id)
    le = lead_email(ld.id)

    message = build_message(
        enrollment=enrollment(),
        mailbox=mb,
        lead=ld,
        lead_email=le,
        workspace=ws,
        subject="Hello",
        body="A direct message",
        opt_out_url="https://example.com/unsubscribe",
    )

    assert message.to_address == "sam@example.net"
    assert "Example Sales" in message.body
    assert "123 Example Street" in message.body
    assert "https://example.com/unsubscribe" in message.body
    assert message.headers["List-Unsubscribe"] == "<https://example.com/unsubscribe>"
    assert "<img" not in message.body
    assert "pixel" not in message.body.lower()


def test_build_message_requires_sender_details():
    ws = workspace()
    ws.postal_address = None
    mb = mailbox(ws.id)
    ld = lead(ws.id)
    le = lead_email(ld.id)

    try:
        build_message(
            enrollment=enrollment(),
            mailbox=mb,
            lead=ld,
            lead_email=le,
            workspace=ws,
            opt_out_url="https://example.com/unsubscribe",
        )
        assert False, "missing postal address should fail"
    except ValueError:
        pass


def test_backoff_is_bounded_and_future():
    now = datetime.now(timezone.utc)
    e = enrollment()

    first = backoff_enrollment(e, now)

    assert first > now
    assert first <= now + timedelta(minutes=60)


class FakeEnabledRedis:
    async def get(self, key: str):
        return "true"


async def test_sending_enabled_reads_true_flag():
    assert await sending_enabled(FakeEnabledRedis(), True)


async def test_sending_disabled_by_configuration():
    assert not await sending_enabled(FakeEnabledRedis(), False)
