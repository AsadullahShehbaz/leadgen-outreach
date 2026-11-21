import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models import Enrollment, Event
from app.services.agents.llm import LLMClient
from app.services.agents.research import ResearchClient
from app.services.budget.spend_caps import SpendLimits, reserve_usage
from app.services.sequencing.state_machine import transition


class Draft(BaseModel):
    subject: str = Field(max_length=70)
    body: str = Field(max_length=900)
    claims: list[str]


class CriticResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class DraftState(TypedDict, total=False):
    lead: dict
    campaign: dict
    context: str
    angle: str
    draft: Draft | None
    critic: CriticResult | None
    attempts: int
    human_review: bool


def score_icp(lead: dict, campaign: dict | None = None) -> float:
    campaign = campaign or {}
    score = float(lead.get("icp_score") or 0)
    target_domains = campaign.get("icp", {}).get("domains")
    domain = lead.get("company_domain")
    if isinstance(target_domains, list) and domain:
        if str(domain).lower() in {str(v).lower() for v in target_domains}:
            score = min(100.0, score + 10.0)
    return min(100.0, score)


def _significant_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) >= 4
    }


def claim_is_supported(claim: str, context: str) -> bool:
    claim_text = claim.strip().lower()
    context_text = context.strip().lower()
    if not claim_text or not context_text:
        return False
    if claim_text in context_text:
        return True
    claim_words = _significant_words(claim_text)
    context_words = _significant_words(context_text)
    if not claim_words:
        return False
    overlap = claim_words & context_words
    return len(claim_words) <= 4 and len(overlap) >= 2


def local_critic(draft: Draft, context: str) -> CriticResult:
    reasons: list[str] = []
    if len(draft.subject) > 70:
        reasons.append("subject exceeds 70 characters")
    if len(draft.body) > 900:
        reasons.append("body exceeds 900 characters")
    if len(draft.body.split()) > 120:
        reasons.append("body exceeds 120 words")

    for claim in draft.claims:
        if not claim_is_supported(claim, context):
            reasons.append(f"unsupported claim: {claim}")

    body_lower = draft.body.lower()
    if "unsubscribe" in body_lower or "postal address" in body_lower:
        reasons.append("draft includes footer or opt-out text")
    if re.search(r"\b(act now|buy now|guaranteed|risk[.-]free|limited time)\b", body_lower):
        reasons.append("draft contains spam-trigger language")
    if re.search(r"\b(i know you|i noticed you|we met|i saw your profile)\b", body_lower):
        reasons.append("draft makes unverified personal familiarity claims")

    cta_patterns = (
        r"\breply\b",
        r"\bbook\b",
        r"\bschedule\b",
        r"\bcall\b",
        r"\bcontact\b",
        r"\blet(?:'|)s\b",
        r"\bwould you\b",
    )
    cta_count = sum(1 for pattern in cta_patterns if re.search(pattern, body_lower))
    if cta_count == 0:
        reasons.append("draft has no clear call to action")
    if cta_count > 1:
        reasons.append("draft has more than one call to action")

    return CriticResult(passed=not reasons, reasons=reasons)


async def _complete_with_budget(
    llm: LLMClient,
    session,
    spend_store,
    model: str,
    messages: list,
    schema: type[BaseModel],
) -> BaseModel:
    if spend_store is not None:
        limits = SpendLimits.from_settings(settings)
        check = await reserve_usage(
            spend_store,
            "llm",
            limits,
            requested_units=1,
            requested_usd=0.001,
        )
        if not check.allowed:
            raise RuntimeError("LLM daily spend cap hit")
        if hasattr(session, "commit"):
            await session.commit()

    result = await llm.complete(model, messages, schema)
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        return schema.model_validate(result)
    raise ValueError("LLM returned an unsupported draft result")


