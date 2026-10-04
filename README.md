# Vireo Audio — Support Intelligence Pipeline

A weekly support digest that measures repeat contacts and their cost. An LLM classifies ticket issues; everything
else is deterministic Python.

| | |
|---|---|
| **Input** | 18-month helpdesk export (12,528 rows, 11,875 tickets after de-duplication) plus orders, customers, products and the agent roster |
| **LLM** | Assigns each ticket one of 26 issue themes, and flags whether the customer says they contacted Vireo before. Nothing else |
| **Python** | Cleaning, validation, joins, dates, repeat detection, cost, SLA, CSAT, leaderboard, aggregation, reporting |
| **Output** | A static HTML weekly digest, CSV extracts, an evaluation report and a one-page memo |
| **Status** | Assignment scope. Run end to end for the week of 22–28 Jun 2026. Not deployed |

## Problem

Vireo's support policy (§10) defines a **repeat contact**: the same customer contacting again about the same issue
within 30 days of resolution. It prices each one at the contact cost of its channel. Nobody was measuring it.

The client asked for three things:
- a weekly digest;
- a tickets-closed leaderboard;
- a measurable outcome with a bounded model cost.

Counting, dating and costing contacts is straightforward. Deciding whether two tickets are about the *same issue*
is not: ticket text is noisy, with typos, Hinglish and IVR transcripts. That one judgement is the only reason an
LLM is involved.

## What the system does

1. **Cleans** the export, with assertions that fail the run on any violated invariant:
   - de-duplicates 653 re-imported legacy tickets;
   - converts legacy `resolved_at` from UTC to IST;
   - treats legacy CSAT 0 as missing and legacy transfers as unknown;
   - links orders only when the match is unambiguous.
2. **Classifies** each ticket into a closed taxonomy, with schema-constrained output and Pydantic validation.
3. **Evaluates** the classifier against a human-labelled, hash-locked gold set, trying models cheapest first.
4. **Gates** the historical backfill on measured cost and runtime, and falls back to the smallest scope that still
   produces the digest.
5. **Computes** repeat contacts, policy costs, SLA breach credits, transfers, CSAT and the leaderboard in Python.
6. **Renders** a static HTML digest and CSVs. Customer free text never appears in any output.

## Key results — week of 22–28 Jun 2026

**Measured business metrics** (deterministic, from the classified week):

| Metric | Value |
|---|---|
| Incoming tickets | 199 (chat 94, email 68, voice 24, social 13) |
| Repeat contacts | **20** |
| Repeat-contact cost (policy channel rates) | **Rs 5,130**: chat 11 / Rs 2,310, email 5 / Rs 1,300, voice 2 / Rs 1,040, social 2 / Rs 480 |
| SLA breach credits | 18 / Rs 6,300 |
| Transfers (helpdesk tickets) | 22 / Rs 6,710 |
| CSAT | 3.26 (n=90, 46.9% response rate) |

These are three separate cost lines and are deliberately **not summed**, because one ticket can be both a repeat and
a breach. Re-pricing the 20 repeats at a single blended rate gives Rs 5,800 (Rs 290 per contact) or Rs 3,600
(Rs 180 per contact). Those are re-pricings of the same count, not additional results.

**Validation:**

| Check | Result |
|---|---|
| Theme classification (120 gold tickets) | 98.3% accuracy (118/120), macro-F1 0.984, lowest family 92.9% (Audio) |
| Repeat recall (proxy reference) | 13/14 = 92.9% |
| Repeat precision (human review) | 25/25 = 100% |

**Engineering:**

| Item | Value |
|---|---|
| Tests | 86 passing, offline (79 pass + 7 skip without the unpublished dataset) |
| Measured AI spend, all runs | $0.1514 (423 API calls, 407 distinct tickets) |
| Digest scope | 273 tickets: 199 from the week + 74 earlier same-customer, same-product tickets |
| New classifications in the digest backfill | 268 (5 were already cached); 0 errors, 0 skipped |

No savings or ROI figure is claimed. Rs 5,130 is the *measured cost* of repeat contacts in one week. The digest
identifies their drivers; it does not reduce contacts by itself.

