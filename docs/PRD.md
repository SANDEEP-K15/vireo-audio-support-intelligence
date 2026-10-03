# PRD — Vireo Audio Support Digest & Repeat-Contact Analysis

Version 1.1 (final, pre-implementation) · Source of truth: the eight files in this directory and the discovery analysis. Every figure below was computed in Python from those files.

**Labels used in this document:**

- **[baseline]**: a deterministic discovery result. Implementation must reproduce it or explain the difference.
- **[discovery-only]**: a preliminary heuristic estimate. It must **not** appear in the digest as a result. The digest reports only figures measured by the implemented methodology.

---

## Amendments v1.2 (3 Oct 2026)

The v1.1 text below is unchanged. These amendments follow implementation evidence. Full evidence is in `DECISIONS.md` (repository root). **No business definition changes**: repeat contact, costs, SLA breach, transfers and CSAT are as written.

| # | Section | Amendment |
|---|---|---|
| D-1 | §7 C9, A2 | Before-order tickets are asserted per link type: **232 direct** (unchanged) **+ 94 fallback**, with the 94 split by evidence (6 quoted order id / 55 pre-sales / 33 unverifiable). The C7 fallback rule is **unchanged**: the before-order rate is the same for direct and fallback links (2.95% vs 2.85%). |
| D-2 | §7 C7, A2 | Ambiguous fallback joins: **751 raw rows = 720 tickets** after de-duplication. **720** is the reported figure; 751 is kept as a raw-export check. |
| D-3 | §11, §13.3 | Declared repeats outside the window: **78**, reconciled to the discovery **67** (+6 with an open previous ticket, +5 with a different-SKU previous ticket). The recall reference set (406) is identical under both definitions. |
| D-4 | §14.4 | The digest scope is exactly the §14.4 minimum (same customer + same SKU): **273** tickets for 22–28 Jun 2026 (the implementation had included 19 extra other-SKU prior tickets, giving 292). |
| D-5 | §14.2, §15, §16 | "Trailing 4 weeks" means the **4 full weeks before the selected week, with the selected week excluded**, everywhere: comparisons, leaderboard and cost projection. |
| D-6 | §8, §13.1, §14.1, §20 | **LLM provider is configurable; Gemini is active.** Anthropic credits were unavailable. §13.1 ladder (active): `gemini-3.5-flash-lite` → `gemini-3.8-flash` → `gemini-3.1-pro-preview`, thinking_level minimal. The Anthropic ladder is kept and selectable. §14.1 price table: Gemini paid-tier prices, pricing page dated 2026-10-01 ($0.30 / $2.50, $0.75 / $3.75 promotional to 2026-12-31, $2.00 / $12.00 per 1M tokens; thinking billed as output). The §8 output contract (two judgements, enum schema, Pydantic validation, retry → OTHER_UNCLEAR, cache, logging, injection protection) is unchanged. §20 architecture adds `vireo/providers.py`. **Open: free tier vs billing-enabled key (data use).** |
| D-7 | §8, §14.3, §14.4 | **Rate limiting.** Gemini requests are paced client-side at ≤13 starts per 61 s (free-tier quota 15/min). SDK retries are disabled, so the adapter is the single retry layer: it honours `RetryInfo`, applies backoff, and never retries a daily quota. A rate-limited ticket is skipped and never cached; the run completes and is resumable. The smoke test keeps 20 tickets; a run cut short counts as < 100% valid, so the gate refuses it. The runtime projection includes pacing, so on the free tier the gate selects the digest scope. Cost caps are unchanged. |
| D-8 | §13.4, A6 | **Repeat-precision review population.** The target was a human review of **30** randomly sampled flagged pairs. Under the digest scope only **25** flagged pairs existed, so all 25 were reviewed as a census, with no padding. Result: 25/25 same issue (reviewer Sandeep Kumar), so precision = 100% and A6's precision part passes. A full-history backfill would allow a 30-pair random sample. |

---

## 1. Business problem

Vireo has 18 months of support tickets (1 Jan 2025 – 30 Jun 2026) that nobody reads (Priya, 7 Sep). Finance will only fund work that "takes contacts out of the queue", and it refuses a surprise per-ticket model bill (Arjun, 8 Sep). Support Ops reports customers returning about issues they had already raised (Neha, 8 Sep).

Support policy §10 defines and costs this failure: a **repeat contact** is the same customer contacting again about the same issue within 30 days of resolution, costed at the channel's contact cost. Today nobody measures it. Doing so requires deciding "same issue" from free text: noisy, typo-heavy, partly Hinglish customer messages, plus agent notes that are empty for 2,532 tickets [baseline]. The intake-bot `category` cannot do this job. Its "Other" bucket holds 1,780 raw rows, most of them classifiable.

