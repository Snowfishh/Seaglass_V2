# Demo walkthrough: the five required examples, plus Cases 6 and 7

Run these from the repository root, pointing at a runtime directory that has its own `.env`, keys and database:

```bash
.venv/bin/python -m aspire_brain.cli --root <RUNTIME> init-demo
.venv/bin/python -m aspire_brain.cli --root <RUNTIME> doctor
cd <RUNTIME> && /path/to/repo/.venv/bin/python -m uvicorn aspire_brain.main:app \
    --host 127.0.0.1 --port 8781 --no-proxy-headers --no-access-log
```

Open `http://127.0.0.1:8781` for the case demo. To choose a persona, follow the travel-policy
link to `http://127.0.0.1:8781/ask`, then go back to `/cases`. Use **employee** for Cases 1–4, 6
and 7, and **auditor** for Case 5. Typed questions need **User A** or **User B**, and the
freshness and permission controls need **Fintech platform admin**. Stay on the same host
throughout, because writes need a matching origin and a CSRF token.

The output below is excerpted from the rendered page text of the running application on
15 October 2026, captured from a fresh `init-demo` runtime after the gap-closure changes. Lines are
copied as rendered; repeated lines and request IDs are left out. The first captures were made in
the 27 September G5 rehearsal (`artifacts/g5/browser-rehearsal.json`), which is local, Git-ignored
evidence.

---

## Case 1: Unified natural-language query (PDF example 1)

*Question:* "What is the status of the database migration project and were there any blockers
raised in Slack last week?"

```text
Answer  answered
Answered from sources you are allowed to read.
Jira · MIGRATE-42
  Database migration project status: in progress.
  Blocker: connection pool limit.
Slack · msg-db-1
  Database migration blocker confirmed in Slack: connection pool limit exceeded.
Slack messages are filtered to the last 7 days by message event time; Jira issues are not time-filtered.

Question coverage 5 of 6 terms (blockers, database, migration, project, raised, status) · needed 75% · applied true
Routing question_driven · Jira, Slack (keyword_signals)
Not searched: Confluence, Google Drive. Routing used keyword signals only. Omitted platforms had no
  explicit signal and were not queried; their omission is not evidence of absence.
Context budget 2 of 8 items · 157 of 12000 characters · 0 dropped · degraded false
Retrieval cap 50 per platform, applied after authorization and event time scope · truncated false
Time scope  Slack: 2026-09-20T10:00:00+00:00 to 2026-09-27T10:00:00+00:00 (by event_at)
```

**What to look for.** One answer draws on two platforms and cites each, quoting the sentences that
answer the question. The Slack scope uses **event time**, so "last week" means when the message
was sent. The coverage line shows how the answer was judged answerable: five of the question's six
content terms appear in permitted evidence ("raised" does not), above the 75% threshold. This
case's fixture holds only Jira and Slack, so the other two platforms are not searched.

## Case 2: Data freshness (PDF example 2)

*Question:* "What is the latest runbook for the payment-service incident?"

```text
Confluence · RUNBOOK-PAY
  Payment-service incident runbook: step 1 restart the service; step 2 notify the on-call lead.
  step 3 enable failover to the standby region.
Sync run completed · 0 created · 1 updated · 0 deleted · 0 permission changes · 1 pages read
Asked before the sync abstained · source stale
Source changed: 2026-09-27T13:00:00+00:00
Change synced into the index: 2026-09-27T13:10:00+00:00
First question after the sync: 2026-09-27T13:10:00+00:00 · answer includes the change true
Change reached the index after 600 s, against a budget of 3600 s
Earliest moment the answer was correct: unknown, because it was not checked continuously
These are simulated times (simulated_elapsed). Wall-clock time: not measured
```

**What to look for.** Before the sync the query abstains and marks the source stale instead of
answering from the old runbook. After it, the answer includes the new failover step. The question
asks for the runbook itself, and the runbook's first sentence covers every term, so the whole
runbook is quoted, including step 3, which shares no words with the question. This card runs on a
simulated clock. The typed card below shows the same behaviour in real elapsed time.

## Case 3: Correct permission enforcement, negative case (PDF example 3)

*Question:* "Show me the security incident report from the Q3 breach."

```text
Answer  abstained
No answer. The evidence you are allowed to read does not answer this question, so nothing was
  released. This does not say whether other records exist.
Question coverage 0 of 5 terms (breach, incident, q3, report, security) · needed 75% · applied true
```

**What to look for.** Nothing from the restricted report appears, and the card neither confirms
nor denies that it exists. The strings `BREACH-RPT` and `classified` appear nowhere in the rendered
output. A denied read and an unknown read look the same.

## Case 4: Live permission change handling (PDF example 4)

```text
Slack · msg-rev-1
  Incident update: service restored.
Saved answer after revocation denied
Same question after revocation abstained
```

**What to look for.** After revocation even the *saved* answer is denied, because access is
checked again when it is read. A revoked source cannot survive in the answer text, the citations,
or the time-scope and budget metadata. This card simulates the revocation; the typed card below
removes access on the (fixture) platform itself.