## Architecture

```
 data/raw/ (5 CSVs)                                                        config.yaml
     │                                                                  (policy constants,
     ▼                                                                   models, caps)
 ingest.py ──► clean.py ──────────────────────────► metrics.py ──────────────┐
 read as        dedup, UTC→IST, CSAT/transfer        week assignment, SLA     │
 strings,       rules, order linking, invariant      credits, transfers,      │
 schema check   and baseline assertions              CSAT, leaderboard        │
                    │                                                         │
                    ▼                                                         ▼
              classify.py ◄──── providers.py ────► Gemini API         repeats.py ──► impact.py ──► report.py
              prompt, JSON       Gemini adapter,                       candidate       cost lines,     Jinja2 →
              schema, Pydantic,  rate limiter,                         pairs, theme    sensitivities   out/digest_*.html
              retry/fallback,    single retry layer                    match, cost,                    out/*.csv
              cache, budget,     (Anthropic client                     coverage
              backfill gate      also selectable)
                    │
                    ▼
              cache/classifications.jsonl, cache/usage.jsonl ──────────────► (read by repeats.py and report.py)

 evaluate.py: gold sample → human labels → SHA-256 lock → model ladder → out/eval/;  pair review → precision
```

**Responsibility boundary.** This is the central design decision.

| LLM (`classify.py` via `providers.py`) | Python (all other modules) |
|---|---|
| Issue theme: one of 26 enum values | Cleaning, validation, invariants |
| `customer_claims_prior_contact`, a boolean used only to validate repeat detection | Joins, dates, Monday–Sunday IST week assignment |
| | Repeat detection (candidate pairs, 30-day window, theme equality) |
| | Policy costs, SLA credits, transfers, CSAT |
| | Leaderboard, aggregation, coverage checks, reporting |

The model never sees costs, dates or other tickets, and its output can't change a calculation except through the
validated theme label. A wrong label shows up as a measurable classification error; it can't become an invented
number.

## AI / LLM design

| Aspect | Implementation |
|---|---|
| Provider | `ai.provider: gemini` (active). An Anthropic client path is implemented and unit-tested with fakes but was never called live (no API credits). The adapter is `vireo/providers.py` |
| Model ladder | `gemini-3.5-flash-lite` → `gemini-3.8-flash` → `gemini-3.1-pro-preview`. Evaluation stops at the first model that passes. **Selected: `gemini-3.5-flash-lite`** (the first rung) |
| Generation settings | `temperature=0`, `thinking_level: minimal`, `max_output_tokens: 1024`. Thinking tokens are counted as output for cost |
| Output contract | A JSON schema whose `theme` field is the taxonomy enum, re-validated by Pydantic (`extra="forbid"`). Invalid output → one retry → `OTHER_UNCLEAR` with `ai_error=true`, which never counts as a repeat |
| Prompt injection | Ticket text is wrapped in `<customer_message>`/`<agent_note>` delimiters, embedded delimiter tags are stripped, and the system prompt says to ignore instructions inside ticket text |
| Cache | `cache/classifications.jsonl`, keyed by `ticket_id + input_hash + prompt_version + model`. A hit makes no API call |
| Usage log | Every API attempt is logged to `cache/usage.jsonl`: purpose, model, tokens, cost, latency, validity |
| Rate limiting | A shared sliding-window limiter allows at most **13 request starts per 61 s** (free-tier quota 15/min). SDK retries are disabled, so the adapter is the only retry layer. A 429 waits `max(RetryInfo.retryDelay, backoff)` and pauses all workers. A daily-quota 429 is not retried. A rate-limited ticket is skipped, not cached, and the run completes normally |
| Cost guards | $5 per command and $30 for the backfill. Each call reserves 2× the running mean cost first, and the run stops before any call that could exceed the cap |
| Backfill gate | Full backfill only if: the smoke test was 100% schema-valid, a model passed the gold set, and projected cost ≤ $30 and runtime ≤ 45 min. Otherwise it uses the trailing-12-month scope, then the digest scope |

## Deterministic business logic

