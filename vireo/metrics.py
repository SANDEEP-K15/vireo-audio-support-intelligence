"""Deterministic metrics (PRD §6) and the tickets-closed leaderboard (PRD §16).

Week assignment (PRD §6.1) — never mixed:
  created_at week  -> incoming volume, complaint themes, bot-category reclassification, repeat contacts
  resolved_at week -> tickets closed, SLA breach credits, transfer cost, CSAT, handle time, Tier 2 days-to-resolve
A week is Monday 00:00 - Sunday 23:59 IST (all timestamps are IST after cleaning).
"""
from __future__ import annotations

import pandas as pd

from .clean import DataQualityError

TIER1_TEAMS = ["Chat Frontline", "Email Frontline", "Voice Frontline", "Logistics", "Billing", "Returns Desk"]
TIER2_TEAM = "Escalations & Warranty"
THROUGHPUT_TITLE = "Tickets closed — throughput, not performance"
THROUGHPUT_CAPTION = (
    "Ticket counts reflect queue mix, shift, channel and case complexity. They are not a measure of individual "
    "performance and must not be read as one. Agents are compared only within their own team; teams are never "
    "ranked against each other. Tier 2 (Escalations & Warranty) is not ranked on volume: its cases are multi-touch "
    "by design and are measured on resolution in days (support policy §6). Team = current roster; no roster "
    "history is available, so past team moves are invisible. SLA breaches are not shown per agent because policy "
    "attributes them to the resolving agent, not the first responder."
)


def week_start(ts: pd.Series) -> pd.Series:
    """Monday 00:00 of the week containing each timestamp."""
    d = ts.dt.normalize()
    return d - pd.to_timedelta(d.dt.weekday, unit="D")


def add_derived(t: pd.DataFrame, policy: dict) -> pd.DataFrame:
    t = t.copy()
    t["created_week"] = week_start(t.created_at)
    t["resolved_week"] = week_start(t.resolved_at)          # NaT for open/pending
    t["first_response_min"] = (t.first_response_at - t.created_at).dt.total_seconds() / 60
    t["sla_target_min"] = t.channel.map(policy["sla_target_minutes"])
    t["breach"] = t.first_response_min > t.sla_target_min  # strict: exactly on target is not a breach (§3)
    t["handle_h"] = (t.resolved_at - t.first_response_at).dt.total_seconds() / 3600   # §10 handle time
    t["days_to_resolve"] = (t.resolved_at - t.created_at).dt.total_seconds() / 86400
    t["off_roster_team"] = t.agent_team != t.assigned_team
    return t


def _week_mask(t: pd.DataFrame, week: pd.Timestamp, col: str, n_weeks: int = 1) -> pd.Series:
    start = pd.Timestamp(week) - pd.Timedelta(weeks=n_weeks - 1)
    return t[col].between(start, pd.Timestamp(week))


def trailing_mask(t: pd.DataFrame, week, col: str, n_weeks: int) -> pd.Series:
    """The n full weeks immediately BEFORE the selected week (W-n ... W-1); the selected week is excluded.
    Single definition of "trailing N weeks" used for every comparison, the leaderboard and the cost projection
    (DECISIONS.md D-5)."""
    w = pd.Timestamp(week)
    return t[col].between(w - pd.Timedelta(weeks=n_weeks), w - pd.Timedelta(weeks=1))


def full_weeks(t: pd.DataFrame) -> list[pd.Timestamp]:
    """Weeks fully covered by the export's created_at range (excludes partial first/last weeks)."""
    first, last = t.created_at.min(), t.created_at.max()
    weeks = pd.date_range(week_start(pd.Series([first]))[0], week_start(pd.Series([last]))[0], freq="7D")
    return [w for w in weeks if w >= first.normalize() and w + pd.Timedelta(days=6) <= last.normalize()]


def created_in_range(t: pd.DataFrame, start: str, end: str) -> pd.Series:
    """created_at within [start 00:00, end 23:59:59] (inclusive calendar dates)."""
    return (t.created_at >= pd.Timestamp(start)) & (t.created_at < pd.Timestamp(end) + pd.Timedelta(days=1))


# ---------------------------------------------------------------- created-week metrics
def incoming_volume(t: pd.DataFrame, week, n_weeks: int = 1) -> pd.Series:
    return t[_week_mask(t, week, "created_week", n_weeks)].groupby("channel").size()


# ---------------------------------------------------------------- resolved-week metrics
def breach_credits(t: pd.DataFrame, policy: dict, week=None, n_weeks: int = 1) -> dict:
    """Rs 350 per breached attended ticket, in the week the ticket was resolved (credit issued on resolution, §3)."""
    m = t.attended & t.breach
    if week is not None:
        m &= _week_mask(t, week, "resolved_week", n_weeks)
    by_ch = t[m].groupby("channel").size()
    n = int(m.sum())
    return {"count": n, "inr": n * policy["breach_credit_inr"],
            "by_channel": {ch: {"count": int(c), "inr": int(c) * policy["breach_credit_inr"]} for ch, c in by_ch.items()}}


