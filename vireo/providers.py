"""LLM provider selection (DECISIONS.md D-6).

The classifier (classify.Classifier) talks to one interface: client.messages.create(model, max_tokens, system,
messages, output_config) returning an object with .content[*].text, .usage.input_tokens/.output_tokens and
.stop_reason. The Anthropic SDK provides that natively; GeminiClient adapts the google-genai SDK to the same shape,
so validation, retry/fallback, cache, cost guards and usage logging are unchanged and provider-agnostic.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from collections import deque
from types import SimpleNamespace

from .classify import ProviderRateLimited

ENV_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}

# Gemini finish reasons that are not a normal completion. MAX_TOKENS -> "max_tokens"; every other non-STOP reason
# (SAFETY, BLOCKLIST, PROHIBITED_CONTENT, SPII, RECITATION, LANGUAGE, OTHER, ...) -> "refusal". Both make
# Classifier._parse reject the output, so the ticket goes through the existing retry -> OTHER_UNCLEAR fallback.
_STOP_MAP = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}


def active_provider(cfg: dict) -> str:
    p = cfg["ai"]["provider"]
    if p not in ENV_KEYS:
        raise ValueError(f"ai.provider must be one of {sorted(ENV_KEYS)}, got {p!r}")
    return p


def model_ladder(cfg: dict) -> list[str]:
    """Cheapest-first model ladder for the active provider (PRD §13.1, amended by D-6)."""
    return cfg["ai"]["model_ladders"][active_provider(cfg)]


def check_model(cfg: dict, model: str) -> None:
    """Refuse to send a model name to the wrong provider (e.g. a Claude model to Gemini)."""
    mcfg = cfg["ai"]["models"].get(model)
    if mcfg is None:
        raise ValueError(f"model {model!r} has no entry in config ai.models")
    if mcfg.get("provider") != active_provider(cfg):
        raise ValueError(f"model {model!r} belongs to provider {mcfg.get('provider')!r}, "
                         f"but ai.provider is {active_provider(cfg)!r}")


class RateLimiter:
    """Thread-safe sliding-window limiter: at most `max_requests` request starts in any `window_s` seconds, shared
    by all worker threads. `cooldown()` pauses every worker until a server-specified time (after an HTTP 429)."""

    def __init__(self, max_requests: int, window_s: float, clock=time.monotonic, sleep=time.sleep):
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        self.max_requests, self.window_s, self.clock, self.sleep = max_requests, window_s, clock, sleep
        self._starts: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request may start; returns the seconds waited. Sleeps outside the lock."""
        waited = 0.0
        while True:
            with self._lock:
                now = self.clock()
                while self._starts and now - self._starts[0] >= self.window_s:
                    self._starts.popleft()
                wait = self._blocked_until - now
                if wait <= 0 and len(self._starts) < self.max_requests:
                    self._starts.append(now)
                    return waited
                if wait <= 0:
                    wait = self.window_s - (now - self._starts[0])
            wait = max(wait, 0.05)                      # never a tight loop
            self.sleep(wait)
            waited += wait

    def cooldown(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, self.clock() + seconds)


_RETRY_DELAY = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)s\s*$")


