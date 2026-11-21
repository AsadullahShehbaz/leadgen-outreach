def catchall_reason(result_reason: str) -> bool:
    if not isinstance(result_reason, str):
        return False
    text = result_reason.lower()
    return "catch" in text and "all" in text


def catchall_status(reason: str) -> str:
    return "risky" if catchall_reason(reason) else "unknown"
