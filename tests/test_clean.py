import pandas as pd
import pytest

from vireo.clean import (DataQualityError, dedup_tickets, link_orders, normalise_csat, normalise_legacy_resolved,
                         normalise_transfers, parse_timestamps, run_clean)
from vireo.ingest import read_raw
from vireo.metrics import check_baselines, add_derived


def _raw(**kw):
    row = {"ticket_id": "T1", "created_at": "2025-01-01 10:00", "first_response_at": "2025-01-01 10:05",
           "resolved_at": "2025-01-01 06:00", "source_system": "legacy_fd", "csat_score": "0", "transfers": "1",
           "customer_id": "C1", "product_sku": "S1", "order_id": ""}
    row.update(kw)
    return row


def test_duplicate_resolution_keeps_helpdesk():
    t = pd.DataFrame([_raw(source_system="legacy_fd", resolved_at="2025-01-01 06:00"),
                      _raw(source_system="helpdesk", resolved_at="2025-01-01 11:30"),
                      _raw(ticket_id="T2", source_system="legacy_fd")])
    out, n_dup = dedup_tickets(t)
    assert n_dup == 1 and len(out) == 2
    assert out.set_index("ticket_id").loc["T1", "source_system"] == "helpdesk"


def test_legacy_timezone_conversion_only_legacy_resolved():
    t = parse_timestamps(pd.DataFrame([_raw(), _raw(ticket_id="T2", source_system="helpdesk",
                                                     resolved_at="2025-01-01 11:30")]))
    out = normalise_legacy_resolved(t, 330).set_index("ticket_id")
    assert out.loc["T1", "resolved_at"] == pd.Timestamp("2025-01-01 11:30")      # 06:00 UTC -> 11:30 IST
    assert out.loc["T2", "resolved_at"] == pd.Timestamp("2025-01-01 11:30")      # helpdesk untouched
    assert out.loc["T1", "created_at"] == pd.Timestamp("2025-01-01 10:00")       # created_at untouched


def test_csat_zero_is_missing_for_legacy():
    t = pd.DataFrame([_raw(csat_score="0"), _raw(ticket_id="T2", csat_score="4"),
                      _raw(ticket_id="T3", source_system="helpdesk", csat_score="")])
    out = normalise_csat(t)
    assert out.csat.isna().tolist() == [True, False, True]
    assert out.csat.iloc[1] == 4


def test_legacy_transfers_unknown():
    t = pd.DataFrame([_raw(transfers="2"), _raw(ticket_id="T2", source_system="helpdesk", transfers="1")])
    out = normalise_transfers(t)
    assert pd.isna(out.transfers.iloc[0]) and out.transfers.iloc[1] == 1


def test_order_fallback_only_when_unique():
    orders = pd.DataFrame({"order_id": ["O1", "O2", "O3", "O9"], "customer_id": ["C1", "C2", "C2", "C5"],
                           "sku": ["S1", "S1", "S1", "S1"], "order_date": ["2025-01-01"] * 4,
                           "order_value_inr": ["100"] * 4})
    t = pd.DataFrame([_raw(ticket_id="direct", order_id="O9", customer_id="C5"),
                      _raw(ticket_id="unique", customer_id="C1"),
                      _raw(ticket_id="ambiguous", customer_id="C2"),
                      _raw(ticket_id="none", customer_id="C3")])
    out = link_orders(t, orders).set_index("ticket_id")
    assert out.loc["direct", "order_link"] == "direct" and out.loc["direct", "linked_order_id"] == "O9"
    assert out.loc["unique", "order_link"] == "fallback_unique" and out.loc["unique", "linked_order_id"] == "O1"
    assert out.loc["ambiguous", "order_link"] == "ambiguous" and out.loc["ambiguous", "linked_order_id"] == ""
    assert out.loc["none", "order_link"] == "unmatched"


@pytest.mark.real_data
def test_real_export_passes_all_assertions(cfg):
    """A2 + A3 on the actual assignment files (offline)."""
    c = run_clean(read_raw(cfg["paths"]["raw_dir"]), cfg)
    assert c.dq["clean_ticket_rows"] == 11875 and c.dq["duplicated_ticket_ids"] == 653
    assert c.dq["raw_order_link_ambiguous"] == 751                  # raw rows (31 re-imported tickets counted twice)
    assert c.dq["order_link_ambiguous"] == 720                      # D-2: reported figure, one per ticket
    # D-1: before-order tickets per link type, and the fallback ones fully partitioned by evidence
    assert c.dq["tickets_before_order_date"] == 232 and c.dq["fallback_linked_before_order_date"] == 94
    assert (c.dq["fallback_before_order_quoted_id_verified"] + c.dq["fallback_before_order_presales_enquiry"]
            + c.dq["fallback_before_order_unverifiable"]) == 94
    t = add_derived(c.tickets, cfg["policy"])
    assert check_baselines(t, cfg) == {"breach_credits_total": 992, "attended_helpdesk_transfers_total": 817}
    # open/pending tickets never carry a resolution timestamp, so they can never be a prior ticket A
    assert t.loc[~t.attended, "resolved_at"].isna().all()


@pytest.mark.real_data
def test_broken_baseline_fails_loudly(cfg):
    bad = {**cfg, "assertions": {**cfg["assertions"], "clean_ticket_rows": 1}}
    with pytest.raises(DataQualityError):
        run_clean(read_raw(cfg["paths"]["raw_dir"]), bad)