| Rule | Detail |
|---|---|
| De-duplication | 653 ticket IDs appear in both systems; the helpdesk copy is kept (12,528 → 11,875 rows) |
| Timezones | Legacy `resolved_at` is UTC: +5:30. Before the fix, 2,263 raw legacy rows resolve before they were created; after it, 0 |
| CSAT | Blank and legacy `0` mean no response and are excluded from means |
| Transfers | Legacy `transfers` is unknown, not zero, so transfer cost covers helpdesk tickets only |
| Order linking | Direct `order_id` first. The customer + SKU fallback is used only when exactly one order matches (720 tickets are ambiguous and left unlinked) |
| Week assignment | `created_at` week: volume, themes, repeat contacts. `resolved_at` week: tickets closed, breach credits, transfers, CSAT, handle time |
| Trailing window | "Previous 4 weeks" means the 4 full weeks before the selected week, excluding it |
| Leaderboard | Ranked within each Tier 1 team only; Tier 2 is unranked and shown with days to resolve. No composite, CSAT or breach score per agent. **Throughput, not performance** |

The cleaning step re-derives the discovery baselines and asserts them on every run. Examples: 992 breach credits and
817 helpdesk transfers over the 18 months.

## Repeat-contact methodology

Ticket **B** is a repeat contact if there is a ticket **A** such that:

1. A is resolved or auto-closed, with a `resolved_at`. Open or pending tickets are never A.
2. A and B have the same `customer_id`.
3. A and B have the same `product_sku`.
4. `A.resolved_at < B.created_at ≤ A.resolved_at + 30 days`.
5. `theme(A) == theme(B)`, and neither is `OTHER_UNCLEAR`.

How it's counted:
- B counts once, whatever its status, in the week it was created.
- It's costed at policy §4 channel rates: chat 210, email 260, voice 520, social 240.
- If any B in the period, or any of its candidate A tickets, is unclassified, the figure is reported as
  **"not computed"**. It is never extrapolated.

## Evaluation and validation

**Gold set.**
- 120 tickets, sampled with a fixed seed (`20260622`).
- At least 3 per theme, stratified using discovery-only keyword hints. The hints were never shown to the labeller.
- At least 8 per stratum: each channel, each source system, Hinglish, IVR and empty-note tickets.
- Labelled by one human from raw text, without seeing model output, following `data/gold/LABELLING_GUIDE.md`.
- Locked by SHA-256 (`data/gold/gold_lock.json`) on the first `evaluate` run; any later edit is refused.

| Result | Value |
|---|---|
| Accuracy | 98.3% (118/120). Errors: one-side audio → warranty status, charging failure → one-side audio |
| Macro-F1 | 0.984 |
| Per family | 8 of 10 families at 100%; Power 93.3%; Audio 92.9% (threshold: every family ≥ 70%) |
| Prior-contact flag | precision 0.917, recall 1.000, on 11 gold positives |
| AI errors | 0 |

**Repeat validation.**

| Check | Reference | Result |
|---|---|---|
| Recall | Customer-declared repeats ("third time", "was told it was resolved") inside the 30-day window, whose pairs are fully classified | **13/14 = 92.9%** |
| Precision | Human "same issue?" review of flagged pairs. The target was 30 random pairs; the digest scope produced only 25, so all 25 were reviewed with no padding (DECISIONS D-8) | **25/25 = 100%** |

**How much weight this can bear:**
- The recall reference is a text-pattern proxy, not ground truth, and has n=14.
- The precision review is a census of 25 pairs by one reviewer, who also labelled the gold set.
- The gold set has no `OTHER_UNCLEAR` examples, and rare themes have about 3–4 examples each.

These results support using the classifier for this digest. They are not a precise error rate.

## Cost and runtime

All figures below are measured from `cache/usage.jsonl`, `out/smoke.json` and `out/backfill_decision.json`.

| Run | API calls | Tickets | Cost | Wall time |
|---|---|---|---|---|
| Smoke (incl. 16 calls from a first run stopped by a 429) | 36 | 20 | $0.012740 | 64 s (successful run) |
| Gold evaluation | 119 | 119 (+1 cached) | $0.042586 | about 9 min |
| Digest backfill | 268 | 268 | $0.096047 | 20 min 24 s |
| **Total** | **423** | **407 distinct** | **$0.151373 (≈ $0.1514)** | |

