from typing import Any

import httpx

from app.services.verify.base import VerifyResult, Verifier


class ApiVerifier:
    name = "api"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint:
            raise ValueError("Verifier endpoint is required")
        if not api_key:
            raise ValueError("Verifier API key is required")
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client

    async def verify(self, email: str) -> VerifyResult:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        try:
            response = await client.post(
                self.endpoint,
                json={"email": email},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        finally:
            if owns_client:
                await client.aclose()

        status = payload.get("status")
        if status not in {"valid", "risky", "invalid", "unknown"}:
            status = "unknown"
        reason = str(payload.get("reason", "Provider did not give a reason"))
        return VerifyResult(
            status=status,
            reason=reason,
            role_based=bool(payload.get("role_based", False)),
        )
