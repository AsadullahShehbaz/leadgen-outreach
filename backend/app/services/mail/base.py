from dataclasses import dataclass, field
from typing import Protocol

from app.models import Mailbox


class TransientSendError(Exception):
    """A temporary provider failure that should be retried later."""


class PermanentSendError(Exception):
    """A provider failure that is not a transient delivery problem."""


@dataclass(frozen=True)
class OutboundMessage:
    from_address: str
    to_address: str
    subject: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()
    from_address: str = ""
    to_address: str = ""
    subject: str = ""
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class MailProvider(Protocol):
    async def send(
        self,
        mailbox: Mailbox,
        message: OutboundMessage,
    ) -> str:
        """Send a message and return the provider's stable Message-ID."""
        ...

    async def fetch_new(
        self,
        mailbox: Mailbox,
        since_uid: int,
    ) -> list[InboundMessage]:
        """Fetch messages newer than the provider UID cursor."""
        ...
