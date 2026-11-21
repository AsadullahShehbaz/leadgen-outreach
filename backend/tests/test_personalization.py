from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import Enrollment
from app.services.agents.llm import FakeLLMClient
from app.services.agents.personalize_graph import (
    Draft,
    build_personalization_graph,
    local_critic,
    personalize_enrollment,
)
from app.services.agents.research import FakeResearchClient
from app.services.budget.spend_caps import SpendCheck


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class DeniedSpendStore:
    async def reserve_usage(self, kind, day, units, est_usd, limits):
        return SpendCheck(
            allowed=False,
            kind="llm",
            used_units=0,
            limit_units=0,
            used_usd=0.0,
            limit_usd=0.0,
        )


def make_objects(require_approval=True):
    enrollment = Enrollment(
        campaign_id=uuid4(),
        lead_id=uuid4(),
        lead_email_id=uuid4(),
        status="verified",
    )
    campaign = SimpleNamespace(
        product={"name": "Test CRM", "angle": "team growth"},
        icp={"domains": ["acme.example"]},
        require_approval=require_approval,
    )
    lead = SimpleNamespace(
        company_domain="acme.example",
        company_name="Acme",
        person_name="Ada",
        title="Director",
        country="US",
        icp_score=75,
    )
    lead_email = SimpleNamespace(email="ada@acme.example")
    return enrollment, campaign, lead, lead_email


def test_draft_subject_and_body_limits():
    with pytest.raises(ValidationError):
        Draft(subject="x" * 71, body="Short.", claims=["Acme exists"])
    with pytest.raises(ValidationError):
        Draft(subject="Short", body="x" * 901, claims=["Acme exists"])


def test_local_critic_accepts_supported_claim_and_one_cta():
    draft = Draft(
        subject="Grow your team",
        body="Acme expanded in Europe. Reply if this could help.",
        claims=["Acme expanded in Europe"],
    )
    result = local_critic(draft, "Acme expanded in Europe in 2026.")
    assert result.passed is True


def test_local_critic_rejects_invented_claim():
    draft = Draft(
        subject="A new idea",
        body="Your team grew revenue by 40 percent. Reply to learn more.",
        claims=["Your team grew revenue by 40 percent"],
    )
    result = local_critic(draft, "Acme is a European software company.")
    assert result.passed is False
    assert any("unsupported claim" in reason for reason in result.reasons)


def test_local_critic_rejects_spam_and_multiple_ctas():
    draft = Draft(
        subject="Limited offer",
        body="Act now and reply today. Book a call immediately.",
        claims=["Acme is a company"],
    )
    result = local_critic(draft, "Acme is a company.")
    assert result.passed is False
    assert any("spam-trigger" in reason for reason in result.reasons)
    assert any("more than one call to action" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_graph_retries_once_then_saves_supported_draft():
    session = FakeSession()
    llm = FakeLLMClient(
        [
            {
                "subject": "Team growth",
                "body": "Your team grew 40 percent. Reply to discuss.",
                "claims": ["Your team grew 40 percent"],
            },
            {
                "subject": "Team growth",
                "body": "Acme expanded in Europe. Reply to discuss.",
                "claims": ["Acme expanded in Europe"],
            },
        ]
    )
    graph = build_personalization_graph(
        llm,
        FakeResearchClient("Acme expanded in Europe."),
        session,
    )
    result = await graph.ainvoke(
        {
            "lead": {"company_domain": "acme.example", "title": "Director"},
            "campaign": {"product": {"angle": "team growth"}, "icp": {}},
            "attempts": 0,
            "human_review": False,
        }
    )

    assert result["human_review"] is False
    assert result["draft"].claims == ["Acme expanded in Europe"]
    assert result["attempts"] == 2
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_graph_stops_after_two_rejected_drafts():
    session = FakeSession()
    llm = FakeLLMClient(
        {
            "subject": "Big claim",
            "body": "Acme doubled revenue overnight. Reply to learn more.",
            "claims": ["Acme doubled revenue overnight"],
        }
    )
    graph = build_personalization_graph(
        llm,
        FakeResearchClient("Acme is a software company."),
        session,
    )
    result = await graph.ainvoke(
        {
            "lead": {"company_domain": "acme.example"},
            "campaign": {"product": {}, "icp": {}},
            "attempts": 0,
            "human_review": False,
        }
    )

    assert result["human_review"] is True
    assert result["draft"] is not None
    assert result["attempts"] == 2
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_missing_context_routes_to_human_review_without_llm_call():
    session = FakeSession()
    llm = FakeLLMClient({})
    graph = build_personalization_graph(
        llm,
        FakeResearchClient(""),
        session,
    )
    result = await graph.ainvoke(
        {
            "lead": {"company_domain": "acme.example"},
            "campaign": {"product": {}, "icp": {}},
            "attempts": 0,
            "human_review": False,
        }
    )

    assert result["human_review"] is True
    assert llm.calls == []


@pytest.mark.asyncio
async def test_approved_draft_transitions_verified_to_drafted():
    enrollment, campaign, lead, lead_email = make_objects(require_approval=True)
    session = FakeSession()
    llm = FakeLLMClient(
        {
            "subject": "Europe expansion",
            "body": "Acme expanded in Europe. Reply to discuss.",
            "claims": ["Acme expanded in Europe"],
        }
    )
    result = await personalize_enrollment(
        session,
        enrollment,
        campaign,
        lead,
        lead_email,
        llm,
        FakeResearchClient("Acme expanded in Europe."),
    )

    assert result["draft"]["subject"] == "Europe expansion"
    assert result["human_review"] is False
    assert enrollment.status == "drafted"
    assert enrollment.draft["claims"] == ["Acme expanded in Europe"]


@pytest.mark.asyncio
async def test_no_approval_requirement_moves_draft_to_queued():
    enrollment, campaign, lead, lead_email = make_objects(require_approval=False)
    session = FakeSession()
    llm = FakeLLMClient(
        {
            "subject": "Europe expansion",
            "body": "Acme expanded in Europe. Reply to discuss.",
            "claims": ["Acme expanded in Europe"],
        }
    )
    await personalize_enrollment(
        session,
        enrollment,
        campaign,
        lead,
        lead_email,
        llm,
        FakeResearchClient("Acme expanded in Europe."),
    )

    assert enrollment.status == "queued"


@pytest.mark.asyncio
async def test_llm_spend_cap_pauses_before_provider_call():
    enrollment, campaign, lead, lead_email = make_objects()
    session = FakeSession()
    llm = FakeLLMClient({})
    result = await personalize_enrollment(
        session,
        enrollment,
        campaign,
        lead,
        lead_email,
        llm,
        FakeResearchClient("Acme expanded in Europe."),
        spend_store=DeniedSpendStore(),
    )

    assert result["paused"] is True
    assert result["provider_calls"] == 0
    assert llm.calls == []


@pytest.mark.asyncio
async def test_existing_draft_is_idempotent():
    enrollment, campaign, lead, lead_email = make_objects()
    enrollment.status = "drafted"
    enrollment.draft = {
        "subject": "Saved",
        "body": "Acme expanded in Europe. Reply to discuss.",
        "claims": ["Acme expanded in Europe"],
    }
    session = FakeSession()
    llm = FakeLLMClient({})

    result = await personalize_enrollment(
        session,
        enrollment,
        campaign,
        lead,
        lead_email,
        llm,
        FakeResearchClient("Acme expanded in Europe."),
    )

    assert result["provider_calls"] == 0
    assert result["draft"] == enrollment.draft
    assert llm.calls == []
