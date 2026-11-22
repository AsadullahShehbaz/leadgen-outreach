from uuid import uuid4

import pytest

from app.main import app
from app.schemas.dashboard import CampaignRequest, DraftResponse, SuppressionRequest
from app.routers.campaigns import router as campaigns_router
from app.routers.leads import router as leads_router
from app.routers.inbox import router as inbox_router
from app.routers.analytics import router as analytics_router
from app.routers.compliance import router as compliance_router


def test_dashboard_routes_are_registered():
    assert campaigns_router.prefix == "/campaigns"
    assert leads_router.prefix == "/leads"
    assert inbox_router.prefix == "/inbox"
    assert analytics_router.prefix == "/analytics"
    assert compliance_router.prefix == "/compliance"


def test_campaign_request_validation_is_simple():
    campaign = CampaignRequest(
        name="Partner outreach",
        product={"name": "LeadGen"},
        icp={"country": "US"},
        compliance_mode="standard",
        require_approval=True,
        sequence_steps=[],
    )
    assert campaign.name == "Partner outreach"
    assert campaign.require_approval is True


def test_duplicate_sequence_step_numbers_are_allowed_by_schema():
    campaign = CampaignRequest(
        name="Test",
        sequence_steps=[
            {"step_no": 1, "delay_days": 0},
            {"step_no": 1, "delay_days": 3},
        ],
    )
    assert len(campaign.sequence_steps) == 2


def test_suppression_request_requires_email_and_reason():
    with pytest.raises(ValueError):
        SuppressionRequest(email="", reason="")


def test_draft_response_has_no_secret_fields():
    response = DraftResponse(
        enrollment_id=uuid4(),
        status="drafted",
        subject="Short subject",
        body="Hello",
        claims=["A supported claim"],
    )
    dumped = response.model_dump()
    assert "license_token" not in dumped
    assert "encrypted_secret" not in dumped


def test_optimizer_routes_are_registered():
    paths = {route.path for route in analytics_router.routes if hasattr(route, "path")}
    assert "/analytics/optimizer" in paths
    assert "/analytics/report/preview" in paths
