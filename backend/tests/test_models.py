from sqlalchemy import UniqueConstraint, Uuid
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table)

EXPECTED_TABLES = {
    "campaigns",
    "connections",
    "domains",
    "enrollments",
    "events",
    "experiments",
    "lead_emails",
    "leads",
    "license_state",
    "mailboxes",
    "messages",
    "sequence_steps",
    "spend_ledger",
    "suppression",
    "users",
    "workspaces",
}


def test_all_tables_exist():
    assert set(SQLModel.metadata.tables) == EXPECTED_TABLES


def test_primary_keys_are_uuid():
    for table_name in EXPECTED_TABLES:
        table = SQLModel.metadata.tables[table_name]
        assert isinstance(table.c.id.type, Uuid), table_name


def test_required_indexes_exist():
    def index_names(table_name: str) -> set[str]:
        table = SQLModel.metadata.tables[table_name]
        return {index.name for index in table.indexes}

    assert "ix_enrollments_status_next_send_at" in index_names("enrollments")
    assert "ix_leads_workspace_id_company_domain" in index_names("leads")
    assert "ix_spend_ledger_day_kind" in index_names("spend_ledger")
    assert "ix_messages_message_id" in index_names("messages")


def test_suppression_email_hash_is_unique():
    table = SQLModel.metadata.tables["suppression"]
    assert table.c.email_hash.unique is True
    assert any(
        index.unique and [column.name for column in index.columns] == ["email_hash"]
        for index in table.indexes
    )


def test_composite_unique_constraints():
    def unique_names(table_name: str) -> set[str]:
        table = SQLModel.metadata.tables[table_name]
        return {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert "uq_enrollments_campaign_id_lead_id" in unique_names("enrollments")
    assert "uq_users_workspace_id_email" in unique_names("users")
    assert "uq_lead_emails_lead_id_email" in unique_names("lead_emails")
    assert "uq_sequence_steps_campaign_id_step_no" in unique_names("sequence_steps")


def test_enrollment_mailbox_is_optional():
    # The mailbox is assigned when the first email is sent, not at enrollment.
    assert SQLModel.metadata.tables["enrollments"].c.mailbox_id.nullable is True


def test_module7_setup_fields_exist():
    workspace_table = SQLModel.metadata.tables["workspaces"]
    assert "setup_responsibility_accepted_at" in workspace_table.c
    assert "setup_completed_at" in workspace_table.c


def test_module7_connection_kind_is_unique_per_workspace():
    table = SQLModel.metadata.tables["connections"]
    assert any(
        constraint.name == "uq_connections_workspace_id_kind"
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
