"""Rate limiting and 429 handling for the Gemini adapter (DECISIONS.md D-7). Fully offline: a fake clock replaces
real sleeping, errors are real google.genai.errors objects built locally, and sockets are blocked by conftest."""
import json
import threading
import time

import pandas as pd
import pytest
from google.genai import _api_client, errors, types

from vireo.classify import Budget, Cache, Classifier, ProviderRateLimited
from vireo.providers import GeminiClient, RateLimiter, gemini_http_options, make_limiter, parse_quota_error

MODEL = "gemini-3.5-flash-lite"
GOOD = json.dumps({"theme": "PAIRING", "customer_claims_prior_contact": False})


class FakeTime:
    """Deterministic clock: sleep() advances time instantly and records every wait."""

    def __init__(self):
        self.now, self.sleeps, self._lock = 0.0, [], threading.Lock()

    def clock(self):
        with self._lock:
            return self.now

    def sleep(self, s):
        with self._lock:
            self.sleeps.append(s)
            self.now += s


def quota_429(retry_delay="34s", quota_id="GenerateRequestsPerMinutePerProject-FreeTier"):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                "quotaId": quota_id, "quotaValue": "15",
                                "quotaDimensions": {"location": "global", "model": MODEL}}]}]
    if retry_delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                              "message": "Resource has been exhausted", "details": details}})


def ok_response():
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=GOOD)]),
                                    finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=970, candidates_token_count=25))


class ScriptedGenai:
    """generate_content follows a script: each item is a response or an exception (last item repeats).
    `per_ticket` maps a substring of the request contents to its own script. Records each call's fake time."""

    def __init__(self, script=None, per_ticket=None, ft=None):
        self.script, self.per_ticket, self.ft = list(script or [ok_response()]), per_ticket or {}, ft
        self.calls, self._lock = [], threading.Lock()
        outer = self

        class _Models:
            def generate_content(self, **kw):
                with outer._lock:
                    outer.calls.append(outer.ft.clock() if outer.ft else time.monotonic())
                    seq = next((s for k, s in outer.per_ticket.items() if k in kw["contents"]), outer.script)
                    item = seq.pop(0) if len(seq) > 1 else seq[0]
                if isinstance(item, Exception):
                    raise item
                return item
        self.models = _Models()


def _gemini(cfg, genai, ft):
    limiter = make_limiter(cfg, clock=ft.clock, sleep=ft.sleep)
    return GeminiClient(cfg, api_key="unused", genai_client=genai, limiter=limiter, sleep=ft.sleep,
                        jitter=lambda a, b: 0.0)


def _send(client):
    return client.messages.create(model=MODEL, max_tokens=64, system="s",
                                  messages=[{"role": "user", "content": "x"}],
                                  output_config={"format": {"type": "json_schema", "schema": {"type": "object"}}})


def _max_in_window(starts, window):
    starts = sorted(starts)
    return max(sum(1 for t in starts if s <= t < s + window) for s in starts) if starts else 0


# ------------------------------------------------------------------ limiter
def test_config_paces_below_free_tier_quota(cfg):
    rl = cfg["ai"]["gemini_rate_limit"]
    assert rl["requests_per_minute"] == 15 and rl["requests_per_minute"] - rl["safety_margin"] == 13
    assert rl["window_s"] >= 60


def test_limiter_blocks_the_14th_request_until_the_window_rolls():
    ft = FakeTime()
    lim = RateLimiter(13, 61, clock=ft.clock, sleep=ft.sleep)
    assert all(lim.acquire() == 0 for _ in range(13)) and ft.now == 0
    lim.acquire()
    assert ft.now == pytest.approx(61)                    # waited for the oldest start to leave the window


def test_limiter_never_exceeds_rate_in_any_window():
    ft = FakeTime()
    lim = RateLimiter(13, 61, clock=ft.clock, sleep=ft.sleep)
    starts = []
    for _ in range(60):
        lim.acquire()
        starts.append(ft.now)
        ft.now += 0.3                                     # request latency
    assert _max_in_window(starts, 61) <= 13


def test_limiter_is_thread_safe_in_real_time():
    lim = RateLimiter(3, 0.3)
    starts, lock = [], threading.Lock()

    def worker():
        for _ in range(3):
            lim.acquire()
            with lock:
                starts.append(time.monotonic())
    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    starts.sort()
    assert len(starts) == 12
    assert all(starts[i + 3] - starts[i] >= 0.3 - 0.01 for i in range(len(starts) - 3))


# ------------------------------------------------------------------ SDK retry layer
def test_sdk_retries_are_disabled_so_retries_cannot_multiply(cfg):
    opts = gemini_http_options(cfg)
    assert opts.retry_options is None and opts.timeout == cfg["ai"]["gemini_http"]["timeout_ms"]
    args = _api_client.retry_args(opts.retry_options)       # the SDK's own translation of our options
    assert args["stop"].max_attempt_number == 1 and "retry" not in args