def transfer_cost(t: pd.DataFrame, policy: dict, week=None, n_weeks: int = 1) -> dict:
    """Rs 305 per transfer on attended helpdesk tickets in the resolved week. Legacy transfers are unknown."""
    in_period = t.attended.copy()
    if week is not None:
        in_period &= _week_mask(t, week, "resolved_week", n_weeks)
    n = int(t.loc[in_period & ~t.is_legacy, "transfers"].sum())
    return {"count": n, "inr": n * policy["transfer_cost_inr"],
            "legacy_tickets_unknown": int((in_period & t.is_legacy).sum()),
            # transfers on still-open helpdesk tickets are not final yet (whole export, not week-bound)
            "not_yet_final_open_tickets": int(t.loc[~t.is_legacy & ~t.attended, "transfers"].sum())}


def csat(t: pd.DataFrame, week=None, n_weeks: int = 1) -> dict:
    m = t.attended.copy()
    if week is not None:
        m &= _week_mask(t, week, "resolved_week", n_weeks)
    s = t.loc[m, "csat"].dropna()
    n_att = int(m.sum())
    return {"mean": round(float(s.mean()), 2) if len(s) else None, "n": int(len(s)), "attended": n_att,
            "response_rate": round(len(s) / n_att, 3) if n_att else None}


def check_baselines(t: pd.DataFrame, cfg: dict) -> dict:
    """A3: secondary-KPI totals computed from source must match the discovery baselines for this export."""
    got = {"breach_credits_total": breach_credits(t, cfg["policy"])["count"],
           "attended_helpdesk_transfers_total": transfer_cost(t, cfg["policy"])["count"]}
    exp = cfg.get("assertions", {})
    if exp.get("strict"):
        for k, v in got.items():
            if exp.get(k) is not None and exp[k] != v:
                raise DataQualityError(f"A3 baseline {k}: expected {exp[k]}, got {v}")
    return got


# ---------------------------------------------------------------- leaderboard
def leaderboard(t: pd.DataFrame, agents: pd.DataFrame, week, trailing_weeks: int) -> dict:
    """Tier 1: per-team tables ranked within team only. Tier 2: separate, unranked, sorted by agent_id.
    Columns: the selected week, and the trailing weeks before it (selected week excluded)."""
    att = t[t.attended]
    wk = att[_week_mask(att, week, "resolved_week", 1)]
    tr = att[trailing_mask(att, week, "resolved_week", trailing_weeks)]
    pre = f"prev{trailing_weeks}w_"

    def per_agent(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        g = df.groupby("agent_id")
        return pd.DataFrame({f"{prefix}closed": g.size(),
                             f"{prefix}auto_closed": g.status.apply(lambda s: int((s == "closed").sum())),
                             f"{prefix}off_roster_team": g.off_roster_team.sum().astype(int)})

    base = agents[["agent_id", "name", "site", "shift", "team", "tier"]].set_index("agent_id")
    table = base.join(per_agent(wk, "week_")).join(per_agent(tr, pre))
    for c in table.columns:
        if c.startswith(("week_", pre)):
            table[c] = pd.to_numeric(table[c]).fillna(0).astype(int)     # agents with no tickets -> 0
    team_handle = wk.groupby("agent_team").handle_h.median()

    tier1 = {}
    for team in TIER1_TEAMS:
        tb = table[table.team == team].reset_index().sort_values(["week_closed", "agent_id"], ascending=[False, True])
        tb["rank_in_team"] = tb.week_closed.rank(method="min", ascending=False).astype(int)
        tier1[team] = {"rows": tb.to_dict("records"),
                       "team_median_handle_h": None if pd.isna(team_handle.get(team)) else round(float(team_handle[team]), 1)}

    t2 = table[table.team == TIER2_TEAM].reset_index().sort_values("agent_id")
    days = wk[wk.agent_team == TIER2_TEAM].groupby("agent_id").days_to_resolve.median()
    days_tr = tr[tr.agent_team == TIER2_TEAM].groupby("agent_id").days_to_resolve.median()
    t2["median_days_to_resolve_week"] = t2.agent_id.map(days).round(1)
    t2[f"median_days_to_resolve_{pre}"[:-1]] = t2.agent_id.map(days_tr).round(1)
    t2 = t2.rename(columns={"week_closed": "week_cases", f"{pre}closed": f"{pre}cases"})
    keep = ["agent_id", "name", "site", "shift", "week_cases", f"{pre}cases",
            "median_days_to_resolve_week", f"median_days_to_resolve_{pre}"[:-1]]
    return {"title": THROUGHPUT_TITLE, "caption": THROUGHPUT_CAPTION, "tier1": tier1,
            "tier2": t2[keep].astype(object).where(t2[keep].notna(), None).to_dict("records")}
