import json

import pandas as pd
import pytest

from conftest import FakeClient
from vireo.classify import Budget, Cache, Classifier
from vireo.evaluate import (GOLD_FILE, load_gold, make_gold_sample, passes, repeat_recall, score_classification)
from vireo.impact import SCENARIO_TEMPLATE, illustrative_scenarios


def _gold_df(rows):
    return pd.DataFrame(rows, columns=["ticket_id", "gold_theme", "gold_customer_claims_prior_contact"])


def test_scoring_accuracy_macro_f1_and_families():
    gold = _gold_df([("1", "PAIRING", "false"), ("2", "PAIRING", "true"), ("3", "MIC", "false"), ("4", "STRAP", "false")])
    gold["gold_prior"] = gold.gold_customer_claims_prior_contact == "true"
    pred = pd.DataFrame({"ticket_id": ["1", "2", "3", "4"], "theme": ["PAIRING", "PAIRING", "MIC", "DISPLAY_TOUCH"],
                         "customer_claims_prior_contact": [False, True, True, False], "ai_error": [False] * 4})
    s = score_classification(gold, pred)
    assert s["accuracy"] == 0.75
    # F1: PAIRING 1, MIC 1, STRAP 0, DISPLAY_TOUCH 0 -> macro 0.5
    assert s["macro_f1"] == 0.5
    assert s["per_family"]["Wearable hardware"] == {"n": 1, "accuracy": 0.0}
    assert s["prior_contact"] == {"precision": 0.5, "recall": 1.0, "gold_positive": 1, "predicted_positive": 2}


def test_thresholds(cfg):
    ok, why = passes({"accuracy": 0.9, "per_family": {"Audio": {"n": 5, "accuracy": 0.8}}}, cfg)
    assert ok and not why
    ok, why = passes({"accuracy": 0.9, "per_family": {"Audio": {"n": 5, "accuracy": 0.6}}}, cfg)
    assert not ok and "Audio" in why[0]
    assert not passes({"accuracy": 0.84, "per_family": {}}, cfg)[0]


def _write_gold(dirpath, labelled=True):
    g = pd.DataFrame({"ticket_id": ["T1", "T2"], "customer_message": ["a", "b"], "agent_notes": ["", ""],
                      "gold_theme": ["PAIRING", "MIC"] if labelled else ["", ""],
                      "gold_customer_claims_prior_contact": ["false", "true"] if labelled else ["", ""]})
    g.to_csv(dirpath / GOLD_FILE, index=False)


def test_unlabelled_gold_refused(tmp_path):
    _write_gold(tmp_path, labelled=False)
    with pytest.raises(ValueError, match="not labelled"):
        load_gold(tmp_path)


def test_gold_is_immutable_after_scoring_begins(tmp_path):
    _write_gold(tmp_path)
    load_gold(tmp_path)                                   # first scoring creates the lock
    assert (tmp_path / "gold_lock.json").exists()
    load_gold(tmp_path)                                   # unchanged file is fine
    g = pd.read_csv(tmp_path / GOLD_FILE, dtype=str, keep_default_na=False)
    g.loc[0, "gold_theme"] = "MIC"
    g.to_csv(tmp_path / GOLD_FILE, index=False)
    with pytest.raises(ValueError, match="changed after scoring"):
        load_gold(tmp_path)


def test_no_network_evaluation_end_to_end(cfg, tmp_path):
    """Gold set scored with a fake client: the evaluation path never needs the real API in tests."""
    _write_gold(tmp_path)
    gold = load_gold(tmp_path)
    tickets = gold[["ticket_id", "customer_message", "agent_notes"]]
    reply = lambda kw: json.dumps({"theme": "PAIRING" if "<customer_message>\na\n" in kw["messages"][0]["content"]
                                   else "MIC", "customer_claims_prior_contact": False})
    clf = Classifier(FakeClient(default=reply), cfg, "claude-haiku-4-5", Cache(tmp_path / "cache"))
    recs, _ = clf.classify_tickets(tickets, "eval", Budget(1.0, 10, 0.01))
    s = score_classification(gold, pd.DataFrame(recs))
    assert s["accuracy"] == 1.0 and s["prior_contact"]["recall"] == 0.0


def test_repeat_recall_uses_in_window_declared_only():
    declared = pd.DataFrame({"ticket_id": ["a", "b", "c"], "status": ["in_window", "in_window", "outside_window"]})
    r = repeat_recall(declared, repeat_ids={"a", "c"}, classified_ids={"a", "b", "c"})
    assert r["reference_n"] == 2 and r["flagged"] == 1 and r["recall"] == 0.5
    assert "validation proxy" in r["note"]


@pytest.mark.real_data
def test_gold_sample_is_reproducible_and_stratified(cfg):
    from vireo.cli import _clean
    t = _clean(cfg).tickets
    a = make_gold_sample(t, 120, 1, 3)
    b = make_gold_sample(t, 120, 1, 3)
    assert a.ticket_id.tolist() == b.ticket_id.tolist() and a.ticket_id.is_unique and len(a) == 120
    assert set(a.channel) == {"chat", "email", "voice", "social"} and set(a.source_system) == {"helpdesk", "legacy_fd"}
    assert (a.gold_theme == "").all()                     # never pre-filled (no model or heuristic labels)


def test_illustrative_scenario_wording():
    s = illustrative_scenarios(100_000, [10, 25])
    assert s == [SCENARIO_TEMPLATE.format(pct=10, inr=10_000), SCENARIO_TEMPLATE.format(pct=25, inr=25_000)]
    assert s[0].startswith("Illustrative arithmetic, not a forecast or savings claim: if repeat contacts were 10% lower")
    assert illustrative_scenarios(None, [10]) == []