The measured usage was about 975 input + 26 output tokens per ticket, i.e. about **$0.00036 per classified ticket**
at the configured `gemini-3.5-flash-lite` list prices. The project ran on the free tier.

**Projections** (not measured):

| Projection | Value | Assumption |
|---|---|---|
| Steady-state monthly cost (digest header, memo) | **$0.28** | Mean cost per classified ticket ($0.000358) × mean weekly new tickets over the 4 weeks before the selected week (181.75) × 52/12 (`vireo/impact.py`). It assumes each weekly run classifies only that week's new tickets, with earlier tickets already cached |
| Same formula at the selected week's volume | $0.31 | 199 tickets/week instead of the trailing mean |
| Repeating this digest run every week, no cache reuse | $0.42 | $0.096 × 52/12, including the 74 earlier tickets that later runs would find cached |
| Full 18-month backfill | $4.15, **627 min** | From the gate's projection (11,736 unclassified tickets). Not run: it exceeds the 45-min runtime limit at free-tier pacing |

All four are well under the $5 per-run and $30 backfill caps. The illustrative "x% fewer repeats" reduction
scenario needs the trailing-12-month cost, so it was **not computed**.

## Repository structure

```
vireo/
  ingest.py      read source CSVs as strings, schema check
  clean.py       cleaning rules, invariants, data-quality summary
  taxonomy.py    26-value theme enum + labelling rules (one source for prompt, validation, guide, report)
  classify.py    classifier, cache, usage log, budget guard, backfill gate (provider-agnostic)
  providers.py   provider selection, Gemini adapter, rate limiter, 429 handling
  metrics.py     week assignment, SLA, transfers, CSAT, leaderboard
  repeats.py     repeat engine, coverage, declared-repeat validation proxy
  impact.py      cost lines, sensitivities, monthly projection
  evaluate.py    gold sample, lock, scoring, repeat recall/precision
  report.py      digest context, rendering, CSV extracts
  cli.py         command-line entry point (python -m vireo)
templates/digest.html.j2
tests/           pytest suite, offline (network blocked by fixture)
docs/PRD.md      product requirements (v1.1 + v1.2 amendments)
DECISIONS.md     investigated deviations and design decisions D-1 to D-8
config.yaml      policy constants (with § references), models, prices, caps, thresholds, baseline assertions
data/            SOURCE_SHA256.txt, gold/gold_lock.json, gold/LABELLING_GUIDE.md (dataset itself not published)
cache/           classification cache and API usage log
out/             digest, CSVs, evaluation report, run records, memo
```

## Setup

Requires Python 3.10+. Tested on Python 3.14.2 on Windows.

```bash
python -m venv .venv
```
```bash
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```

Dependencies: `pandas`, `pydantic`, `jinja2`, `pyyaml`, `python-dotenv`, `pytest`, `google-genai`, `anthropic`.

On Windows, the `anthropic` package has very long internal paths. Install from a short directory path or enable
long-path support.

## Configuration

| Setting | Where | Notes |
|---|---|---|
| `GEMINI_API_KEY` | `.env` (copy `.env.example`; `.env` is git-ignored) | Needed only for `smoke`, `evaluate`, `backfill` |
| `ANTHROPIC_API_KEY` | `.env` | Only when `ai.provider: anthropic` |
| `ai.provider`, `ai.model_ladders`, `ai.models` | `config.yaml` | Provider, ladder, per-model prices and settings |
| `ai.gemini_rate_limit` | `config.yaml` | Pacing and 429 policy |
| `ai.max_usd_per_run`, `ai.max_usd_backfill`, `ai.backfill_max_runtime_minutes` | `config.yaml` | Cost and runtime guards |
| `policy.*` | `config.yaml` | SLA targets, contact costs, breach credit, transfer cost, repeat window, each with its policy § |
| `assertions.*` | `config.yaml` | Baseline counts for this export. Set `strict: false` for a different export |

## Running

