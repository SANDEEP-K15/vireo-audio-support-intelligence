"""Cleaning rules C2-C11 (PRD §7). Every rule is a small function so it can be unit-tested."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

ATTENDED = ("resolved", "closed")          # policy §10 "Attendance"
CHANNELS = ("chat", "email", "voice", "social")
TS_COLS = ("created_at", "first_response_at", "resolved_at")


class DataQualityError(AssertionError):
    """Raised when a cleaning invariant or a configured baseline assertion fails."""


@dataclass
class CleanData:
    tickets: pd.DataFrame
    agents: pd.DataFrame
    orders: pd.DataFrame
    products: pd.DataFrame
    dq: dict = field(default_factory=dict)       # C11 data-quality summary
    warnings: list = field(default_factory=list)


# ---------- C2 ----------
def dedup_tickets(t: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep one row per ticket_id; where helpdesk and legacy_fd both exist, keep helpdesk."""
    n_dup_ids = int(t.loc[t.ticket_id.duplicated(keep=False), "ticket_id"].nunique())
    rank = t.source_system.map({"helpdesk": 0, "legacy_fd": 1}).fillna(2)
    out = (t.assign(_rank=rank).sort_values(["ticket_id", "_rank"], kind="stable")
           .drop_duplicates("ticket_id", keep="first").drop(columns="_rank"))
    return out.reset_index(drop=True), n_dup_ids


