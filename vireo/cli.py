"""Command-line entry point: python -m vireo <command> [options]

Workflow (PRD §24):  check -> prepare-gold -> (human labels) -> smoke -> evaluate -> backfill -> prepare-pairs
                     -> (human review) -> digest
Only smoke, evaluate and backfill call the configured LLM provider (config ai.provider); every other command is
offline.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from . import load_config
from .clean import run_clean
from .classify import Budget, Cache, Classifier, backfill_gate
from .evaluate import (GOLD_FILE, PAIRS_FILE, labelling_guide, load_gold, make_gold_sample, make_pair_review,
                       passes, score_classification, stability)
from .ingest import read_raw
from .providers import active_provider, check_model, make_client, model_ladder
from .metrics import add_derived, check_baselines, created_in_range
from .repeats import candidate_pairs, label_pairs, scope_ticket_ids
from .report import build_context, render, selected_model, write_csvs


def _clean(cfg):
    c = run_clean(read_raw(cfg["paths"]["raw_dir"]), cfg)
    c.tickets = add_derived(c.tickets, cfg["policy"])
    return c


def _client(cfg):
    """Client for ai.provider (anthropic | gemini); the key comes from that provider's variable in .env."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return make_client(cfg)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---------------------------------------------------------------- commands
def cmd_check(cfg, args):
    c = _clean(cfg)
    dq = {**c.dq, **check_baselines(c.tickets, cfg)}
    for k, v in dq.items():
        print(f"{k:40s} {v}")
    for w in c.warnings:
        print("WARNING:", w)
    print("All cleaning invariants and baseline assertions passed.")


def cmd_prepare_gold(cfg, args):
    gold_dir = cfg["paths"]["gold_dir"]
    path = gold_dir / GOLD_FILE
    if path.exists():
        sys.exit(f"{path} already exists; refusing to overwrite a gold file.")
    c = _clean(cfg)
    ev = cfg["evaluation"]
    g = make_gold_sample(c.tickets, ev["gold_size"], ev["gold_seed"], ev["min_per_theme"])
    gold_dir.mkdir(parents=True, exist_ok=True)
    g.to_csv(path, index=False, encoding="utf-8")
    (gold_dir / "LABELLING_GUIDE.md").write_text(labelling_guide(), encoding="utf-8")
    print(f"Wrote {len(g)} tickets to {path}. Label them by hand following {gold_dir / 'LABELLING_GUIDE.md'}.")


def cmd_smoke(cfg, args):
    c = _clean(cfg)
    model = args.model or model_ladder(cfg)[0]
    check_model(cfg, model)
    n = cfg["ai"]["smoke_test_size"]
    sample = c.tickets.sample(n, random_state=cfg["ai"]["smoke_test_seed"])
    clf = Classifier(_client(cfg), cfg, model, Cache(cfg["paths"]["cache_dir"]))
    budget = Budget(cfg["ai"]["max_usd_per_run"], n, cfg["ai"]["first_call_cost_estimate_usd"])
    recs, stats = clf.classify_tickets(sample, "smoke", budget, use_cache=False)
    valid = sum(not r["ai_error"] for r in recs)
    # valid_rate is over the REQUESTED tickets: a run cut short by rate limits or caps is < 100% and cannot pass
    # the backfill gate. wall_s_per_ticket includes pacing waits, so gate runtime projections are realistic.
    out = {**stats.as_dict(), "provider": active_provider(cfg), "valid_rate": valid / n,
           "complete": stats.classified == n,
           "wall_s_per_ticket": stats.wall_s / stats.classified if stats.classified else None,
           "concurrency": cfg["ai"]["concurrency"]}
    _write_json(cfg["paths"]["out_dir"] / "smoke.json", out)
    print(json.dumps(out, indent=1, default=str))
    if not out["complete"]:
        print(f"WARNING: smoke incomplete ({stats.classified}/{n} classified; rate-limited "
              f"{stats.skipped_rate_limited}, budget {stats.skipped_budget}). {stats.rate_limit_message or ''} "
              "Re-run `python -m vireo smoke` after the quota window resets.")


