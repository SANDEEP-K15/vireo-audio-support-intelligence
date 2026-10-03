"""Evaluation (PRD §13): human gold set, classification metrics, repeat recall/precision, stability.

Gold labels are created by a human from the raw text, before any model prediction is scored, and are locked
(SHA-256) the first time scoring runs. Model predictions are never used as gold labels.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .taxonomy import FAMILIES, Theme, family_of, taxonomy_text

GOLD_FILE = "gold_tickets.csv"
LOCK_FILE = "gold_lock.json"
PAIRS_FILE = "repeat_pairs_review.csv"
HINGLISH = re.compile(r"\b(?:bhai|ji|kal se|abhi|nahi|kuch|hai|kya)\b", re.I)

# ---- [discovery-only] keyword mapping of agent-note issue phrases. Used ONLY to stratify the gold sample;
# ---- never shown to the labeller, never used as a label or a metric.
_NOTE_ISSUE = [r"(?i)\bissue:\s*([^.|\n]+)", r"(?i)^re:\s*([^|\n]+)\|", r"(?i)^1\.\s*([^\n]+)",
               r"(?i)\b(?:cx|cust|customer) (?:says|states|reported|reached out -|contacted re|:)\s*([^.|\n]+)",
               r"(?i)ticket raised for\s*([^.|\n]+)", r"(?i)contact re\s*([^.|\n]+)", r"(?i)reported:\s*([^.|\n]+)"]
_KEYWORDS = [
    ("DELIVERY_DELAY", r"deliver|dlv|dlry|shipm|ord(d)?er not|not rcvd$|not received$"),
    ("TRANSIT_DAMAGE_WRONG_ITEM", r"damage|wrong|incorrect|variant"), ("ADDRESS_CHANGE", r"address|adress|pincode"),
    ("CANCELLATION", r"cancel"), ("RETURN_PICKUP", r"pickup|pkp"), ("REFUND_NOT_RECEIVED", r"refund|rfnd"),
    ("PAYMENT_FAILED_DUPLICATE", r"payment|deducted|charge(d)? twice|double charge|duplicate"),
    ("DISCOUNT_COUPON", r"discount|coupon|promo"), ("INVOICE_GST", r"invoice|gst"), ("LOGIN_OTP", r"log ?in|otp"),
    ("APP_CRASH", r"app "), ("FIRMWARE_UPDATE", r"fw|firmware|update hang"), ("PAIRING", r"pair|discoverable"),
    ("BT_DISCONNECT", r"disconnect|drop|connection"), ("WIFI_SETUP", r"wifi|network"),
    ("BATTERY_DRAIN", r"battery|drain"), ("CHARGING_FAILURE", r"charg|no led"),
    ("AUDIO_DISTORTION", r"distortion|static|crackl"), ("ONE_SIDE_AUDIO", r"side|single"), ("MIC", r"mic"),
    ("DISPLAY_TOUCH", r"touch|display"), ("STRAP", r"strap"), ("DEAD_NO_POWER", r"no power|unit dead|not powering"),
    ("WARRANTY_REPAIR_STATUS", r"repair|warranty|wty|rma"), ("PRESALES", r"pre-sales|compat|enquiry"),
]


def preliminary_theme(note: str) -> str | None:
    for p in _NOTE_ISSUE:
        m = re.search(p, (note or "").strip())
        if m:
            label = m.group(1).lower()
            for theme, rx in _KEYWORDS:
                if re.search(rx, label):
                    return theme
            return None
    return None


# ---------------------------------------------------------------- gold sample
def make_gold_sample(t: pd.DataFrame, size: int, seed: int, min_per_theme: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = t.assign(_prelim=t.agent_notes.map(preliminary_theme),
                 _hinglish=t.customer_message.str.contains(HINGLISH),
                 _ivr=t.customer_message.str.startswith("[IVR transcript]"))
    chosen: list[str] = []

    def take(pool: pd.DataFrame, n: int) -> None:
        pool = pool[~pool.ticket_id.isin(chosen)]
        if len(pool):
            chosen.extend(pool.ticket_id.iloc[rng.permutation(len(pool))[:n]])

    for th in Theme:
        if th is not Theme.OTHER_UNCLEAR:
            take(t[t._prelim == th.value], min_per_theme)
    strata = {**{f"channel={c}": t.channel == c for c in ("chat", "email", "voice", "social")},
              "source=legacy_fd": t.is_legacy, "source=helpdesk": ~t.is_legacy,
              "hinglish": t._hinglish, "ivr": t._ivr, "empty_note_issue_text": t._prelim.isna()}
    for mask in strata.values():
        have = t.ticket_id.isin(chosen) & mask
        take(t[mask], max(0, 8 - int(have.sum())))
    take(t, size - len(chosen))
    s = t[t.ticket_id.isin(chosen)].sample(frac=1, random_state=seed)
    return pd.DataFrame({"ticket_id": s.ticket_id, "channel": s.channel, "source_system": s.source_system,
                         "customer_message": s.customer_message, "agent_notes": s.agent_notes,
                         "gold_theme": "", "gold_customer_claims_prior_contact": "", "labeller": "", "comment": ""})


def labelling_guide() -> str:
    return (
        "# Gold-set labelling guide (PRD §13)\n\n"
        "Label every row of `gold_tickets.csv` **from the text only**. Do not look at model output, the cache, or the\n"
        "bot category. Fill:\n\n"
        "- `gold_theme`: exactly one value from the taxonomy below\n"
        "- `gold_customer_claims_prior_contact`: `true` or `false`\n"
        "- `labeller`: your name or initials\n\n"
        "Once `python -m vireo evaluate` runs, the file is locked (SHA-256 in `gold_lock.json`) and must not change.\n\n"
        "```\n" + taxonomy_text() + "\n```\n")


def load_gold(gold_dir: Path, lock: bool = True) -> pd.DataFrame:
    path = Path(gold_dir) / GOLD_FILE
    g = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = g[(g.gold_theme == "") | (g.gold_customer_claims_prior_contact == "")]
    if len(missing):
        raise ValueError(f"{len(missing)} gold rows are not labelled yet ({path})")
    bad = set(g.gold_theme) - {t.value for t in Theme}
    if bad:
        raise ValueError(f"gold_theme values outside the taxonomy: {sorted(bad)}")
    flags = g.gold_customer_claims_prior_contact.str.strip().str.lower()
    if not flags.isin(["true", "false"]).all():
        raise ValueError("gold_customer_claims_prior_contact must be true/false")
    g["gold_prior"] = flags == "true"
    if lock:
        _verify_or_create_lock(path)
    return g


def _verify_or_create_lock(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lock = path.parent / LOCK_FILE
    if lock.exists():
        saved = json.loads(lock.read_text(encoding="utf-8"))["sha256"]
        if saved != digest:
            raise ValueError("gold_tickets.csv changed after scoring began (SHA-256 mismatch with gold_lock.json)")
    else:
        lock.write_text(json.dumps({"sha256": digest, "file": GOLD_FILE}, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- metrics
def score_classification(gold: pd.DataFrame, pred: pd.DataFrame) -> dict:
    """gold: ticket_id, gold_theme, gold_prior. pred: ticket_id, theme, customer_claims_prior_contact, ai_error."""
    m = gold.merge(pred, on="ticket_id", how="left")
    if m.theme.isna().any():
        raise ValueError(f"{int(m.theme.isna().sum())} gold tickets have no prediction")
    y, p = m.gold_theme.tolist(), m.theme.tolist()
    labels = sorted(set(y) | set(p))
    f1s = {}
    for lab in labels:
        tp = sum(a == lab and b == lab for a, b in zip(y, p, strict=False))
        fp = sum(a != lab and b == lab for a, b in zip(y, p, strict=False))
        fn = sum(a == lab and b != lab for a, b in zip(y, p, strict=False))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s[lab] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    fam = {}
    for f in FAMILIES:
        sel = [(a, b) for a, b in zip(y, p, strict=False) if family_of(a) == f]
        if sel:
            fam[f] = {"n": len(sel), "accuracy": round(sum(a == b for a, b in sel) / len(sel), 3)}
    gp, pp = m.gold_prior.tolist(), m.customer_claims_prior_contact.astype(bool).tolist()
    tp = sum(a and b for a, b in zip(gp, pp, strict=False))
    confusion = Counter((a, b) for a, b in zip(y, p, strict=False) if a != b)
    return {
        "n": len(m),
        "accuracy": round(sum(a == b for a, b in zip(y, p, strict=False)) / len(m), 3),
        "macro_f1": round(sum(f1s.values()) / len(f1s), 3),
        "per_theme_f1": {k: round(v, 3) for k, v in f1s.items()},
        "per_family": fam,
        "confusion_top": [{"gold": a, "pred": b, "n": n} for (a, b), n in confusion.most_common(15)],
        "confusion_matrix": pd.crosstab(m.gold_theme, m.theme).to_dict(),
        "prior_contact": {"precision": round(tp / sum(pp), 3) if sum(pp) else None,
                          "recall": round(tp / sum(gp), 3) if sum(gp) else None,
                          "gold_positive": int(sum(gp)), "predicted_positive": int(sum(pp))},
        "ai_errors": int(m.ai_error.astype(bool).sum()),
    }


def passes(scores: dict, cfg: dict) -> tuple[bool, list[str]]:
    ev = cfg["evaluation"]
    why = []
    if scores["accuracy"] < ev["accuracy_threshold"]:
        why.append(f"accuracy {scores['accuracy']:.1%} < {ev['accuracy_threshold']:.0%}")
    for f, v in scores["per_family"].items():
        if v["accuracy"] < ev["family_min_accuracy"]:
            why.append(f"family '{f}' accuracy {v['accuracy']:.1%} < {ev['family_min_accuracy']:.0%} (n={v['n']})")
    return not why, why


def repeat_recall(declared: pd.DataFrame, repeat_ids: set[str], classified_ids: set[str]) -> dict:
    """Share of customer-declared in-window repeats that the §11 method flags. Validation proxy, not ground truth."""
    ref = declared[(declared.status == "in_window") & declared.ticket_id.isin(classified_ids)]
    hit = ref.ticket_id.isin(repeat_ids).sum()
    return {"reference_n": int(len(ref)), "flagged": int(hit),
            "recall": round(hit / len(ref), 3) if len(ref) else None,
            "note": "Reference = customer-declared repeats (strict text patterns) inside the 30-day window; "
                    "a validation proxy, not perfect ground truth."}


def make_pair_review(pairs: pd.DataFrame, t: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Random sample of flagged repeat pairs for human 'same issue?' review (themes hidden to avoid anchoring)."""
    flagged = pairs[pairs.is_repeat_pair].drop_duplicates("ticket_id_b")
    s = flagged.sample(min(n, len(flagged)), random_state=seed)
    txt = t.set_index("ticket_id")
    return pd.DataFrame({
        "ticket_id_a": s.ticket_id_a.values, "ticket_id_b": s.ticket_id_b.values,
        "a_customer_message": txt.loc[s.ticket_id_a, "customer_message"].values,
        "a_agent_notes": txt.loc[s.ticket_id_a, "agent_notes"].values,
        "b_customer_message": txt.loc[s.ticket_id_b, "customer_message"].values,
        "b_agent_notes": txt.loc[s.ticket_id_b, "agent_notes"].values,
        "same_issue": "", "reviewer": ""})


def score_pair_review(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    r = pd.read_csv(path, dtype=str, keep_default_na=False)
    done = r[r.same_issue.str.strip().str.lower().isin(["yes", "no"])]
    if len(done) < len(r):
        return {"reviewed": len(done), "sample": len(r), "precision": None, "note": "review incomplete"}
    yes = (done.same_issue.str.strip().str.lower() == "yes").sum()
    return {"reviewed": len(done), "sample": len(r), "precision": round(yes / len(done), 3)}


def stability(first: pd.DataFrame, second: pd.DataFrame) -> dict:
    m = first.merge(second, on="ticket_id", suffixes=("_1", "_2"))
    agree = (m.theme_1 == m.theme_2).mean() if len(m) else None
    return {"n": len(m), "theme_agreement": None if agree is None else round(float(agree), 3)}