## 2. Users and decisions supported

| User | Uses | Decision supported |
|---|---|---|
| Priya Raman, Head of CX (primary) | Weekly digest, tickets-closed leaderboard | Which complaint themes and products to act on this week. How throughput is distributed across teams |
| Arjun Mehta, Finance Controller | Business-impact and cost sections | Whether the tool earns its keep. Whether the AI cost is bounded |
| Neha Kulkarni, Support Ops Manager | Repeat-contact section, leaderboard caveats | Where repeat contacts originate. Confirms Tier 2 is not ranked on volume |

## 3. Business objective

Make repeat contacts (failure demand) visible every week, with their rupee cost under the client's own policy, broken down by issue theme and product. This lets Vireo target the issues that bring customers back. Deliver it as a simple weekly static report with a bounded, reported AI cost.

The product **measures** repeat-contact cost. It does not by itself reduce contacts. **It makes no savings claim.**

## 4. Primary KPI

**Repeat contacts (same customer, same issue, within 30 days of resolution) and their cost in Rs**, as measured by the §11 methodology. Reported per week, as a trailing-12-month total and as an 18-month total.

[discovery-only] Heuristic range from discovery: 406–978 repeat contacts, Rs 102,400–250,660 over 18 months. This range was used only to show the metric is material. It is not a target, it does not appear in the digest, and it is not an acceptance criterion. The digest reports the measured count and cost.

## 5. Secondary KPIs (deterministic, no AI)

| KPI | [baseline], 18 months, deduplicated |
|---|---|
| SLA breach credits (§3 of policy) | 992 credits, Rs 347,200 (resolved Jul 2025–Jun 2026 subset is reported by implementation) |
| Transfer cost (§4), helpdesk, attended tickets | 817 transfers, Rs 249,185. A further 51 transfers sit on open/pending helpdesk tickets and are reported as "not yet final" |
| CSAT: mean, n, response rate (§8) | 3.32 mean, 44.2% response rate on attended tickets |
| Incoming volume by channel and theme | weekly median 171, max 240 (full weeks) |
| Tickets closed per agent (throughput, §16) | n/a |

## 6. Exact metric definitions

All timestamps are IST after cleaning (§7). A week runs Monday 00:00 – Sunday 23:59 IST.

### 6.1 Week assignment (fixed)

| Analysis | Week key |
|---|---|
| Incoming volume, complaint themes, bot-category reclassification, **repeat contacts** (each repeat is an incoming contact B) | **`created_at`** |
| Tickets closed (leaderboard), **SLA breach credits** (issued on resolution, policy §3), transfer cost (final only once the ticket is closed), CSAT (survey sent on resolution, §8), handle time, Tier 2 days-to-resolve | **`resolved_at`** (attended tickets only) |

### 6.2 Definitions

| Metric | Definition |
|---|---|
| Ticket universe | Deduplicated tickets: 11,875 |
| Attended | `status ∈ {resolved, closed}` (§10 "Attendance"). `closed` = auto-closed after 72 h without a customer reply (§8) |
| Incoming volume (week W) | Tickets with `created_at` in W |
| First-response minutes | `first_response_at − created_at` |
| SLA breach | First-response minutes > target. Targets: chat 15, voice 120, social 240, email 480. The comparison is strict (exactly on target is not a breach) |
| Breach credits (week W) | Rs 350 × breached attended tickets with `resolved_at` in W |
| Transfer cost (week W) | Rs 305 × Σ `transfers` on attended `helpdesk` tickets with `resolved_at` in W. Legacy tickets are reported as "unknown", not 0 |
| CSAT (week W) | Mean of scores 1–5 on attended tickets resolved in W. Blank and legacy 0 are excluded. Always shown with n and response rate |
| Handle time | `resolved_at − first_response_at` (§10). Reported as a median |
| Days to resolve (Tier 2 view) | `(resolved_at − created_at)` in days. Reported as a median |
| Repeat contact | Defined in §11. Counted in the `created_at` week of the repeat ticket B |
| Repeat cost | Σ §4 channel cost of each repeat ticket B: chat 210, email 260, voice 520, social 240 |
| Tickets closed (agent, week W) | Attended tickets with `resolved_at` in W, grouped by `agent_id`. Auto-closed tickets are shown in a separate column |

## 7. Data-cleaning rules

Apply these in order. Each rule has an assertion, and a run fails if an assertion fails.

