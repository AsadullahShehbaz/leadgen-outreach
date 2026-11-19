from app.models.base import apply_naming_convention

# The naming convention must be set before any table class below is imported,
# because table names are generated when the class is defined.
apply_naming_convention()

# Import every model so SQLModel.metadata knows about all tables.
# Alembic and the tests rely on this.
from app.models.workspace import User, Workspace  # noqa: E402, F401
from app.models.connection import Connection  # noqa: E402, F401
from app.models.domain import Domain, Mailbox  # noqa: E402, F401
from app.models.campaign import Campaign, SequenceStep  # noqa: E402, F401
from app.models.lead import Lead, LeadEmail  # noqa: E402, F401
from app.models.enrollment import Enrollment, Event, Message  # noqa: E402, F401
from app.models.suppression import Suppression  # noqa: E402, F401
from app.models.analytics import Experiment, SpendLedger  # noqa: E402, F401
from app.models.license import LicenseState  # noqa: E402, F401

__all__ = [
    "Campaign",
    "Connection",
    "Domain",
    "Enrollment",
    "Event",
    "Experiment",
    "Lead",
    "LeadEmail",
    "LicenseState",
    "Mailbox",
    "Message",
    "SequenceStep",
    "SpendLedger",
    "Suppression",
    "User",
    "Workspace",
]
