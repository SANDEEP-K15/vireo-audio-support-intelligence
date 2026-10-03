# Decisions log — PRD v1.1 deviations investigated (3 Oct 2026)

Every figure below was computed from the source files with the code in this repository; no API calls were made.
Each decision says whether it changes a business definition. **None of them changes how repeat contacts, costs,
SLA breaches, transfers or CSAT are defined.** The PRD text is not edited; the amendments are listed in
`docs/PRD.md` → "Amendments v1.2" with a pointer here.

---

## D-1 · C9 — tickets created before their linked order (232 direct + 94 fallback)

**Question.** Are the 94 fallback-linked cases genuine, or artifacts of the `customer_id + product_sku` fallback?
Does C7 need tightening? Should A2 stay at 232?

**Evidence**

| | Direct `order_id` links | Fallback (unique customer+SKU) links |
|---|---|---|
| Links | 7,852 | 3,303 |
| Ticket created before linked order | 232 | 94 |
| **Rate** | **2.95%** | **2.85%** |
| Customer quotes exactly the linked order id in the message | 111 | 6 |
| Intake category *Product Enquiry* (asking before buying), not quoted | 61 | 55 |
| No evidence either way | 60 | 33 |

- The before-order rate is the same for direct and fallback links. Among the direct links, 111 tickets quote that
  exact order id in the message, so their link is certainly correct and their date still precedes the order.
  **Tickets predating their order is a property of the source data, not of the fallback rule.**
- Fallback precision on the verifiable subset: of all 3,303 fallback links, 160 tickets quote an order id in the
  message, and **160/160 match the fallback-linked order**.
- Of the 94:
  - **6 are verified genuine**: the customer quoted the linked order id.
  - **55 are genuine customer–product relationships**: pre-sales enquiries, with the purchase following the
    question by a median of 5.6 days (IQR 2.6–7.8, max 166.4).
  - **33 cannot be verified**: 20 of them have a gap over 60 days, most likely because the customer's actual
    purchase is not in `orders.csv` (orders start 15 Jun 2024). **At most 33 (1.0% of fallback links) are
    fallback artifacts.**
- My earlier statement in the v1 digest/README, that these 94 were "evidence that those fallback links are
  wrong", was **overstated** and has been corrected.

**Decision**

1. **C7 fallback rule unchanged.** Tightening it with a date condition would discard 6 verified links and 55
   pre-sales links in order to remove at most 33 uncertain ones, and the direct links show the same date pattern.
   Order links feed **no** digest metric; only the C6 refund guard reads them, and it found 0 issues.
2. **C9 reporting:** all 326 tickets stay flagged (`created_before_order`). The data-quality report shows:
   - `tickets_before_order_date` = 232 (direct, the PRD basis)
   - `fallback_linked_before_order_date` = 94
   - the 6 / 55 / 33 evidence split
3. **A2:** keeps **232** as the direct-link assertion (unchanged), and **adds** an assertion
   `fallback_linked_before_order_date = 94`. This adds coverage and changes no existing figure.

*Smallest defensible change: one additional assertion plus a reporting breakdown. No rule change.*

---

## D-2 · C7 — ambiguous fallback joins: 751 vs 720

**Evidence.** The 751 raw rows are 720 distinct tickets. 62 of the rows belong to 31 tickets that were re-imported
from Freshdesk, so each appears twice (helpdesk + legacy_fd), and both copies are ambiguous. 720 + 31 = 751.

**Decision.** The data-quality report uses **720** (`order_link_ambiguous`). The ticket is the unit of analysis
everywhere after C2 de-duplication, and 751 counts 31 tickets twice. **751** is kept only as a raw-export
reconciliation assertion (`raw_order_link_ambiguous`), so a change in the raw export is still caught.

**A2 amendment:** "751 ambiguous fallback joins" now reads "751 raw rows = 720 tickets after de-duplication"; both
are asserted. This is a basis clarification, not a definition change.

