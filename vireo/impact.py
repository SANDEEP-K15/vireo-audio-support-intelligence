"""Business-impact arithmetic (PRD §12). Measures cost of repeat contacts; makes no savings claim."""
from __future__ import annotations

SCENARIO_TEMPLATE = ("Illustrative arithmetic, not a forecast or savings claim: if repeat contacts were {pct}% lower, "
                     "the trailing-12-month repeat cost would be Rs {inr:,} lower.")

NO_CLAIM_NOTE = ("These figures measure the cost of repeat contacts under support policy §4/§10. The tool itself does "
                 "not reduce contacts; any reduction depends on Vireo acting on the drivers. Repeat cost, SLA breach "
                 "credits and transfer cost are separate lines and are not added together, because one ticket can "
                 "appear in more than one of them.")


def illustrative_scenarios(trailing_12m_repeat_inr: int | None, pcts: list[int]) -> list[str]:
    if trailing_12m_repeat_inr is None:
        return []
    return [SCENARIO_TEMPLATE.format(pct=p, inr=round(trailing_12m_repeat_inr * p / 100)) for p in pcts]


def monthly_ai_cost_usd(mean_cost_per_ticket: float | None, mean_weekly_tickets: float) -> float | None:
    """Projected steady-state monthly AI cost (PRD §14.2)."""
    if mean_cost_per_ticket is None:
        return None
    return mean_cost_per_ticket * mean_weekly_tickets * 52 / 12
