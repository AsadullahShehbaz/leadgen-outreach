from sqlalchemy import select

from app.models import (
    Enrollment,
    LeadEmail,
    Mailbox,
    Message,
    Suppression,
)
from app.models.base import utcnow
from app.services.compliance.suppression import (
    domain_from_email,
    hash_email,
)
from app.services.mail.base import InboundMessage
from app.services.mail.bounce_parser import parse_bounce
from app.services.sequencing.state_machine import ACTIVE, transition


def should_pause_for_hard_bounce(hard_bounces: int, sent_messages: int) -> bool:
    if sent_messages <= 0:
        return False
    return hard_bounces / sent_messages > 0.03


def should_pause_for_complaints(complaints: int, sent_messages: int) -> bool:
    if sent_messages <= 0:
        return False
    return complaints / sent_messages >= 0.003


def apply_mailbox_penalty(
    mailbox: Mailbox,
    kind: str,
) -> None:
    if kind == "hard_bounce":
        mailbox.health_score = max(0.0, mailbox.health_score - 10.0)
    elif kind == "complaint":
        mailbox.health_score = max(0.0, mailbox.health_score - 20.0)

    if mailbox.health_score <= 70.0:
        mailbox.status = "paused"


async def find_outbound_message(
    db,
    inbound: InboundMessage,
) -> Message | None:
    candidates: list[str] = []
    if inbound.in_reply_to:
        candidates.append(inbound.in_reply_to.strip())
    candidates.extend(reference.strip() for reference in inbound.references if reference.strip())

    if inbound.headers:
        header_references = inbound.headers.get("References") or inbound.headers.get("references")
        if header_references:
            candidates.extend(part.strip() for part in header_references.split() if part.strip())

    if not candidates:
        return None

    result = await db.exec(
        select(Message)
        .where(Message.direction == "out", Message.message_id.in_(candidates))
    )
    messages = result.all()
    by_id = {message.message_id: message for message in messages}
    for candidate in candidates:
        if candidate in by_id:
            return by_id[candidate]
    return None


async def find_enrollment_by_inbound(
    db,
    inbound: InboundMessage,
) -> Enrollment | None:
    outbound = await find_outbound_message(db, inbound)
    if outbound is None:
        return None
    return await db.get(Enrollment, outbound.enrollment_id)


async def add_database_suppression(
    db,
    email: str,
    reason: str,
) -> str:
    email_hash = hash_email(email)
    result = await db.exec(
        select(Suppression).where(Suppression.email_hash == email_hash).limit(1)
    )
    existing = result.first()
    if existing is not None:
        return email_hash

    db.add(
        Suppression(
            email_hash=email_hash,
            domain=domain_from_email(email),
            reason=reason,
        )
    )
    return email_hash


async def count_events(db, enrollment: Enrollment, event_type: str) -> int:
    result = await db.exec(
        select(Message).where(
            Message.enrollment_id == enrollment.id,
            Message.direction == "in",
            Message.subject == event_type,
        )
    )
    return len(result.all())


def _header_value(inbound: InboundMessage, name: str) -> str:
    for key, value in inbound.headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def is_complaint(inbound: InboundMessage) -> bool:
    complaint = _header_value(inbound, "X-Complaint")
    feedback = _header_value(inbound, "Feedback-Type")
    fc = _header_value(inbound, "X-FC")
    complaint_header = _header_value(inbound, "Complaint")
    return (
        complaint.lower() in {"1", "true", "yes", "complaint"}
        or fc.lower() in {"abuse", "complaint"}
        or complaint_header.lower() in {"1", "true", "yes", "complaint"}
        or (
        feedback.lower() in {"abuse", "complaint"}
        )
    )


async def record_inbound(
    db,
    enrollment: Enrollment,
    inbound: InboundMessage,
    label: str,
) -> bool:
    existing = await db.exec(
        select(Message).where(
            Message.enrollment_id == enrollment.id,
            Message.direction == "in",
            Message.message_id == inbound.message_id,
        ).limit(1)
    )
    if existing.first() is not None:
        return False

    db.add(
        Message(
            enrollment_id=enrollment.id,
            direction="in",
            message_id=inbound.message_id,
            in_reply_to=inbound.in_reply_to,
            thread_id=inbound.headers.get("thread-id")
            or inbound.headers.get("Thread-ID"),
            subject=label,
            body=inbound.body,
            sent_at=utcnow(),
        )
    )
    return True