All commands run from the repository root. The data-dependent commands need the source files in `data/raw/` (see
[Data handling](#data-handling-and-security)).

Offline, with no API calls:

```bash
python -m vireo check
```
```bash
python -m vireo digest --week 2026-06-22
```
```bash
python -m vireo backfill --dry-run
```

`check` runs cleaning plus every assertion. `digest` builds `out/digest_<week>.html` and the CSVs from the cache;
`--week` takes the Monday of a full week inside the export. `backfill --dry-run` prints the gate decision without
calling the API or writing state.

API commands, in the order they were run:

```bash
python -m vireo smoke
```
```bash
python -m vireo evaluate
```
```bash
python -m vireo backfill
```

- `smoke`: 20 tickets, writes `out/smoke.json`.
- `evaluate`: needs a labelled gold file. Locks it, then runs the model ladder. `--stability` additionally
  re-classifies 50 gold tickets without the cache.
- `backfill`: applies the gate, then classifies the allowed scope.

Human-in-the-loop steps (offline):

```bash
python -m vireo prepare-gold
```
```bash
python -m vireo prepare-pairs
```

`prepare-gold` writes the stratified gold sample for labelling and refuses to overwrite an existing one.
`prepare-pairs` writes up to 30 flagged pairs for the `same_issue` review: all of them if fewer than 30 exist.

## Testing

```bash
python -m pytest -q
```

- **Counts:** 86 tests with the dataset present. In a clone without the data, 79 pass and 7 skip (marked
  `real_data`).
- **No network:** a fixture fails any socket connection; the LLM clients are faked.
- **Coverage:**
  - every cleaning rule, plus the real-export baseline assertions
  - SLA boundaries and created vs resolved week assignment
  - repeat edge cases: exactly 30 days, 30 days + 1 minute, before resolution, different product, different theme,
    `OTHER_UNCLEAR`, open prior ticket, a B with two candidate A tickets
  - leaderboard tier separation
  - cache hits, retry and fallback, cost and ticket caps, the backfill gate
  - Gemini request/response translation, using real `google-genai` types built offline
  - rate limiting with a fake clock
  - digest rendering, including checks for no savings claims and no customer free text

Lint: `ruff check vireo tests --select E,F,W,B --ignore E501,E702,E731` (ruff is not in `requirements.txt`).

## Outputs

| Path | Contents |
|---|---|
| `out/digest_2026-06-22.html` | The weekly digest: header, repeat contacts, drivers, themes, secondary KPIs, leaderboard, cost, evaluation, data quality and limitations |
| `out/leaderboard_tier{1,2}_2026-06-22.csv` | Leaderboard tables. Agent names and IDs come from the roster |
| `out/repeat_contacts_2026-06-22.csv` | Ticket IDs of the week's repeat contacts |
| `out/classified_tickets.csv` | `ticket_id`, theme, prior-contact flag, model: no ticket text |
| `out/eval/eval_report.md`, `out/eval/selection.json` | Gold-set metrics and the confusion matrix |
| `out/smoke.json`, `out/backfill_decision.json` | Smoke-test and backfill-gate records |
| `out/memo_priya_raman.md` | One-page memo to the client's Head of Customer Experience |
| `cache/classifications.jsonl`, `cache/usage.jsonl` | Labels, token counts, cost, latency per ticket/attempt: no ticket text |

## Data handling and security

**The assignment dataset is not in this public repository.** The five CSVs, the policy PDF, the email thread and the
data README are employer-provided assignment materials and contain customer and ticket information. For the same
reason, the human gold labels (`data/gold/gold_tickets.csv`) and the pair review (`data/gold/repeat_pairs_review.csv`)
are excluded: both contain ticket text.

A reviewer with permission to use the assignment materials can restore them:
1. Copy the 8 files, unchanged, into `data/raw/`.
2. Verify them: `cd data/raw && sha256sum -c ../SOURCE_SHA256.txt`.
3. Run `python -m vireo check` and the test suite.

Re-running `evaluate` additionally needs the original labelled `gold_tickets.csv`, whose hash must match
`data/gold/gold_lock.json`.

**Reproducibility.** Without the data, a clone can be read but not re-run: the published outputs can be inspected,
and the 79 data-independent tests pass. Rebuilding the digest, running `check`, and the 7 real-export tests need
`data/raw/`. With the data in place, the committed cache lets the digest be rebuilt offline with no API calls.

**Included and why:**
- `out/` and `cache/` hold ticket IDs, labels, aggregate counts, costs and agent names (the leaderboard). They hold
  no ticket text and no customer names.
- `.env` (API keys), `.venv` and tool caches are git-ignored.
- The published files and history were scanned for API-key patterns before publishing; none were found.

**LLM data use.** Classification used the **Gemini API free tier**: billing was not enabled, and the 429 quota id was
`…-FreeTier`. The customer message and agent note for 407 distinct tickets were sent to Google. Google's pricing page
states that free-tier content is used to improve its products. This is recorded as a project limitation (DECISIONS
D-6 amendment). Any further run should use a billing-enabled key.

## Known limitations

- **Digest-scope classification only.** 273 of 11,875 tickets are classified. The 12-month and 18-month repeat
  totals, the previous-4-week comparisons, the reduction scenario and the without-same-product count are "not
  computed".
- **Small validation samples.** Recall n=14 (a proxy reference). Precision is 25 pairs (a census) from one reviewer,
  who also produced the gold labels. The prior-contact flag rests on 11 positives.
- **"Same issue" = same theme + same product.** Repeats across adjacent themes (e.g. firmware update → charging) or
  across products are undercounted.
- **History boundary.** January 2025 repeats are undercounted because earlier tickets are outside the export.
  Declared repeats more than 30 days after resolution are excluded by the policy definition.
- **Legacy data.** Legacy transfers are unknown. There is no roster history, so team moves are invisible. 720 order
  links are ambiguous and some tickets predate their linked order (order links feed no metric). CSAT is a ~47%
  response sample in the selected week.
- **Leaderboard.** Ticket counts are throughput, not performance. SLA breaches aren't attributed per agent, because
  policy charges them to the resolving agent.
- **Not production.** No live helpdesk integration, scheduler, hosting, authentication or monitoring. Runs are
  manual CLI invocations.
- **Provider.** The Anthropic path is tested only with fakes. Gemini runs used the free tier (see data handling).

## Design decisions and documentation

- [`docs/PRD.md`](docs/PRD.md): requirements, metric definitions, acceptance criteria (A1–A13), and the v1.2
  amendments table.
- [`DECISIONS.md`](DECISIONS.md): evidence behind each deviation:

| ID | Decision |
|---|---|
| D-1 | Tickets predating their order come from the source data, not from the fallback join; the join rule is unchanged |
| D-2 | Ambiguous joins are reported per ticket (720), not per raw row (751) |
| D-3 | Declared-repeat counts reconcile exactly with discovery (78 = 67 + 6 + 5) |
| D-4 | Digest scope is the PRD minimum (same customer + same product): 273 tickets |
| D-5 | "Trailing 4 weeks" excludes the selected week everywhere |
| D-6 | Gemini adapter added and made active; Anthropic kept. Amendment: free-tier data use |
| D-7 | Client-side pacing and a single retry layer for the free-tier rate limit |
| D-8 | Precision review covered the full flagged population of 25 pairs |

## Current status

| Done (3 Oct 2026) | Not done |
|---|---|
| Discovery, PRD, pipeline, 86 tests | Full 18-month backfill (projected 627 min, $4.15) |
| Gold set labelled and locked; model selected on the first ladder rung | 12-month repeat baseline and week-over-week trends |
| Smoke, evaluation and digest-scope backfill; 25-pair review | Billing-enabled re-run (removes the free-tier data-use issue and rate limit) |
| Digest, CSVs, evaluation report and memo for 22–28 Jun 2026 | Any deployment or helpdesk integration |

Acceptance criteria A5, A6 and A7 pass for the selected week.

Development note: the code, tests and documentation were written with an AI coding assistant (Claude Code). Every
figure is computed by the pipeline from the data. Elapsed time from receiving the files to the final documentation
pass was about 4 h 20 min, including human labelling and review and the paced API runs.
