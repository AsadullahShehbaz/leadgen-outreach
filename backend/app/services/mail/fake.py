from app.models import Mailbox
from app.services.mail.base import (
    InboundMessage,
    OutboundMessage,
    PermanentSendError,
    TransientSendError,
)


class FakeMailProvider:
    """In-memory mail provider used by tests. It never touches the network."""

    def __init__(
        self,
        transient_failures: int = 0,
        permanent_failure: bool = False,
        message_id_prefix: str = "fake-message",
        inbound: list[InboundMessage] | None = None,
        inbound_messages: list[InboundMessage] | None = None,
    ) -> None:
        self.transient_failures = transient_failures
        self.permanent_failure = permanent_failure
        self.message_id_prefix = message_id_prefix
        self.sent: list[tuple[Mailbox, OutboundMessage, str]] = []
        self.inbound = list(inbound_messages if inbound_messages is not None else (inbound or []))
        self.fetched: list[tuple[Mailbox, int]] = []
        self._next_uid = 0

    async def send(
        self,
        mailbox: Mailbox,
        message: OutboundMessage,
    ) -> str:
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise TransientSendError("Temporary fake mail failure")
        if self.permanent_failure:
            raise PermanentSendError("Permanent fake mail failure")

        message_id = f"{self.message_id_prefix}-{len(self.sent) + 1}"
        self.sent.append((mailbox, message, message_id))
        return message_id

    async def fetch_new(
        self,
        mailbox: Mailbox,
        since_uid: int,
    ) -> list[InboundMessage]:
        """Return configured messages without network or DNS access."""
        self.fetched.append((mailbox, since_uid))
        start = since_uid
        batch = self.inbound[start:]
        self._next_uid = since_uid + len(batch)
        return batch