---

## D-3 · Declared repeats outside the window: discovery 67 vs implementation 78

**The 67 is reproduced exactly** with the discovery code path:

> **Rule used for 67:**
> 1. Take tickets whose customer message matches the strict declared-repeat pattern (484).
> 2. Remove those with an in-window same-customer + same-SKU prior ticket A (406), leaving 78.
> 3. Sort the customer's tickets by `created_at` and take the **immediately previous ticket**.
> 4. Keep the case only if that ticket has the **same SKU** and a **non-null `resolved_at`**.
> 5. Measure the gap from its `resolved_at` to B's `created_at` → **67 tickets**, gaps 30–42 days.

> **Rule used for 78:** the same 484, minus the same 406 in-window tickets. Each remaining ticket is labelled by
> the gap to the **nearest earlier resolved same-SKU ticket**, which is the same prior-ticket test as the §11
> repeat definition.

**They are the same 78 tickets.** Discovery's 67 is a sub-bucket. The 11 others were left out of the 67 only
because of what the *immediately* previous ticket looked like:

| Bucket (implementation `outside_detail`) | n | Why it isn't in the 67 |
|---|---|---|
| `prev_same_sku_resolved` | **67** | identical to discovery |
| `prev_same_sku_unresolved` | 6 | the immediately previous same-SKU ticket was still open, so `resolved_at` was null and no gap was computed |
| `prev_other_sku` | 5 | the immediately previous ticket was a different product |

The 11 tickets (each one has an earlier resolved same-SKU ticket 30.5–66.2 days before it):

| ticket | immediately previous | nearest same-SKU resolved gap |
|---|---|---|
| TK-241486 | TK-241201, same SKU, open | 44.8 d |
| TK-244932 | TK-244441, same SKU, open | 46.6 d |
| TK-249094 | TK-248648, same SKU, open | 33.4 d |
| TK-251117 | TK-250515, same SKU, open | 52.8 d |
| TK-251449 | TK-250416, same SKU, open | 47.4 d |
| TK-251570 | TK-251117, same SKU, open | 66.2 d |
| TK-244922 | TK-244438 (VA-SW-NX2 ≠ VA-EB-PL2) | 30.5 d |
| TK-248712 | TK-247578 (VA-EB-AIR ≠ VA-SW-NX1) | 30.6 d |
| TK-249358 | TK-248163 (VA-HP-ST2 ≠ VA-SP-MINI) | 36.5 d |
| TK-253007 | TK-252004 (VA-HP-ST2 ≠ VA-SW-FIT) | 31.3 d |
| TK-254078 | TK-253607 (VA-SP-MINI ≠ VA-EB-PL2) | 34.4 d |

**Which definition is used for evaluation.** Repeat recall (PRD §13.3) uses **only the in-window set**, which is
**identical (406 tickets, same IDs) under both definitions**. The outside-window figure is transparency reporting
(§11) and does not enter any metric. The digest reports **78** split as **67 / 6 / 5**, so the discovery figure is
visible and reconciled. The 78 basis is kept because it applies the same prior-ticket test as the §11 definition
(A must be resolved before B, same SKU). The "immediately previous ticket" test is a discovery shortcut that
depends on unrelated intervening tickets.

**Note for the client:** 6 customers said "I already raised this" while their previous same-SKU ticket was still
open. Policy §10 cannot count these as repeat contacts, because there is no resolution to measure 30 days from.

---

## D-4 · Digest classification scope: 292 → 273

**Evidence.** For week 2026-06-22: 199 tickets were created (B). Their same-customer **same-SKU** candidate prior
tickets add 74, giving **273**, the PRD §14.4 minimum. The earlier implementation also pulled in **19** other-SKU
prior tickets so that the optional "without the SKU condition" sensitivity could be computed, giving 292. That
exceeded the PRD's definition of the minimum scope.

