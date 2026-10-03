"""Repeat-contact engine (PRD §11) — the primary business metric.

Ticket B is a repeat contact if some ticket A exists with:
  1. A attended and A.resolved_at not null      (open/pending tickets are never A)
  2. same customer_id
  3. same product_sku                           (operationalises "same issue"; sensitivity reported without it)
  4. A.resolved_at < B.created_at <= A.resolved_at + 30 days
  5. theme(A) == theme(B), neither OTHER_UNCLEAR
B counts once, may have any status, and is bucketed in B's created week.
Figures are computed only where every B and every candidate A is classified (no extrapolation).
"""
from __future__ import annotations

import re

import pandas as pd

OTHER = "OTHER_UNCLEAR"

# Validation proxy only (PRD §13.3): customer explicitly says they contacted Vireo about this before.
DECLARED_REPEAT = re.compile(
    r"(?:second|third|fourth) time|third ticket|same issue as before|still not fixed after|"
    r"already raised this|was told it was resolved|same thing", re.I)


def candidate_pairs(t: pd.DataFrame, window_days: int, same_sku: bool = True) -> pd.DataFrame:
    """All (A, B) pairs satisfying conditions 1-4 (or 1, 2, 4 when same_sku=False)."""
    a = t.loc[t.attended & t.resolved_at.notna(), ["ticket_id", "customer_id", "product_sku", "resolved_at"]]
    b = t[["ticket_id", "customer_id", "product_sku", "created_at", "created_week", "channel"]]
    keys = ["customer_id", "product_sku"] if same_sku else ["customer_id"]
    p = b.merge(a, on=keys, suffixes=("_b", "_a")) if same_sku else \
        b.merge(a.drop(columns="product_sku"), on=keys, suffixes=("_b", "_a"))
    p = p[(p.ticket_id_a != p.ticket_id_b) & (p.created_at > p.resolved_at)
          & (p.created_at <= p.resolved_at + pd.Timedelta(days=window_days))]
    return p.rename(columns={"created_at": "b_created_at", "resolved_at": "a_resolved_at",
                             "created_week": "b_created_week", "channel": "b_channel"}).reset_index(drop=True)


def label_pairs(pairs: pd.DataFrame, themes: pd.Series) -> pd.DataFrame:
    """themes: Series indexed by ticket_id (missing = not classified)."""
    p = pairs.copy()
    p["theme_a"] = p.ticket_id_a.map(themes)
    p["theme_b"] = p.ticket_id_b.map(themes)
    p["classified"] = p.theme_a.notna() & p.theme_b.notna()
    p["excluded_other"] = p.classified & ((p.theme_a == OTHER) | (p.theme_b == OTHER))
    p["is_repeat_pair"] = p.classified & ~p.excluded_other & (p.theme_a == p.theme_b)
    return p


def repeat_summary(t: pd.DataFrame, themes: pd.Series, policy: dict, b_mask: pd.Series) -> dict:
    """Repeat count and cost for B tickets selected by b_mask (e.g. a created-week range).

    Returns computed=False (and no figures) if any B in scope, or any candidate A of those Bs, is unclassified.
    """
    window, costs = policy["repeat_window_days"], policy["contact_cost_inr"]
    b_ids = set(t.loc[b_mask, "ticket_id"])
    pairs = label_pairs(candidate_pairs(t, window), themes)
    pairs = pairs[pairs.ticket_id_b.isin(b_ids)]
    b_classified = sum(1 for i in b_ids if i in themes.index)
    coverage = {"b_tickets": len(b_ids), "b_classified": b_classified,
                "candidate_pairs": len(pairs), "candidate_pairs_classified": int(pairs.classified.sum())}
    complete = b_classified == len(b_ids) and coverage["candidate_pairs_classified"] == len(pairs)
    out = {"computed": complete, "coverage": coverage}
    if not complete:
        return out

    rep = pairs[pairs.is_repeat_pair].drop_duplicates("ticket_id_b")           # B counts once
    by_ch = rep.groupby("b_channel").size()
    count = len(rep)
    out.update({
        "count": count,
        "cost_inr": int(sum(costs[ch] * n for ch, n in by_ch.items())),
        "by_channel": {ch: {"count": int(n), "inr": int(costs[ch] * n)} for ch, n in by_ch.items()},
        "sensitivity_blended_inr": count * policy["blended_contact_cost_inr"],
        "sensitivity_finance_inr": count * policy["finance_quoted_contact_cost_inr"],
        "excluded_other_unclear_pairs": int(pairs.excluded_other.sum()),
        "repeat_ticket_ids": sorted(rep.ticket_id_b),
    })
    # Sensitivity without the same-SKU condition (needs the cross-SKU candidate As classified too)
    nos = label_pairs(candidate_pairs(t, window, same_sku=False), themes)
    nos = nos[nos.ticket_id_b.isin(b_ids)]
    out["without_sku_condition"] = (int(nos[nos.is_repeat_pair].ticket_id_b.nunique())
                                    if nos.classified.all() else None)
    rep_t = rep                                    # same-SKU pairs: product_sku is shared by A and B
    out["drivers_theme"] = (rep_t.assign(inr=rep_t.b_channel.map(costs)).groupby("theme_b")
                            .agg(count=("ticket_id_b", "size"), inr=("inr", "sum"))
                            .sort_values(["count", "inr"], ascending=False).reset_index().to_dict("records"))
    out["drivers_theme_sku"] = (rep_t.assign(inr=rep_t.b_channel.map(costs)).groupby(["theme_b", "product_sku"])
                                .agg(count=("ticket_id_b", "size"), inr=("inr", "sum"))
                                .sort_values(["count", "inr"], ascending=False).head(10).reset_index().to_dict("records"))
    return out


