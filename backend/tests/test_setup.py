import pytest
from uuid import uuid4

from app.models import Domain, Mailbox
from app.schemas.setup import (
    SetupAdminRequest,
    SetupStatus,
    SetupWorkspaceRequest,
)
from app.services.compliance.footer import build_footer


def test_setup_admin_schema_requires_minimum_password():
    with pytest.raises(ValueError):
        SetupAdminRequest(
            workspace_name="Example",
            email="admin@example.com",
            password="short",
        )


def test_setup_status_does_not_expose_secrets():
    status = SetupStatus(
        initialized=True,
        admin_created=True,
        workspace_created=True,
        license_stored=True,
        llm_configured=True,
        verifier_configured=True,
        sender_configured=True,
        responsibility_accepted=True,
        complete=True,
    )
    dumped = status.model_dump()
    assert "license_token" not in dumped
    assert "encrypted_secret" not in dumped
    assert "password_hash" not in dumped


def test_setup_workspace_requires_responsibility():
    request = SetupWorkspaceRequest(
        name="Example",
        sender_identity="Example Sales",
        postal_address="123 Example Street",
        accept_responsibility=False,
    )
    assert request.accept_responsibility is False


def test_domain_and_mailbox_safety_values():
    workspace_id = uuid4()
    domain = Domain(id=uuid4(), workspace_id=workspace_id, name="example.com")
    mailbox = Mailbox(
        id=uuid4(),
        workspace_id=workspace_id,
        domain_id=domain.id,
        address="sender@example.com",
        status="warming",
        daily_cap=40,
    )
    assert mailbox.status == "warming"
    assert domain.spf_ok is False
    assert domain.dkim_ok is False
    assert domain.dmarc_ok is False


def test_sender_footer_still_requires_setup_details():
    with pytest.raises(ValueError):
        build_footer("", "123 Example Street", "https://example.com/unsubscribe")
