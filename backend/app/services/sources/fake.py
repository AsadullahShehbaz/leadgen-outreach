from app.services.sources.base import RawLead


class FakeLeadSource:
    name = "fake"

    def __init__(self, leads: list[RawLead] | None = None) -> None:
        self.leads = list(leads or [])
        self.calls: list[tuple[dict, int]] = []

    async def fetch(self, query: dict, limit: int) -> list[RawLead]:
        self.calls.append((dict(query), limit))
        return self.leads[:limit]
