**To:** Priya Raman, Head of Customer Experience, Vireo Audio
**Cc:** Arjun Mehta (Finance), Neha Kulkarni (Support Ops)
**Re:** Weekly support digest and repeat-contact cost, week of 22–28 Jun 2026
**Date:** 3 Oct 2026

### Executive summary

The weekly digest and tickets-closed leaderboard are built and validated. In the latest full week, **20 of 199
incoming contacts were repeat contacts** under support-policy §10 (same customer, same product, same issue, within
30 days of resolution). At the policy's per-channel contact costs they cost **Rs 5,130**. The AI classifier was
checked against 120 human-labelled tickets (**98.3% accurate**) and cost **$0.1514 in total**; projected running cost
is **$0.28/month**.

### What customers are complaining about (199 tickets)

1. Delivery delay / not received: **25**
2. Refund not received: **16**
3. Battery drain: **15**
4. Charging failure: **12**
5. Pre-sales questions: **12**
6. Transit damage / wrong item: **11**

All 28 tickets the intake bot filed as "Other" were assigned a specific issue.

### Repeat-contact burden and cost

**20 repeat contacts, Rs 5,130:**

| Channel | Repeats | Cost |
|---|---|---|
| Chat | 11 | Rs 2,310 |
| Email | 5 | Rs 1,300 |
| Voice | 2 | Rs 1,040 |
| Social | 2 | Rs 480 |

Valued at a single blended rate instead, the figure is Rs 5,800 at Rs 290/contact, or Rs 3,600 at Finance's
Rs 180/contact.

**Largest driver:** transit damage / wrong item, 3 repeats (Rs 1,040). Charging, mic, return pickup and warranty
status follow with 2 each.

Pulse 2 earbuds account for 10 of the 20 repeats, but also 80 of the 199 tickets (40%). One week is too small to call
that a product issue.

**Separate cost lines, not added to the above:**
- SLA breach credits: 18 / Rs 6,300
- Transfers: 22 / Rs 6,710

CSAT is 3.26 (n=90).

### Agent throughput (leaderboard caveat)

The leaderboard shows **tickets closed: throughput, not performance**. Agents are ranked only within their own Tier 1
team, never across teams. Escalations & Warranty (Tier 2) is unranked and shown with days to resolve, per policy §6
and Neha's request. Counts reflect queue mix, shift and case complexity.

### AI validation

| Check | Result |
|---|---|
| Issue classification | 98.3% accuracy (118/120), macro-F1 0.984; every issue family at least 92.9% |
| Repeat detection, recall | 13 of 14 customer-declared repeats found (92.9%) |
| Repeat detection, precision | 25 of 25 flagged repeats confirmed by human review (100%) |

The AI only labels the issue. Python does every count, cost and ranking.

### Business impact (measured, not savings)

Rs 5,130 is the **measured cost of repeat contacts this week**, using your own policy rates. It is **not a savings
figure**. The digest does not reduce contacts by itself; savings would only follow from fixing the drivers it
identifies, and none are claimed here.

### Scope and limitations

- **Only the selected week was classified** (273 tickets). On the free Gemini tier, the full 18-month history would
  take about 10 hours. So these are not yet computed:
  - 12-month and 18-month repeat totals
  - week-over-week trends
- **Small validation samples:** 14 for recall, 25 for precision.
- **Data use:** classification used the **Gemini free tier**. Ticket text for 407 tickets was sent to Google, whose
  terms allow free-tier content to be used to improve its products.

### Recommended next step

1. Approve a **billing-enabled Gemini key**. This removes the free-tier data-use issue and the rate limit.
2. Run the full-history backfill: projected cost about **$4.15**.
3. That gives a 12-month repeat baseline and trends. Then assign owners to the top repeat drivers, starting with
   transit damage / wrong item and refund delays.
