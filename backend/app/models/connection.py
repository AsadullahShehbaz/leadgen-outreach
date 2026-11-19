from uuid import UUID, uuid4

from sqlmodel import Field

from app.models.base import TimestampMixin


class Connection(TimestampMixin, table=True):
    __tablename__ = "connections"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    kind: str  # llm | verifier | apollo | apify | smtp | imap
    encrypted_secret: str  # Fernet-encrypted credential; never returned by the API
    status: str = "unconfigured"