async def process_inbound_message(
    db,
    mailbox: Mailbox,
    inbound: InboundMessage,
    classifier=None,
) -> bool:
    """Process one replay-safe inbound message. Returns True when it was new."""
    if not inbound.message_id:
        return False

    enrollment = await find_enrollment_by_inbound(db, inbound)
    if enrollment is None:
        return False

    bounce = parse_bounce(
        "\n".join([
            inbound.body,
            inbound.subject,
            _header_value(inbound, "Status"),
            _header_value(inbound, "Diagnostic-Code"),
        ])
    )
    complaint = is_complaint(inbound)
    if complaint:
        label = "complaint"
    elif bounce.kind == "hard":
        label = "hard_bounce"
    elif bounce.kind == "soft":
        label = "soft_bounce"
    else:
        label = "reply"

    new_message = await record_inbound(db, enrollment, inbound, label)
    if not new_message:
        return False

    if complaint:
        await handle_complaint(db, mailbox, enrollment, inbound)
        return True

    if bounce.kind == "hard":
        await handle_hard_bounce(db, mailbox, enrollment)
        return True

    if bounce.kind == "soft":
        await handle_soft_bounce(db, mailbox, enrollment)
        return True

    if classifier is not None:
        reply_class = await classifier.classify(inbound)
    else:
        reply_class = "other"

    if reply_class == "auto_reply":
        return True

    if reply_class == "unsubscribe":
        await handle_unsubscribe(db, mailbox, enrollment)
        return True

    if enrollment.status in ACTIVE:
        await transition(db, enrollment, "replied", "reply received", {
            "reply_class": reply_class,
            "message_id": inbound.message_id,
        })
    return True


async def handle_hard_bounce(
    db,
    mailbox: Mailbox,
    enrollment: Enrollment,
) -> None:
    lead_email = await db.get(LeadEmail, enrollment.lead_email_id)
    if lead_email is not None:
        lead_email.verify_status = "invalid"
        try:
            await add_database_suppression(db, lead_email.email, "bounced")
        except ValueError:
            pass

    apply_mailbox_penalty(mailbox, "hard_bounce")
    if enrollment.status in ACTIVE:
        await transition(db, enrollment, "bounced", "hard bounce", {
            "mailbox_id": str(mailbox.id),
        })


async def handle_soft_bounce(
    db,
    mailbox: Mailbox,
    enrollment: Enrollment,
) -> None:
    count = await count_events(db, enrollment, "soft_bounce")
    if count >= 3:
        await handle_hard_bounce(db, mailbox, enrollment)


async def handle_unsubscribe(
    db,
    mailbox: Mailbox,
    enrollment: Enrollment,
) -> None:
    lead_email = await db.get(LeadEmail, enrollment.lead_email_id)
    if lead_email is not None:
        try:
            await add_database_suppression(db, lead_email.email, "unsubscribe")
        except ValueError:
            pass

    if enrollment.status in ACTIVE:
        await transition(db, enrollment, "unsubscribed", "reply unsubscribe", {
            "mailbox_id": str(mailbox.id),
        })


async def handle_complaint(
    db,
    mailbox: Mailbox,
    enrollment: Enrollment,
    inbound: InboundMessage,
) -> None:
    lead_email = await db.get(LeadEmail, enrollment.lead_email_id)
    if lead_email is not None:
        try:
            await add_database_suppression(db, lead_email.email, "spam_complaint")
        except ValueError:
            pass

    apply_mailbox_penalty(mailbox, "complaint")
    if enrollment.status in ACTIVE:
        await transition(db, enrollment, "unsubscribed", "spam complaint", {
            "message_id": inbound.message_id,
        })


async def poll_inbox(ctx: dict) -> int:
    mail = ctx["mail"]
    session = ctx["session"]
    classifier = ctx.get("reply_classifier")
    mailbox_uids = ctx.setdefault("mailbox_uids", {})
    processed = 0

    async with session() as db:
        result = await db.exec(
            select(Mailbox).where(Mailbox.status == "active")
        )
        mailboxes = result.all()

        for mailbox in mailboxes:
            since_uid = int(mailbox_uids.get(str(mailbox.id), 0))
            try:
                inbound_messages = await mail.fetch_new(mailbox, since_uid)
            except (NotImplementedError, AttributeError):
                continue

            for inbound in inbound_messages:
                if await process_inbound_message(db, mailbox, inbound, classifier):
                    processed += 1
            since_uid += len(inbound_messages)
            mailbox_uids[str(mailbox.id)] = since_uid

        await db.commit()

    return processed
