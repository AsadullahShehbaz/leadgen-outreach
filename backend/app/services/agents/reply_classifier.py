from typing import Protocol

from app.services.mail.base import InboundMessage


VALID_REPLY_CLASSES = {
    "interested",
    "question",
    "not_now",
    "not_interested",
    "unsubscribe",
    "out_of_office",
    "referral",
    "auto_reply",
    "other",
}


class ReplyClassifier(Protocol):
    async def classify(self, message: InboundMessage) -> str:
        ...


class FakeReplyClassifier:
    """Deterministic reply classifier for tests and local development."""

    def __init__(self, reply_class: str = "other") -> None:
        if reply_class not in VALID_REPLY_CLASSES:
            raise ValueError("Unknown reply class")
        self.reply_class = reply_class

    async def classify(self, message: InboundMessage) -> str:
        return self.reply_class
