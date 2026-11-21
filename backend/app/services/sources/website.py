import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.services.sources.base import LeadSource, RawLead


def is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("URL is required")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Only explicit HTTP(S) URLs are allowed")
    if parts.username or parts.password:
        raise ValueError("Credentials in URLs are not allowed")

    try:
        addresses = await __import__("asyncio").get_running_loop().getaddrinfo(
            parts.hostname,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc

    if not addresses or not any(is_public_ip(item[4][0]) for item in addresses):
        raise ValueError("Private or reserved IP addresses are not allowed")
    return url


assert_public_url = validate_public_url


class WebsiteLeadSource:
    name = "website"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        max_bytes: int = 1_000_000,
        max_pages: int = 5,
    ) -> None:
        self.client = client
        self.max_bytes = max_bytes
        self.max_pages = max_pages

    async def fetch(self, query: dict, limit: int) -> list[RawLead]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        urls = query.get("urls") or ([query["url"]] if query.get("url") else [])
        if not isinstance(urls, list) or not urls:
            raise ValueError("An explicit URL or URLs list is required")

        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(5.0),
        )
        leads: list[RawLead] = []
        try:
            for url in urls[: min(self.max_pages, limit or self.max_pages)]:
                await validate_public_url(url)
                response = await client.get(url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        continue
                    redirect_url = urljoin(url, location)
                    await validate_public_url(redirect_url)
                    response = await client.get(redirect_url)
                content = response.content[: self.max_bytes]
                if not response.is_success:
                    continue

                soup = BeautifulSoup(content, "html.parser")
                title = soup.title.string.strip() if soup.title and soup.title.string else None
                heading = soup.find(["h1", "h2"])
                company_name = heading.get_text(" ", strip=True) if heading else title
                domain = urlsplit(str(response.url)).hostname

                leads.append(
                    RawLead(
                        company_name=company_name,
                        company_domain=domain,
                        title=title,
                        source="website",
                        raw={"url": str(response.url), "status_code": response.status_code},
                    )
                )
                if len(leads) >= limit:
                    break
        finally:
            if owns_client:
                await client.aclose()
        return leads