**Decision.** The scope is now exactly PRD §14.4: B + same-customer same-SKU candidate A tickets → **273**. The
trailing-12-month scope is 9,653 (previously 9,661). Under a fallback scope, the no-SKU sensitivity shows "not
computed". The code already refuses to compute it unless every cross-SKU candidate is classified. Under the full
backfill it is computed as before. The primary metric needs nothing outside the 273.

---

## D-5 · Comparison windows

**Finding.** The implementation was inconsistent with itself:

| Use | PRD wording | Before | After |
|---|---|---|---|
| Repeat comparison (§15.2) | "compared with the trailing 4-week average" | W−4…W−1 | W−4…W−1 (unchanged) |
| Theme change (§15.4) | "change against the trailing 4-week average" | W−4…W−1 | W−4…W−1 (unchanged) |
| Leaderboard (§16) | "selected week **and** trailing 4 weeks" | W−3…W (included W) | **W−4…W−1** |
| Projected monthly cost (§14.2) | "trailing 4 full weeks" | W−3…W (included W) | **W−4…W−1** |

**Decision.** There is one definition everywhere: **"trailing 4 weeks" = the 4 full Monday–Sunday weeks
immediately before the selected week, with the selected week excluded.** It is implemented once
(`metrics.trailing_mask`) and covered by a test. Reasons:

- A comparison baseline must not contain the week it is compared with.
- §16 lists the selected week and the trailing weeks as separate items.
- The PRD uses the same phrase everywhere, so it must mean one thing.

Leaderboard columns are renamed `prev4w_*` and the report labels say "previous 4 weeks". This is a correction to
match the PRD, not a definition change.

---

## Verification

- `python -m vireo check`:
  - 751 raw / 720 ambiguous
  - 232 direct + 94 fallback before-order, with the 94 split 6 / 55 / 33
  - all invariants and baselines pass
- `python -m vireo backfill --dry-run`: scopes full 11,875 / trailing-12m 9,653 / digest 273. No API call.
- `python -m pytest -q`: **55 passed** (was 52), with FutureWarnings treated as errors. The new tests:
  - D-1/D-2 assertions on the real export
  - the same-SKU minimum scope
  - the 406 / 67 / 6 / 5 reconciliation on the real export
  - trailing-window exclusion, including in the leaderboard

---

## D-6 · LLM provider: Gemini added and made active; Anthropic kept (3 Oct 2026)

**Trigger.** Anthropic API access failed because the account had insufficient credits. The client chose not to buy
credits and asked for Gemini, keeping the Anthropic implementation selectable.

**Design: smallest change that preserves the contract.** The classifier talks to one interface,
`client.messages.create(...)`, and reads `.content[*].text`, `.usage.input_tokens/.output_tokens` and `.stop_reason`.
The new `vireo/providers.py` adds a `GeminiClient` adapter that exposes that same interface on top of Google's
official `google-genai` SDK (tested with 2.28.0). **`vireo/classify.py` is unchanged.** So, unchanged for both
providers:

- the 26-value taxonomy enum, the JSON schema and Pydantic validation (`extra="forbid"`)
- retry once, then `OTHER_UNCLEAR` with `ai_error=true`
- the cache key (`ticket_id + input_hash + prompt_version + model`; Gemini and Claude results never mix)
- the budget guards, the backfill gate and usage/cost logging
- the prompt-injection delimiters and the system-prompt instruction
- all Python metrics, repeats, leaderboard and digest code

