from datetime import datetime, timedelta, timezone

import pytest

from app.services.agents.optimizer import (
    build_weekly_report,
    choose_variant,
    negative_outcome_ready,
    rank_leads,
    update_variant_stats,
)


def test_variant_selection_round_robin_before_threshold():
    arms = {
        "subject-a": {"sent": 29, "beta_alpha": 1, "beta_beta": 1},
        "subject-b": {"sent": 28, "beta_alpha": 2, "beta_beta": 1},
    }
    assert choose_variant(arms, minimum_sample=30) == "subject-b"


def test_variant_selection_can_shift_after_threshold():
    arms = {
        "a": {"sent": 50, "beta_alpha": 30, "beta_beta": 5},
        "b": {"sent": 50, "beta_alpha": 2, "beta_beta": 20},
    }
    assert choose_variant(
        arms,
        minimum_sample=30,
        rng=lambda alpha, beta: 0.9 if alpha > beta else 0.1,
    ) == "a"


def test_variant_outcome_update_is_replay_safe():
    stats = {"sent": 1, "successes": 0, "failures": 0}
    updated = update_variant_stats(stats, "event-1", positive=True)
    replayed = update_variant_stats(updated, "event-1", positive=True)
    assert updated["successes"] == 1
    assert replayed["successes"] == 1
    assert replayed["observed_keys"] == ["event-1"]


def test_rank_leads_is_deterministic_and_feature_safe():
    positive = [{"industry": "software", "title": "VP Sales", "country": "US"}]
    ranked = rank_leads([
        {"id": "2", "icp_score": 70, "industry": "unknown", "title": "CEO", "country": "CA"},
        {"id": "1", "icp_score": 70, "industry": "Software", "title": "VP Sales", "country": "US"},
    ], positive)
    assert ranked[0]["id"] == "1"
    assert all("email" not in row for row in ranked)


def test_negative_outcome_waits_for_window():
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    sent = now - timedelta(days=13)
    assert negative_outcome_ready(sent, now, outcome_window_days=14) is False
    assert negative_outcome_ready(sent - timedelta(days=1), now, outcome_window_days=14) is True


def test_weekly_report_safe_zero_values():
    report = build_weekly_report(
        workspace_name="Acme",
        week_start=datetime(2026, 11, 16, tzinfo=timezone.utc),
        sent=0,
        positive_replies=0,
        best_segment=None,
        best_angle=None,
        spend_by_kind={"llm": 0, "verify": 0, "source": 0},
    )
    assert report["sent"] == 0
    assert report["positive_reply_rate"] == 0
    assert report["cost_per_positive_reply_usd"] is None
    assert "ada@example.com" not in str(report)


def test_weekly_report_has_no_private_fields():
    report = build_weekly_report(
        workspace_name="Acme",
        week_start=datetime(2026, 11, 16, tzinfo=timezone.utc),
        sent=10,
        positive_replies=2,
        best_segment="software",
        best_angle="team growth",
        spend_by_kind={"llm": 1.0, "verify": 0.2, "source": 0.3},
    )
    dumped = str(report)
    assert "email" not in dumped
    assert "body" not in dumped
    assert "license" not in dumped
    assert report["cost_per_positive_reply_usd"] == pytest.approx(0.75)