## Case 5: Audit inquiry (PDF example 5)

*Officer question:* "What did employee access in the payment-gateway Confluence space in the last 30
days?" (auditor persona required)

```text
Found 3 recorded questions the employee asked about the payment-gateway Confluence space in the
  last 30 days.
When 2026-10-15T11:48:47.992445+00:00
Question asked What is the latest runbook for the payment-service incident?
Sources retrieved confluence:RUNBOOK-PAY:RUNBOOK-PAY:v1
Access decisions  Confluence · RUNBOOK-PAY allowed
Audit chain valid true
Both query routes are covered, including queries stopped before an answer. Every event matches the
  separate audit witness. Removing the newest events from the database and the witness together
  would not show here; a checkpoint exported after them and kept elsewhere catches that.
Checkpoint verified through checkpoint true · 0 events after it
Paging page size 100 · 3 returned of 3 · more false · next-page token none
```

Each run of Case 2 adds three matching records (before the update, after the sync, and the demo
query), so the counts grow with use.

**What to look for.** The officer sees the exact question, the retrieved IDs, every per-document
decision and the answer, with timestamps. The completeness line now rests on the audit witness: a
separate file, under its own key, records each committed chain head, so deleting the newest events
from the database would make this check fail. Deleting them from the witness as well would not;
only a checkpoint exported after them and kept elsewhere detects that. For any other user, space or document, the **Audit trail** page has a
search form (below).

---

## Typed question: one question, two personas

The first card on the Case demo page takes your own question and searches all four platforms of
the shared, synchronized fintech index. Its fixture clock starts at 12 October 2026, 03:00 UTC when
the server starts, then runs in real time.

*Question:* "Why is Cedar Quay's payment held?"

```text
As User A
Answer  answered
Confluence · conf-restricted-case
  Restricted Case Note — Beneficiary Verification Exception
  Cedar Quay Analytics Pte. Ltd., a fictional business customer, submitted a supplier payment of
    USD 12,480.00 for invoice CQ-DEMO-2048.
  The payment is held before release because the beneficiary account details were changed after
    the invoice entered the approval workflow.
Question coverage 4 of 4 terms (cedar, hold, payment, quay) · needed 75%
Checked with the platforms before quoting 7 sources · 7 still readable and current

As User B
Answer  abstained
The evidence you are permitted to read does not answer this question; human review required.
Question coverage 2 of 4 terms (cedar, hold, payment, quay) · needed 75%
```

*Question, as User B:* "How many supplier payments need manual review in the 09:30 handover?"

```text
Answer  answered
Confluence · conf-morning-handover
  Daily Payment Operations — Singapore Morning Handover
  The morning queue contains 126 supplier-payment instructions.
  Of these, 118 are completed, five are processing and three require manual review.
Slack · slack-shift-root
  The 09:30 snapshot still has five payments processing and three in manual review.
Question coverage 6 of 6 terms (09:30, handover, manual, payments, review, supplier)
Nothing relevant you may read on: Jira, Google Drive
```

*Question, as User B:* "What is the approved budget for fixing the callback delay?"

```text
Answer  abstained
The evidence you are permitted to read does not answer this question; human review required.
Question coverage 3 of 5 terms (approved, budget, callback, delay, fixing) · needed 75%
```

**What to look for.** The same question gives User A the restricted case note and gives User B a
plain abstention, worded exactly as it would be for a customer that doesn't exist. Answers quote
the passages that cover the question instead of whole documents; the handover answer is under
1,500 characters where it used to be over 8,600. The budget question finds the Jira issue about the
callback delay, but nothing about a budget, so it releases nothing rather than quoting unrelated
text. Before quoting, each source is checked again with its platform as the asking user.

## Freshness and permission changes in the typed card

Open **Freshness and permission changes** under the typed card and sign in as **Fintech platform
admin**.

*Publish runbook revision 1.1*, then *Sync now*:

```text
Upstream change apply runbook update: conf-payment-runbook. It reaches answers at the next sync.
Confluence stale last synced 2026-10-12T03:00:00+00:00 · budget 3600 s · 3 records · changes
  waiting for the next sync
Sync finished Confluence completed · Jira completed · Slack completed · Google Drive completed
Confluence fresh last synced 2026-10-12T03:00:34.234484+00:00 · budget 3600 s · 3 records
Measured propagation
Confluence · conf-payment-runbook revised to 1.1: visible after 5.512 s of a 3600 s budget true
  (measured elapsed)
```

Asked as User B before and after, "What is the escalation threshold for processing payments?"
quotes "more than 30 minutes" before the sync, nothing from Confluence while the change is waiting,
and "more than 15 minutes" after it.

*Remove User A's access to the restricted case and invoice*, then, as User A, re-open the answer
saved earlier:

```text
Before:  allowed The saved answer is still available: every cited source is still readable and
         unchanged.
After:   denied Evidence unavailable. A cited source is no longer readable or has changed, so the
         saved answer is closed.
```