| Anthropic request/response | Gemini (`client.models.generate_content`) |
|---|---|
| `system` | `GenerateContentConfig.system_instruction` |
| one user message (delimited ticket text) | `contents` (same string) |
| `output_config.format.schema` (JSON schema) | `response_mime_type="application/json"` + `response_json_schema` (**same schema object**) |
| `max_tokens` | `max_output_tokens` |
| `output_config.effort` (Claude only) | not used; `ThinkingConfig(thinking_level=MINIMAL)` from config |
| n/a | `temperature=0` |
| `usage.input_tokens` | `usage_metadata.prompt_token_count` |
| `usage.output_tokens` | `candidates_token_count + thoughts_token_count` (thinking is billed as output) |
| `stop_reason` | `STOP`→`end_turn`; `MAX_TOKENS`→`max_tokens`; any other finish reason, a blocked prompt, or no candidates→`refusal`. The last two make the classifier treat the output as invalid → retry → fallback |
| SDK transport retries | `HttpRetryOptions`: 4 attempts, 2–30 s backoff, on 429/500/502/503/504; 60 s timeout |

`thought=True` parts are excluded from the answer text. A model name sent to the wrong provider is refused
(`check_model`), and a stored evaluation selection made under another provider is ignored.

**Model ladder (cheapest viable first).** `gemini-3.5-flash-lite` → `gemini-3.8-flash` → `gemini-3.1-pro-preview`.
Prices are the Gemini API paid tier per 1M text tokens (pricing page updated 2026-10-01):

| Model | Input | Output (incl. thinking) | Note |
|---|---|---|---|
| gemini-3.5-flash-lite | $0.30 | $2.50 | stable; no shutdown announced. **First smoke/eval model (client decision)** |
| gemini-3.8-flash | $0.75 | $3.75 | promotional until 2026-12-31; increases 2027-01-01 by an unpublished amount |
| gemini-3.1-pro-preview | $2.00 | $12.00 | preview; used only if both Flash models fail the gold set |

Rejected: `gemini-2.5-flash-lite` (legacy, available only to accounts with past usage) and
`gemini-3.1-flash-lite` (shutdown no earlier than 2027-05-07, which is too soon for a weekly digest).

**Settings.** `thinking_level: minimal` for every Gemini model (client decision). Concurrency was lowered from 8 to 4
for free-tier rate limits, whose actual values are shown only in AI Studio. `GEMINI_API_KEY` is read from `.env`;
the SDK's `GOOGLE_API_KEY` fallback is bypassed because the key is passed explicitly.

**Estimated cost (before measurement).** These assume ~1,600 input + 80 output tokens per ticket, at minimal
thinking. Measured values from the smoke test replace them.

| Model | Smoke (20) | Gold (120) | Weekly (240) | Full backfill (11,875) |
|---|---|---|---|---|
| gemini-3.5-flash-lite | $0.014 | $0.08 | $0.16 | $8.08 ($14.01 with 200 thinking tokens per ticket) |

**Open item for the client: data use.** Google's pricing page states that on the **free tier, content is used to
improve Google's products**; on the paid tier (billing linked, Tier 1) it is not. The ticket text contains customer
names, order IDs and complaint details. The provider switch was approved; whether the key is free-tier or
billing-enabled is the client's decision and is not recorded as made.

**Not changed.** Gold labels (SHA-256 `189a79ae…`, not locked), PRD business definitions, thresholds, caps and every
deterministic metric.

**Verification (offline).** 17 new tests in `tests/test_providers.py` build real `google-genai` response objects
locally and fail on any network connection. They cover:

- request translation: same schema, same system prompt, delimiters, `MINIMAL` thinking, temperature 0
- thinking tokens counted in cost
- thought parts excluded from the answer
- finish-reason mapping
- invalid-enum retry; `MAX_TOKENS` and blocked-prompt fallback
- zero calls on a cache hit, and the cost cap
- the provider-mismatch refusal, the missing-key message, and building both clients offline

---

## D-7 · Gemini free-tier rate limit: client-side pacing and a single retry layer (3 Oct 2026)

**What happened.** The first `python -m vireo smoke` reached Gemini.
- **16 requests succeeded within 4 seconds** (15:17:58–15:18:02 UTC). All were schema-valid, at about 970 input /
  25 output tokens each, and were cached. That cost $0.0057.
