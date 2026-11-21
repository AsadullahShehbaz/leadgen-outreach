"""The one and only place where an enrollment's status may change.

The rulebook mirrors Section 11 of the design document.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Enrollment, Event

# Statuses where the send engine may still send another step.
ACTIVE = {"queued", "step1_sent", "step2_sent", "step3_sent"}

# Statuses that end the sequence because of something the prospect did.
EXIT = {"replied", "bounced", "unsubscribed"}

# Any ending status. Once here, an enrollment has no way back.
TERMINAL = EXIT | {"completed", "rejected"}

# The complete rulebook: from a status, only these next statuses are legal.
# Everything not listed here is an illegal transition and must raise.
ALLOWED: dict[str, set[str]] = {
    "new": {"scored", "rejected"},
    "scored": {"verified", "rejected"},
    "verified": {"drafted", "rejected"},
    "drafted": {"queued", "rejected"},
    "queued": {"step1_sent"} | EXIT,
    "step1_sent": {"step2_sent", "completed"} | EXIT,
    "step2_sent": {"step3_sent", "completed"} | EXIT,
    "step3_sent": {"completed"} | EXIT,
}


class IllegalTransition(Exception):
    """Raised when someone tries a move the rulebook does not allow."""

    def __init__(self, current: str, new: str) -> None:
        self.current = current
        self.new = new
        super().__init__(f"cannot move enrollment from {current!r} to {new!r}")


async def transition(
    db: AsyncSession,
    enrollment: Enrollment,
    new_status: str,
    reason: str,
    payload: dict | None = None,
) -> None:
    """Move an enrollment to a new status, or raise before changing anything.

    The caller owns the transaction: this function never commits. That lets a
    job change several rows and commit them together, or roll them all back.
    """
    allowed = ALLOWED.get(enrollment.status, set())
    if new_status not in allowed:
        raise IllegalTransition(enrollment.status, new_status)

    enrollment.status = new_status

    # No further emails are scheduled once the sequence is over.
    if new_status in TERMINAL:
        enrollment.next_send_at = None

    # Always leave a diary entry so support can reconstruct what happened.
    db.add(
        Event(
            enrollment_id=enrollment.id,
            type=f"status:{new_status}",
            payload={"reason": reason, **(payload or {})},
        )
    )
