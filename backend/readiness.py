"""Rule-based readiness calculation and daily study planner.

This module mirrors the architecture decision for the readiness tracker:
- per-topic readiness is a transparent weighted formula
- overall readiness is weighted across topics
- pressure, mode selection, and daily plan generation are rule-based
"""

from __future__ import annotations

from typing import Iterable, List, Optional

TARGET = 85
MIN_PER_POINT = 3


def topic_readiness(quiz_acc: Optional[float], card_mastery: Optional[float], recency: float) -> Optional[float]:
    """Compute a per-topic readiness score in the 0..100 range.

    `quiz_acc` and `card_mastery` are expected to be fractions in 0..1 (not 0..100),
    while `recency` is also a fraction in 0..1. If no evidence exists, return None.
    """
    parts: List[float] = []
    weights: List[float] = []

    if quiz_acc is not None:
        parts.append(float(quiz_acc))
        weights.append(0.45)
    if card_mastery is not None:
        parts.append(float(card_mastery))
        weights.append(0.35)
    if not parts:
        return None

    parts.append(min(1.0, max(0.0, float(recency))))
    weights.append(0.20)

    score = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    return round(100 * score, 1)


def overall(topics: Iterable[dict]) -> Optional[float]:
    """Weighted mean readiness across all known topics."""
    known = [t for t in topics if t.get("readiness") is not None]
    if not known:
        return None
    weighted = sum(float(t["readiness"]) * float(t.get("weight", 1.0)) for t in known)
    total_weight = sum(float(t.get("weight", 1.0)) for t in known)
    return round(weighted / total_weight, 1) if total_weight else None


def pressure(
    topics: Iterable[dict],
    days_left: int,
    daily_minutes: int,
    target: float = TARGET,
) -> float:
    """Return the planning pressure ratio needed to choose a study mode."""
    needed = sum(
        max(0.0, target - (float(t.get("readiness") or 0.0))) * float(t.get("weight", 1.0)) * MIN_PER_POINT
        for t in topics
    )
    available = max(1, int(days_left)) * max(1, int(daily_minutes))
    return needed / available


def choose_mode(p: float, has_activity: bool) -> str:
    if not has_activity or p > 1.0:
        return "intensive"
    if p >= 0.5:
        return "steady"
    return "polish"


def build_day_plan(
    topics: Iterable[dict],
    daily_minutes: int,
    mode: str,
    due_cards: int,
    days_left: int,
    target: float = TARGET,
    days_since_last_mock: Optional[int] = None,
):
    """Build a list of plan items for the current day."""
    topics = list(topics)
    plan = []
    left = max(0, int(daily_minutes))

    if days_left <= 2:
        return [{"activity": "review", "minutes": left}]

    if due_cards:
        card_min = min(-(-due_cards * 25 // 60), int(left * 0.4))
        if card_min > 0:
            plan.append({"activity": "flashcards", "minutes": card_min, "count": due_cards})
            left -= card_min

    limit = {"polish": 3, "steady": 5}.get(mode, len(topics))
    weak = sorted(
        (
            {
                **t,
                "gap": max(0.0, target - (float(t.get("readiness") or 0.0)))
                * float(t.get("weight", 1.0)),
            }
            for t in topics
            if mode != "polish" or t.get("readiness") is not None
        ),
        key=lambda t: t["gap"],
        reverse=True,
    )
    weak = [t for t in weak if t["gap"] > 0][:limit]
    total = sum(t["gap"] for t in weak) or 1

    for index, t in enumerate(weak):
        if left <= 0:
            break
        minutes = left if index == len(weak) - 1 else min(left, max(1, round(left * t["gap"] / total)))
        plan.append({"activity": "quiz", "topic_id": t.get("id"), "minutes": minutes})
        left -= minutes

    mock_interval = {"intensive": 4, "steady": 7, "polish": 6}.get(mode)
    if (
        mock_interval
        and days_since_last_mock is not None
        and days_since_last_mock >= mock_interval
        and daily_minutes >= 40
    ):
        shortfall = max(0, sum(item["minutes"] for item in plan) + 40 - daily_minutes)
        for item in reversed(plan):
            if item["activity"] != "quiz" or shortfall <= 0:
                continue
            reduction = min(item["minutes"], shortfall)
            item["minutes"] -= reduction
            shortfall -= reduction
        plan = [item for item in plan if item["minutes"] > 0]
        if sum(item["minutes"] for item in plan) + 40 <= daily_minutes:
            plan.append({"activity": "mock", "minutes": 40})

    return plan


def coach_note(mode: str, days_left: int, overall_score: float, weakest):
    if mode == "intensive":
        weakest_name = weakest[0] if isinstance(weakest, (list, tuple)) and weakest else "your weakest topic"
        return f"{days_left} days left and readiness at {overall_score:.0f}%. Full days ahead, starting with {weakest_name}."
    if mode == "steady":
        if isinstance(weakest, (list, tuple)) and weakest:
            highlight = ", ".join(weakest[:2])
            return f"You are on track. Focus on {highlight} this week."
        return "You are on track. Keep a steady rhythm and protect your study time."
    if isinstance(weakest, (list, tuple)) and weakest:
        return f"You are ahead of schedule, so today is light. A short session on {weakest[0]} is enough."
    return "You are ahead of schedule, so today is light. Keep it short and focused."
