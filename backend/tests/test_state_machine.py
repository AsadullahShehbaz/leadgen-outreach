from datetime import datetime, timezone
from itertools import product
from uuid import uuid4

import pytest

from app.models import Enrollment, Event
from app.services.sequencing.state_machine import (
    ACTIVE,
    ALLOWED,
    EXIT,
    TERMINAL,
    IllegalTransition,
    transition,
)

ALL_STATUSES = set(ALLOWED) | TERMINAL
ALLOWED_PAIRS = [(old, new) for old, targets in ALLOWED.items() for new in targets]
ILLEGAL_PAIRS = [
    (old, new)
    for old, new in product(ALL_STATUSES, repeat=2)
    if new not in ALLOWED.get(old, set())
]
NEXT_SEND_AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FakeSession:
    """Just enough of an AsyncSession to capture Event rows, with no database."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def make_enrollment(status: str) -> Enrollment:
    return Enrollment(
        campaign_id=uuid4(),
        lead_id=uuid4(),
        lead_email_id=uuid4(),
        status=status,
        next_send_at=NEXT_SEND_AT,
    )


@pytest.mark.parametrize(("old", "new"), ALLOWED_PAIRS)
async def test_allowed_moves_succeed(old: str, new: str):
    db = FakeSession()
    enrollment = make_enrollment(old)

    await transition(db, enrollment, new, "test reason")

    assert enrollment.status == new
    assert len(db.added) == 1

    event = db.added[0]
    assert isinstance(event, Event)
    assert event.enrollment_id == enrollment.id
    assert event.type == f"status:{new}"
    assert event.payload == {"reason": "test reason"}

    if new in TERMINAL:
        assert enrollment.next_send_at is None
    else:
        assert enrollment.next_send_at == NEXT_SEND_AT


@pytest.mark.parametrize(("old", "new"), ILLEGAL_PAIRS)
async def test_illegal_moves_raise_without_changing_anything(old: str, new: str):
    db = FakeSession()
    enrollment = make_enrollment(old)

    with pytest.raises(IllegalTransition) as error:
        await transition(db, enrollment, new, "test reason")

    assert error.value.current == old
    assert error.value.new == new
    assert enrollment.status == old
    assert enrollment.next_send_at == NEXT_SEND_AT
    assert db.added == []


async def test_unknown_current_status_is_illegal():
    db = FakeSession()
    enrollment = make_enrollment("banana")

    with pytest.raises(IllegalTransition):
        await transition(db, enrollment, "scored", "test reason")

    assert enrollment.status == "banana"
    assert db.added == []


async def test_event_keeps_reason_and_extra_payload():
    db = FakeSession()
    enrollment = make_enrollment("new")

    await transition(db, enrollment, "scored", "icp scored", {"score": 82})

    assert db.added[0].payload == {"reason": "icp scored", "score": 82}


async def test_missing_payload_is_allowed():
    db = FakeSession()
    enrollment = make_enrollment("new")

    await transition(db, enrollment, "scored", "icp scored")

    assert db.added[0].payload == {"reason": "icp scored"}


def test_rulebook_is_consistent():
    # Every move must point at a status this module knows about.
    for targets in ALLOWED.values():
        assert targets <= ALL_STATUSES

    # Exactly the non-terminal statuses have outgoing moves.
    assert set(ALLOWED) == ALL_STATUSES - TERMINAL
    assert EXIT <= TERMINAL
    assert ACTIVE.isdisjoint(TERMINAL)

    # No dead ends except the endings themselves.
    for status, targets in ALLOWED.items():
        assert targets, f"{status} has no allowed moves"

    assert len(ALLOWED_PAIRS) == 26
    assert len(ILLEGAL_PAIRS) == 143