def parse_quota_error(err) -> tuple[list[str], float | None]:
    """(quota ids, retry delay in seconds) from a Gemini 429 body (google.rpc.QuotaFailure + google.rpc.RetryInfo)."""
    body = getattr(err, "details", None) or {}
    error = body.get("error", body) if isinstance(body, dict) else {}
    quota_ids: list[str] = []
    delay = None
    for d in (error.get("details") or []) if isinstance(error, dict) else []:
        kind = str(d.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            quota_ids += [str(v.get("quotaId", "")) for v in d.get("violations", [])]
        elif kind.endswith("RetryInfo"):
            m = _RETRY_DELAY.match(str(d.get("retryDelay", "")))
            delay = float(m.group(1)) if m else None
    return quota_ids, delay


class _GeminiMessages:
    def __init__(self, genai_client, cfg: dict, limiter: RateLimiter, sleep=time.sleep, jitter=random.uniform):
        self._client, self._cfg, self._limiter, self._sleep, self._jitter = genai_client, cfg, limiter, sleep, jitter
        self._rl = cfg["ai"]["gemini_rate_limit"]

    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict], output_config: dict):
        from google.genai import types

        if len(messages) != 1 or messages[0]["role"] != "user" or not isinstance(messages[0]["content"], str):
            raise ValueError("Gemini adapter expects exactly one user message with string content")
        fmt = output_config.get("format", {})
        if fmt.get("type") != "json_schema":
            raise ValueError("Gemini adapter requires output_config.format.type == 'json_schema'")
        # output_config["effort"] is an Anthropic-only setting; Gemini models are configured with thinking_level.
        mcfg = self._cfg["ai"]["models"][model]
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=fmt["schema"],          # the same enum-constrained schema as the Anthropic path
            max_output_tokens=max_tokens,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=mcfg["thinking_level"].upper()),
        )
        return to_message(self._send(model=model, contents=messages[0]["content"], config=config))

    def _backoff(self, n: int) -> float:
        return min(self._rl["backoff_initial_s"] * 2 ** (n - 1), self._rl["max_wait_s"])

    def _send(self, **request):
        """The ONLY retry layer for Gemini (SDK retries are disabled in gemini_http_options). Every attempt,
        including retries, first takes a slot from the shared rate limiter."""
        import httpx
        from google.genai import errors

        n429 = ntransient = 0
        while True:
            self._limiter.acquire()
            try:
                return self._client.models.generate_content(**request)
            except errors.APIError as e:
                if e.code == 429:
                    quota_ids, delay = parse_quota_error(e)
                    if any("PerDay" in q for q in quota_ids):
                        raise ProviderRateLimited(f"Gemini daily quota exhausted ({', '.join(quota_ids)}); "
                                                  "not retrying") from e
                    if n429 >= self._rl["max_429_retries"]:
                        raise ProviderRateLimited(f"Gemini 429 RESOURCE_EXHAUSTED after {n429} paced retries "
                                                  f"({', '.join(quota_ids) or 'quota id not reported'})") from e
                    n429 += 1
                    wait = min(max(delay or 0.0, self._backoff(n429)), self._rl["max_wait_s"])
                    self._limiter.cooldown(wait + self._jitter(0, 1))     # pause ALL workers; honours RetryInfo
                    continue
                if e.code in self._rl["transient_status_codes"] and ntransient < self._rl["transient_retries"]:
                    ntransient += 1
                    self._sleep(self._backoff(ntransient) + self._jitter(0, 1))
                    continue
                raise                                   # 400/401/403/404 etc. and exhausted 5xx: fail loudly
            except httpx.TransportError:
                if ntransient >= self._rl["transient_retries"]:
                    raise
                ntransient += 1
                self._sleep(self._backoff(ntransient) + self._jitter(0, 1))


def to_message(resp) -> SimpleNamespace:
    """Translate a google-genai GenerateContentResponse into the Anthropic-shaped object the classifier reads."""
    um = getattr(resp, "usage_metadata", None)
    input_tokens = (getattr(um, "prompt_token_count", None) or 0) if um else 0
    # Thinking tokens are billed as output (Gemini pricing page), so they are counted in output_tokens for cost.
    output_tokens = ((getattr(um, "candidates_token_count", None) or 0)
                     + (getattr(um, "thoughts_token_count", None) or 0)) if um else 0

    text, stop = "", "refusal"
    feedback = getattr(resp, "prompt_feedback", None)
    candidates = getattr(resp, "candidates", None) or []
    if not (feedback and getattr(feedback, "block_reason", None)) and candidates:
        cand = candidates[0]
        reason = getattr(cand.finish_reason, "name", str(cand.finish_reason or ""))
        stop = _STOP_MAP.get(reason, "refusal")
        parts = (getattr(cand.content, "parts", None) or []) if cand.content else []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


def gemini_http_options(cfg: dict):
    """SDK transport options. retry_options is deliberately None: the SDK then uses stop_after_attempt(1), i.e. it
    never retries, so the adapter (which honours RetryInfo and the rate limiter) is the single retry layer and
    retries cannot multiply."""
    from google.genai import types
    return types.HttpOptions(timeout=cfg["ai"]["gemini_http"]["timeout_ms"], retry_options=None)


def make_limiter(cfg: dict, clock=time.monotonic, sleep=time.sleep) -> RateLimiter:
    rl = cfg["ai"]["gemini_rate_limit"]
    return RateLimiter(rl["requests_per_minute"] - rl["safety_margin"], rl["window_s"], clock=clock, sleep=sleep)


class GeminiClient:
    """Exposes .messages.create(...) like anthropic.Anthropic, backed by google-genai and paced by one RateLimiter
    shared by every worker thread of the command."""

    def __init__(self, cfg: dict, api_key: str, genai_client=None, limiter: RateLimiter | None = None,
                 sleep=time.sleep, jitter=random.uniform):
        if genai_client is None:
            from google import genai
            genai_client = genai.Client(api_key=api_key, http_options=gemini_http_options(cfg))
        self.limiter = limiter or make_limiter(cfg, sleep=sleep)
        self.messages = _GeminiMessages(genai_client, cfg, self.limiter, sleep=sleep, jitter=jitter)


def make_client(cfg: dict):
    """Build the client for ai.provider. The key is read only from the provider's own variable (.env supported)."""
    provider = active_provider(cfg)
    key = os.environ.get(ENV_KEYS[provider], "").strip()
    if not key:
        raise SystemExit(f"{ENV_KEYS[provider]} is not set (ai.provider = {provider}). "
                         "Copy .env.example to .env and add the key (see README).")
    if provider == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=key)
    return GeminiClient(cfg, api_key=key)