| # | Rule | Assertion on the provided export |
|---|---|---|
| C1 | Parse with a real CSV parser (messages contain newlines). Read every column as a string first | tickets: 12,528 rows, 21 columns |
| C2 | Deduplicate by `ticket_id`. Where an ID exists in both `helpdesk` and `legacy_fd`, keep the `helpdesk` row | 653 duplicated IDs. 11,875 rows after dedup with unique `ticket_id` |
| C3 | Legacy `resolved_at` += 5h30m (UTC → IST). `created_at` and `first_response_at` are unchanged | Before the fix: 2,263 legacy rows with `resolved_at < created_at`. After the fix: 0 rows with `resolved_at < created_at` or `resolved_at < first_response_at` |
| C4 | Legacy `csat_score = 0` → missing | No 0 remains. Values are in {1..5} or missing |
| C5 | Legacy `transfers` → unknown (null) | Transfer KPIs use helpdesk rows only |
| C6 | `refund_amount_inr` → numeric. Blank = no refund | Guard: no refund exceeds the matched order's value. Where the agent note states an amount, it equals the field. A mismatch is a warning, never a silent conversion (§9 money-unit risk; not observed in this export) |
| C7 | Order link: use `order_id` when present. Otherwise use the `customer_id + product_sku` fallback **only if exactly one order matches**. If several match, leave the order unlinked and flag it as ambiguous | 8,310 direct (raw), 3,467 unique fallback, **751 ambiguous**, 0 unmatched |
| C8 | Agent attributes come from `agents.csv` via `agent_id`, never by name | 44 agents, 100% match. Team = current roster team for the whole period (no history exists) |
| C9 | Flag tickets created before their linked order date. Keep them in volume metrics | 232 after dedup |
| C10 | Open/pending tickets are kept for incoming volume and as possible repeat contacts, but never act as the "first contact" | 609 open/pending after dedup |
| C11 | Write a data-quality summary with every count above into each report | n/a |

## 8. AI responsibilities

The AI makes exactly two semantic judgements per ticket:

1. **`theme`**: one label from the closed taxonomy (§10), judged from `customer_message` + `agent_notes`.
2. **`customer_claims_prior_contact`** (boolean): the customer states they contacted Vireo about this before. This is used to validate the repeat methodology (§13). It does not define repeats.

Repeat-issue determination is a deterministic comparison of AI theme labels within deterministically generated candidate pairs (§11).

Output contract:

- **Structured output** whose JSON schema restricts `theme` to the enum. Validate it again in Python (Pydantic).
- If validation fails, retry once. If it fails again, set `theme = OTHER_UNCLEAR` with `ai_error = true`, and count it in the report.
- Customer and agent text go into the prompt as delimited, untrusted data. The prompt states that instructions inside the text must be ignored.
- Every result records `ticket_id`, `theme`, `customer_claims_prior_contact`, `model`, `prompt_version`, `input_hash`, `input_tokens`, `output_tokens` and `ai_error`.
- **Cache key** = `ticket_id + input_hash + prompt_version + model`. A ticket is classified once, and re-runs make no API calls.

The AI does **not** do arithmetic, aggregation, date logic, joins, ranking or digest numbers. It writes no free-text narrative; digest sentences are templated in Python.

## 9. Deterministic responsibilities (Python)

- Ingestion and cleaning C1–C11, plus the data-quality report.
- All §6 metrics and week assignment.
- Generating repeat candidate pairs, the 30-day window and repeat costing.
- SLA breaches and credits, transfer cost, CSAT, handle time and days-to-resolve.
- Leaderboard aggregation and tier separation.
- Business-impact arithmetic, sensitivities and the illustrative scenario.
- Token-to-cost conversion, runtime and cost projections, the backfill gate and cost caps.
- Evaluation scoring.
- Rendering the report.

## 10. Complaint taxonomy

Built from the issue vocabulary actually found in agent notes and customer messages. Counts are [discovery-only] keyword mappings over the 9,343 tickets whose notes contain an issue phrase. They are shown here only to support the label set, and they are used to stratify the gold-set sample.

