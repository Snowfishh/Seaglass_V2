# Demo walkthrough — five required examples, plus Case 6 and Case 7

Run from the repository root against a runtime with its own `.env`, keys and database:

```bash
.venv/bin/python -m aspire_brain.cli --root <RUNTIME> init-demo
.venv/bin/python -m aspire_brain.cli --root <RUNTIME> doctor
cd <RUNTIME> && /path/to/repo/.venv/bin/python -m uvicorn aspire_brain.main:app \
    --host 127.0.0.1 --port 8781 --no-proxy-headers --no-access-log
```

Open `http://127.0.0.1:8781` for the case demo. Follow the travel-policy link to
`http://127.0.0.1:8781/ask` to use the persona selector, then return to `/cases`: **employee** for Cases 1–4, 6 and
7; **auditor** for Case 5. Keep the same host throughout — writes require a matching origin and a
CSRF token.

Rendered evidence below is **verbatim text from the running application**, re-checked in the
browser on 15 October 2026 against the current code (see the rehearsal record at the end). It was
first captured in the 27 September G5 rehearsal (`artifacts/g5/browser-rehearsal.json`, with
screenshots under `var/`); those files are local, Git-ignored evidence and are not in the
repository. Run the steps above to reproduce the views.

---

## Case 1 — Unified natural-language query (PDF example 1)

*Question:* "What's the status of the database migration project and were there any blockers raised
in Slack last week?"

```text
Platforms: jira, slack
Query status: answered
Routing: question_driven · jira, slack (keyword_signals)
Omitted: confluence, drive — Routing used keyword signals only. Omitted platforms had no explicit
  signal and were not queried; their omission is not evidence of absence.
Source freshness: jira: fresh · slack: fresh
Context budget: items 2/8 · chars 157/12000 · dropped 0 · degraded false
Retrieval cap: 50 per platform, applied after authorization_and_event_time_scope · truncated false
Time scope:
  slack: 2026-09-20T10:00:00+00:00 → 2026-09-27T10:00:00+00:00 (basis event_at)
  Slack messages are filtered to the last 7 days by message event time; Jira issues are not
  time-filtered.
Citations:
  jira — MIGRATE-42 (issue) simulated://jira/MIGRATE-42
  slack — msg-db-1 (thread_message) simulated://slack/msg-db-1
```

**What to look for.** The answer spans two platforms with citations back to each. The Slack scope
uses **event time** (`basis event_at`), not `source_updated_at`, so "last week" means when the
message was sent. The routing decision is disclosed, including that unqueried platforms are *not*
evidence of absence. The retrieval cap is reported as applied **after** authorization and
event-time scope.

## Case 2 — Data freshness (PDF example 2)

*Question:* "What's the latest runbook for the payment-service incident?"

The card shows the observed sequence: a runbook update at 13:00, ingestion at 13:10 (a 600 s
propagation against a declared 3600 s budget), the first post-sync query **observed** at ingestion
time, and — critically — the label:

```text
Before sync: query status abstained · freshness stale
Mutation: 2026-09-27T13:00:00+00:00
Ingested: 2026-09-27T13:10:00+00:00
First post-sync query (observed): 2026-09-27T13:10:00+00:00 · contains update true
Earliest correct answer: unknown (not polled) · observation mode: observed_query
Budget 3600 s · propagation 600 s · answer latency 3900 s
Within budget: true
Time mode: simulated_elapsed · wall-clock: unmeasured · live propagation: unmeasured
```

**What to look for.** Before the sync, the query abstains and the source is marked stale rather
than answering from the old runbook. After the sync, the answer includes the new failover step
("step 3 enable failover to the standby region"). The system reports the update as visible from
the observation it actually made, and refuses to claim an earliest-visibility bound it did not
measure. Times are simulated elapsed time, not wall-clock latency.

## Case 3 — Correct permission enforcement, negative case (PDF example 3)

*Question:* "Show me the security incident report from the Q3 breach."

```text
Query status: abstained
```

**What to look for.** The card does **not** contain the restricted report's contents, and it does
not confirm or deny the report's existence. The string `BREACH-RPT` and the word `classified` do
not appear anywhere in the rendered output — the denial is verified by rendered assertion, not by
inspection. A denied read and an unknown read are outward-identical.

## Case 4 — Live permission change handling (PDF example 4)

Case 4 runs in fresh permission state each time: it saves a packet, then revokes the source, then
re-reads the saved packet.

```text
Citations: slack — msg-rev-1 (channel_message) simulated://slack/msg-rev-1
After revocation: saved packet access denied
After revocation query status: abstained
```

**What to look for.** The *saved* packet is denied after revocation — the restriction is re-checked
at read time, not merely at write time. A revoked source cannot survive in the answer text,
citations, time-scope metadata or context-budget metadata.

