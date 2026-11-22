from datetime import datetime, timedelta, timezone
from math import isfinite
from random import betavariate
from typing import Iterable, Mapping, Sequence


POSITIVE_REPLY_CLASSES = {"interested", "question"}


def choose_variant(
    arms: Mapping[str, Mapping[str, float | int]],
    minimum_sample: int = 30,
    rng=None,
) -> str:
    """Choose a variant with round-robin sampling before the threshold."""
    if not arms:
        raise ValueError("at least one variant arm is required")
    if isinstance(minimum_sample, bool) or minimum_sample < 1:
        raise ValueError("minimum_sample must be a positive integer")

    normalized = []
    for variant_id, stats in arms.items():
        sent = int(stats.get("sent", 0))
        normalized.append((str(variant_id), sent))

    lowest_sent = min(sent for _, sent in normalized)
    candidates = [variant_id for variant_id, sent in normalized if sent == lowest_sent]
    if lowest_sent < minimum_sample:
        return sorted(candidates)[0]

    sampler = rng if rng is not None else betavariate
    best_id = normalized[0][0]
    best_score = -1.0
    for variant_id, stats in arms.items():
        alpha = max(1.0, float(stats.get("beta_alpha", 1.0)))
        beta = max(1.0, float(stats.get("beta_beta", 1.0)))
        score = float(sampler(alpha, beta))
        if score > best_score:
            best_id = str(variant_id)
            best_score = score
    return best_id


def update_variant_stats(
    stats: dict,
    observation_id: str,
    positive: bool,
) -> dict:
    """Apply one replay-safe success or failure to experiment stats."""
    if not isinstance(observation_id, str) or not observation_id:
        raise ValueError("observation_id is required")
    if not isinstance(positive, bool):
        raise ValueError("positive must be a boolean")

    result = dict(stats)
    observed = set(result.get("observed_keys", []))
    if observation_id in observed:
        return result

    observed.add(observation_id)
    result["observed_keys"] = sorted(observed)
    result["sent"] = max(0, int(result.get("sent", 0)))
    result["successes"] = max(0, int(result.get("successes", 0)))
    result["failures"] = max(0, int(result.get("failures", 0)))
    result["beta_alpha"] = max(1.0, float(result.get("beta_alpha", 1.0)))
    result["beta_beta"] = max(1.0, float(result.get("beta_beta", 1.0)))

    if positive:
        result["successes"] += 1
        result["beta_alpha"] += 1.0
    else:
        result["failures"] += 1
        result["beta_beta"] += 1.0
    return result


def rank_leads(
    leads: Iterable[Mapping[str, object]],
    positive_features: Sequence[Mapping[str, object]] | None = None,
) -> list[dict]:
    """Sort leads with a simple transparent feature-weight model."""
    positive_features = positive_features or []
    weights: dict[str, float] = {}

    for feature_name in ("industry", "size", "title", "country"):
        positive_values = {
            str(row.get(feature_name)).strip().lower()
            for row in positive_features
            if row.get(feature_name) not in (None, "")
        }
        if positive_values:
            weights[feature_name] = 1.0

    ranked = []
    for lead in leads:
        score = float(lead.get("icp_score") or 0.0)
        if not isfinite(score):
            score = 0.0

        for feature_name, weight in weights.items():
            value = lead.get(feature_name)
            if value not in (None, ""):
                normalized = str(value).strip().lower()
                if normalized in {
                    str(row.get(feature_name)).strip().lower()
                    for row in positive_features
                    if row.get(feature_name) not in (None, "")
                }:
                    score += weight

        lead_id = lead.get("id")
        ranked.append({
            "id": str(lead_id) if lead_id is not None else "",
            "score": round(score, 4),
        })
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))


def negative_outcome_ready(
    sent_at: datetime,
    now: datetime,
    outcome_window_days: int = 14,
) -> bool:
    if outcome_window_days < 1:
        raise ValueError("outcome_window_days must be positive")
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - sent_at >= timedelta(days=outcome_window_days)


def build_weekly_report(
    *,
    workspace_name: str,
    week_start: datetime,
    sent: int,
    positive_replies: int,
    best_segment: str | None,
    best_angle: str | None,
    spend_by_kind: Mapping[str, float],
) -> dict:
    if sent < 0 or positive_replies < 0:
        raise ValueError("counts must be non-negative")
    if positive_replies > sent:
        raise ValueError("positive replies cannot exceed sent")

    spend = {
        kind: round(max(0.0, float(spend_by_kind.get(kind, 0.0))), 6)
        for kind in ("llm", "verify", "source")
    }
    total_spend = round(sum(spend.values()), 6)
    cost_per_positive = round(total_spend / positive_replies, 6) if positive_replies else None
    reply_rate = round(positive_replies / sent, 6) if sent else 0.0

    return {
        "workspace": workspace_name,
        "week_start": week_start.astimezone(timezone.utc).isoformat(),
        "sent": sent,
        "positive_replies": positive_replies,
        "positive_reply_rate": reply_rate,
        "best_segment": best_segment,
        "best_angle": best_angle,
        "spend_by_kind": spend,
        "cost_per_positive_reply_usd": cost_per_positive,
        "action": (
            "Keep the current winner"
            if positive_replies > 0
            else "Collect more send and reply outcomes before changing variants"
        ),
    }
