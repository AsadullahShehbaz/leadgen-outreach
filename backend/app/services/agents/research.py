from typing import Protocol


class ResearchClient(Protocol):
    async def research(self, company_domain: str) -> str:
        ...


class FakeResearchClient:
    def __init__(self, context: str = "") -> None:
        self.context = context
        self.domains: list[str] = []

    async def research(self, company_domain: str) -> str:
        self.domains.append(company_domain)
        return self.context