def scope_ticket_ids(t: pd.DataFrame, b_mask: pd.Series, window_days: int) -> set[str]:
    """Smallest valid scope (PRD §14.4): B tickets selected by b_mask plus their same-customer, same-SKU candidate
    prior tickets A. Cross-SKU priors are NOT included, so under a fallback scope the optional no-SKU sensitivity
    shows "not computed" (DECISIONS.md D-4)."""
    b_ids = set(t.loc[b_mask, "ticket_id"])
    p = candidate_pairs(t, window_days, same_sku=True)
    return b_ids | set(p.loc[p.ticket_id_b.isin(b_ids), "ticket_id_a"])


def declared_repeats(t: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Customer-declared repeats (strict text patterns): a validation proxy, not ground truth.

    status: in_window | outside_window (nearest earlier resolved same-SKU ticket > 30 days before) |
            no_resolved_same_sku_prior
    outside_detail (outside_window only) reconciles to the discovery figure, which looked only at the customer's
    immediately previous ticket (DECISIONS.md D-3):
      prev_same_sku_resolved   -> discovery's 67 (gap 30-42 days)
      prev_same_sku_unresolved -> previous same-SKU ticket not resolved before B, so it can never be prior ticket A
      prev_other_sku           -> immediately previous ticket is a different product
    """
    d = t[t.customer_message.str.contains(DECLARED_REPEAT)][["ticket_id", "customer_id", "product_sku", "created_at",
                                                            "created_week"]]
    a = t.loc[t.attended & t.resolved_at.notna(), ["ticket_id", "customer_id", "product_sku", "resolved_at"]]
    m = d.merge(a, on=["customer_id", "product_sku"], how="left", suffixes=("", "_a"))
    m = m[m.resolved_at.isna() | (m.resolved_at < m.created_at)]
    m["gap_days"] = (m.created_at - m.resolved_at).dt.total_seconds() / 86400
    last = m.groupby("ticket_id").gap_days.min()
    out = d.set_index("ticket_id")
    out["min_gap_days"] = last
    out["status"] = "no_resolved_same_sku_prior"
    out.loc[out.min_gap_days.notna() & (out.min_gap_days > window_days), "status"] = "outside_window"
    out.loc[out.min_gap_days.notna() & (out.min_gap_days <= window_days), "status"] = "in_window"

    s = t.sort_values(["created_at", "ticket_id"])
    g = s.groupby("customer_id")
    prev = pd.DataFrame({"prev_sku": g.product_sku.shift().values, "prev_resolved": g.resolved_at.shift().values,
                         "prev_exists": g.ticket_id.shift().notna().values}, index=s.ticket_id.values)
    out = out.join(prev)
    detail = pd.Series("", index=out.index)
    outside = out.status == "outside_window"
    same = out.prev_exists & (out.prev_sku == out.product_sku)
    detail[outside & ~out.prev_exists] = "no_previous_ticket"
    detail[outside & out.prev_exists & ~same] = "prev_other_sku"
    resolved_before_b = out.prev_resolved.notna() & (out.prev_resolved < out.created_at)
    detail[outside & same & ~resolved_before_b] = "prev_same_sku_unresolved"
    detail[outside & same & resolved_before_b] = "prev_same_sku_resolved"
    out["outside_detail"] = detail
    return out.drop(columns=["prev_sku", "prev_resolved", "prev_exists"]).reset_index()