# ------------------------------------------------------------------ 429 / RetryInfo handling
def test_parse_quota_error():
    assert parse_quota_error(quota_429("34s")) == (["GenerateRequestsPerMinutePerProject-FreeTier"], 34.0)
    assert parse_quota_error(quota_429("1.5s"))[1] == 1.5
    assert parse_quota_error(quota_429(None))[1] is None


def test_429_honours_retry_info_then_succeeds(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([quota_429("34s"), ok_response()], ft=ft)
    msg = _send(_gemini(cfg, genai, ft))
    assert msg.content[0].text == GOOD and len(genai.calls) == 2
    assert genai.calls[1] - genai.calls[0] >= 34                 # waited at least the server's retryDelay


def test_429_without_retry_info_uses_backoff_not_a_tight_loop(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([quota_429(None), quota_429(None), ok_response()], ft=ft)
    _send(_gemini(cfg, genai, ft))
    gaps = [b - a for a, b in zip(genai.calls, genai.calls[1:], strict=False)]
    assert gaps[0] >= 5 and gaps[1] >= 10                        # 5 s, then 10 s


def test_persistent_429_gives_up_after_bounded_paced_retries(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([quota_429("34s")], ft=ft)
    with pytest.raises(ProviderRateLimited, match="after 4 paced retries"):
        _send(_gemini(cfg, genai, ft))
    assert len(genai.calls) == 1 + cfg["ai"]["gemini_rate_limit"]["max_429_retries"]
    assert all(b - a >= 34 for a, b in zip(genai.calls, genai.calls[1:], strict=False))


def test_daily_quota_is_not_retried(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([quota_429("34s", quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier")], ft=ft)
    with pytest.raises(ProviderRateLimited, match="daily quota"):
        _send(_gemini(cfg, genai, ft))
    assert len(genai.calls) == 1 and ft.sleeps == []


def test_server_error_retried_with_backoff(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}), ok_response()],
                          ft=ft)
    _send(_gemini(cfg, genai, ft))
    assert len(genai.calls) == 2 and ft.sleeps and ft.sleeps[0] >= 5


def test_client_errors_are_not_retried(cfg):
    ft = FakeTime()
    genai = ScriptedGenai([errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})], ft=ft)
    with pytest.raises(errors.ClientError):
        _send(_gemini(cfg, genai, ft))
    assert len(genai.calls) == 1


# ------------------------------------------------------------------ classifier integration
def _tickets(n):
    return pd.DataFrame({"ticket_id": [f"T{i:02d}" for i in range(n)],
                         "customer_message": [f"ticket-{i:02d} pairing fails" for i in range(n)],
                         "agent_notes": ["note"] * n})


def test_smoke_sized_run_classifies_all_20_within_the_rate(cfg, tmp_path):
    """20 tickets, 4 workers, 13 request starts per 61 s: all classified, never more than 13 in any window."""
    ft = FakeTime()
    genai = ScriptedGenai(ft=ft)
    clf = Classifier(_gemini(cfg, genai, ft), cfg, MODEL, Cache(tmp_path))
    recs, stats = clf.classify_tickets(_tickets(20), "smoke", Budget(5.0, 20, 0.01), use_cache=False)
    assert stats.classified == 20 and stats.skipped_rate_limited == 0 and len(genai.calls) == 20
    assert _max_in_window(genai.calls, 61) <= 13
    assert max(genai.calls) >= 61                                # the 14th start had to wait for the window


def test_rate_limit_exhaustion_is_graceful_and_caches_nothing_for_skipped(cfg, tmp_path):
    ft = FakeTime()
    genai = ScriptedGenai(per_ticket={"ticket-01": [quota_429("34s")]}, ft=ft)
    cfg1 = {**cfg, "ai": {**cfg["ai"], "concurrency": 1}}        # deterministic order: T00, T01, T02, T03
    clf = Classifier(_gemini(cfg1, genai, ft), cfg1, MODEL, Cache(tmp_path))
    recs, stats = clf.classify_tickets(_tickets(4), "smoke", Budget(5.0, 4, 0.01), use_cache=False)  # no exception
    assert stats.classified == 1 and stats.skipped_rate_limited == 3 and "paced retries" in stats.rate_limit_message
    assert [r["ticket_id"] for r in recs] == ["T00"]
    assert set(Cache(tmp_path).records) == {k for k in Cache(tmp_path).records if k.startswith("T00|")}
    assert len(genai.calls) == 1 + 5                             # T00 once, T01 1+4 retries, T02/T03 never called
