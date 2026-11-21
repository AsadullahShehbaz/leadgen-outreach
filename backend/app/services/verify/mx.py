import asyncio
import socket
from typing import Protocol


class MxLookup(Protocol):
    async def has_mx(self, domain: str) -> bool:
        ...


class DnsMxLookup:
    async def has_mx(self, domain: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(
                domain,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            return False
        return bool(records)

    async def lookup_mx(self, domain: str) -> bool:
        return await self.has_mx(domain)


class FakeMxLookup:
    def __init__(self, has_mx: bool = True) -> None:
        self.has_mx_value = has_mx
        self.lookups: list[str] = []

    async def has_mx(self, domain: str) -> bool:
        self.lookups.append(domain)
        return self.has_mx_value