| Family | Theme (enum value) | Covers (examples seen in data) | [discovery-only] n |
|---|---|---|---|
| Order & Delivery | `DELIVERY_DELAY` | not delivered, tracking stuck, "out for delivery for a week", marked delivered but not received | 1,537 |
| | `TRANSIT_DAMAGE_WRONG_ITEM` | arrived damaged, dent or crack out of the box, wrong item or colour or variant | 650 |
| | `ADDRESS_CHANGE` | change address, wrong pincode, typo in flat number | 151 |
| | `CANCELLATION` | cancel order, ordered by mistake, stop shipment | 360 |
| Returns & Refunds | `RETURN_PICKUP` | pickup missed or not done, box still waiting | 591 |
| | `REFUND_NOT_RECEIVED` | refund promised but not credited, return accepted but no money | 641 |
| Payments | `PAYMENT_FAILED_DUPLICATE` | debited but no order, UPI success but no order, charged twice | 542 |
| | `DISCOUNT_COUPON` | coupon invalid, discount not applied, offer vanished at payment | 271 |
| | `INVOICE_GST` | GST invoice, invoice not downloading, tax bill | 219 |
| Account & App | `LOGIN_OTP` | OTP not received, locked out, cannot log in | 190 |
| | `APP_CRASH` | app crashes, won't open, white screen | 349 |
| | `FIRMWARE_UPDATE` | update stuck or failed, including "update failed and now it won't turn on" | 258 |
| Connectivity | `PAIRING` | won't pair, not discoverable, vanishes from device list | 709 |
| | `BT_DISCONNECT` | drops, stutters, cuts out during calls | 330 |
| | `WIFI_SETUP` | speaker Wi-Fi or network setup failing | 37 |
| Power | `BATTERY_DRAIN` | drains fast, poor battery backup | 447 |
| | `CHARGING_FAILURE` | bud or case not charging, no LED | 347 |
| | `DEAD_NO_POWER` | won't power on, with no update cause stated | 22 |
| Audio | `AUDIO_DISTORTION` | crackling, static, hiss, distortion | 258 |
| | `ONE_SIDE_AUDIO` | one earbud or side silent | 259 |
| | `MIC` | mic not working, "people can't hear me" | 108 |
| Wearable hardware | `DISPLAY_TOUCH` | touch unresponsive, display issues | 92 |
| | `STRAP` | strap torn, pin came off | 53 |
| Warranty | `WARRANTY_REPAIR_STATUS` | warranty claim, RMA or repair status chasing | 234 |
| Pre-sales | `PRESALES` | compatibility, water resistance, pre-purchase questions | 505 |
| Fallback | `OTHER_UNCLEAR` | no identifiable issue (for example "hello??" with an empty note) | n/a |

**Labelling rules** (the gold-set labeller and the prompt use the same rules):

- Label the issue the customer needs resolved, not the action the agent took.
- When a stated cause exists, prefer it over the symptom ("update failed, now won't turn on" → `FIRMWARE_UPDATE`).
- Chasing the status of a refund → `REFUND_NOT_RECEIVED`. Chasing the status of a warranty repair → `WARRANTY_REPAIR_STATUS`.
- With several issues, label the first one stated.
- Use `OTHER_UNCLEAR` only when no issue is identifiable from both texts combined.

## 11. Repeat-contact methodology (primary business metric)

Policy §10: "a return contact [by the same customer] about the same issue within 30 days of resolution".

Ticket **B is a repeat contact** if at least one ticket **A** exists such that all of the following hold:

1. A is attended and `A.resolved_at` is not null.
2. `A.customer_id == B.customer_id`.
3. `A.product_sku == B.product_sku`. This operationalises "same issue". In discovery, only 5 of 484 customer-declared repeats had a different SKU on the prior ticket.
4. `A.resolved_at < B.created_at ≤ A.resolved_at + 30 days`.
5. `theme(A) == theme(B)` and neither theme is `OTHER_UNCLEAR`.

Counting rules:

- B counts once, even when several A tickets match.
- B may have any status, because the contact happened either way.
- B is counted in the `created_at` week of B.

Reported alongside, for transparency:

- Pairs excluded only because a theme is `OTHER_UNCLEAR`.
- Sensitivity without the SKU condition.
- Customer-declared repeats that fall outside the 30-day window. [baseline] 67 fell at 30–42 days and are excluded by the policy definition.

**Maturity:** the digest reports *repeat contacts arriving in week W*, which are known immediately. A first-contact-resolution rate for tickets resolved in W is final only 30 days after W ends, so it is not shown for immature weeks.

**Boundary:** tickets from January 2025 may repeat contacts from before the export window, so repeats in the first 30 days are undercounted.

**Coverage:** a repeat count is only valid over tickets that have AI themes. Every repeat figure states the classification coverage it rests on (§14.4).

## 12. Business-impact calculation

