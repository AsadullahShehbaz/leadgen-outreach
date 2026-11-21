from app.services.verify.base import VerifyResult


class FakeVerifier:
    def __init__(
        self,
        result: VerifyResult | None = None,
        results: dict[str, VerifyResult] | None = None,
    ) -> None:
        self.result = result or VerifyResult(status="unknown", reason="not configured")
        self.results = dict(results or {})
        self.calls: list[str] = []

    async def verify(self, email: str) -> VerifyResult:
        self.calls.append(email)
        return self.results.get(email, self.result)