def cmd_evaluate(cfg, args):
    c = _clean(cfg)
    gold = load_gold(cfg["paths"]["gold_dir"], lock=True)
    tickets = c.tickets.set_index("ticket_id").loc[gold.ticket_id].reset_index()
    cache = Cache(cfg["paths"]["cache_dir"])
    client = _client(cfg)
    ladder, selected = [], None
    for model in model_ladder(cfg):
        check_model(cfg, model)
        clf = Classifier(client, cfg, model, cache)
        budget = Budget(cfg["ai"]["max_usd_per_run"], len(tickets), cfg["ai"]["first_call_cost_estimate_usd"])
        recs, stats = clf.classify_tickets(tickets, "eval", budget)
        if len(recs) < len(tickets):
            sys.exit(f"Evaluation of {model} incomplete: {len(recs)}/{len(tickets)} classified (rate-limited "
                     f"{stats.skipped_rate_limited}, cost/ticket guard {stats.skipped_budget}). "
                     f"{stats.rate_limit_message or ''} Completed labels are cached; re-running resumes from them.")
        pred = pd.DataFrame(recs)
        scores = score_classification(gold, pred)
        ok, why = passes(scores, cfg)
        ladder.append({"model": model, "passed": ok, "why": why, "scores": scores,
                       "cost_per_ticket": float(pred.cost_usd.mean()), "eval_cost_usd_this_run": stats.cost_usd,
                       "eval_cost_usd_total": float(pred.cost_usd.sum()), "cached": stats.cached})
        print(f"{model}: accuracy {scores['accuracy']:.1%}, macro-F1 {scores['macro_f1']:.3f}, "
              f"{'PASS' if ok else 'FAIL: ' + '; '.join(why)}")
        if ok:
            selected, selected_pred = model, pred
            break                                  # cheapest-first: stop at the first model that passes
    sel = {"selected_model": selected, "provider": active_provider(cfg), "gold_n": len(gold), "ladder": ladder,
           "prompt_version": cfg["ai"]["prompt_version"]}
    if args.stability and selected:
        sub = tickets.head(cfg["evaluation"]["stability_sample"])
        clf = Classifier(client, cfg, selected, cache)
        b = Budget(cfg["ai"]["max_usd_per_run"], len(sub), cfg["ai"]["first_call_cost_estimate_usd"])
        recs2, _ = clf.classify_tickets(sub, "stability", b, use_cache=False, write_cache=False)
        sel["stability"] = stability(selected_pred[["ticket_id", "theme"]], pd.DataFrame(recs2)[["ticket_id", "theme"]])
    out = cfg["paths"]["out_dir"] / "eval"
    _write_json(out / "selection.json", sel)
    _write_eval_report(out / "eval_report.md", sel, cfg)
    print(f"Selected model: {selected or 'none passed'} -> {out / 'selection.json'}")