**What to look for.** A change made on the platform side is not quoted as current until a sync
ingests it, and the panel records the real elapsed time it took against the one-hour budget. The
server also syncs on its own every 300 seconds. A removed permission works at once: new answers stop
quoting the records and the saved answer closes before any sync. With
`ASPIRE_PLATFORM_SOURCE=connectors` the same index reads the real platforms, and these changes are
made on the platforms themselves ([live platform check](../../eval/live_platform/README.md)).

## Audit trail search

Sign in as **Auditor** or **Fintech auditor** and open **Audit trail**. The **Reconstruct
activity** form searches the encrypted query records by user, platform, space or document, or any
combination. As Fintech auditor, searching for the document `conf-restricted-case` returns every
user it was retrieved for. Searching for user `user-a` returns:

```text
1 matching record(s)
Every event up to the newest one matches the separate audit witness. Removing the newest events from the database and the witness together would not show here; a checkpoint exported after them and kept elsewhere catches that.
user-a · 2026-10-15T11:48:47.916483+00:00
Question: Why is Cedar Quay's payment held?
Outcome: answered · four-platform route
Retrieved: confluence:conf-restricted-case:1
Access decisions (8)
```

Travel-policy questions appear the same way with platform `policy_store`, and a query stopped
after retrieval (for example by a provider failure) appears with its retrieved IDs and no answer.

---

## Case 6 (supplemental): Google Drive, deletion and a real late sync

This case runs the Drive path: create a file, sync, query, then delete it, tombstone it and query
again. It also includes a **real over-budget** run. The change happens at 13:00 and is ingested at
14:10, which is 4200 s against a 3600 s budget, and the query is reported as an observed
over-budget failure instead of being hidden.

```text
Over-budget comparison
After delete
observed_late_sync
```

**What to look for.** A deletion becomes a tombstone. The deleted file drops out of the answer
set, and the audit record of it stays. The over-budget run is shown as a **failure**, because it
missed the budget.

## Case 7 (supplemental): grounded answers and the claim gate

Case 7 explicitly uses the deterministic local `fake_grounded` provider.

```text
Claim-by-claim support · mode simulated · provider fake_grounded · method exact_cited_span
3 claims checked · 3 supported · 0 unsupported · all supported true
Held back: false · notices left out of the count: 1
supported From simulated://jira/MIGRATE-42: Database migration project status: in progress.
  (supported_by_exact_cited_span; word overlap 0.545455, shown for diagnosis only)
supported Blocker: connection pool limit. (supported_by_exact_cited_span; word overlap 1, shown for
  diagnosis only)
Default mode for comparison offline_extractive · answered
Control question it should refuse abstained · 0 claims made · held back true
Provider run · mode simulated · outcome not_run
Live request made: false
```

**What to look for.** Every live field reads `not measured`, and `Live request made: false`, so a
local result can't be mistaken for a live one. The method label `exact_cited_span` is kept for
compatibility. The gate itself now requires a complete source sentence or complete colon tail
(case and whitespace normalised). The lexical-overlap ratio is labelled **diagnostic only** so
nobody mistakes it for the release gate. The abstention control shows that when evidence is
insufficient, the answer asserts nothing.

---

## Supplemental: a provider failure releases nothing

Here the opt-in `live_grounded` provider is configured but unavailable, because the approved
request budget is already spent. Nothing is released:

```text
POST /api/queries  (employee, "What is the contractor travel cap?", case date 2026-09-10)
→ 502  Provider could not produce a validated answer
POST /api/cases/case_7
→ 503  Case simulation unavailable
Audit: query_attempt → policy_decision → provider_error → query_aborted · chain valid true
```

**What to look for.** The refusal happens before any request is reserved or sent, so the spend
ledger doesn't change. The failure is audited, and no evidence or partial answer reaches the user.
This was rehearsed against a copy of the spent ledger with a placeholder key, so no request could
have reached the provider.

---

## Rehearsal record

| Check | 15 October 2026 (after gap closure) | 27 September 2026 (G5) |
|---|---|---|
| Cases run | 1–4, 6, 7 as employee; 5 as auditor; typed questions as User A and User B; runbook revision, revocation and sync as Fintech platform admin; audit search as Fintech auditor. The provider-failure runtime is from the earlier 15 October rehearsal | 1–7 |
| Result | Every card rendered as shown above. Case 3: `BREACH-RPT` and `classified` absent from the rendered text. Saved answer re-open: allowed before revocation, denied after | **30 / 30** automated rendered assertions passed (`artifacts/g5/browser-rehearsal.json`) |
| Runtime | a fresh `init-demo` root with its own `.env`, keys, witness and SQLite database, on `127.0.0.1:8790` | isolated root on `127.0.0.1:8781` |
| Live contact | none: fixture source, offline provider | none |

The 27 September wall-clock figure (3.03 s) timed pipeline execution only. It does not measure
simulated freshness propagation.
