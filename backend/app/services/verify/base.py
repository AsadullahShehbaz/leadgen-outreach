from typing import Literal, Protocol

from pydantic import BaseModel


class VerifyResult(BaseModel):
    status: Literal["valid", "risky", "invalid", "unknown"]
    reason: str
    role_based: bool = False


class Verifier(Protocol):
    async def verify(self, email: str) -> VerifyResult:
        ...
