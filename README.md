# Vireo Audio — support digest & repeat-contact analysis

A command-line tool that turns Vireo Audio's 18-month helpdesk export into a **weekly static HTML digest**. The
digest measures **repeat contacts** (the same customer contacting again about the same issue within 30 days of
resolution, support policy §10) and their rupee cost. It also shows deterministic secondary KPIs and a
**tickets-closed leaderboard that is explicitly throughput, not performance**.

> **Final status (3 Oct 2026):**
> - The pipeline is complete and all 86 tests pass offline.
> - The 120-ticket gold set was labelled by a human and is **locked** (`gold_lock.json`, SHA-256 `189a79ae…`).
> - The smoke test, gold evaluation and **digest-scope backfill (273 tickets)** have all run on Gemini
>   (`gemini-3.5-flash-lite`). Anthropic credits were unavailable (`DECISIONS.md` D-6).
> - The 25 flagged repeat pairs were human-reviewed.
> - **A5, A6 and A7 pass.**
> - Total AI spend **$0.1514** (423 API calls, 407 distinct tickets).
> - The full 11,875-ticket backfill was **deliberately not run**: its projected runtime exceeded the limit (D-7).
> - Classification used the **Gemini free tier**; see the [data-use disclosure](#data-use-disclosure).
>
> See [Final results](#final-results-week-2228-jun-2026).

The specification is [`docs/PRD.md`](docs/PRD.md) (v1.1 with the v1.2 amendments). Implementation decisions are in
[`DECISIONS.md`](DECISIONS.md).

> **Data (not included in this public repository).** The eight assignment files (`tickets.csv`, `agents.csv`,
> `customers.csv`, `orders.csv`, `products.csv`, `README.txt`, `email-thread.txt`, `support-policy.pdf`) are the
> client's assignment materials and contain customer and ticket text, so they are not published. Put them, unchanged,
> in `data/raw/`, and check them with `sha256sum -c data/SOURCE_SHA256.txt` (run inside `data/raw/`).
>
> The human-labelled gold set (`data/gold/gold_tickets.csv`) and the pair review
> (`data/gold/repeat_pairs_review.csv`) contain ticket text and are also excluded. Their integrity lock
> (`data/gold/gold_lock.json`) and the full evaluation results (`out/eval/`) are included.
>
> **What runs where.** The published outputs in `out/` and the classification cache in `cache/` (ticket IDs and
> labels only, no ticket text) let reviewers read the digest and memo without the data. Running the pipeline, and the
> tests that read the real export, need the data files in `data/raw/`; those tests skip automatically without them.

---

## Final results (week 22–28 Jun 2026)

All figures are measured by the pipeline from the source data and the classification cache. Full detail is in
`out/digest_2026-06-22.html`.

**Acceptance (PRD v1.2)**

| Criterion | Result | Status |
|---|---|---|
| A5: gold-set classification | Accuracy **98.3%** (118/120), macro-F1 **0.984**, lowest family **Audio 92.9%** (threshold 70%); model `gemini-3.5-flash-lite`, 0 AI errors | **PASS** |
| A6: repeat validation | Recall **13/14 = 92.9%** (customer-declared in-window repeats, a validation proxy). Precision **25/25 = 100%**: human review of 25 flagged pairs, the complete flagged population available under the digest scope; reviewer Sandeep Kumar (D-8) | **PASS** |
| A7: measured repeat count and cost in the digest | **20 repeat contacts, Rs 5,130** for the selected week, with coverage stated (199/199 tickets, 87/87 candidate pairs) | **PASS** |

**Weekly business metrics**

| Metric | Value |
|---|---|
| Incoming tickets | **199** (chat 94, email 68, voice 24, social 13) |
| Repeat contacts | **20**: chat 11 (Rs 2,310), email 5 (Rs 1,300), voice 2 (Rs 1,040), social 2 (Rs 480) |
| Repeat-contact cost | **Rs 5,130** at policy channel rates. Sensitivity: Rs 5,800 at Rs 290/contact; Rs 3,600 at Rs 180/contact |
| Top repeat drivers | Transit damage / wrong item 3 (Rs 1,040); charging failure, mic, return pickup and warranty status 2 each. 10 of the 20 repeats involve Pulse 2 earbuds (VA-EB-PL2) |
| Top complaint themes | Delivery delay 25, refund not received 16, battery drain 15, charging failure 12, pre-sales 12. All 28 intake-bot "Other" tickets received a specific theme |
| SLA breach credits | **18 / Rs 6,300** |
| Transfers (helpdesk) | **22 / Rs 6,710** |
| CSAT | **3.26** (n=90, 46.9% response rate) |
| Leaderboard | Tier 1 ranked within each team only; Tier 2 unranked. **Throughput, not performance** |

Repeat cost, breach credits and transfer cost are separate lines and are not summed. **These are measured costs, not
savings.** No savings or ROI is claimed.

**AI cost:** smoke $0.012740, evaluation $0.042586, digest backfill $0.096047. **Total $0.1514** ($0.151373). About
$0.00036 per ticket; projected **$0.28 per month**.

---

## 1. What the tool does

1. **Cleans** the export with assertions that fail loudly. It de-duplicates the 653 re-imported legacy tickets,
   shifts legacy `resolved_at` from UTC to IST, treats legacy CSAT 0 as missing, treats legacy transfers as unknown,
   and links orders safely.
2. **Classifies** each ticket into a closed 26-value issue taxonomy with an LLM (Gemini by default, Claude
   selectable), using structured output plus
   Pydantic validation. It also records whether the customer says they contacted Vireo about this before.
3. **Computes deterministically** in Python:
   - repeat contacts and their cost
   - SLA breach credits
   - transfer cost
   - CSAT
   - volume
   - the leaderboard
4. **Evaluates** the classifier against a human-labelled gold set. Models are tried cheapest first.
5. **Gates** the full 11,875-ticket backfill on measured cost and runtime.
6. **Renders** a self-contained HTML digest plus CSVs. It never reproduces customer free text.

## 2. Business problem

The tickets go unread (Head of CX). Finance will only fund work that "takes contacts out of the queue", and it
wants no surprise model bill. Support Ops hears customers repeating themselves. Policy §10 defines a repeat contact
and costs it at the channel's contact cost (§4: chat Rs 210, email 260, voice 520, social 240). Deciding "same issue"
needs language understanding, and the intake-bot category can't provide it. The digest **measures** this cost. It
makes **no savings claim**; the only reduction figure is a labelled illustrative scenario.

## 3. Architecture

```
data/raw/*.csv ──► ingest (C1) ──► clean (C2–C11, assertions) ──► metrics (deterministic)
                                            │                         │
                                            ▼                         ▼
                           classify (LLM via providers.py,        repeats (§11 engine)
                           Pydantic, JSONL cache, cost guards)  ──►    │
                                            │                         ▼
                           evaluate (gold set, model ladder)     impact (§12) ──► report (Jinja2 → HTML + CSV)
```

- CLI + Python + pandas + Pydantic + Jinja2 + pytest, plus the provider SDK: `google-genai` (active) or `anthropic`.
- `vireo/providers.py` adapts Gemini to the same interface the classifier uses for Claude, so validation, retry,
  cache, cost guards and logging are identical for both (`DECISIONS.md` D-6).
- No server, database, frontend framework, agents or RAG.
- The cache is flat JSONL files.

## 4. Repository structure

```
DECISIONS.md           investigated PRD deviations (D-1…D-5): evidence and final decisions
config.yaml            policy constants (with § references), model ladder + prices, caps, thresholds, baseline assertions
vireo/
  ingest.py            C1 read CSVs as strings
  clean.py             C2–C11 cleaning rules, invariants, data-quality summary
  taxonomy.py          the 26-theme enum + labelling rules (single source for prompt, validation, gold guide, report)
  classify.py          classifier, cache, usage/cost log, budget guard, backfill gate (provider-agnostic)
  providers.py         provider selection (ai.provider) + Gemini adapter exposing the classifier's client interface
  metrics.py           §6 metrics, created/resolved week assignment, leaderboard
  repeats.py           §11 repeat engine, coverage, declared-repeat validation proxy
  impact.py            §12 business-impact arithmetic and illustrative scenario
  evaluate.py          gold sample, scoring, lock, repeat recall/precision, stability
  report.py            digest context + rendering + CSVs
  cli.py               commands
templates/digest.html.j2
data/raw/              unmodified assignment files
data/gold/             gold_tickets.csv (human-labelled, locked), gold_lock.json (SHA-256), LABELLING_GUIDE.md,
                       repeat_pairs_review.csv (25 human-reviewed pairs)
cache/                 classifications.jsonl, usage.jsonl   (git-ignored)
out/                   digest_<week>.html, CSVs, smoke.json, eval/, backfill_decision.json, memo_priya_raman.md
                       (git-ignored: archive out/ separately if submitting through git)
tests/                 pytest suite (no network)
```

## 5. Installation

Requires Python 3.10+. It was tested only on Python 3.14.2 on Windows; a fresh `.venv` inside this folder installed
and passed everything.

> **Windows note:** the `anthropic` package contains very long file paths. If the project sits in a deeply nested
> folder, `pip` can fail with "No such file or directory" on a `beta_managed_agents_…` file. Keep the checkout path
> short, or enable Windows long-path support.

```bash
python -m venv .venv
```
```bash
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```

## 6. Environment variables

| Variable | Needed for | How |
|---|---|---|
| `GEMINI_API_KEY` | `smoke`, `evaluate`, `backfill` when `ai.provider: gemini` (the default) | `cp .env.example .env`, then put the key in `.env` (git-ignored) |
| `ANTHROPIC_API_KEY` | the same commands, only when `ai.provider: anthropic` | same file |

Switch provider in `config.yaml` → `ai.provider` (`gemini` or `anthropic`). Only the active provider's key is
needed.

> **Data-use note (Gemini):** on Google's free tier, submitted content is used to improve Google's products; on the
> paid tier (billing linked) it is not. **This project's runs used the free tier** (see the
> [data-use disclosure](#data-use-disclosure)). Use a billing-enabled key for any further runs.

Every other command runs offline.

## 7. How to run (end to end)

All commands run from this directory with `python -m vireo <command>`.

| Step | Command | API? | What it does |
|---|---|---|---|
| 1 | `python -m vireo check` | no | Clean + all assertions (A2) + baseline KPIs (A3) |
| 2 | `python -m vireo prepare-gold` | no | Writes the stratified 120-ticket `data/gold/gold_tickets.csv` (already done; refuses to overwrite) |
| 3 | *(human)* | no | Label the gold file following `data/gold/LABELLING_GUIDE.md`, **without looking at model output** |
| 4 | `python -m vireo smoke` | yes | Classifies 20 tickets on `gemini-3.5-flash-lite` (the first model in the active provider's list) and measures validity, cost and runtime (`out/smoke.json`). Paced to the free-tier limit, so it takes about 1 min |
| 5 | `python -m vireo evaluate [--stability]` | yes | Scores the gold set cheapest first. Writes `out/eval/selection.json` and `eval_report.md` |
| 6 | `python -m vireo backfill [--dry-run]` | yes | Applies the backfill gate, then classifies the allowed scope |
| 7 | `python -m vireo prepare-pairs` | no | Samples up to 30 flagged repeat pairs into `data/gold/repeat_pairs_review.csv`. For 22–28 Jun 2026: 25 flagged pairs, representing the complete flagged population available under the digest scope (D-8) |
| 8 | *(human)* | no | Fill `same_issue` = yes/no and `reviewer` for every pair (done: 25/25 yes) |
| 9 | `python -m vireo digest [--week YYYY-MM-DD]` | no | Builds `out/digest_<week>.html` + CSVs (default week 2026-06-22) |

## 8. How to classify

Classification only happens through `smoke`, `evaluate` and `backfill`.

- **What the model returns:** one JSON object `{theme, customer_claims_prior_contact}`, constrained by a JSON
  schema whose `theme` is the taxonomy enum. Python validates it again with Pydantic (`extra="forbid"`).
- **Invalid output:** it is retried once. If it is still invalid, the ticket is set to `OTHER_UNCLEAR` with
  `ai_error=true`. These are counted in the report and never count as repeats.
- **Prompt injection:** ticket text is wrapped in `<customer_message>` / `<agent_note>` delimiters, any such tags
  inside the text are stripped, and the system prompt tells the model never to follow instructions found in ticket
  text.
- **What the model never does:** arithmetic, dates, joins, windows, rankings or aggregation.

## 9. How to evaluate

- `evaluate` locks `gold_tickets.csv` with SHA-256 (`gold_lock.json`) the first time it runs. Any later edit is
  refused.
- It runs the active provider's cheapest model first. Gemini: **3.5-flash-lite → 3.8-flash → 3.1-pro-preview**
  (Anthropic: Haiku 4.5 → Sonnet 5.5 → Opus 5.5). It stops at the first model that reaches
  accuracy ≥ 85% with every family ≥ 70%.
- It records accuracy, macro-F1, per-family accuracy, the confusion matrix, prior-contact precision/recall, cost per
  ticket and total evaluation cost for every model it tries.
- **Repeat recall** uses customer-declared repeats inside the 30-day window as the reference (406 tickets matched
  by strict text patterns). This is a validation proxy, not perfect ground truth.
- **Repeat precision** comes from the human review of 25 flagged pairs, representing the complete flagged population
  available under the digest scope (`DECISIONS.md` D-8).

## 10. How to generate a digest

```bash
python -m vireo digest --week 2026-06-22
```

The week must be a full Monday–Sunday week inside the export. The partial week 29 Jun – 5 Jul 2026 is rejected.

**Week assignment:**
- `created_at` drives incoming volume, complaint themes, bot-category reclassification and repeat contacts.
- `resolved_at` drives tickets closed, SLA breach credits, transfer cost, CSAT, handle time and Tier 2 days to
  resolve.

## 11. How caching works

- `cache/classifications.jsonl` is keyed by `ticket_id + input_hash + prompt_version + model`. A hit makes zero
  API calls.
- Changing the ticket text, the prompt version or the model produces a new key.
- `cache/usage.jsonl` logs every API attempt: purpose, model, tokens, cost and latency.
- The digest reads only the cache.

## 12. How costs are calculated

- **Cost per call** = input tokens × input price + output tokens × output price, using measured `usage` from each
  response.
- **Prices** (USD per 1M tokens, in `config.yaml`):

  | Provider | Model | Input | Output | Source |
  |---|---|---|---|---|
  | **Gemini (active)** | gemini-3.5-flash-lite | 0.30 | 2.50 | paid tier, pricing page 2026-10-01 |
  | Gemini | gemini-3.8-flash | 0.75 | 3.75 | promotional until 2026-12-31 |
  | Gemini | gemini-3.1-pro-preview | 2.00 | 12.00 | preview model |
  | Anthropic | Haiku 4.5 / Sonnet 5.5 / Opus 5.5 | 1 / 2 / 4 | 5 / 10 / 20 | list prices, 2026-09-25 |

- **Gemini thinking tokens** are billed as output and counted in `output_tokens` (`thoughts_token_count`). Thinking
  is set to `minimal`.
- **Rate limiting (Gemini free tier: 15 requests/min):** every request, including retries, takes a slot from a
  shared limiter, with at most 13 starts per 61 s. SDK retries are off. On HTTP 429 the adapter waits
  `max(RetryInfo.retryDelay, backoff)` and pauses all workers, retrying up to 4 times. A daily-quota 429 is never
  retried. A ticket that is still rate-limited is skipped and not cached, and the run finishes normally and can be
  resumed. Paced lower bounds: smoke ~1 min, gold evaluation ~9 min, digest scope ~20 min. A full backfill takes
  ~15.5 h, so on the free tier the backfill gate falls back to the digest scope (`DECISIONS.md` D-7).

- **Projected monthly cost** = mean measured cost per classified ticket × mean weekly tickets over the trailing 4
  weeks × 52 / 12. "Trailing 4 weeks" always means the 4 full weeks before the selected week, with the selected
  week excluded; this applies to every comparison and the leaderboard too (`DECISIONS.md` D-5).
- **Guards:** `max_usd_per_run` ($5) and `max_new_tickets_per_run`. The budget reserves 2× the running mean cost
  before each call and stops before any call that could exceed the cap.
- AI cost is reported in USD; there is no INR rate until Finance supplies one (`ai.usd_inr_rate`).

## 13. How the backfill gate works (PRD §14.4)

**Full backfill** of the 11,875 tickets runs only if **all** of these hold:

1. The smoke test was 100% schema-valid.
2. A model passed the gold set.
3. The projected cost is ≤ `max_usd_backfill` ($30).
4. The projected runtime is ≤ 45 min.

Projections use the smoke test's measured cost and wall-clock time per ticket.

**Otherwise it falls back** to the smallest viable scope, where each scope includes the candidate prior tickets
those repeats need:

- **trailing-12-month scope:** 9,653 tickets
- **digest scope:** 273 tickets for week 2026-06-22 (199 created that week + 74 same-customer, same-SKU prior
  tickets)

Fallback scopes include only same-SKU prior tickets, exactly as PRD §14.4 defines them. Under a fallback scope, the
optional "without SKU condition" sensitivity therefore shows "not computed" (see `DECISIONS.md` D-4). If no model
passed evaluation, only the digest scope runs, and its figures are labelled unvalidated. Without a smoke
test, nothing runs. Use `backfill --dry-run` to see the decision without any API call.

**Actual decision (3 Oct 2026, `out/backfill_decision.json`):** scope **`digest`**. Projections from the measured
smoke run:

| Scope | Projected runtime | Projected cost | Result |
|---|---|---|---|
| Full backfill | 627 min | $4.15 | not run: runtime over the 45-min limit |
| Trailing 12 months | 510 min | $3.37 | not run: runtime over the limit |
| Digest | 14.3 min | $0.095 | **run** |

The digest run classified **268 new tickets** (273 in scope; 5 were already cached from the gold and smoke runs):
0 skipped, 0 errors, $0.096047, 20 min 24 s.

## 14. Expected outputs

| File | Contents |
|---|---|
| `out/digest_2026-06-22.html` | The nine-section digest |
| `out/leaderboard_tier1_<week>.csv`, `out/leaderboard_tier2_<week>.csv` | Leaderboard tables |
| `out/classified_tickets.csv` | `ticket_id`, theme and flags, with no free text |
| `out/repeat_contacts_<week>.csv` | The week's repeat tickets |
| `out/smoke.json` | Smoke-test measurements |
| `out/eval/selection.json`, `out/eval/eval_report.md` | Evaluation results |
| `out/backfill_decision.json` | The gate decision |
| `out/memo_priya_raman.md` | One-page memo to the Head of CX |

## 15. Testing

```bash
python -m pytest -q
```

- 86 tests. They pass with network access blocked: a fixture makes any socket connection fail.
- **Coverage:**
  - every cleaning rule
  - the real-export assertions (A2/A3)
  - the SLA boundary, attended-only credits, and created vs resolved weeks
  - every repeat edge case (exactly 30 days, 30 days + 1 min, before resolution, different SKU, different theme,
    OTHER_UNCLEAR, open prior ticket, duplicate A, week bucketing, incomplete coverage)
  - leaderboard tier separation and the trailing-window definition
  - the same-SKU minimum scope, and the 406 / 67 / 6 / 5 declared-repeat reconciliation on the real export
  - cache hit, retry, fallback, extra fields, cost cap, ticket cap and backfill-gate paths
  - gold lock and no-network evaluation
  - the Gemini adapter, built from real `google-genai` response objects offline: request translation (same schema,
    prompt and delimiters, minimal thinking), thinking-token cost, finish-reason mapping, retry and fallback,
    blocked prompts, cache hits, cost cap, provider mismatch and missing key
  - rate limiting with a fake clock: at most 13 starts per 61 s window, thread safety, SDK retries disabled,
    `RetryInfo` honoured, backoff, bounded retries, no retry on a daily quota, 5xx vs 400 handling, a 20-ticket
    smoke-sized run that classifies all 20 within the rate, and graceful exhaustion with nothing cached
  - offline digest rendering, including the no-savings-claim and no-free-text checks
- Static check: `ruff check vireo tests --select E,F,W,B --ignore E501,E702,E731` is clean.

## 16. Known limitations

- "Same issue" means equal AI themes, so repeats across adjacent themes are undercounted. The same-SKU condition
  misses cross-SKU repeats; a sensitivity without it is reported.
- January 2025 repeats are undercounted because earlier tickets fall outside the export.
- The roster has no history, so team moves are invisible.
- Legacy transfers are unknown.
- CSAT is a ~44% response sample.
- Breaches aren't shown per agent, because policy attributes them to the resolving agent.
- AI labels carry the gold-set error rate, and the 120-ticket gold set gives wide uncertainty for rare themes.
- **PRD deviations, investigated and resolved** (evidence in `DECISIONS.md`):
  - **D-1:** 232 direct-linked + 94 fallback-linked tickets predate their order. The rate is the same for both link
    types (2.95% vs 2.85%), so this comes from the source data, not the fallback rule, and the C7 rule is unchanged.
    The 94 split as 6 verified by a quoted order id, 55 pre-sales enquiries and 33 unverifiable.
  - **D-2:** ambiguous joins are reported as 720 tickets; the 751 raw rows count 31 re-imported tickets twice.
  - **D-3:** the 78 declared repeats outside the window reconcile exactly to discovery's 67 (+6 whose previous
    ticket was still open, +5 whose previous ticket was another product). The 406-ticket recall reference is
    identical under both definitions.
  - **D-4:** the digest scope is the PRD minimum, 273 tickets.
  - **D-5:** "trailing 4 weeks" excludes the selected week everywhere.
- Some order links are unverifiable (at most 33 fallback links, 1.0%). Order links feed no digest metric.
- On Sonnet/Opus, refusals or `max_tokens` stops are treated as invalid output (retry, then `ai_error`). The
  server-side refusal fallback parameter is not used.
- **Digest-scope limitations.** Only the 273-ticket digest scope was classified, so these are **not computed** (never
  extrapolated):
  - 12-month and 18-month repeat-contact totals
  - the previous-4-week comparisons
  - the illustrative reduction scenario
  - the repeat count without the same-product condition
- **Small validation samples.**
  - Repeat recall rests on **14** customer-declared repeats.
  - Repeat precision rests on **25** pairs: the full flagged population under this scope, not a 30-pair random
    sample. They were reviewed by the same person who labelled the gold set.
  - The prior-contact flag rests on 11 gold positives.
  - `OTHER_UNCLEAR` had no gold examples.
- **D-6 to D-8:** Gemini provider, free-tier pacing and the 25-pair review are documented in `DECISIONS.md`.

### Data-use disclosure

Classification used the **Gemini API free tier**: the observed 429 quota id was
`GenerateRequestsPerMinutePerProject-FreeTier`, and billing was not enabled. The customer message and agent note for
**407 distinct tickets** (423 API calls) were sent to Google under free-tier terms. Google's Gemini API pricing page
states that free-tier content is used to improve Google's products. The ticket text includes customer names, order
IDs and complaint details. This is recorded as a project data-use limitation (`DECISIONS.md` D-6 amendment), and the
digest repeats it. Further runs should use a billing-enabled key.

## 17. Scope deliberately excluded

- Live helpdesk integration, a scheduler, hosting and authentication.
- A web server, database, frontend framework, agents, RAG, vector databases, LangChain/LangGraph or microservices.
- LLM-written narrative.
- Any performance, productivity or composite score; per-agent CSAT, breach or repeat rates.
- Savings or ROI claims.
- Lot-code defect clustering.
- Finance review of refund-plus-replacement orders and GW-OTHER refunds above Rs 500 (discovery observations).
- Stale-ticket chasing, the Message Batches API, translation, sentiment and roster-history reconstruction.

## 18. AI tools and models used

- **Runtime classifier (active):** the Gemini API via `google-genai` 2.28.0 `models.generate_content`, with JSON
  output constrained by `response_json_schema`. The ladder is `gemini-3.5-flash-lite` → `gemini-3.8-flash` →
  `gemini-3.1-pro-preview`, all at `thinking_level: minimal`.
- **Runtime classifier (selectable):** the Anthropic Messages API with structured outputs. The ladder is
  `claude-haiku-4-5` → `claude-sonnet-5-5` → `claude-opus-5-5`; Sonnet and Opus run at `effort: low`.
- **Development:** the code, tests and documentation were written with an AI coding assistant (Claude Code). The
  discovery analysis and every baseline figure were computed with pandas.

## 19. Actual measured cost

All costs below are measured from `cache/usage.jsonl` (`gemini-3.5-flash-lite`, paid-tier list prices; billed as
free tier). The Anthropic API was never called (no credits).

| Run | API calls | Tickets | Cost (USD) |
|---|---|---|---|
| Smoke (incl. 16 calls from the first, quota-interrupted run) | 36 | 20 | 0.012740 |
| Gold evaluation | 119 | 119 (+1 cached) | 0.042586 |
| Digest backfill | 268 | 268 | 0.096047 |
| **Total** | **423** | **407 distinct** | **0.151373 → $0.1514** |

- Measured usage: about 975 input + 26 output tokens per ticket, **about $0.00036 per ticket**. The pre-run estimate
  of 1,600 + 80 tokens was conservative.
- Projected steady-state cost: **$0.28 per month**.
- Projected full-history backfill: about $4.15 (from the backfill gate; not run).

## 20. Honest implementation time

- **Elapsed wall-clock time: about 4 h 20 min** (source files placed 18:00 IST; this final documentation pass
  ~22:20 IST, 3 Oct 2026). That covers discovery, the PRD, the AI-assisted build, deviation fixes, the provider
  switch, rate-limit handling, human labelling and review, and the paced API runs.
- **Initial code, tests and README build:** about 15 minutes (18:42–18:57 IST), AI-assisted.
- **Live API runs:**
  - smoke: 64 s
  - gold evaluation: about 9 min (15:36–15:45 UTC)
  - digest backfill: 20 min 24 s (15:59–16:19 UTC)
- **Human work:** gold labels saved 19:42 IST; pair review saved 21:57 IST. The time spent on each was not
  recorded.

---

## Run history and reproduction

Completed on 3 Oct 2026:
1. Gold set labelled by a human and locked.
2. `smoke`: 20/20 valid.
3. `evaluate`: A5 passed on the first, cheapest model.
4. `backfill`: gate chose the digest scope; 268/268 classified.
5. `prepare-pairs`: 25 pairs, all human-reviewed.
6. `digest`.

To rebuild the digest and CSVs from the cache **without any API call**:

```bash
python -m vireo digest
```

`check` and the test suite are also offline. Re-running `smoke`, `evaluate` or `backfill` calls the API (cached
tickets are not re-sent; `evaluate` will refuse an edited gold file).
