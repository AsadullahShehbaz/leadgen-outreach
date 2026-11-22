from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import select

from app.models import (
    Campaign,
    Enrollment,
    Experiment,
    Lead,
    LeadEmail,
    Mailbox,
    Message,
    SequenceStep,
    Suppression,
    Workspace,
)
from app.services.compliance.footer import build_footer
from app.services.compliance.rules_by_country import can_contact
from app.services.compliance.suppression import (
    domain_from_email,
    hash_email,
)
from app.services.license.license import license_allows_sending as verified_license_allows_sending
from app.services.agents.optimizer import choose_variant
from app.services.mail.base import (
    OutboundMessage,
    PermanentSendError,
    TransientSendError,
)
from app.services.sequencing.limiter import (
    release,
    try_acquire,
)
from app.services.sequencing.state_machine import ACTIVE, transition
from app.services.sequencing.windows import (
    in_send_window,
    next_window,
    window_from_settings,
    workspace_day,
)


async def advance_enrollment(
    db,
    enrollment: Enrollment,
    reason: str = "send completed",
) -> None:
    """Move a sent enrollment to its next sequence status."""
    next_status = {
        "queued": "step1_sent",
        "step1_sent": "step2_sent",
        "step2_sent": "step3_sent",
        "step3_sent": "completed",
    }.get(enrollment.status)
    if next_status is None:
        raise ValueError(f"Cannot advance enrollment from {enrollment.status}")
    await transition(db, enrollment, next_status, reason)


def in_enrollment_send_window(
    workspace: Workspace,
    now: datetime,
) -> bool:
    return in_send_window(now, workspace.timezone, window_from_settings())


def next_enrollment_send_at(
    workspace: Workspace,
    now: datetime,
) -> datetime:
    return next_window(now, workspace.timezone, window_from_settings())


def backoff_enrollment(
    enrollment: Enrollment,
    now: datetime,
) -> datetime:
    """Use a small bounded retry delay after a temporary provider failure."""
    minutes = min(60, 5 * (2 ** min(enrollment.step_no, 4)))
    return (now.astimezone(timezone.utc) + timedelta(minutes=minutes)).replace(
        tzinfo=timezone.utc
    )


async def is_suppressed_for_enrollment(db, enrollment: Enrollment) -> bool:
    lead_email = await db.get(LeadEmail, enrollment.lead_email_id)
    if lead_email is None:
        return True
    try:
        email_hash = hash_email(lead_email.email)
        domain = domain_from_email(lead_email.email)
    except ValueError:
        return True

    result = await db.exec(
        select(Suppression).where(
            (Suppression.email_hash == email_hash)
            | (Suppression.domain == domain)
        ).limit(1)
    )
    return result.first() is not None


async def pick_mailbox(db, enrollment: Enrollment) -> Mailbox | None:
    if enrollment.mailbox_id is not None:
        result = await db.exec(
            select(Mailbox).where(
                Mailbox.id == enrollment.mailbox_id,
                Mailbox.status == "active",
            )
        )
        mailbox = result.first()
        if mailbox is not None:
            return mailbox
        return None

    lead = await db.get(Lead, enrollment.lead_id)
    if lead is None:
        return None
    result = await db.exec(
        select(Mailbox)
        .where(
            Mailbox.workspace_id == lead.workspace_id,
            Mailbox.status == "active",
        )
        .order_by(Mailbox.created_at, Mailbox.id)
        .limit(1)
    )
    return result.first()


async def license_allows_sending(
    db,
    now: datetime | None = None,
) -> bool:
    """A missing or expired license blocks sends, but never compliance work."""
    return await verified_license_allows_sending(db, now)


