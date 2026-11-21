"""module 7 setup audit fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("setup_responsibility_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_connections_workspace_id_kind",
        "connections",
        ["workspace_id", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_connections_workspace_id_kind",
        "connections",
        type_="unique",
    )
    op.drop_column("workspaces", "setup_completed_at")
    op.drop_column("workspaces", "setup_responsibility_accepted_at")
