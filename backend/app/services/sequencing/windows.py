from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


@dataclass(frozen=True)
class SendWindow:
    start_hour: int = 9
    end_hour: int = 17
    weekdays: frozenset[int] = frozenset({1, 2, 3, 4, 5})

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < self.end_hour <= 23:
            raise ValueError("Window hours must satisfy 0 <= start < end <= 23")
        if not self.weekdays:
            raise ValueError("Window weekdays cannot be empty")
        if any(day not in range(1, 8) for day in self.weekdays):
            raise ValueError("Window weekdays must be ISO numbers from 1 to 7")


def window_from_settings() -> SendWindow:
    weekdays: set[int] = set()
    raw_days = settings.send_window_days.strip()
    if not raw_days:
        raise ValueError("SEND_WINDOW_DAYS cannot be empty")

    for item in raw_days.split(","):
        item = item.strip()
        if not item:
            raise ValueError("SEND_WINDOW_DAYS contains an empty weekday")
        try:
            day = int(item)
        except ValueError as exc:
            raise ValueError(
                "SEND_WINDOW_DAYS must be comma-separated ISO weekday numbers"
            ) from exc
        weekdays.add(day)

    return SendWindow(
        start_hour=settings.send_window_start_hour,
        end_hour=settings.send_window_end_hour,
        weekdays=frozenset(weekdays),
    )


def _local_now(now: datetime, tz_name: str) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    timezone_info = ZoneInfo(tz_name)
    return now.astimezone(timezone_info)


def in_send_window(now: datetime, tz_name: str, window: SendWindow) -> bool:
    local = _local_now(now, tz_name)
    return (
        local.isoweekday() in window.weekdays
        and window.start_hour <= local.hour < window.end_hour
    )


def workspace_day(now: datetime, tz_name: str) -> date:
    return _local_now(now, tz_name).date()


def next_window(
    now: datetime, tz_name: str, window: SendWindow
) -> datetime:
    local = _local_now(now, tz_name)
    timezone_info = local.tzinfo

    for offset in range(8):
        candidate_date = local.date() + timedelta(days=offset)
        if candidate_date.isoweekday() not in window.weekdays:
            continue

        opening = datetime.combine(
            candidate_date,
            time(hour=window.start_hour),
            tzinfo=timezone_info,
        )
        if offset == 0 and local.time() < time(hour=window.start_hour):
            return opening.astimezone(timezone.utc)
        if offset == 0 and local.time() < time(hour=window.end_hour):
            return opening.astimezone(timezone.utc)
        if offset > 0:
            return opening.astimezone(timezone.utc)

    raise ValueError("Could not find a valid send window")
