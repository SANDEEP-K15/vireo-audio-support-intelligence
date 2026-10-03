"""Static HTML digest + CSV extracts (PRD §15, §17). Reads cached classifications only — never calls the API."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import PROJECT_ROOT
from .impact import NO_CLAIM_NOTE, illustrative_scenarios, monthly_ai_cost_usd
from .metrics import (breach_credits, check_baselines, created_in_range, csat, full_weeks, incoming_volume,
                      leaderboard, trailing_mask, transfer_cost)
from .repeats import declared_repeats, label_pairs, candidate_pairs, repeat_summary
from .evaluate import repeat_recall, score_pair_review, PAIRS_FILE
from .taxonomy import Theme, label_of
from .providers import active_provider, model_ladder

LIMITATIONS = [
    "“Same issue” relies on equality of AI theme labels: repeats across adjacent themes (e.g. firmware update → "
    "charging) are undercounted. Repeat recall against customer-declared repeats measures this.",
    "The same-SKU condition misses repeats recorded against a different SKU; a sensitivity without it is reported.",
    "Repeats in January 2025 are undercounted because earlier tickets are outside the export. Declared repeats more "
    "than 30 days after resolution are excluded by the policy definition.",
    "If the backfill gate restricted the classification scope, totals for uncovered periods show “not computed” and "
    "are never extrapolated.",
    "The roster has one row per agent and no history: team moves are invisible. Indore night-shift agents resolve "
    "other teams' tickets by design (policy §7), shown as “outside roster team”.",
    "Legacy (pre-14 Sep 2025) transfers are unknown, so transfer cost covers helpdesk tickets only.",
    "Some order links are ambiguous (several orders for the same customer + SKU) and are left unlinked; some "
    "tickets predate their linked order. Order links are not used by any metric in this digest.",
    "CSAT is a ~44% response sample; blanks and legacy zeros are excluded from the mean.",
    "Policy attributes SLA breaches to the resolving agent, not the first responder, so breaches are not shown per agent.",
    "The intake-bot category shows no evidence of agent re-tagging, despite the README.",
    "Trends crossing the 14 Sep 2025 migration mix two source systems.",
    "AI labels carry the error rate measured on the 120-ticket gold set; rare themes have wide uncertainty.",
]

SCOPE_CUTS = [
    "Live helpdesk/API integration, scheduler, hosting, authentication, web server, database, frontend framework.",
    "Agents, RAG, vector databases, LangChain/LangGraph, microservices.",
    "LLM-written narrative (all digest text is templated from computed numbers).",
    "Any employee-performance, productivity or composite score; per-agent CSAT, breach or repeat rates.",
    "Savings or ROI claims (only the labelled illustrative scenario).",
    "Lot-code defect clustering (opportunity noted, not analysed).",
    "Finance review of orders with both a refund and a replacement and of GW-OTHER refunds above Rs 500 "
    "(discovery observations handed to the client).",
    "Chasing stale open/pending tickets; Message Batches API; translation; sentiment; roster-history reconstruction.",
]

DISCREPANCIES = [   # resolved decisions; full evidence in DECISIONS.md
    "C9 (D-1): tickets created before their linked order are reported per link type — direct (PRD baseline basis) "
    "and fallback — and the fallback ones are split by evidence (customer-quoted order id, pre-sales enquiry, "
    "unverifiable). The rate is the same for direct and fallback links, so this is a property of the source data, "
    "not of the fallback rule; the C7 fallback rule is unchanged. Order links feed no digest metric.",
    "C7 (D-2): ambiguous fallback joins are reported after de-duplication (order_link_ambiguous); the raw-row figure "
    "(raw_order_link_ambiguous) double-counts re-imported legacy tickets and is kept only as a raw-export check.",
    "Declared repeats (D-3): the in-window reference set used for repeat recall is identical under the discovery "
    "and implementation definitions. Outside-window declared repeats are split so they reconcile to the discovery "
    "figure (declared_outside_prev_same_sku_resolved).",
]


def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def selected_model(cfg: dict) -> tuple[str, bool]:
    """(model, validated) for the active provider. Falls back to the provider's cheapest ladder model, labelled
    unvalidated, before evaluation. A selection made under a different provider is ignored."""
    ladder = model_ladder(cfg)
    sel = _load_json(cfg["paths"]["out_dir"] / "eval" / "selection.json")
    if sel and sel.get("selected_model") in ladder:
        return sel["selected_model"], True
    return ladder[0], False


def build_context(clean, cache, cfg: dict, week: pd.Timestamp) -> dict:
    t, pol, dg = clean.tickets, cfg["policy"], cfg["digest"]
    out_dir = cfg["paths"]["out_dir"]
    week = pd.Timestamp(week)
    weeks_full = full_weeks(t)
    if week not in weeks_full:
        raise ValueError(f"{week.date()} is not a full Monday-Sunday week inside the export "
                         f"({weeks_full[0].date()} to {weeks_full[-1].date()})")
    nw = dg["trailing_weeks"]

    model, validated = selected_model(cfg)
    labels = cache.themes(model, cfg["ai"]["prompt_version"], t)
    themes = labels.set_index("ticket_id").theme if len(labels) else pd.Series(dtype=str)

    # ---- repeats (B bucketed by created week)
    in_week = t.created_week == week
    in_prev = trailing_mask(t, week, "created_week", nw)          # W-4..W-1 (selected week excluded)
    in_12m = created_in_range(t, *dg["trailing_12m"])
    rep_week = repeat_summary(t, themes, pol, in_week)
    rep_prev = repeat_summary(t, themes, pol, in_prev)
    rep_12m = repeat_summary(t, themes, pol, in_12m)
    rep_all = repeat_summary(t, themes, pol, pd.Series(True, index=t.index))

    # ---- complaint themes (created week)
    wk_t = t[in_week].assign(theme=lambda d: d.ticket_id.map(themes))
    week_cov = round(wk_t.theme.notna().mean(), 3) if len(wk_t) else 0.0
    prev_t = t[in_prev].assign(theme=lambda d: d.ticket_id.map(themes))
    prev_complete = len(prev_t) > 0 and prev_t.theme.notna().all()
    theme_rows = []
    if week_cov == 1.0:
        cur = wk_t.theme.value_counts()
        prev_avg = prev_t.theme.value_counts() / nw if prev_complete else None
        for th in Theme:
            c = int(cur.get(th.value, 0))
            p = None if prev_avg is None else round(float(prev_avg.get(th.value, 0.0)), 1)
            if c or (p or 0):
                theme_rows.append({"theme": th.value, "label": label_of(th.value), "count": c, "prev_avg": p,
                                   "change": None if p is None else round(c - p, 1)})
        theme_rows.sort(key=lambda r: -r["count"])
    other = wk_t[wk_t.category == "Other"]
    reclass = {"bot_other": len(other),
               "reclassified": int((other.theme.notna() & (other.theme != "OTHER_UNCLEAR")).sum()) if week_cov == 1.0 else None,
               "by_theme": other.theme.value_counts().to_dict() if week_cov == 1.0 else {}}

    # ---- secondary KPIs
    vol = incoming_volume(t, week)
    trailing_weekly_mean = int(trailing_mask(t, week, "created_week", nw).sum()) / nw   # PRD §14.2, D-5

    # ---- AI cost
    usage = cache.usage()
    spend = (usage.groupby("purpose").cost_usd.sum().round(6).to_dict() if len(usage) else {})
    spend_total = round(float(usage.cost_usd.sum()), 4) if len(usage) else 0.0     # sum unrounded, round once
    # cache.themes() already matches on model + prompt_version; cached records carry their own measured cost
    mean_cost = float(labels.cost_usd.mean()) if len(labels) and "cost_usd" in labels.columns else None
    monthly = monthly_ai_cost_usd(mean_cost, trailing_weekly_mean)
    backfill = _load_json(out_dir / "backfill_decision.json")
    selection = _load_json(out_dir / "eval" / "selection.json")
    fx = cfg.get("ai", {}).get("usd_inr_rate")

    # ---- evaluation summary
    declared = declared_repeats(t, pol["repeat_window_days"])
    classified_ids = set(themes.index)
    pairs_all = label_pairs(candidate_pairs(t, pol["repeat_window_days"]), themes)
    complete_b = set(pairs_all.groupby("ticket_id_b").classified.all().loc[lambda s: s].index) | (
        classified_ids - set(pairs_all.ticket_id_b))
    rep_ids = set(pairs_all[pairs_all.is_repeat_pair].ticket_id_b)
    recall = repeat_recall(declared, rep_ids, complete_b & classified_ids) if classified_ids else None
    precision = score_pair_review(cfg["paths"]["gold_dir"] / PAIRS_FILE)

    dq = dict(clean.dq)
    dq.update(check_baselines(t, cfg))
    dq["declared_repeats_total"] = int(len(declared))
    dq.update({f"declared_repeats_{k}": int(v) for k, v in declared.status.value_counts().items()})
    detail = declared.loc[declared.status == "outside_window", "outside_detail"].value_counts()
    dq.update({f"declared_outside_{k}": int(v) for k, v in detail.items()})

    return {
        "week_start": week.date(), "week_end": (week + pd.Timedelta(days=6)).date(),
        "data_range": (t.created_at.min().strftime("%d %b %Y"), t.created_at.max().strftime("%d %b %Y")),
        "partial_week_note": _partial_week_note(t, weeks_full),
        "run_ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provider": active_provider(cfg), "model": model, "validated": validated, "prompt_version": cfg["ai"]["prompt_version"],
        "classified_total": len(classified_ids), "tickets_total": len(t), "week_coverage": week_cov,
        "scope": backfill["gate"]["scope"] if backfill else "none (backfill not run)",
        "rep_week": rep_week, "rep_prev": rep_prev, "rep_12m": rep_12m, "rep_all": rep_all, "trailing_weeks": nw,
        "rep_prev_avg": round(rep_prev["count"] / nw, 1) if rep_prev.get("computed") else None,
        "theme_rows": theme_rows, "reclass": reclass, "label_of": label_of,
        "volume": {ch: int(vol.get(ch, 0)) for ch in ("chat", "email", "voice", "social")}, "volume_total": int(vol.sum()),
        "breach": breach_credits(t, pol, week), "transfers": transfer_cost(t, pol, week), "csat": csat(t, week),
        "board": leaderboard(t, clean.agents, week, nw),
        "scenarios": illustrative_scenarios(rep_12m.get("cost_inr") if rep_12m.get("computed") else None,
                                            dg["illustrative_reduction_pcts"]),
        "no_claim_note": NO_CLAIM_NOTE, "policy": pol,
        "spend": spend, "spend_total": spend_total, "mean_cost_per_ticket": mean_cost,
        "scope_limitations": _scope_limitations(backfill, rep_prev, rep_12m, rep_all, rep_week, nw,
                                                cfg["ai"]["backfill_max_runtime_minutes"]),
        "data_use": _data_use_note(cfg, len(classified_ids)),
        "monthly_usd": monthly, "fx": fx, "backfill": backfill, "selection": selection,
        "recall": recall, "precision": precision, "eval_thresholds": cfg["evaluation"],
        "dq": dq, "warnings": clean.warnings, "limitations": LIMITATIONS, "scope_cuts": SCOPE_CUTS,
        "discrepancies": DISCREPANCIES,
    }


def _scope_limitations(backfill, rep_prev, rep_12m, rep_all, rep_week, nw, max_runtime_min) -> list[str]:
    """Explicit list of figures not computed because the classification scope does not cover them (no extrapolation)."""
    out = []
    if backfill and backfill["gate"]["scope"] != "full":
        proj = backfill["gate"]["projections"].get("full", {})
        out.append(f"Classification scope was '{backfill['gate']['scope']}', not the full history: the backfill gate "
                   f"projected the full backfill at {proj.get('runtime_min')} min against a "
                   f"{max_runtime_min}-min limit, so it was deliberately not run.")
    if not rep_12m.get("computed"):
        out.append("Trailing-12-month repeat-contact total: not computed.")
    if not rep_all.get("computed"):
        out.append("18-month (full export) repeat-contact total: not computed.")
    if not rep_prev.get("computed"):
        out.append(f"Previous-{nw}-week comparisons (repeat contacts and complaint themes): not computed.")
    if not rep_12m.get("computed"):
        out.append("Illustrative reduction scenario: not computed (it requires the trailing-12-month total).")
    if rep_week.get("computed") and rep_week.get("without_sku_condition") is None:
        out.append("Repeat count without the same-product (SKU) condition: not computed (cross-product prior "
                   "tickets are outside the digest scope).")
    return out


def _data_use_note(cfg: dict, n_classified: int) -> str | None:
    """Data-use disclosure for the configured provider tier (DECISIONS.md D-6, D-8)."""
    if active_provider(cfg) == "gemini" and cfg["ai"].get("gemini_tier") == "free":
        return (f"Classification used the Gemini API free tier (quota id GenerateRequestsPerMinutePerProject-"
                f"FreeTier observed on 2026-10-03). Customer message and agent note text for {n_classified:,} distinct "
                "tickets was sent to Google under free-tier terms; Google's Gemini API pricing page states that "
                "free-tier content is used to improve Google's products. A billing-enabled key avoids this.")
    return None


def _partial_week_note(t: pd.DataFrame, weeks_full: list) -> str:
    last_full_end = weeks_full[-1] + pd.Timedelta(days=6)
    tail = t[t.created_at > last_full_end + pd.Timedelta(days=1)]
    return (f"The export ends {t.created_at.max():%d %b %Y}; the partial week after {last_full_end:%d %b %Y} "
            f"({len(tail)} tickets) is never shown as a full week.")


def render(ctx: dict, out_dir: Path) -> Path:
    env = Environment(loader=FileSystemLoader(PROJECT_ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("digest.html.j2").render(**ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"digest_{ctx['week_start']}.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_csvs(ctx: dict, clean, cache, cfg: dict, out_dir: Path) -> list[Path]:
    w = ctx["week_start"]
    paths = []
    rows = [r for d in ctx["board"]["tier1"].values() for r in d["rows"]]
    p = out_dir / f"leaderboard_tier1_{w}.csv"; pd.DataFrame(rows).to_csv(p, index=False); paths.append(p)
    p = out_dir / f"leaderboard_tier2_{w}.csv"; pd.DataFrame(ctx["board"]["tier2"]).to_csv(p, index=False); paths.append(p)
    model = ctx["model"]
    labels = cache.themes(model, cfg["ai"]["prompt_version"], clean.tickets)
    cols = ["ticket_id", "theme", "customer_claims_prior_contact", "ai_error", "model", "prompt_version"]
    p = out_dir / "classified_tickets.csv"
    (labels[cols] if len(labels) else pd.DataFrame(columns=cols)).to_csv(p, index=False); paths.append(p)
    p = out_dir / f"repeat_contacts_{w}.csv"
    pd.DataFrame({"ticket_id_b": ctx["rep_week"].get("repeat_ticket_ids", [])}).to_csv(p, index=False); paths.append(p)
    return paths
