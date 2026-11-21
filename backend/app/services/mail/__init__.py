from app.services.mail.base import (
    InboundMessage,
    MailProvider,
    OutboundMessage,
    PermanentSendError,
    TransientSendError,
)
from app.services.mail.fake import FakeMailProvider

__all__ = [
    "FakeMailProvider",
    "InboundMessage",
    "MailProvider",
    "OutboundMessage",
    "PermanentSendError",
    "TransientSendError",
]