async def sending_enabled(redis, configured: bool) -> bool:
    if not configured:
        return False
    if redis is None:
        return False
    get_method = getattr(redis, "get", None)
    if get_method is None:
        return True
    try:
        value = await get_method("SENDING_ENABLED")
    except Exception:
        return False
    if value is None:
        return True
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_message(
    enrollment: Enrollment,
    mailbox: Mailbox,
    lead: Lead,
    lead_email: LeadEmail,
    workspace: Workspace,
    subject: str | None = None,
    body: str | None = None,
    opt_out_url: str | None = None,
    previous_messages: list[Message] | None = None,
) -> OutboundMessage:
    url = (opt_out_url or "").strip()
    if not url:
        raise ValueError("Opt-out URL is required")

    final_subject = (subject or "").strip()
    if not final_subject:
        final_subject = "Following up"

    final_body = (body or "").strip()
    if not final_body:
        name = lead.person_name or "there"
        final_body = f"Hi {name},"

    final_body = f"{final_body.rstrip()}\n\n{build_footer(workspace.sender_identity, workspace.postal_address, url)}"

    headers = {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }

    previous = sorted(
        [
            message
            for message in (previous_messages or [])
            if message.direction == "out" and message.message_id
        ],
        key=lambda message: message.sent_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    if previous:
        first = previous[0]
        last = previous[-1]
        thread_id = first.thread_id or first.message_id
        headers["In-Reply-To"] = last.message_id or ""
        references = [
            message.thread_id or message.message_id
            for message in previous
            if message.thread_id or message.message_id
        ]
        if thread_id:
            headers["References"] = " ".join(dict.fromkeys(references + [thread_id]))

    return OutboundMessage(
        from_address=mailbox.address,
        to_address=lead_email.email,
        subject=final_subject,
        body=final_body,
        headers=headers,
    )


async def advance_step(
    db,
    enrollment: Enrollment,
    campaign: Campaign,
    now: datetime,
) -> None:
    next_status = {
        "queued": "step1_sent",
        "step1_sent": "step2_sent",
        "step2_sent": "step3_sent",
        "step3_sent": "completed",
    }[enrollment.status]

    await transition(db, enrollment, next_status, "send completed")
    if next_status in {"completed"}:
        enrollment.next_send_at = None
        enrollment.step_no = 3
        return

    enrollment.step_no = {
        "step1_sent": 1,
        "step2_sent": 2,
        "step3_sent": 3,
    }[next_status]

    next_step_no = enrollment.step_no + 1
    result = await db.exec(
        select(SequenceStep)
        .where(
            SequenceStep.campaign_id == campaign.id,
            SequenceStep.step_no == next_step_no,
        )
        .limit(1)
    )
    step = result.first()
    delay_days = step.delay_days if step is not None else 3
    enrollment.next_send_at = (
        now.astimezone(timezone.utc) + timedelta(days=delay_days)
    ).replace(tzinfo=timezone.utc)


async def has_receipt_for_step(db, enrollment: Enrollment) -> bool:
    result = await db.exec(
        select(Message)
        .where(
            Message.enrollment_id == enrollment.id,
            Message.direction == "out",
        )
        .order_by(Message.sent_at.desc())
    )
    messages = result.all()
    if enrollment.status == "queued":
        return bool(messages)
    expected = {
        "step1_sent": 1,
        "step2_sent": 2,
        "step3_sent": 3,
    }.get(enrollment.status, 0)
    return len(messages) >= expected


async def send_due(ctx: dict) -> int:
    """Send due enrollments in 50-row locked batches."""
    redis = ctx.get("redis")
    mail = ctx.get("mail")
    if mail is None:
        raise ValueError("send_due requires a MailProvider in ctx['mail']")

    configured = ctx.get("sending_enabled")
    if configured is None:
        configured = ctx.get("configured_sending_enabled", False)
    if not await sending_enabled(redis, bool(configured)):
        return 0

    session_factory = ctx.get("session")
    if session_factory is None:
        from app.core.db import Session

        session_factory = Session
    now = ctx.get("now") or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    sent_count = 0
    async with session_factory() as db:
        result = await db.exec(
            select(Enrollment)
            .where(
                Enrollment.status.in_(ACTIVE),
                Enrollment.next_send_at.is_not(None),
                Enrollment.next_send_at <= now,
            )
            .order_by(Enrollment.next_send_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        enrollments = result.all()

        license_checker = ctx.get("license_checker") or ctx.get("license_allows_sending")
        for enrollment in enrollments:
            if await has_receipt_for_step(db, enrollment):
                continue

            if await is_suppressed_for_enrollment(db, enrollment):
                await transition(db, enrollment, "unsubscribed", "suppressed")
                continue

            if "license" in ctx:
                allowed = ctx["license"]
            elif license_checker is not None:
                try:
                    allowed = license_checker(db, now)
                except TypeError:
                    allowed = license_checker(db)
            else:
                allowed = await license_allows_sending(db, now)
            if hasattr(allowed, "__await__"):
                allowed = await allowed
            if not bool(allowed):
                continue

            mailbox = await pick_mailbox(db, enrollment)
            if mailbox is None or mailbox.status != "active":
                continue
            enrollment.mailbox_id = mailbox.id

            lead = await db.get(Lead, enrollment.lead_id)
            lead_email = await db.get(LeadEmail, enrollment.lead_email_id)
            campaign = await db.get(Campaign, enrollment.campaign_id)
            workspace = await db.get(Workspace, mailbox.workspace_id)
            if lead is None or lead_email is None or campaign is None or workspace is None:
                continue

            if enrollment.variant_id is None:
                experiment_result = await db.exec(
                    select(Experiment).where(
                        Experiment.campaign_id == campaign.id,
                        Experiment.kind == "subject",
                    ).limit(1)
                )
                experiment = experiment_result.first()
                if experiment is not None:
                    arm_stats = experiment.stats if isinstance(experiment.stats, dict) else {}
                    if arm_stats:
                        enrollment.variant_id = choose_variant(
                            arm_stats,
                            minimum_sample=int(
                                ctx.get("optimizer_minimum_sample", 30)
                            ),
                        )

            allowed, reason = can_contact(
                lead.country,
                lead.lawful_basis,
                campaign.compliance_mode,
            )
            if not allowed:
                continue

            if not in_enrollment_send_window(workspace, now):
                enrollment.next_send_at = next_enrollment_send_at(workspace, now)
                continue

            day = workspace_day(now, workspace.timezone)
            acquired = await try_acquire(
                redis,
                mailbox.id,
                mailbox.daily_cap,
                day,
            )
            if not acquired:
                continue

            previous_result = await db.exec(
                select(Message)
                .where(
                    Message.enrollment_id == enrollment.id,
                    Message.direction == "out",
                )
                .order_by(Message.sent_at)
            )
            previous_messages = previous_result.all()

            subject = None
            body = None
            if isinstance(campaign.product, dict):
                subject = campaign.product.get("subject")
                body = campaign.product.get("body")
            opt_out_url = f"{ctx.get('public_url', 'http://localhost').rstrip('/')}/unsubscribe"

            try:
                message = build_message(
                    enrollment=enrollment,
                    mailbox=mailbox,
                    lead=lead,
                    lead_email=lead_email,
                    workspace=workspace,
                    subject=subject,
                    body=body,
                    opt_out_url=opt_out_url,
                    previous_messages=previous_messages,
                )
            except (ValueError, Exception) as exc:
                await release(redis, mailbox.id, day)
                continue

            try:
                message_id = await mail.send(mailbox, message)
            except TransientSendError:
                await release(redis, mailbox.id, day)
                enrollment.next_send_at = backoff_enrollment(enrollment, now)
                continue
            except PermanentSendError:
                await release(redis, mailbox.id, day)
                enrollment.next_send_at = backoff_enrollment(enrollment, now)
                continue
            except Exception:
                await release(redis, mailbox.id, day)
                enrollment.next_send_at = backoff_enrollment(enrollment, now)
                continue

            duplicate = await db.exec(
                select(Message)
                .where(
                    Message.enrollment_id == enrollment.id,
                    Message.direction == "out",
                    Message.message_id == message_id,
                )
                .limit(1)
            )
            if duplicate.first() is not None:
                continue

            db.add(
                Message(
                    enrollment_id=enrollment.id,
                    direction="out",
                    message_id=message_id,
                    thread_id=message_id,
                    subject=message.subject,
                    body=message.body,
                    sent_at=now,
                    variant_id=enrollment.variant_id,
                )
            )
            await advance_step(db, enrollment, campaign, now)
            sent_count += 1

        await db.commit()
    return sent_count