def _write_eval_report(path: Path, sel: dict, cfg: dict) -> None:
    ev = cfg["evaluation"]
    lines = ["# Classifier evaluation report", "",
             f"Gold set: {sel['gold_n']} human-labelled tickets (locked by SHA-256). Prompt `{sel['prompt_version']}`.",
             f"Thresholds: accuracy >= {ev['accuracy_threshold']:.0%}, every family >= {ev['family_min_accuracy']:.0%}.",
             f"Provider: `{sel['provider']}`. Selected model: **{sel['selected_model'] or 'none passed'}** "
             "(cheapest-first ladder).", ""]
    for r in sel["ladder"]:
        s = r["scores"]
        lines += [f"## {r['model']} — {'PASS' if r['passed'] else 'FAIL'}", "",
                  f"- accuracy {s['accuracy']:.1%}, macro-F1 {s['macro_f1']:.3f}, AI errors {s['ai_errors']}",
                  f"- cost per ticket ${r['cost_per_ticket']:.5f}; evaluation cost ${r['eval_cost_usd_total']:.4f}",
                  f"- prior-contact flag: precision {s['prior_contact']['precision']}, recall {s['prior_contact']['recall']} "
                  f"(gold positives {s['prior_contact']['gold_positive']})"]
        if r["why"]:
            lines.append(f"- failed: {'; '.join(r['why'])}")
        lines += ["", "| Family | n | Accuracy |", "|---|---|---|"]
        lines += [f"| {f} | {v['n']} | {v['accuracy']:.1%} |" for f, v in s["per_family"].items()]
        lines += ["", "| Theme | F1 |", "|---|---|"]
        lines += [f"| {k} | {v:.3f} |" for k, v in sorted(s["per_theme_f1"].items())]
        lines += ["", "Most frequent confusions (gold → predicted):", ""]
        lines += [f"- {x['gold']} → {x['pred']}: {x['n']}" for x in s["confusion_top"]] or ["- none"]
        lines.append("")
    if sel.get("stability"):
        lines.append(f"Stability (re-classified without cache): {sel['stability']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_backfill(cfg, args):
    c = _clean(cfg)
    t = c.tickets
    out = cfg["paths"]["out_dir"]
    smoke = _read_json(out / "smoke.json")
    sel = _read_json(out / "eval" / "selection.json")
    model, validated = selected_model(cfg)
    cache = Cache(cfg["paths"]["cache_dir"])
    week = pd.Timestamp(args.week or cfg["digest"]["default_week_start"])
    window = cfg["policy"]["repeat_window_days"]
    digest_ids = scope_ticket_ids(t, t.created_week == week, window)
    t12_ids = scope_ticket_ids(t, created_in_range(t, *cfg["digest"]["trailing_12m"]), window) | digest_ids
    scopes = {"full": set(t.ticket_id), "trailing_12m": t12_ids, "digest": digest_ids}
    done = set(cache.themes(model, cfg["ai"]["prompt_version"], t).get("ticket_id", []))
    unclassified = {k: len(v - done) for k, v in scopes.items()}
    gate = backfill_gate(
        smoke_valid_rate=smoke["valid_rate"] if smoke and smoke["model"] == model else None,
        eval_passed=bool(sel and sel.get("selected_model") == model),
        mean_cost_per_ticket=smoke["mean_cost_per_ticket"] if smoke and smoke["model"] == model else None,
        wall_s_per_ticket=smoke["wall_s_per_ticket"] if smoke and smoke["model"] == model else None,
        unclassified_by_scope=unclassified, max_usd=cfg["ai"]["max_usd_backfill"],
        max_runtime_min=cfg["ai"]["backfill_max_runtime_minutes"])
    decision = {"model": model, "gate": asdict(gate), "unclassified_by_scope": unclassified, "week": str(week.date())}
    print(json.dumps(decision, indent=1, default=str))
    if args.dry_run:
        print("Dry run: no API calls made, no state written.")
        return
    if gate.scope is None:
        _write_json(out / "backfill_decision.json", decision)
        sys.exit("Backfill gate: nothing may run. " + "; ".join(gate.reasons))
    todo = t[t.ticket_id.isin(scopes[gate.scope] - done)]
    budget = Budget(cfg["ai"]["max_usd_backfill"], len(todo), cfg["ai"]["first_call_cost_estimate_usd"])
    check_model(cfg, model)
    clf = Classifier(_client(cfg), cfg, model, cache)
    _, stats = clf.classify_tickets(todo, f"backfill_{gate.scope}", budget)
    decision["run"] = stats.as_dict()
    _write_json(out / "backfill_decision.json", decision)
    print(json.dumps(stats.as_dict(), indent=1, default=str))


def cmd_prepare_pairs(cfg, args):
    path = cfg["paths"]["gold_dir"] / PAIRS_FILE
    if path.exists():
        sys.exit(f"{path} already exists; refusing to overwrite a review file.")
    c = _clean(cfg)
    model, _ = selected_model(cfg)
    labels = Cache(cfg["paths"]["cache_dir"]).themes(model, cfg["ai"]["prompt_version"], c.tickets)
    if not len(labels):
        sys.exit("No classified tickets in the cache for the selected model; run backfill first.")
    pairs = label_pairs(candidate_pairs(c.tickets, cfg["policy"]["repeat_window_days"]),
                        labels.set_index("ticket_id").theme)
    review = make_pair_review(pairs, c.tickets, cfg["evaluation"]["repeat_precision_sample"], cfg["evaluation"]["gold_seed"])
    review.to_csv(path, index=False, encoding="utf-8")
    print(f"Wrote {len(review)} flagged pairs to {path}. Fill same_issue = yes/no for each row.")


def cmd_digest(cfg, args):
    c = _clean(cfg)
    cache = Cache(cfg["paths"]["cache_dir"])
    week = pd.Timestamp(args.week or cfg["digest"]["default_week_start"])
    ctx = build_context(c, cache, cfg, week)
    out = cfg["paths"]["out_dir"]
    html = render(ctx, out)
    csvs = write_csvs(ctx, c, cache, cfg, out)
    print(f"Digest: {html}")
    for p in csvs:
        print(f"CSV:    {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vireo", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="path to config.yaml (default: project root)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="clean the data and run all assertions (offline)")
    sub.add_parser("prepare-gold", help="write the stratified 120-ticket gold sample for human labelling (offline)")
    p = sub.add_parser("smoke", help="classify 20 tickets to measure validity, cost and runtime (API)")
    p.add_argument("--model", default=None)
    p = sub.add_parser("evaluate", help="score the gold set up the cheapest-first model ladder (API)")
    p.add_argument("--stability", action="store_true", help="also re-classify 50 gold tickets without cache")
    p = sub.add_parser("backfill", help="apply the backfill gate and classify the allowed scope (API)")
    p.add_argument("--week", default=None)
    p.add_argument("--dry-run", action="store_true", help="show the gate decision without calling the API")
    sub.add_parser("prepare-pairs", help="sample 30 flagged repeat pairs for human precision review (offline)")
    p = sub.add_parser("digest", help="build the static HTML digest + CSVs from cached labels (offline)")
    p.add_argument("--week", default=None, help="Monday of the week, YYYY-MM-DD (default 2026-06-22)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    commands = {"check": cmd_check, "prepare-gold": cmd_prepare_gold, "smoke": cmd_smoke, "evaluate": cmd_evaluate,
                "backfill": cmd_backfill, "prepare-pairs": cmd_prepare_pairs, "digest": cmd_digest}
    try:
        commands[args.cmd](cfg, args)
    except (ValueError, AssertionError) as e:     # data-quality / gold-set / week validation: fail loudly, cleanly
        sys.exit(f"ERROR ({args.cmd}): {e}")


if __name__ == "__main__":
    main()