- **The rest failed with HTTP 429 `RESOURCE_EXHAUSTED`**, quota `GenerateRequestsPerMinutePerProject-FreeTier`
  (limit 15, `gemini-3.5-flash-lite`).

**Root cause** (verified in `google-genai` 2.28.0 source, `_api_client.retry_args`):
1. **No client-side pacing.** 4 worker threads started requests as fast as responses came back, about 4 per second.
2. **SDK retries multiplied requests.** Our D-6 config passed `HttpRetryOptions(attempts=4, http_status_codes=[429, …])`.
   That makes tenacity retry each 429'd request up to 4 times with `wait_exponential_jitter` (about 2, 4, 8 s).
   That retry **ignores Gemini's `RetryInfo.retryDelay`**, bypasses any pacing, and lands inside the same
   exhausted 60-second window, so each failing ticket spent up to 4 requests.
3. **The 429 aborted the run.** The final `APIError` propagated through `classify_tickets` and aborted the whole
   run, so `out/smoke.json` was never written.

**Fix: one retry layer, paced.**

| Layer | Behaviour |
|---|---|
| SDK (`gemini_http_options`) | `retry_options=None`, which the SDK turns into `stop_after_attempt(1)`, i.e. **no SDK retries**. Timeout 60 s |
| `RateLimiter` (shared by all worker threads of a command) | Sliding window: at most **13 request starts per 61 s**, i.e. 15/min minus a safety margin of 2. Every attempt takes a slot, including every retry. Sleeps happen outside the lock, with a 0.05 s minimum, so there is no tight loop. Concurrency stays at 4; the limiter, not the thread count, bounds the rate |
| 429, per-minute quota | Parse `google.rpc.RetryInfo.retryDelay` and `QuotaFailure.quotaId`. Wait `max(retryDelay, backoff)`, where backoff is 5, 10, 20, 40 s capped at 120 s, plus 0–1 s jitter. The wait is applied as a **limiter cooldown, so all workers pause**, not just the one that hit the 429. Up to 4 retries |
| 429, daily quota (`quotaId` contains `PerDay`) | No retry: waiting cannot help. Raise `ProviderRateLimited` at once |
| 5xx / network transport errors | Up to 3 retries, backoff 5, 10, 20 s, still through the limiter |
| 400/401/403/404 | Not retried: fail loudly, as before |
| Retries exhausted | `ProviderRateLimited`, a provider-neutral exception in `classify.py`. **The classifier no longer crashes.** It records the ticket as `skipped_rate_limited`, **writes nothing to the cache for it** (no fake `OTHER_UNCLEAR`), stops starting new requests in that run (queued tickets make no calls), settles the cost of any attempt already made, and finishes normally. Re-running resumes from the cache |

The existing **validate-then-retry-once** step in `classify_one` is unchanged and separate: it fires only on a
*successful* HTTP response with invalid content. Each of its attempts also passes through the limiter.

**Smoke and gate semantics.**
- The smoke test still requests **20 tickets**.
- `valid_rate` is now computed over the requested 20, and `out/smoke.json` gains a `complete` flag. A run cut short
  by rate limits or caps therefore has `valid_rate < 1.0`, and the backfill gate refuses it.
- `wall_s_per_ticket` includes the pacing waits, so the gate's runtime projections reflect the real free-tier
  throughput.

**Expected paced durations** (lower bounds at 13 starts per 61 s):

| Run | Tickets | Paced lower bound |
|---|---|---|
| Smoke | 20 | ~1 min (13 at once, the other 7 after the window rolls) |
| Gold evaluation | 120 | ~9 min |
| Digest scope | 273 | ~20 min |
| Trailing 12 months | 9,653 | ~12.6 h |
| Full backfill | 11,875 | ~15.5 h |

On the free tier, the gate (45-min runtime cap) will therefore fall back to the **digest scope**. The free-tier
**requests-per-day** quota is not published outside AI Studio. A daily-quota 429 is reported, never retried.

