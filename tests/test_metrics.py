import pandas as pd

from conftest import make_tickets
from vireo.metrics import TIER2_TEAM, breach_credits, csat, incoming_volume, leaderboard, transfer_cost, week_start

W1 = pd.Timestamp("2026-06-15")   # Monday
W2 = pd.Timestamp("2026-06-22")   # Monday


def test_week_starts_monday():
    s = pd.Series(pd.to_datetime(["2026-06-22 00:00", "2026-06-28 23:59", "2026-06-29 00:00"]))
    assert week_start(s).tolist() == [W2, W2, pd.Timestamp("2026-06-29")]


def test_sla_boundary_is_strict(cfg):
    t = make_tickets([
        {"ticket_id": "on", "created_at": "2026-06-22 10:00", "first_response_at": "2026-06-22 10:15",
         "resolved_at": "2026-06-22 11:00"},
        {"ticket_id": "over", "created_at": "2026-06-22 10:00", "first_response_at": "2026-06-22 10:16",
         "resolved_at": "2026-06-22 11:00"}], cfg["policy"])
    assert t.set_index("ticket_id").breach.to_dict() == {"on": False, "over": True}


def test_breach_credits_attended_only_and_resolved_week(cfg):
    t = make_tickets([
        # breached, created week 1, resolved week 2 -> credit in week 2
        {"ticket_id": "a", "created_at": "2026-06-21 23:00", "first_response_at": "2026-06-21 23:30",
         "resolved_at": "2026-06-22 09:00"},
        # breached but still open -> no credit
        {"ticket_id": "b", "status": "open", "created_at": "2026-06-22 10:00",
         "first_response_at": "2026-06-22 11:00"}], cfg["policy"])
    assert breach_credits(t, cfg["policy"], W1)["count"] == 0
    wk2 = breach_credits(t, cfg["policy"], W2)
    assert wk2["count"] == 1 and wk2["inr"] == 350


def test_created_vs_resolved_week_assignment(cfg):
    t = make_tickets([{"ticket_id": "x", "created_at": "2026-06-21 23:59", "resolved_at": "2026-06-22 00:01",
                       "csat": 5}], cfg["policy"])
    assert incoming_volume(t, W1).sum() == 1 and incoming_volume(t, W2).sum() == 0     # created week
    assert csat(t, W1)["n"] == 0 and csat(t, W2)["n"] == 1                            # resolved week


def test_csat_excludes_missing(cfg):
    t = make_tickets([{"ticket_id": "a", "created_at": "2026-06-22 10:00", "resolved_at": "2026-06-22 12:00", "csat": 4},
                      {"ticket_id": "b", "created_at": "2026-06-22 10:00", "resolved_at": "2026-06-22 12:00", "csat": None}],
                     cfg["policy"])
    r = csat(t, W2)
    assert r["mean"] == 4 and r["n"] == 1 and r["attended"] == 2 and r["response_rate"] == 0.5


def test_transfer_cost_helpdesk_attended_only(cfg):
    t = make_tickets([
        {"ticket_id": "h", "created_at": "2026-06-22 10:00", "resolved_at": "2026-06-22 12:00", "transfers": 2},
        {"ticket_id": "l", "created_at": "2026-06-22 10:00", "resolved_at": "2026-06-22 12:00",
         "source_system": "legacy_fd", "transfers": None},
        {"ticket_id": "o", "status": "open", "created_at": "2026-06-22 10:00", "transfers": 1}], cfg["policy"])
    r = transfer_cost(t, cfg["policy"], W2)
    assert r["count"] == 2 and r["inr"] == 610 and r["legacy_tickets_unknown"] == 1 and r["not_yet_final_open_tickets"] == 1


def test_leaderboard_tier_separation(cfg):
    agents = pd.DataFrame([
        {"agent_id": "A1", "name": "a", "site": "X", "shift": "Day", "team": "Chat Frontline", "tier": "1"},
        {"agent_id": "A2", "name": "b", "site": "X", "shift": "Day", "team": "Chat Frontline", "tier": "1"},
        {"agent_id": "A3", "name": "c", "site": "X", "shift": "Day", "team": "Logistics", "tier": "1"},
        {"agent_id": "A9", "name": "d", "site": "X", "shift": "Day", "team": TIER2_TEAM, "tier": "2"}])
    rows = [{"ticket_id": f"t{i}", "agent_id": aid, "agent_team": team, "created_at": "2026-06-22 10:00",
             "resolved_at": "2026-06-23 10:00"}
            for i, (aid, team) in enumerate([("A1", "Chat Frontline")] * 1 + [("A2", "Chat Frontline")] * 3
                                            + [("A3", "Logistics")] * 5 + [("A9", TIER2_TEAM)] * 9)]
    lb = leaderboard(make_tickets(rows, cfg["policy"]), agents, W2, 4)
    chat = lb["tier1"]["Chat Frontline"]["rows"]
    assert [r["agent_id"] for r in chat] == ["A2", "A1"] and [r["rank_in_team"] for r in chat] == [1, 2]
    assert lb["tier1"]["Logistics"]["rows"][0]["rank_in_team"] == 1          # ranked within its own team only
    assert all("rank_in_team" not in r for r in lb["tier2"])                   # Tier 2 is never ranked
    assert lb["tier2"][0]["week_cases"] == 9 and "median_days_to_resolve_week" in lb["tier2"][0]
    assert TIER2_TEAM not in lb["tier1"]
    assert lb["title"] == "Tickets closed — throughput, not performance"
    assert "not a measure of individual performance" in lb["caption"]
    banned = {"score", "performance_score", "productivity", "csat", "repeat_rate", "breach"}
    assert not banned & set(chat[0]) and not banned & set(lb["tier2"][0])


def test_trailing_window_excludes_selected_week(cfg):
    """D-5: 'trailing 4 weeks' = the 4 full weeks before the selected week, everywhere (leaderboard included)."""
    from vireo.metrics import trailing_mask
    agents = pd.DataFrame([{"agent_id": "A1", "name": "a", "site": "X", "shift": "Day", "team": "Chat Frontline",
                            "tier": "1"}])
    rows = [{"ticket_id": "in_week", "created_at": "2026-06-22 09:00", "resolved_at": "2026-06-23 10:00"},
            {"ticket_id": "w_minus_1", "created_at": "2026-06-15 09:00", "resolved_at": "2026-06-16 10:00"},
            {"ticket_id": "w_minus_4", "created_at": "2026-05-25 09:00", "resolved_at": "2026-05-26 10:00"},
            {"ticket_id": "w_minus_5", "created_at": "2026-05-18 09:00", "resolved_at": "2026-05-19 10:00"}]
    t = make_tickets(rows, cfg["policy"])
    assert t[trailing_mask(t, W2, "created_week", 4)].ticket_id.tolist() == ["w_minus_1", "w_minus_4"]
    row = leaderboard(t, agents, W2, 4)["tier1"]["Chat Frontline"]["rows"][0]
    assert row["week_closed"] == 1 and row["prev4w_closed"] == 2
