import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BounceResult:
    kind: Literal["hard", "soft", "unknown"]
    status_code: str | None


_DSN_STATUS = re.compile(r"\b([45])\.(\d{1,3})\.(\d{1,3})\b")


def parse_bounce(raw_text: str) -> BounceResult:
    """Parse a DSN status code; ordinary email text stays unknown."""
    if not isinstance(raw_text, str):
        return BounceResult("unknown", None)

    match = _DSN_STATUS.search(raw_text)
    if match is None:
        return BounceResult("unknown", None)

    status_code = ".".join(match.groups())
    kind: Literal["hard", "soft", "unknown"]
    if match.group(1) == "5":
        kind = "hard"
    elif match.group(1) == "4":
        kind = "soft"
    else:
        kind = "unknown"
    return BounceResult(kind, status_code)


# Clear aliases for callers that use DSN or status terminology.
parse_dsn = parse_bounce
parse_bounce_status = parse_bounce
parse_status = parse_bounce