- **Measured repeat-contact cost** = Σ over repeat tickets B (per §11) of the §4 channel cost of B. Reported weekly, as the trailing-12-month total (B created Jul 2025 – Jun 2026) and as the 18-month total, each with its classification coverage.
- **Rate sensitivity**, shown because the client disputes the rate: measured repeat count × Rs 290 (policy blended) and × Rs 180 (Arjun's figure). The per-channel figure is the headline because §10 prescribes it.
- **SLA breach credits** and **transfer cost** are reported as separate lines. They are **not summed** with repeat cost, because one ticket can be both a repeat and a breach.
- **No savings claim** anywhere in the product.
- **Illustrative reduction scenario.** Fixed label in the digest: *"Illustrative arithmetic, not a forecast or savings claim: if repeat contacts were X% lower, the trailing-12-month repeat cost would be Rs Y lower."* X is shown at 10% and 25%. Y = X% × measured trailing-12-month repeat cost. The tool does not cause any reduction.
- **AI cost** is shown next to repeat cost for scale, in USD. It is converted to INR only if Finance supplies an FX rate (D3).

## 13. Evaluation methodology

1. **Gold set (human-reviewed):** a stratified sample of 120 tickets, at least 3 per theme by [discovery-only] label, covering all four channels, both source systems, Hinglish/IVR text and empty-note tickets. Fix the random seed. A human labels `theme` and `customer_claims_prior_contact` from the raw text using the §10 rules, **before seeing any model output**. The gold file is committed and never edited after scoring starts.
2. **Classification metrics on the gold set:** overall accuracy, macro-F1, per-family accuracy, a confusion matrix, and precision/recall of the prior-contact flag.
3. **Repeat recall:** take the customer-declared repeats that fall inside the window (strict text patterns, [baseline] 406 over 18 months). Report the share the §11 method flags as repeats, restricted to classified tickets.
4. **Repeat precision:** a human reviews 30 randomly sampled flagged (A, B) pairs and answers "same issue? yes/no". Report the precision.
5. **Silver agreement (sanity check only):** compare against note-derived keyword labels. This is reported as non-independent, because the model also sees the notes.
6. **Stability:** re-classify 50 tickets without the cache and report label agreement. This is the first item to cut if time runs short.

### 13.1 Model selection (cheapest-first ladder)

1. Run the gold set on the **cheapest candidate, Claude Haiku 4.5** (`claude-haiku-4-5`).
2. If it meets the A5 thresholds, adopt it. Stop.
3. If it fails, run the gold set on **Claude Sonnet 5.5** (`claude-sonnet-5-5`). Adopt it if it passes.
4. Move to **Claude Opus 5.5** (`claude-opus-5-5`) only if Sonnet 5.5 also fails.
5. If no model passes, report the best result as failing A5 and do not present repeat figures as validated.

Prompt changes count as a new `prompt_version` and are re-scored on the same gold set. Every escalation is recorded in the evaluation report with the accuracy and cost per ticket at each step.

## 14. Cost and runtime methodology

### 14.1 Measurement

- Read token usage from each API response (`usage.input_tokens` and `usage.output_tokens`, including any thinking tokens billed as output).
- Cost = tokens × the price table in config. Anthropic list prices cached 2026-09-25, USD per million tokens:

  | Model | Input | Output |
  |---|---|---|
  | Haiku 4.5 | 1 | 5 |
  | Sonnet 5.5 | 2 | 10 |
  | Opus 5.5 | 4 | 20 |

- Wall-clock time is logged per call and per run.

### 14.2 Reported figures

- **Cost per run** = Σ cost of calls made in the run. Cached tickets cost 0.
- **Projected monthly cost** = mean measured cost per newly classified ticket × mean weekly new tickets over the trailing 4 full weeks × 52 / 12.
- **One-off backfill cost** is reported separately from the steady-state cost.

### 14.3 Guards

- `max_new_tickets_per_run` and `max_usd_per_run`. The run stops before making a call that would exceed either limit and says so.

### 14.4 Backfill gate

Full classification of the 11,875 tickets is **not** automatic. It proceeds only after both of these:

1. **The smoke test passes:** 20 tickets classified with 100% schema-valid output, and the cost and wall-clock time are logged.
2. **The gold set passes A5** on the selected model (§13.1).

Then compute, from measured means at the configured concurrency:

- projected backfill cost = mean cost per ticket × unclassified tickets
- projected backfill runtime = mean seconds per ticket ÷ concurrency × unclassified tickets

**Proceed with the full backfill only if** projected cost ≤ `max_usd_backfill` (D4) **and** projected runtime fits inside the remaining time slot of the 5-hour plan (§24).

**If the gate fails**, use the smallest scope that still produces the digest, in this order:

1. **Digest scope** (minimum): tickets created in the selected week, plus every attended ticket that is a candidate prior ticket A for them (same customer + SKU, resolved within the 30 days before).
2. **Trailing-12-month scope:** tickets created Jul 2025 – Jun 2026 plus their candidate A tickets.
3. **Full scope:** all 11,875.

The digest states the scope used and its coverage. Totals for periods that are not covered are shown as "not computed", never extrapolated.

Discovery estimate, to be replaced by measured values. It assumes about 1,600 input + 80 output tokens per ticket and excludes thinking tokens.

| Model | Weekly run (240 tickets, max week) | 18-month backfill |
|---|---|---|
| Haiku 4.5 | about $0.48 | about $23.75 |
| Sonnet 5.5 | about $0.96 | about $47.50 |
| Opus 5.5 | about $1.92 | about $95.00 |

## 15. Weekly digest requirements

One report per selected week. The default is the **latest full week in the data: 22–28 Jun 2026** (199 tickets created). The partial week 29 Jun – 5 Jul (46 tickets) is never presented as a full week.

Sections, in order:

1. **Header:** week, data range, run timestamp, model and prompt version, classification scope and coverage, cost of this run, projected monthly cost.
2. **Headline: repeat contacts** (created-week). The measured count and Rs this week, compared with the trailing 4-week average, plus trailing-12-month and 18-month totals where coverage allows.
3. **Repeat drivers:** the top themes and theme × SKU combinations by repeat count and Rs.
4. **Complaint themes this week** (created-week): count per theme, change against the trailing 4-week average, and how many bot "Other" tickets the AI reclassified.
5. **Secondary KPIs:**
   - incoming volume by channel (created-week)
   - SLA breach credits by channel, count and Rs (resolved-week)
   - transfers, count and Rs, helpdesk only (resolved-week)
   - CSAT: mean, n, response rate (resolved-week)
6. **Tickets-closed leaderboard** (resolved-week): see §16.
7. **Business impact and cost:** the §12 lines, the rate sensitivities, the labelled illustrative scenario and the AI cost.
8. **Evaluation summary:** gold-set accuracy and macro-F1, model-ladder outcome, repeat recall and precision, with a link to the full evaluation report.
9. **Data quality and limitations:** the C11 counts plus §22.

Ticket IDs are listed for drill-down. Free-text customer messages are not reproduced in the digest.

## 16. Agent throughput (tickets-closed leaderboard)

- Title: **"Tickets closed — throughput, not performance"**. A fixed caption says that ticket counts reflect queue mix, shift and case complexity, and are not a measure of individual performance.
- **Tier 1:** one table per team (Chat, Email, Voice, Logistics, Billing, Returns Desk), ordered by tickets closed within the team. Columns:
  - agent_id and name
  - site and shift
  - tickets closed (selected week and trailing 4 weeks)
  - of which auto-closed
  - of which outside the agent's roster team (night-shift coverage, policy §7)
  - team median handle time, as context
- **No ranking across teams.** For example, Logistics median handle time is about 24 h and Chat about 0.4 h [baseline].
- **Tier 2 (Escalations & Warranty):** a separate section, **unranked** (sorted by agent_id). Shows median days to resolve and the case count only (policy §6, Neha's request).
- **Excluded from the leaderboard:**
  - SLA breaches (policy attributes them to the resolving agent, not the first responder)
  - CSAT per agent
  - repeat rate per agent
  - any composite or performance score
- Caption: "team = current roster; no history available".

## 17. UI requirements

- A command-line entry point only, for example `python -m vireo run --week 2026-06-22`, with separate `classify` and `evaluate` commands.
- Output: one **self-contained static HTML file** per week (tables, no JavaScript framework), plus CSV extracts of the leaderboard, the repeat pairs and the classified tickets.
- A static evaluation report (HTML or Markdown).
- **No** web server, React or other frontend framework, database, login or hosted application.

## 18. MVP scope

1. Cleaning pipeline C1–C11 with assertions and a data-quality summary.
2. Deterministic metrics (§6) and the leaderboard (§16).
3. AI classifier (§8) with structured outputs, validation, JSONL cache, usage/cost/runtime logging and caps.
4. Gold-set evaluation and the cheapest-first model ladder (§13).
5. Backfill under the gate in §14.4.
6. Repeat-contact engine (§11) and business impact (§12).
7. Weekly static HTML digest (§15) for any selected week, defaulting to 22–28 Jun 2026.
8. README covering how to run it, measured costs, the limitations and the scope cuts.

## 19. Explicitly out of scope

- Web server, React or any frontend framework, database, RAG, agents, vector databases, LangChain or LangGraph, and microservices.
- Live helpdesk or API integration, a scheduler (a cron example is documented only), hosting and authentication.
- An LLM-written digest narrative.
- Employee-performance scoring of any kind.
- Savings or ROI claims. Only the labelled illustrative scenario in §12 is allowed.
- Lot-code defect clustering (opportunity noted, not analysed).
- Finance review of the 103 orders with both a refund and a replacement, and of the 37 GW-OTHER refunds above Rs 500. These are discovery observations handed to the client, not features.
- Chasing the 609 stale open/pending tickets.
- Message Batches API (a documented 50% cost option), translation and sentiment.
- Reconstructing roster history or legacy transfer data.

## 20. Architecture

```
config.yaml   policy constants with § references, price table, model ladder, prompt_version,
              cost caps (per run, backfill), concurrency, FX (optional)
vireo/
  ingest.py      read the 5 CSVs as strings (C1)
  clean.py       C2–C10, returns clean frames + data-quality dict (C11)
  taxonomy.py    enum, family map, labelling rules text (single source for prompt and validation)
  classify.py    Claude API call, structured output, Pydantic validation, retry, JSONL cache,
                 usage/cost/runtime log, caps, backfill gate + scope selection
  metrics.py     §6 metrics with created/resolved week assignment, leaderboard (§16)
  repeats.py     §11 candidate pairs, theme match, costing, sensitivities, coverage
  impact.py      §12 arithmetic incl. illustrative scenario
  evaluate.py    §13 gold-set scoring, recall/precision, stability, model ladder record
  report.py      Jinja2 → static HTML + CSV
  cli.py         run / classify / evaluate
data/gold/       gold_tickets.csv, gold_pairs.csv (human labels)
cache/           classifications.jsonl, usage.jsonl   (flat files — no database)
out/             digest_<week>.html, eval_report.html, CSVs
tests/
```

Stack: Python, pandas, the Anthropic Python SDK, Pydantic, Jinja2 and pytest.

## 21. Testing requirements

- **Cleaning unit tests** on small fixtures, one per rule C2–C10. Examples: a duplicate pair keeps the helpdesk row; the +5:30 shift applies to legacy only; CSAT 0 becomes missing; legacy transfers become null; an ambiguous fallback join stays unlinked.
- **Real-data assertions** using the §7 expected counts. They run as part of the pipeline.
- **Metric tests:**
  - breach boundary: exactly 15 minutes on chat is not a breach, 16 is
  - credits counted only on attended tickets and in the resolved week
  - incoming volume counted in the created week
  - CSAT excludes missing values
  - transfer cost uses attended helpdesk rows only
  - week boundaries are Monday–Sunday IST
- **Repeat tests:**
  - 30 days 0 min after A resolves → repeat
  - 30 days 1 min → not a repeat
  - created before A resolved → no
  - different SKU → no
  - different theme → no
  - `OTHER_UNCLEAR` → no
  - open prior ticket → no
  - B matching two A tickets → counted once
  - repeats bucketed by B's created week
- **Leaderboard tests:** Tier 2 has no rank column; there is no cross-team ranking; agents are keyed by ID; the throughput caption is present.
- **AI-layer tests with a mocked client (no network):**
  - an invalid enum is rejected and retried, then falls back to `OTHER_UNCLEAR` with `ai_error`
  - a cache hit makes no API call
  - the per-run cost cap stops the run before a call that would exceed it
  - the backfill gate refuses when projected cost or runtime exceeds its limit, and selects the fallback scope
  - usage is logged
- **Reproducibility:** two runs over a warm cache produce byte-identical digest numbers.

## 22. Known limitations

- "Same issue" relies on theme equality. Repeats across adjacent themes are undercounted (for example firmware update → charging). This is measured by the repeat recall in §13.
- The SKU condition misses repeats recorded against a different SKU (5 of 484 declared repeats in discovery).
- Repeats in January 2025 are undercounted because earlier tickets are outside the export. The repeat window excludes declared repeats beyond 30 days by design.
- If the backfill gate restricts scope, longer-period totals are not computed.
- The roster has no history, so team changes are invisible. Night-shift agents resolve other teams' tickets (policy §7).
- Legacy transfers are unknown, so transfer cost covers helpdesk tickets only.
- 751 tickets have ambiguous order links. 232 tickets predate their linked order.
- CSAT is a roughly 44% response sample.
- Breach attribution in policy goes to the resolving agent, so the leaderboard excludes breaches.
- The intake `category` shows no evidence of agent re-tagging despite the README.
- Trends that cross the 14 Sep 2025 migration date mix two source systems.
- AI labels carry the error rate measured in §13. The gold set has 120 tickets, so rare themes (n < 40) have wide uncertainty.
- Cost estimates before measurement exclude thinking tokens. The digest uses measured values only.

## 23. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | One command produces the static HTML digest for 22–28 Jun 2026 from the raw files |
| A2 | All §7 assertions pass: 12,528 raw rows, 653 duplicate IDs, 11,875 clean rows, 0 resolved-before-created after the fix, 751 ambiguous fallback joins |
| A3 | Secondary KPIs reproduce the [baseline] figures: 992 breach credits / Rs 347,200, and 817 attended helpdesk transfers / Rs 249,185. Any difference is explained |
| A4 | 100% of AI outputs pass schema validation or are explicitly counted as `ai_error` |
| A5 | Gold-set results are reported (accuracy, macro-F1, per-family, confusion matrix) for each model tried on the §13.1 ladder. Thresholds (D2): overall accuracy ≥ 85%, no family below 70% |
| A6 | Repeat recall against in-window customer-declared repeats and repeat precision on 30 reviewed pairs are reported. Thresholds (D2): recall ≥ 80%, precision ≥ 80% |
| A7 | The digest reports the **measured** repeat count and Rs cost from the §11 methodology, with coverage stated, per-channel cost and the Rs 290 / Rs 180 sensitivities. The discovery range does not appear as a result |
| A8 | Cost per run, projected monthly cost and the backfill-gate decision come from measured token usage and runtime. Per-run caps and gate behaviour are demonstrated in tests |
| A9 | The leaderboard carries the "throughput, not performance" title and caption, has no cross-team ranking and no composite score, and ranks no Tier 2 agent |
| A10 | The digest contains no savings claim. The only reduction figure is the labelled illustrative scenario |
| A11 | The limitations and scope-cut sections appear in the digest or README |
| A12 | The test suite passes without network access |
| A13 | Week assignment follows §6.1 (created week vs resolved week) and is stated in the digest |

## 24. Five-hour implementation priority order

| Slot | Work | Exit check |
|---|---|---|
| 0:00–0:40 | Ingest + clean (C1–C11) + assertions + cleaning tests. Generate the gold-set sample file | A2 passes. Gold sample exists |
| 0:40–1:20 | Deterministic metrics with §6.1 week assignment, leaderboard, repeat candidate-pair generation + tests | A3, A9, A13 |
| 1:20–2:00 | Classifier: taxonomy, prompt, structured output, validation, cache, usage/cost/runtime log, caps, gate logic, mocked tests. **Smoke test: 20 tickets on Haiku 4.5** | A4. Smoke-test cost and runtime logged |
| 2:00–2:40 | **Human labels the gold set** (blind). Then classify the gold set on Haiku 4.5, run the evaluation, and climb the model ladder only if A5 fails | A5 |
| 2:40 | **Backfill gate decision** (§14.4). If it passes, start the full backfill in the background. Otherwise use the fallback scope | Gate decision recorded |
| 2:40–3:30 | Repeat engine, impact, recall check, human review of 30 pairs (as backfill coverage allows) | A6, A7, A10 |
| 3:30–4:20 | Static HTML digest + CSVs + evaluation report | A1 |
| 4:20–5:00 | README (run steps, measured costs, limitations, scope cuts), full test run, acceptance checklist | A8, A11, A12 |

**Cut order if behind schedule** (first to drop):

1. Stability re-run (§13.6).
2. Theme × SKU breakdown (keep theme only).
3. Trailing-4-week comparison columns.
4. Full backfill (fall back to the §14.4 scopes).

**Never cut:** cleaning assertions, structured-output validation, the gold set, cost and runtime logging, the backfill gate, the leaderboard tier separation and caveats, or the limitations section.

---

## Open decisions (defaults apply if not answered)

| # | Decision | Default |
|---|---|---|
| D1 | Do auto-closed tickets count as "tickets closed"? | Yes, per policy §10 Attendance, shown in a separate column |
| D2 | Thresholds in A5 and A6 | Accuracy ≥ 85% with no family below 70%; repeat recall ≥ 80% and precision ≥ 80% |
| D3 | FX rate for INR cost reporting | USD only until Finance supplies a rate |
| D4 | `max_usd_backfill` for the gate in §14.4 | Must be set by you before the backfill runs. The pipeline refuses the full backfill while it is unset |