## Case 5 — Audit inquiry (PDF example 5)

*Officer question:* "What did employee access in the payment-gateway Confluence space in the last 30
days?" (auditor persona required)

```text
Audit chain valid: true
Retention: window 90 days · cap 10000 entries · payloads removed 0
Checkpoint anchoring: verified through checkpoint false · unanchored tail events 36
Pagination: page size 100 · returned 3 · total matches 3 · more false · continuation none
Exact question: What is the latest runbook for the payment-service incident?
Retrieved IDs: confluence:RUNBOOK-PAY:RUNBOOK-PAY:v1
Per-document decisions: confluence:RUNBOOK-PAY — allowed
```

The counts depend on how often Case 2 has run in the runtime: each run adds three matching
queries (one before the update, one after the sync, one demo query), and the unanchored-tail count
grows with every audited request.

**What to look for.** The officer reconstructs the exact question, the retrieved IDs, the final
answer and the per-document authorization decision, with timestamps. Three governance limits are
stated rather than hidden: retention scope, that the chain is **not** verified through a checkpoint,
and that `completeness_unproven`. The **pagination** line shows the result set is traversable — a
matching set larger than the page size returns a signed continuation cursor instead of silently
truncating at 100.

---

## Case 6 — Supplemental: Google Drive, deletion and a real late sync

The Drive path: file create → sync → query, then delete → tombstone → query. It also contains a
**real over-budget** run (mutation 13:00 → ingestion 14:10, i.e. 4200 s against a 3600 s budget)
whose query is reported as an observed over-budget failure rather than being hidden.

```text
Over-budget comparison
After delete
observed_late_sync
```

**What to look for.** Deletion is a tombstone, not a gap: the deleted file leaves the answer set
while the audit record of it remains. The over-budget case is shown as a **failure**, which is the
honest outcome.

## Case 7 — Supplemental: grounded answers and the claim gate

Case 7 explicitly selects the deterministic local `fake_grounded` provider.

```text
Provider runtime · mode simulated · outcome not_run
Live request made: false
service: unmeasured · model: unmeasured · endpoint_host: unmeasured · region: unmeasured
cost_usd: unmeasured · latency_ms: unmeasured

Claim-level support · mode simulated · provider fake_grounded · method exact_cited_span
Denominator: 3 claims · supported 3 · unsupported 0 · all supported true
Abstained: false · notices excluded 1
supported (supported_by_exact_cited_span, overlap 0.545455 — diagnostic only)
supported (supported_by_exact_cited_span, overlap 1 — diagnostic only)
supported (supported_by_exact_cited_span, overlap 0.6875 — diagnostic only)

Default mode: offline_extractive · query status answered
Abstention control: query status abstained · claims asserted 0 · abstained true
```

**What to look for.** Every live field is `unmeasured` and `Live request made: false` — a local
result can never look like a live one. The compatibility method label is `exact_cited_span`; the current gate requires a complete
source sentence or complete colon tail (case and whitespace normalised), and
the lexical-overlap ratio is labelled **diagnostic only**, so it cannot be mistaken for the release
gate. The abstention control proves the insufficient-evidence path asserts nothing.

---

## Supplemental — provider failure fails closed

With the opt-in `live_grounded` provider configured and the provider unavailable (here, the
approved request budget already spent), nothing is released:

```text
POST /api/queries  (employee, "What is the contractor travel cap?", case date 2026-09-10)
→ 502  Provider could not produce a validated answer
POST /api/cases/case_7
→ 503  Case simulation unavailable
Audit: query_attempt → policy_decision → provider_error → query_aborted · chain valid true
```

**What to look for.** The refusal happens before any request is reserved or sent, so the spend
ledger is unchanged; the failure is audited, and no evidence or partial answer reaches the user.
This was rehearsed against a copy of the spent ledger with a placeholder key, so no request could
reach the provider.

---

## Rehearsal record

| Check | 15 October 2026 (current code) | 27 September 2026 (G5) |
|---|---|---|
| Cases run | 1–4, 6, 7 as employee; 5 as auditor; provider failure in a separate runtime | 1–7 |
| Result | Every card rendered as shown above. Case 3: `BREACH-RPT` absent from the page HTML and `classified` absent from its text | **30 / 30** automated rendered assertions passed (`artifacts/g5/browser-rehearsal.json`) |
| Runtime | isolated roots with their own `.env`, keys and SQLite databases, on `127.0.0.1:8781` and `:8782` | isolated root on `127.0.0.1:8781` |
| Live contact | none: platforms simulated; offline provider, or live mode refused before any request | none |

The 27 September wall-clock figure (3.03 s) measured pipeline execution only and is not simulated
freshness propagation.