**Cost.** Unchanged guards: $5 per run, $30 for the backfill. The measured tokens give about $0.00035 per ticket on
`gemini-3.5-flash-lite`.

**Tests (offline).** 14 new tests in `tests/test_rate_limit.py`, using a fake clock and real `google.genai.errors`
objects:

- the 14th request waits for the window, and no 61 s window ever exceeds 13 starts
- the limiter is thread-safe under real threads
- SDK retries are disabled, checked through the SDK's own `retry_args`
- `RetryInfo` parsing, with the retry delay honoured
- backoff when `RetryInfo` is missing
- bounded retries, and no retry on a daily quota
- 5xx retried; 400 not retried
- **a 20-ticket, 4-worker smoke-sized run classifies all 20 while staying at or below 13 per window**
- exhaustion is graceful, with nothing cached for skipped tickets

No API calls were made while implementing or testing this.

---

## D-8 · Repeat-precision review: 25 pairs, the complete flagged population (3 Oct 2026)

**Target.** PRD §13.4 and A6 call for a human "same issue?" review of **30** randomly sampled flagged repeat pairs.

**What the data allowed.** After the digest-scope backfill (D-7, 273 tickets), the classified data contained
**25** flagged repeat contacts: 20 whose repeat ticket B is in the digest week 22–28 Jun 2026, and 5 where gold-set
or smoke-test tickets happened to form fully classified pairs. `prepare-pairs` samples `min(30, available)`, so it
wrote **all 25** to `data/gold/repeat_pairs_review.csv`. **No synthetic or padded rows were added**, and no
`same_issue` value was pre-filled by the tool or by any model.

**Review.** Every one of the 25 pairs was reviewed by a human: **reviewer Sandeep Kumar**, `same_issue = yes` for
**25/25**. **Repeat precision = 25/25 = 100%** (threshold 80%). Together with repeat recall of **13/14 = 92.9%**
(customer-declared in-window repeats as a validation proxy; threshold 80%), **A6 passes**.

**Caveats, stated rather than hidden.**
- The 25 pairs are a census of what this scope produced, not a random sample from a larger population.
- They were reviewed by the same person who labelled the gold set.
- The recall reference is only 14 tickets.

A full-history backfill would produce a larger population to sample 30 from.

**Changes.** The digest now prints the reviewed population size from the review file ("human review of 25 flagged
pairs — the complete flagged population available under the digest scope; target was 30") instead of the configured
target. No metric logic changed. PRD amendment D-8 records the deviation.

---

## D-6 amendment · Data-use item resolved: the Gemini free tier was used (3 Oct 2026)

D-6 left one item open: whether the Gemini key was free-tier or billing-enabled. **It was the free tier.** The
smoke-test 429 on 2026-10-03 reported quota id `GenerateRequestsPerMinutePerProject-FreeTier`, and no billing was
enabled for this project.

**What was sent.** For each classified ticket, the customer message and the agent's closing note (delimited, as in
D-6) were sent to the Gemini API. That covered **407 distinct tickets** across 423 API calls:

| Run | Calls | Tickets |
|---|---|---|
| Smoke | 36 | 20 (16 calls from the first, quota-interrupted run) |
| Gold evaluation | 119 | 119 (plus 1 reused from cache) |
| Digest backfill | 268 | 268 |

No other ticket fields were sent. Google's Gemini API pricing page (updated 2026-10-01) states that free-tier content
is used to improve Google's products; on the paid tier it is not.

**Decision and limitation.** This is recorded as a **project data-use limitation**. The ticket text includes
customer names, order IDs and complaint details. The digest's data-quality section now shows this disclosure
whenever `ai.gemini_tier: free` is configured. Any production or repeat use should use a billing-enabled key, which
also removes the 15 requests/min limit that forced the digest scope (D-7). No claim is made here about how Google
actually handles this specific data beyond its published terms.