# ---------- timestamps / C3 ----------
def parse_timestamps(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    for c in TS_COLS:
        t[c] = pd.to_datetime(t[c].replace("", None), format="%Y-%m-%d %H:%M")
    return t


def normalise_legacy_resolved(t: pd.DataFrame, offset_minutes: int) -> pd.DataFrame:
    """Legacy resolved_at was rebuilt from a UTC event log (policy §9); shift it to IST."""
    t = t.copy()
    legacy = t.source_system == "legacy_fd"
    t.loc[legacy, "resolved_at"] = t.loc[legacy, "resolved_at"] + pd.Timedelta(minutes=offset_minutes)
    return t


# ---------- C4 / C5 / C6 ----------
def normalise_csat(t: pd.DataFrame) -> pd.DataFrame:
    """Blank = no response (policy §8); legacy rows use 0 for no response."""
    t = t.copy()
    s = pd.to_numeric(t.csat_score.replace("", None))
    s = s.where(~((t.source_system == "legacy_fd") & (s == 0)))
    t["csat"] = s.astype("Float64")
    return t


def normalise_transfers(t: pd.DataFrame) -> pd.DataFrame:
    """The transfers field exists only in the current helpdesk (policy §9): legacy -> unknown."""
    t = t.copy()
    s = pd.to_numeric(t.transfers.replace("", None)).astype("Int64")
    t["transfers"] = s.where(t.source_system == "helpdesk", pd.NA)
    return t


def parse_refunds(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["refund_inr"] = pd.to_numeric(t.refund_amount_inr.replace("", None)).astype("Float64")
    return t


_NOTE_AMOUNT = re.compile(r"(?:rs\.?\s*|refund(?:ed)?\s*(?:of\s*)?(?:rs\.?\s*)?|\()(\d{2,6})", re.I)


def note_refund_amount(note: str) -> float | None:
    m = _NOTE_AMOUNT.search(note or "")
    return float(m.group(1)) if m else None


# ---------- C7 ----------
def link_orders(t: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Direct order_id first; customer_id+sku fallback only when exactly one order matches."""
    t = t.copy()
    counts = orders.groupby(["customer_id", "sku"]).order_id.agg(["count", "first"])
    key = list(zip(t.customer_id, t.product_sku, strict=False))
    n = pd.Series([counts["count"].get(k, 0) for k in key], index=t.index)
    first = pd.Series([counts["first"].get(k) for k in key], index=t.index)
    direct = t.order_id != ""
    t["order_link"] = "unmatched"
    t.loc[direct, "order_link"] = "direct"
    t.loc[~direct & (n == 1), "order_link"] = "fallback_unique"
    t.loc[~direct & (n > 1), "order_link"] = "ambiguous"
    t["linked_order_id"] = t.order_id.where(direct, first.where(n == 1, ""))
    t.loc[t.linked_order_id.isna(), "linked_order_id"] = ""
    o = orders.set_index("order_id")
    t["order_date"] = pd.to_datetime(t.linked_order_id.map(o.order_date))
    t["order_value_inr"] = pd.to_numeric(t.linked_order_id.map(o.order_value_inr))
    return t


# ---------- C8 ----------
def join_agents(t: pd.DataFrame, agents: pd.DataFrame) -> pd.DataFrame:
    a = agents[["agent_id", "name", "site", "team", "shift", "tier"]].rename(
        columns={"name": "agent_name", "team": "agent_team", "site": "agent_site",
                 "shift": "agent_shift", "tier": "agent_tier"})
    out = t.merge(a, on="agent_id", how="left", validate="many_to_one")
    out["agent_tier"] = pd.to_numeric(out.agent_tier).astype("Int64")
    return out


_ORDER_REF = re.compile(r"\bVR\d{6}\b", re.I)


def _before_order_breakdown(t: pd.DataFrame) -> dict:
    """Split fallback-linked tickets that predate their linked order by evidence (DECISIONS.md D-1):
    quoted   - the customer quoted exactly the linked order id in the message (link verified)
    presales - intake category Product Enquiry (asking before buying; customer-product relationship is genuine)
    other    - no evidence either way (upper bound on fallback-link artifacts)"""
    b = t[t.created_before_order & (t.order_link == "fallback_unique")]
    quoted = pd.Series([lid.upper() in {x.upper() for x in _ORDER_REF.findall(msg)}
                        for lid, msg in zip(b.linked_order_id, b.customer_message, strict=True)], index=b.index, dtype=bool)
    presales = (b.category == "Product Enquiry") & ~quoted
    return {"fallback_before_order_quoted_id_verified": int(quoted.sum()),
            "fallback_before_order_presales_enquiry": int(presales.sum()),
            "fallback_before_order_unverifiable": int((~quoted & ~presales).sum())}


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise DataQualityError(msg)


def run_clean(raw: dict[str, pd.DataFrame], cfg: dict) -> CleanData:
    pol, exp = cfg["policy"], cfg.get("assertions", {})
    strict = exp.get("strict", False)
    t_raw, orders, agents, products = raw["tickets"], raw["orders"], raw["agents"], raw["products"]
    dq: dict = {}
    warnings: list[str] = []

    # C1 facts + raw-level measurements made before any transformation
    dq["raw_ticket_rows"], dq["raw_ticket_columns"] = len(t_raw), t_raw.shape[1]
    r = parse_timestamps(t_raw)
    leg = r.source_system == "legacy_fd"
    dq["raw_legacy_resolved_before_created"] = int((leg & (r.resolved_at < r.created_at)).sum())
    raw_links = link_orders(t_raw, orders).order_link.value_counts()
    for k in ("direct", "fallback_unique", "ambiguous", "unmatched"):
        dq[f"raw_order_link_{k}"] = int(raw_links.get(k, 0))

    # C2-C6
    t, dq["duplicated_ticket_ids"] = dedup_tickets(t_raw)
    t = parse_timestamps(t)
    t = normalise_legacy_resolved(t, pol["legacy_resolved_utc_offset_minutes"])
    t = normalise_csat(t)
    t = normalise_transfers(t)
    t = parse_refunds(t)
    # C7-C9
    t = link_orders(t, orders)
    t = join_agents(t, agents)
    t["created_before_order"] = t.order_date.notna() & (t.created_at < t.order_date)
    t["attended"] = t.status.isin(ATTENDED)
    t["is_legacy"] = t.source_system == "legacy_fd"

    links = t.order_link.value_counts()
    dq.update({
        "clean_ticket_rows": len(t),
        "order_link_direct": int(links.get("direct", 0)),
        "order_link_fallback_unique": int(links.get("fallback_unique", 0)),
        "order_link_ambiguous": int(links.get("ambiguous", 0)),
        "order_link_unmatched": int(links.get("unmatched", 0)),
        # C9 (DECISIONS.md D-1): reported per link type, then split by the evidence available for each ticket.
        "tickets_before_order_date": int((t.created_before_order & (t.order_link == "direct")).sum()),
        "fallback_linked_before_order_date": int((t.created_before_order & (t.order_link == "fallback_unique")).sum()),
        **_before_order_breakdown(t),
        "open_or_pending": int((~t.attended).sum()),
        "agents": int(agents.agent_id.nunique()),
        "legacy_tickets": int(t.is_legacy.sum()),
        "csat_responses": int(t.csat.notna().sum()),
    })

    # C6 guards (warnings, never silent conversion)
    over = t.refund_inr.notna() & t.order_value_inr.notna() & (t.refund_inr > t.order_value_inr)
    note_amt = t.agent_notes.map(note_refund_amount)
    mismatch = t.refund_inr.notna() & note_amt.notna() & (t.refund_inr != note_amt)
    dq["refund_exceeds_order_value"] = int(over.sum())
    dq["refund_note_amount_mismatch"] = int(mismatch.sum())
    if over.any():
        warnings.append(f"{int(over.sum())} refunds exceed the linked order value (check money units, policy §9)")
    if mismatch.any():
        warnings.append(f"{int(mismatch.sum())} refunds differ from the amount stated in the agent note")

    # Invariants: always true for a correctly cleaned export (fail loudly)
    _check(t.ticket_id.is_unique, "ticket_id not unique after dedup")
    _check(not (t.resolved_at < t.created_at).any(), "resolved_at before created_at after timezone fix")
    _check(not (t.resolved_at < t.first_response_at).any(), "resolved_at before first_response_at after fix")
    _check(t.csat.dropna().between(1, 5).all(), "CSAT outside 1-5 after cleaning")
    _check(t.loc[t.is_legacy, "transfers"].isna().all(), "legacy transfers not nulled")
    _check(t.loc[t.attended, "resolved_at"].notna().all(), "attended ticket without resolved_at")
    _check(t.loc[~t.attended, "resolved_at"].isna().all(), "open/pending ticket with resolved_at")
    _check(t.agent_team.notna().all(), "agent_id not found in agents.csv")
    _check(t.channel.isin(CHANNELS).all(), "unknown channel")
    _check(t.status.isin(ATTENDED + ("open", "pending")).all(), "unknown status")

    # Baseline assertions for this export (PRD §7 / A2)
    if strict:
        for key, expected in exp.items():
            if key in ("strict", "breach_credits_total", "attended_helpdesk_transfers_total"):
                continue  # A3 metric baselines are checked in metrics.check_baselines
            _check(dq.get(key) == expected, f"assertion {key}: expected {expected}, got {dq.get(key)}")

    return CleanData(tickets=t, agents=agents, orders=orders, products=products, dq=dq, warnings=warnings)