def build_personalization_graph(
    llm: LLMClient,
    research: ResearchClient,
    session,
    spend_store=None,
):
    """Build a small LangGraph workflow. LLM calls reserve LLM spend first."""

    async def score_node(state: DraftState) -> DraftState:
        score = score_icp(state.get("lead", {}), state.get("campaign", {}))
        lead = dict(state.get("lead", {}))
        lead["icp_score"] = score
        return {**state, "lead": lead}

    async def research_node(state: DraftState) -> DraftState:
        lead = state.get("lead", {})
        domain = str(lead.get("company_domain") or "")
        context = await research.research(domain) if domain else ""
        return {
            **state,
            "context": context.strip(),
            "attempts": state.get("attempts", 0),
        }

    async def angle_node(state: DraftState) -> DraftState:
        campaign = state.get("campaign", {})
        lead = state.get("lead", {})
        product = campaign.get("product") or {}
        angle_hint = product.get("angle") if isinstance(product, dict) else None
        if not angle_hint:
            angle_hint = lead.get("title") or lead.get("company_name") or "company growth"
        return {**state, "angle": str(angle_hint)}

    async def draft_node(state: DraftState) -> DraftState:
        if not state.get("context"):
            return {
                **state,
                "human_review": True,
                "attempts": 2,
            }

        messages = [
            {"role": "system", "content": "Use only the supplied research context. Never invent claims."},
            {
                "role": "user",
                "content": (
                    f"Angle: {state.get('angle', '')}\n"
                    f"Research context: {state['context']}\n"
                    "Return JSON with subject, body, and claims."
                ),
            },
        ]
        result = await _complete_with_budget(
            llm,
            session,
            spend_store,
            settings.LLM_MODEL_LARGE,
            messages,
            Draft,
        )
        draft = result if isinstance(result, Draft) else Draft.model_validate(result)
        return {
            **state,
            "draft": draft,
            "attempts": state.get("attempts", 0) + 1,
        }

    async def critic_node(state: DraftState) -> DraftState:
        draft = state.get("draft")
        if draft is None:
            critic = CriticResult(passed=False, reasons=["missing context"])
            return {**state, "critic": critic, "human_review": True}
        critic = local_critic(draft, state.get("context", ""))
        return {**state, "critic": critic}

    async def save_node(state: DraftState) -> DraftState:
        return {**state, "human_review": False}

    async def human_review_node(state: DraftState) -> DraftState:
        return {**state, "human_review": True}

    def critic_route(state: DraftState) -> Literal["draft", "save", "human_review"]:
        critic = state.get("critic")
        if critic is not None and critic.passed:
            return "save"
        if state.get("attempts", 0) < 2:
            return "draft"
        return "human_review"

    graph = StateGraph(DraftState)
    graph.add_node("score_icp", score_node)
    graph.add_node("research", research_node)
    graph.add_node("pick_angle", angle_node)
    graph.add_node("draft", draft_node)
    graph.add_node("critic", critic_node)
    graph.add_node("save", save_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "score_icp")
    graph.add_edge("score_icp", "research")
    graph.add_edge("research", "pick_angle")
    graph.add_edge("pick_angle", "draft")
    graph.add_edge("draft", "critic")
    graph.add_conditional_edges(
        "critic",
        critic_route,
        {"draft": "draft", "save": "save", "human_review": "human_review"},
    )
    graph.add_edge("save", END)
    graph.add_edge("human_review", END)
    return graph.compile()


async def personalize_enrollment(
    session,
    enrollment: Enrollment,
    campaign,
    lead,
    lead_email,
    llm: LLMClient,
    research: ResearchClient,
    spend_store=None,
    suppression_store=None,
) -> dict[str, Any]:
    if enrollment.draft is not None:
        return {
            "paused": False,
            "human_review": False,
            "draft": enrollment.draft,
            "provider_calls": 0,
        }
    if enrollment.status != "verified":
        return {
            "paused": False,
            "human_review": True,
            "draft": None,
            "provider_calls": 0,
        }

    if suppression_store is not None:
        from app.services.compliance.suppression import is_suppressed

        if await is_suppressed(suppression_store, lead_email.email):
            session.add(
                Event(
                    enrollment_id=enrollment.id,
                    type="personalization:suppressed",
                    payload={"reason": "suppressed enrollment was not personalized"},
                )
            )
            await session.commit()
            return {
                "paused": True,
                "human_review": True,
                "draft": None,
                "provider_calls": 0,
            }

    lead_state = {
        "company_domain": lead.company_domain,
        "company_name": lead.company_name,
        "person_name": lead.person_name,
        "title": lead.title,
        "country": lead.country,
        "icp_score": lead.icp_score,
    }
    campaign_state = {"product": campaign.product, "icp": campaign.icp}
    graph = build_personalization_graph(llm, research, session, spend_store)
    try:
        result = await graph.ainvoke(
            {
                "lead": lead_state,
                "campaign": campaign_state,
                "attempts": 0,
                "human_review": False,
            }
        )
    except RuntimeError as exc:
        if "daily spend cap hit" not in str(exc):
            raise
        session.add(
            Event(
                enrollment_id=enrollment.id,
                type="personalization:spend_cap",
                payload={"reason": "LLM daily spend cap hit"},
            )
        )
        await session.commit()
        return {
            "paused": True,
            "human_review": True,
            "draft": None,
            "provider_calls": 0,
        }

    if result.get("human_review") or result.get("draft") is None:
        session.add(
            Event(
                enrollment_id=enrollment.id,
                type="personalization:human_review",
                payload={"reason": "draft rejected by local critic or missing context"},
            )
        )
        await session.commit()
        return {
            "paused": False,
            "human_review": True,
            "draft": None,
            "provider_calls": int(result.get("attempts", 0)),
        }

    draft = result["draft"]
    draft_dict = (
        draft.model_dump()
        if isinstance(draft, Draft)
        else Draft.model_validate(draft).model_dump()
    )
    enrollment.draft = draft_dict
    await transition(
        session,
        enrollment,
        "drafted",
        "personalization approved",
        {"subject": draft_dict["subject"]},
    )
    if not campaign.require_approval:
        await transition(session, enrollment, "queued", "approval not required")
    await session.commit()
    return {
        "paused": False,
        "human_review": False,
        "draft": draft_dict,
        "provider_calls": int(result.get("attempts", 0)),
    }
