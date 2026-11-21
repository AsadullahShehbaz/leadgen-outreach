from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.core.config import settings
from app.services.sequencing.windows import (
    SendWindow,
    in_send_window,
    next_window,
    window_from_settings,
    workspace_day,
)


WINDOW = SendWindow()


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (8, 59, False),
        (9, 0, True),
        (12, 30, True),
        (16, 59, True),
        (17, 0, False),
    ],
)
def test_window_boundaries(hour: int, minute: int, expected: bool):
    now = datetime(2026, 11, 23, hour, minute, tzinfo=timezone.utc)
    assert in_send_window(now, "UTC", WINDOW) is expected


def test_weekend_is_closed():
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    assert not in_send_window(now, "UTC", WINDOW)


def test_same_instant_uses_workspace_timezone():
    now = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)
    assert in_send_window(now, "Asia/Karachi", WINDOW)
    assert not in_send_window(now, "UTC", WINDOW)


def test_next_window_before_today_start():
    now = datetime(2026, 11, 23, 8, 30, tzinfo=ZoneInfo("UTC"))
    opening = next_window(now, "UTC", WINDOW)
    assert opening == datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def test_next_window_exact_opening():
    now = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("UTC"))
    assert next_window(now, "UTC", WINDOW) == now


def test_next_window_after_friday_close_is_monday():
    now = datetime(2026, 11, 20, 17, 0, tzinfo=ZoneInfo("UTC"))
    assert next_window(now, "UTC", WINDOW) == datetime(
        2026, 11, 23, 9, 0, tzinfo=timezone.utc
    )


def test_next_window_during_weekend_is_monday():
    now = datetime(2026, 11, 22, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert next_window(now, "UTC", WINDOW) == datetime(
        2026, 11, 23, 9, 0, tzinfo=timezone.utc
    )


def test_next_window_handles_dst():
    now = datetime(2026, 5, 9, 13, 0, tzinfo=timezone.utc)
    opening = next_window(now, "America/New_York", WINDOW)
    assert opening == datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc)


def test_workspace_day_differs_from_utc_date():
    now = datetime(2026, 11, 23, 20, 30, tzinfo=timezone.utc)
    assert workspace_day(now, "Asia/Karachi").isoformat() == "2026-11-24"
    assert workspace_day(now, "UTC").isoformat() == "2026-11-23"


def test_naive_datetime_and_unknown_timezone_raise():
    with pytest.raises(ValueError, match="timezone-aware"):
        in_send_window(datetime(2026, 11, 23, 10, 0), "UTC", WINDOW)
    with pytest.raises(ZoneInfoNotFoundError):
        in_send_window(
            datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
            "Mars/Unknown",
            WINDOW,
        )


@pytest.mark.parametrize(
    ("start", "end", "weekdays"),
    [
        (-1, 17, frozenset({1})),
        (17, 9, frozenset({1})),
        (9, 24, frozenset({1})),
        (9, 17, frozenset()),
        (9, 17, frozenset({0})),
        (9, 17, frozenset({8})),
    ],
)
def test_invalid_window_is_rejected(start: int, end: int, weekdays: frozenset):
    with pytest.raises(ValueError):
        SendWindow(start_hour=start, end_hour=end, weekdays=weekdays)


def test_window_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "send_window_start_hour", 8)
    monkeypatch.setattr(settings, "send_window_end_hour", 16)
    monkeypatch.setattr(settings, "send_window_days", "1, 3, 5")
    assert window_from_settings() == SendWindow(
        start_hour=8,
        end_hour=16,
        weekdays=frozenset({1, 3, 5}),
    )


@pytest.mark.parametrize("days", ["", "1,,2", "Monday", "1,8", "1,0"])
def test_malformed_send_window_days_raise(monkeypatch, days: str):
    monkeypatch.setattr(settings, "send_window_days", days)
    with pytest.raises(ValueError):
        window_from_settings()
