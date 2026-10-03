import pandas as pd
import pytest

from conftest import make_tickets
from vireo.repeats import declared_repeats, repeat_summary, scope_ticket_ids

A_RESOLVED = "2026-06-01 10:00"


def _case(cfg, b_created, *, a_status="resolved", b_sku="SKU1", theme_a="PAIRING", theme_b="PAIRING", extra=None):
    rows = [{"ticket_id": "A", "status": a_status, "created_at": "2026-05-31 09:00",
             "resolved_at": A_RESOLVED if a_status in ("resolved", "closed") else None},
            {"ticket_id": "B", "status": "open", "created_at": b_created, "product_sku": b_sku, "channel": "voice"}]
    rows += extra or []
    t = make_tickets(rows, cfg["policy"])
    themes = pd.Series({"A": theme_a, "B": theme_b, **{r["ticket_id"]: theme_a for r in extra or []}})
    return repeat_summary(t, themes, cfg["policy"], t.ticket_id == "B")


def test_repeat_exactly_at_30_days(cfg):
    r = _case(cfg, "2026-07-01 10:00")
    assert r["computed"] and r["count"] == 1 and r["cost_inr"] == 520          # voice contact cost (§4)


def test_repeat_one_minute_after_30_days(cfg):
    assert _case(cfg, "2026-07-01 10:01")["count"] == 0


def test_repeat_before_resolution(cfg):
    assert _case(cfg, "2026-06-01 09:59")["count"] == 0


def test_different_sku(cfg):
    r = _case(cfg, "2026-06-05 10:00", b_sku="SKU2")
    assert r["count"] == 0


def test_different_theme(cfg):
    assert _case(cfg, "2026-06-05 10:00", theme_b="BATTERY_DRAIN")["count"] == 0


def test_other_unclear_never_repeat(cfg):
    r = _case(cfg, "2026-06-05 10:00", theme_a="OTHER_UNCLEAR", theme_b="OTHER_UNCLEAR")
    assert r["count"] == 0 and r["excluded_other_unclear_pairs"] == 1


def test_open_prior_ticket_is_never_A(cfg):
    assert _case(cfg, "2026-06-05 10:00", a_status="open")["count"] == 0


def test_b_matching_two_prior_tickets_counts_once(cfg):
    extra = [{"ticket_id": "A2", "created_at": "2026-05-30 09:00", "resolved_at": "2026-05-30 12:00"}]
    r = _case(cfg, "2026-06-05 10:00", extra=extra)
    assert r["count"] == 1 and r["coverage"]["candidate_pairs"] == 2


def test_sensitivities_and_sku_free_variant(cfg):
    r = _case(cfg, "2026-06-05 10:00")
    assert r["sensitivity_blended_inr"] == 290 and r["sensitivity_finance_inr"] == 180
    r2 = _case(cfg, "2026-06-05 10:00", b_sku="SKU2")
    assert r2["count"] == 0 and r2["without_sku_condition"] == 1


def test_not_computed_when_a_candidate_is_unclassified(cfg):
    t = make_tickets([{"ticket_id": "A", "created_at": "2026-05-31 09:00", "resolved_at": A_RESOLVED},
                      {"ticket_id": "B", "status": "open", "created_at": "2026-06-05 10:00"}], cfg["policy"])
    r = repeat_summary(t, pd.Series({"B": "PAIRING"}), cfg["policy"], t.ticket_id == "B")
    assert r["computed"] is False and "count" not in r


def test_repeat_bucketed_by_b_created_week(cfg):
    t = make_tickets([{"ticket_id": "A", "created_at": "2026-06-10 09:00", "resolved_at": "2026-06-12 10:00"},
                      {"ticket_id": "B", "created_at": "2026-06-21 23:00", "resolved_at": "2026-06-23 10:00"}],
                     cfg["policy"])
    themes = pd.Series({"A": "MIC", "B": "MIC"})
    wk = lambda d: t.created_week == pd.Timestamp(d)
    assert repeat_summary(t, themes, cfg["policy"], wk("2026-06-15"))["count"] == 1
    assert repeat_summary(t, themes, cfg["policy"], wk("2026-06-22"))["count"] == 0


def test_scope_is_same_sku_minimum(cfg):
    """PRD §14.4 (D-4): B tickets plus same-customer SAME-SKU priors only; other-SKU priors are not pulled in."""
    t = make_tickets([{"ticket_id": "A_same", "created_at": "2026-06-10 09:00", "resolved_at": "2026-06-12 10:00"},
                      {"ticket_id": "A_other", "product_sku": "SKU9", "created_at": "2026-06-10 09:00",
                       "resolved_at": "2026-06-12 10:00"},
                      {"ticket_id": "B", "created_at": "2026-06-22 10:00", "resolved_at": "2026-06-23 10:00"}],
                     cfg["policy"])
    assert scope_ticket_ids(t, t.ticket_id == "B", 30) == {"A_same", "B"}


@pytest.mark.real_data
def test_declared_repeats_reconcile_to_discovery(cfg):
    """D-3: on the real export, 406 in-window; the 78 outside split 67 / 6 / 5 exactly as discovery measured."""
    from vireo.cli import _clean
    d = declared_repeats(_clean(cfg).tickets, 30)
    assert d.status.value_counts().to_dict() == {"in_window": 406, "outside_window": 78}
    detail = d.loc[d.status == "outside_window", "outside_detail"].value_counts().to_dict()
    assert detail == {"prev_same_sku_resolved": 67, "prev_same_sku_unresolved": 6, "prev_other_sku": 5}
