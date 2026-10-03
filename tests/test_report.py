"""End-to-end offline digest on the real export with an isolated (empty or fake-filled) cache."""
import re

import pandas as pd
import pytest

from conftest import FakeClient
from vireo.classify import Budget, Cache, Classifier
from vireo.providers import model_ladder
from vireo.cli import _clean
from vireo.report import build_context, render, write_csvs
from vireo.repeats import scope_ticket_ids

pytestmark = pytest.mark.real_data          # every test here renders from the real export
WEEK = pd.Timestamp("2026-06-22")


@pytest.fixture(scope="module")
def clean_data(cfg):
    return _clean(cfg)


def _isolated_cfg(cfg, tmp_path):
    paths = {**cfg["paths"], "out_dir": tmp_path / "out", "cache_dir": tmp_path / "cache", "gold_dir": tmp_path / "gold"}
    return {**cfg, "paths": paths}


def test_digest_renders_offline_without_labels(cfg, clean_data, tmp_path):
    c2 = _isolated_cfg(cfg, tmp_path)
    ctx = build_context(clean_data, Cache(c2["paths"]["cache_dir"]), c2, WEEK)
    html = render(ctx, c2["paths"]["out_dir"]).read_text(encoding="utf-8")
    assert "Tickets closed — throughput, not performance" in html                      # A9
    assert "AI labels not validated" in html and "not computed" in html                 # no fabricated figures
    assert "created_at" in html and "resolved_at" in html                               # A13 stated
    assert "Known limitations" in html and "Deliberately out of scope" in html          # A11
    assert "<script" not in html.lower()                                                # static, no JS
    # A10: no savings claim; the only reduction wording is the labelled illustrative scenario
    allowed = ["not a forecast or savings claim", "Savings or ROI claims (only the labelled illustrative scenario)"]
    stripped = html
    for phrase in allowed:                                                              # disclaimers, not claims
        stripped = stripped.replace(phrase, "")
    assert not re.search(r"\bsav(e|es|ing|ings)\b|\bROI\b", stripped, re.I)


def test_digest_rejects_partial_week(cfg, clean_data, tmp_path):
    c2 = _isolated_cfg(cfg, tmp_path)
    with pytest.raises(ValueError, match="not a full"):
        build_context(clean_data, Cache(c2["paths"]["cache_dir"]), c2, pd.Timestamp("2026-06-29"))


def test_digest_with_fake_labels_computes_week_repeats_and_hides_free_text(cfg, clean_data, tmp_path):
    c2 = _isolated_cfg(cfg, tmp_path)
    t = clean_data.tickets
    scope = scope_ticket_ids(t, t.created_week == WEEK, cfg["policy"]["repeat_window_days"])
    cache = Cache(c2["paths"]["cache_dir"])
    clf = Classifier(FakeClient(), c2, model_ladder(c2)[0], cache)        # active provider; every ticket -> PAIRING
    clf.classify_tickets(t[t.ticket_id.isin(scope)], "test", Budget(100.0, 10_000, 0.001))
    ctx = build_context(clean_data, cache, c2, WEEK)
    assert ctx["rep_week"]["computed"] and ctx["week_coverage"] == 1.0
    assert ctx["rep_12m"]["computed"] is False                              # not covered -> not extrapolated
    assert ctx["scenarios"] == []                                           # scenario needs trailing-12m cost
    html = render(ctx, c2["paths"]["out_dir"]).read_text(encoding="utf-8")
    sample_msgs = t[t.created_week == WEEK].customer_message.str.strip().head(20)
    assert not any(m in html for m in sample_msgs if len(m) > 25)           # no customer free text
    paths = write_csvs(ctx, clean_data, cache, c2, c2["paths"]["out_dir"])
    assert all(p.exists() for p in paths)
