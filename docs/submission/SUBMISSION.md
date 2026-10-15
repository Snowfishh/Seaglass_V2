# Submission package: Aspire Internal Brain

This is the submission package for the Aspire challenge, *The Internal Brain — Building a
Context-Aware Enterprise Knowledge System with RBAC, Security Logging & Audit Trail*. The task is
section 4 of the participant brief, "The FinTech Track". The submission rules are in its section 8,
"Project Submission Requirements".

The package was **prepared locally**. This audit did not publish, deploy or submit it. Public
access to the repository and the commit currently on the remote were not independently confirmed,
so check both before submitting. Separately from their general proof gate, the submission rules
list **two Required proof items**:

- **Conversation history: satisfied.** `chat-proof/conversation-history/` holds an authentic
  export of the six real development sessions.
- **At least 3 chat-log screenshots: still open.** `chat-proof/excerpts/` holds three *transcript
  exports*, each labelled as an exported transcript rather than a UI screenshot. It is **unknown**
  whether the organiser will accept them for this item. See
  [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md).

Until that item is resolved, the submission is **incomplete**.

---

## 1. Project title

**Aspire Internal Brain**

## 2. Short blurb (hard limit: under 10 words)

> Unified answers across four platforms, permission-scoped and audited.

*8 words.* Count: Unified(1) answers(2) across(3) four(4) platforms(5) permission-scoped(6)
and(7) audited(8).

## 3. Project description

### 3.1 Project overview — target scenarios, users, value proposition

**Target scenarios.** In a mid-to-large engineering organisation, one incident ends up in four
places: a Jira ticket, a Confluence runbook, a Slack thread and a Drive postmortem. Each has its own
permission model and goes stale at its own pace, and nothing searches all four. The system answers
natural-language questions by pulling context from **across** those platforms, and it refuses to
show anything the person asking may not read.

**Users.** Three roles, each with its permissions modelled explicitly:

| User | What they need | What the system must not do |
|---|---|---|
| Backend engineer | Status of a migration project plus blockers raised in Slack last week | Return threads from private channels they are not in |
| Contractor / external | A general answer that does not depend on restricted material | Confirm or deny that a restricted security report exists |
| Compliance officer | Reconstruct what any user asked, what was retrieved on their behalf and what was answered | Give ordinary knowledge access just because they hold an audit role |

**Value proposition.** Finding documents is the easy part. The hard part is returning only what the
asker may read, and keeping a record that holds up when someone checks it later. So the system
treats each authorization decision as an object in its own right, and audits it. Every
source-derived field in an answer comes from an authorized set of records, and every query attempt
and outcome is written to a tamper-evident chain.

### 3.2 Real-world scenario insights — pain points, audience, core problems

**Where the pain points come from.** The challenge statement. It says employees of the modelled
company "waste an estimated 30% of their workweek searching for information", and that an incident
responder at 3 AM has to cross-reference four systems with four permission models. **The 30% figure
is the challenge statement's premise. This project did not measure it.** §3.4 lists what the
project did measure.

**Target audience.** Platform and security engineering teams at companies that run a mix of SaaS
tools. After them, compliance and internal-audit teams who today can't answer "what did user X
access last week" without digging through logs by hand.

**Core problems solved.**

1. **Each platform handles permissions differently, and flattening them loses information.**
   Confluence works by space and page, Jira by project, role and issue, Slack by channel
   membership, and Drive by file, folder and user. Ingestion keeps those differences instead of
   squeezing them into one ACL column.
2. **Filtering has to happen *before* the model sees anything.** Otherwise the model can leak
   content the asker may not read, or be prompt-injected by it.
3. **Permissions can change between ingestion and query.** After a revocation, content that used
   to be allowed must not stay reachable, and that includes an answer packet saved earlier.
4. **A confident model can make up content it was never given.** So each claim is checked against
   its cited source, and one unsupported claim gets the whole answer refused.
5. **An audit log has to say whether it can prove it is complete.** The system reports "the chain
   is valid" and "the chain is complete" separately, and never passes off the first as the second.

### 3.3 Comprehensive solution design

**Business architecture.** A successful request goes *ask → resolve identity → authorize and
retrieve → project bounded context → call provider → treat output as untrusted → validate and
recheck → commit audit event and packet atomically → return*. The audit path also receives ingress
denials, query attempts, controlled aborts and provider failures. A failed request leaves no answer
packet to inspect; its safe audit events and its HTTP result are the evidence, kept separately.

**Technical architecture.** Everything runs on FastAPI, Pydantic, SQLite/FTS5 and Jinja2. The
travel-policy route uses SQLite/FTS5. The four-platform route keeps one shared index per process,
and a synchronizer refreshes it every 300 seconds against a one-hour freshness budget. The index
has two possible sources. The default is the fictional fintech fixture, held in memory. The other
is the four HTTP connectors reading real Confluence, Jira, Slack and Google Drive accounts
(`ASPIRE_PLATFORM_SOURCE=connectors`). In that mode each connector lists what each user can see,
with that user's own token: the pages in a Confluence space, the issues in a Jira project, the
Slack channels the user belongs to and their threads, and the text files in a Drive folder. No item
IDs need to be known in advance.

On 14 October 2026 the owner ran a read-only check of the connectors against real test accounts
with per-user tokens. It passed 16/16, and the second user was refused every restricted item (see
the [live access check](../reviews/live-access-2026-10-14/README.md)). The integrated path, meaning
sync, answers, the query-time re-check and revocation against those same accounts, has its own
owner-run check in [`eval/live_platform/`](../../eval/live_platform/README.md). That check has not
been run yet. Its offline tests drive the same code against a stateful fake of all four APIs.

Local providers are the default. The opt-in `live_grounded` mode connects Groq, for fictional demo
data only: the model picks which permitted evidence sentences answer the question, and the answer
is rebuilt from those exact sentences. Before that mode existed, a separately injected 5E service
path sent fixed fictional requests to Groq.

[architecture-trust-boundary.svg](architecture-trust-boundary.svg) (rendered as
[PNG](architecture-trust-boundary.png)) shows the directed execution view and its three labelled
boundary crossings. Here is how to read it:

1. **Outside the service.** The browser sends an untrusted request. Confluence, Jira, Slack and
   Drive are external source platforms. With the connectors source the service reads them through
   each user's own read-only token; by default it reads the fictional fixture instead. At trust
   boundary 1, source prose is treated as data, and ACLs come from what each platform let each
   user read.
2. **Inside the service.** Session and CSRF checks and server-owned identity come before
   authorization. The service keeps a local FTS5 policy store and a separate in-memory platform
   snapshot. Platform ACLs stay distinct (space and page, project and issue, channel and thread,
   folder and file), and tombstones and revisions are explicit state. The same synchronizer serves
   the fixture and the connectors, and the 3,600-second freshness budget is checked on every
   query. In four-platform retrieval, the tenant/ACL predicate runs *before* ranking and top-k. Question-driven routing picks the platforms and a half-open event-time window scopes the
   records. The per-platform cap applies **after** that scope, so it can't hide a recent match
   behind older ones. Cross-platform ranking is deterministic, and a bounded context budget records
   what it drops. Routing decides which platforms the question needs, and every other platform the
   index serves is searched too, so a keyword miss can't keep a relevant runbook out of the answer.
   If a platform the question named has nothing relevant, the answer is `partial` and says which
   platform. A platform searched only as a precaution is listed but doesn't make the answer
   partial. Before anything is quoted, the service counts how many of the question's content terms
   the permitted evidence covers. Below 75% it abstains with one fixed sentence instead of quoting
   unrelated text. Otherwise it quotes only the passages that cover the question, after asking the
   source (the fixture or the platform itself, as the asking user) whether each record is still
   readable and unchanged.
3. **Provider call (trust boundary 2).** The service hands the provider a question and a bounded
   set of permitted evidence. `offline_extractive` (the default) quotes permitted evidence, and
   `fake_grounded` composes from permitted evidence only. Neither makes an external call.
   The opt-in `live_grounded` provider is built only for the approved Groq target and limits, with
   a key file outside the project and a file-locked spend ledger. Any other configuration is
   refused before a request is made. It sends only the question and the permitted evidence split
   into numbered sentences. It never sends identity, tenant, roles, ACLs, audit data, document
   identifiers or locators, and on the platform path it withholds restricted-classified sources.
   Each attempt is reserved in the ledger before any byte goes out, and nothing is retried. The
   earlier, separately injected 5E preflight sent Groq a fixed fictional question, permitted source
   text and citation ID, a system instruction, model settings and a schema. It observed one
   corrected HTTP 200 and a readable packet. Human acceptance is still pending.
4. **Provider return (trust boundary 3).** The returned answer and citation IDs are treated as
   untrusted. From `live_grounded`, the model returns only sentence numbers or an abstention. The
   provider rebuilds the answer from those exact sentences under labels the service writes, so
   prose written by the model never reaches the user. An abstention releases no sentences the model
   chose. On a `needs_review` or `insufficient_evidence` decision, the service releases its own
   deterministic decision with no citations; on an answerable decision, an abstention still fails
   closed. The service validates the typed output and checks that every citation belongs to the
   evidence set. Each claim must match a **complete cited source sentence or complete colon tail**,
   normalized for case and whitespace. Access is checked again before the packet and audit event
   are written atomically. A timeout, a spend-limit refusal, an invalid selection or citation, or an
   unsupported claim all fail before the packet is saved. This gate cannot take back provider input
   that was already sent.
5. **Audit on every path.** Identity and CSRF refusals at ingress write `access_denied`, and the
   query attempt is recorded before retrieval starts. When `QueryService` hits a provider or gate
   failure, it writes `provider_error` and then `query_aborted`; the four-platform simulator writes
   `query_aborted` without that extra event. A successful request commits `query_completed` and the
   packet in one transaction before it returns. A query stopped after retrieval writes its
   terminal event together with an encrypted record of what was retrieved and decided, so it can be
   reconstructed later like an answered one. If the audit write itself fails, the service refuses
   to release the answer, and it cannot guarantee that the missing event was recorded.
   Governance rests on five pieces: a per-tenant HMAC-SHA256 chain; AES-GCM protected payloads;
   tenant-scoped retention that covers only encrypted simulated-case payloads; local checkpoints
   that report `chain_valid` separately from `completeness_unproven`; an officer inquiry over both
   query routes, stopped queries included, that searches by user, platform, space or document in
   any combination, with signed pagination bound to tenant and filter; and an audit witness. The
   witness is a separate append-only file, under its own key, that records each committed chain
   head. Removing the newest events from the database alone therefore shows up as a
   verification failure, and when every event is witnessed the report states completeness
   relative to the witness. The witness proves only its own prefix, so deleting the newest
   events from both the database and the witness needs no key and is not detected; only a
   checkpoint exported after them and kept elsewhere catches it. Ordinary saved packets are
   plaintext SQLite records and fall outside the encrypted-payload retention policy.

**Status of the intended live system (15 October 2026).** The opt-in `live_grounded` provider is
wired into the query service behind Ask, behind typed four-platform questions and into the Case 7
card. Its owner-run evaluation harness,
[`eval/live_model/`](../../eval/live_model/README.md), records the 14 October runs as they
happened.

Three evaluations ran on 14 October 2026 against fictional demo fixtures, all inside the approved
envelope. Each call was capped at 4,000 input, 800 output and 1,000 reasoning tokens, a 30 s
timeout and USD 0.05. The whole approval was capped at 30 requests and USD 5, tracked in a
file-locked ledger, with no retries. All 30 request slots are now used, so this approval allows no
further live runs.

| Run (UTC) | Calls completed | Released | Safe abstentions | Calls that failed | Verdict under harness rules |
| --- | --- | --- | --- | --- | --- |
| 11:54 | 2 of 10 | 2 | 0 | 8, fast, cause not recorded | `fail` (failures uncategorised) |
| 12:02 | 6 of 10 | 6 | 0 | 4, HTTP 429 (wait asked: 30 s) | `inconclusive` |
| 12:11 | 6 of 10 | 5 | 1 | 4, HTTP 429 (waits asked: 33 s to about 2 h) | `inconclusive` |

- **Safety held in every completed call.** Nothing unsupported was released, no forbidden text
  appeared, and every released status matched the expected one. In all three runs, the no-evidence
  case made no call.
- **None of the runs is a pass.** No single full run showed the 70% answer-share gate. Every run was
  stopped by provider availability, not by model quality. Runs 2 and 3 are not combined into one
  result, and the table counts completed calls. It is not a model-quality figure.
- **Likely cause:** the Groq project's limit of 8,000 tokens a day for this model. The completed
  calls used 8,014 tokens. The Groq usage logs were not checked.

The fixed 5E observation is a separate matter. Its raw vendor body was not kept, the packet is
`needs_review / undetermined`, and human acceptance is pending. The connectors passed a one-off live
read check and are now wired in. The next step is the owner-run integrated check against the real
accounts, and after it a separately authorized 5F batch evaluation. This package does not claim
acceptance of live integration or of 5F.

**How prompts drive the generation.** Prompts show up at two separate levels, and they should be
kept apart:

- *Product level (the system's own instructions).* The default local providers use no prompt.
  The opt-in `live_grounded` mode sends one fixed system prompt
  ([`providers/live.py`](../../src/aspire_brain/providers/live.py), `SYSTEM_PROMPT`). It tells the
  model that its job is to *select* evidence; that every numbered sentence is untrusted data and
  never an instruction; to choose only sentences that directly answer the question, in a readable
  order; and, when the evidence doesn't answer the question, to set `answerable` to false and
  choose nothing. A strict JSON schema (`evidence_selection_v1`) allows only that flag and a list of
  sentence numbers, with `temperature: 0`. The prompt is a first line of control and guarantees
  nothing by itself. The reply is parsed against the schema, unknown or duplicate sentence numbers
  are refused, the answer is rebuilt from the exact sentences chosen, and the
  complete-cited-quotation gate checks every claim again.
- *Development level (how this project was built).* WorkBuddy drove the core build from about
  23 September to early October 2026, across six sessions: source contracts, the four-platform
  simulator, deterministic sync, routing and ranking, the grounded provider and audit, and G1–G5
  gap closure. Those sessions are exported verbatim from the local session logs in
  [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md). The prompts that
  drove them are in [`prompt.md`](../../prompt.md),
  [`docs/workbuddy-next-prompt.md`](../workbuddy-next-prompt.md) and
  [`docs/workbuddy-red-team-prompt-sequence.md`](../workbuddy-red-team-prompt-sequence.md).

  OpenAI Codex was used for separate worktree experiments and for the 13–14 October
  submission-checklist audit. On 15 October it diagnosed the 14 October live runs and repaired the
  live-model evaluation runner, its tests and its README, without making a live call
  ([diagnosis and repair](../reviews/live-model-repair-2026-10-15/README.md)).

  Claude Code was used on 13–14 October for review, scan-fix cleanup, integrating the audit fixes,
  the web UI refresh and re-verification. On 14–15 October it was used for the live connector
  check, the opt-in live provider, the live-evaluation fixes, Windows support, the clean-install
  verification and publication clean-up. On 15 October it also built the endpoint that answers
  typed questions across the four simulated platforms. Those commits are listed in the
  [assistant attribution record](../reviews/assistant-attribution-2026-10-15/README.md). Later on
  15 October it closed the gaps a requirements review had found (§3.5): focused answers and
  abstention, the shared synchronized index with its admin controls, connector discovery and the
  connector source, the query-time permission re-check, audit records for both routes and for
  stopped queries, and the audit witness. Those changes were still uncommitted when this was
  written.

  WorkBuddy was used again from 13 to 15 October. It re-checked the submission checklist, drafted
  this development-process account, and worked through the
  [live-run fix prompt](../workbuddy-live-run-fix-prompt-2026-10-14.md): it recorded Groq's
  rate-limit headers, added the cross-process rate-limit cooldown, drafted the live-run status
  above with its corrections to run 1, and changed the evaluator so that a run whose Case 7 safety
  check was never observed is reported as inconclusive. On 15 October it also built the
  typed-question card on the Case demo page and updated the documentation for typed questions. Its
  own notes are in [`.workbuddy-ai/memory/`](../../.workbuddy-ai/memory/). The owner reviewed,
  directed and committed all of it.

  The WorkBuddy sessions followed one working pattern. State the requirement and its evidence.
  Cross-check the PDF against the evidence before implementing anything. Write tests that fail for
  the right reason before fixing. Update the report after each milestone. That prompt discipline is
  part of the submission. [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md) lists the three
  literal chat-surface screenshots, which are still outstanding.

**Worked examples for the five required scenarios.** Each one runs on the `/cases` page against
fictional, simulated platform data. [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) has the captured
output and what to look for.

| Challenge scenario | Worked example | What it shows | Limit |
|---|---|---|---|
| 1. Unified natural-language query | [Case 1](DEMO-WALKTHROUGH.md#case-1-unified-natural-language-query-pdf-example-1): migration status and last week's Slack blockers; also any question typed in the typed-question card | One answer citing a Jira issue and a Slack message, with routing, time scope and omitted platforms disclosed. Typed questions search all four platforms of the shared, synchronized index with the configured provider and quote only the passages that cover the question | Routing and coverage are lexical, so a question worded with synonyms the sources don't use is refused rather than answered |
| 2. Data freshness | [Case 2](DEMO-WALKTHROUGH.md#case-2-data-freshness-pdf-example-2): the 13:00 runbook update | The updated runbook with the new failover step, synced in 600 s against a declared 3,600 s budget; [Case 6](DEMO-WALKTHROUGH.md#case-6-supplemental-google-drive-deletion-and-a-real-late-sync) reports an over-budget sync as a failure | This card runs on a simulated clock. In the typed card, the sync loop runs in real elapsed time and records how long each change took to reach answers. Live propagation is measured by the owner-run check, not yet run |
| 3. Permission enforcement (negative case) | [Case 3](DEMO-WALKTHROUGH.md#case-3-correct-permission-enforcement-negative-case-pdf-example-3): the contractor and the Q3 breach report | An abstention that neither reveals nor confirms the restricted report | Simulated platform ACLs |
| 4. Live permission change | [Case 4](DEMO-WALKTHROUGH.md#case-4-live-permission-change-handling-pdf-example-4): revoke, then reopen a saved answer | The saved packet is denied after revocation, and no revoked source survives in any field | This card simulates the revocation. In the typed card, a grant removed on the platform closes new and saved answers before the next sync, through the query-time re-check |
| 5. Audit inquiry | [Case 5](DEMO-WALKTHROUGH.md#case-5-audit-inquiry-pdf-example-5): what `employee` accessed in the payment-gateway Confluence space | The exact question, retrieved IDs, answer and per-document decisions, with timestamps | This card asks one fixed question; the Audit trail page searches any user, platform, space or document, both query routes and stopped queries |

**Key design trade-offs** (also shown on the diagram):

| Trade-off | Choice made | Cost accepted |
|---|---|---|
| Claim support: lexical overlap vs bounded quotation | Complete cited sentence or complete colon tail | A paraphrase a reader would accept is **refused**. This checks quotation boundaries, not source truth or entailment |
| Filtering before the provider vs after | Filter before the model | Needs permission state at query time, so each request does more work |
| Retrieval breadth vs a hard cap | Cap applied **after** event-time scope | A cap can never hide recency, but a very large permitted set is still truncated (and the output says so) |
| Simulated vs live integration | Fixture by default; the same index and sync loop read real accounts through the connectors when configured; an opt-in live model that only selects permitted sentences; a separate 16/16 connector read check | The integrated live path is tested offline against a fake of all four APIs; its owner-run check has not been run. No claim about general model quality or production capacity |
| Local answers: quote everything vs quote what covers the question | Lexical term coverage with a 75% threshold, then passage selection | A question phrased with synonyms the sources don't share is refused rather than answered |
| Revocation: wait for the next sync vs ask the platform again | Ask the platform about every quoted record at query time | Each answer costs one extra read per quoted record on the connector source |
| Audit "valid" vs "complete" | Report both; claim completeness only against the separate witness | Someone holding both the database and the witness, with both keys, could rewrite both; the report says so |

### 3.4 Business value

**Measured in this checkout.** Denominators are stated, and everything can be re-run from the
repository. The oracle, freshness and witness rows were measured on 15 October 2026 in the
working tree after the gap-closure changes, before they were committed; the test-count and
coverage rows were re-measured on 16 October after the incremental audit-witness append. The
earlier clean install of the previous commit is recorded in the
[clean-install verification](../reviews/freeze-2026-10-14/README.md). On the same day the typed
card, the platform-admin controls, revocation and the audit search were rehearsed against a running
server from a fresh `init-demo`, driven by script rather than a recorded end-to-end suite. The live
connector row is from 14 October 2026. The adversarial rows come from the 27–28 September simulated
snapshot; the red-team tests themselves were re-run on 15 October.

| Measure | Result | Denominator / basis |
|---|---|---|
| Automated tests passing | **1,068** unit/integration + **93** red-team | 0 failures, working tree after the review fixes, 16 Oct 2026 |
| Statement coverage over `aspire_brain` | **92.08 %** | 5,466 of 5,936 statements, unit/integration tests (floor 80 %), same run |
| Fixture oracle (`expected-outcomes.json`) | **9 / 9** assertions met | 7 typed questions through the web route as their stated user, plus the runbook revision and the case revocation through the admin controls. The cross-platform question is checked against all four required sources (Confluence, Jira, Slack, Drive), its facts and two of its three next actions verbatim; the third (obtain the missing partner references) appears as the stated gap, not as an instruction |
| Answer to the handover question | under 1,500 characters, every claim an exact quotation | previously over 8,600 characters of whole documents |
| Unanswerable question ("approved budget for fixing the callback delay") | abstains, 0 citations | 3 of 5 question terms covered, under the 75% threshold |
| Freshness in the running app | revision answered after the next sync; elapsed seconds recorded per change | fixture source, 300 s sync interval, 3,600 s budget |
| Audit tail removal | detected | deleting the newest event fails verification against the witness |
| Live connector read check | **16 / 16** | 4 platforms × 2 users × 2 items, real test accounts, per-user tokens; B refused all 4 restricted items (14 Oct 2026) |
| Permission/leakage regression tests | **55** new | 49 finding regressions + 6 audit/retention |
| Deterministic adversarial seed suite | **22 cases**: 21 valid, 1 deliberate invalid control | `eval/redteam/` (playbook 1.4.0, schema 2); 16 valid attacks, 4 benign controls, 1 unscored limitation, 0 benign false positives |
| Adversarial outcomes observed | 4 `attack_not_retrieved`, 8 `attack_retrieved_but_blocked`, 0 `attack_succeeded`, 1 `availability_preserved`, 2 `availability_degraded`, 1 `ingestion_inert` | RT-009 is an **expected block**; RT-011 is an unscored `limitation`; RT-016/RT-018 are **measured availability degradation** and are never reported as a blanket "blocked" |
| Deterministic local release gate | **9 / 9 hard checks pass**, exit 0, `network_attempts []` | `eval/redteam/release_gate.py` (1 reviewed noncritical threshold: `availability_loss` 2/3); a clean run passes and an induced implementation defect fails with an RT-009 packet |
| Offline retrieval evaluation | **8 / 12** cases | `evaluate --offline` (22/22 labelled cases passed) |
| Grounding evaluation | 5 supported, 0 unsupported, 1 abstention | `{cases: 3, claims_evaluated: 5}` |
| Officer inquiry traversal | every match, none lost or duplicated | paged against a fixture with more than 100 matches |
| Revoked-source disclosure | 0 source IDs survive in answer, citations, time-scope or budget metadata | regression fixture |
| Loopback API rehearsal | 3 / 3 as expected | cross-tenant sentinel, revocation/saved-packet read, forged citation on `/api/queries` (raw audit rows with request ID, sequence and event type retained) |

**Expected impact (hypotheses, not measured here).** These are benefits the design is meant to
deliver. They are **hypotheses only**: the project has run no user study and cannot put numbers on
them.

- *H1: less time spent searching.* If the challenge statement's "30 % of the workweek searching"
  premise holds for a target organisation, cross-platform answers that respect permissions could
  win back a real share of that time. **Unmeasured.**
- *H2: fewer permission incidents.* Filtering before the model should mean fewer answer-leakage
  incidents than designs that filter afterwards. **Unmeasured; no incident data exists.**
- *H3: less audit effort.* Reconstructing an access question through the officer inquiry replaces
  digging through logs by hand. **Unmeasured; no baseline captured.**
- *H4: better disclosure.* Showing "unknown" and "inaccessible" identically to the asker, while
  logging the difference internally, reduces metadata side-channels. **Demonstrated on a bounded
  local fixture only.**

**What these numbers don't cover.** Apart from the test, coverage and live connector rows, the
§3.4 measurements describe the earlier **simulated, local** snapshot. The separate fixed 5E
synthetic request is documented under `docs/reviews/stage5e-preflight-2026-10-10/`. Live ingestion
is implemented and tested offline, but propagation and revocation against the real accounts wait on
the owner-run check. A published live model evaluation and organiser acceptance have not been
established. The default local provider path still records live fields as `not_run`. Routing and
answer coverage are lexical, so a question worded in terms the sources never use is refused.

### 3.5 Requirement coverage, 15 October 2026

A review on 15 October rated several challenge requirements as partly met. Each finding was checked
against the code. The table records what was found and what changed.

| Requirement | What the review found | What changed | Still needs the owner |
|---|---|---|---|
| Unified questions across four platforms | Typed questions always used the offline provider. A Jira-style code in a question (`OPS-DEMO-01`) routed it to Jira alone | Typed questions use the configured provider, including the live model. Every platform the index serves is searched; routing only decides which platforms must contribute | Nothing |
| Useful grounded answers | Answers quoted every permitted document in full, and an unanswerable question got unrelated excerpts | Answers quote the passages that cover the question and abstain under 75% term coverage. The full fixture oracle passes | Nothing for the default path. The live model is wired in, but its quality is unmeasured: the approved 30-request budget is used up |
| Heterogeneous source integration | Connectors were not connected to ingestion or queries, and read only known item IDs | Each connector discovers items per container and per user, and the connector source feeds the same index and synchronizer | Run `eval/live_platform/check.py ingest` against the real accounts |
| Freshness within minutes to an hour | Typed questions used a fixed clock and no sync loop ran | A sync loop runs every 300 s against a 3,600 s budget. Stale platforms are not quoted, and propagation time is recorded | Run the `freshness` step to measure it on the real platforms |
| Permission enforcement before the model | Proven locally, not on the integrated live path | The connector path builds each user's grants from that user's own reads, and quoted records are re-checked with the platform | Covered by the `ingest` step |
| Permission changes affect later queries | Proven in simulation only; typed questions rebuilt the index per request, so no change could persist | A removed grant closes new and saved answers at once through the re-check, and the next sync folds it into the index | Run the `revocation` step |
| Queryable audit | Travel-policy queries and stopped queries were not reconstructable; one platform per inquiry | Both routes and stopped queries keep encrypted records; search by user, platform, space or document; an Audit trail page form | Nothing |
| Tamper-evident, complete audit | Tail removal was undetectable; `completeness_unproven` was always true | A separate witness records every committed head, so tail removal fails verification and completeness is stated relative to the witness | Keep the witness on separately protected storage in a real deployment |
| LLM safety against unsupported disclosure | Judged met within its scope | No change needed. Answers are rebuilt from exact source sentences and every claim is checked. Relevance is now handled by the item above | Nothing |
| Worked examples, demo, architecture | Present; browser rehearsal not repeated | Rehearsed again on 15 October against the new build | Nothing |

A second review later on 15 October checked those fixes and found further gaps. Each was confirmed
in the code before it was changed, and each fix has a regression test that fails without it.

| Finding | What changed |
|---|---|
| The cross-platform oracle answer cited only Confluence and Jira; its test checked only those two | A question that names an identifier (`OPS-DEMO-01`) now draws a passage from every permitted record carrying it, and from replies in a thread whose root carries it. The answer cites all four required sources, and the test checks every one and the oracle's facts |
| The owner-run `ingest` check passed on four empty syncs and six abstentions | It now needs positive evidence: indexed records and the targets' general and restricted items on every platform, answered general questions for both users, a restricted citation for user A, and citations spanning all four platforms |
| Lookup suggestions listed revoked source IDs and locators until the next sync; answers showed checked, allowed and withheld counts | Suggestions are re-checked with the platform; answers say only whether the check ran |
| Propagation was measured from the start of the crawl (a mid-crawl edit showed −60 s) and an old item that merely became visible counted as an overdue update | Measured from the end of the crawl, and only for items modified since the previous sync |
| A user-only audit search dropped a stopped query that had no document decisions; the page had no next-page control | With no item filter, the search matches by user and time alone; the page pages through `next_cursor` |
| Restricted records used up the live-evidence bound before they were dropped, and that character bound did not guarantee the request fit the provider's byte cap | Restricted records are skipped first, and evidence is sized by the provider's own request body |
| A missing witness key silently disabled the witness | Startup fails when a witness is configured or already in use but its key is missing |
| A record's first paragraph could be taken as its title, quoting unrelated passages with it | Only a real heading or table header can make a record the subject of a question |

Not changed: each audit write re-reads the witness file, which is linear in history and acceptable
at demo scale only, and Jira's per-user preflight is tested against mocks only. Live acceptance on
the real accounts is still the owner's step.

---

## 4. Required attachments — status

| Required item | Status | Location / note |
|---|---|---|
| Project title | **Ready** | §1 |
| Short blurb (<10 words) | **Ready** | §2 (8 words) |
| Project description | **Ready** | §3 |
| Cover image, 16:9 | **Ready** (required by brief p. 35) | Design refreshed 14 October 2026. **Preferred upload, exact 16:9**: [`cover-16x9-768x432.png`](cover-16x9-768x432.png); compact: [`cover-16x9-384x216.png`](cover-16x9-384x216.png). Recommended-size alternatives: [`380×216`](cover-16x9-380x216.png), [`760×432`](cover-16x9-760x432.png) (95:54, slightly different from 16:9). |
| Architecture + trust-boundary diagram | **Ready** | [`architecture-trust-boundary.png`](architecture-trust-boundary.png) / [SVG](architecture-trust-boundary.svg) |
| Demo walkthrough | **Ready** | [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) (long form: [`docs/demo.md`](../demo.md)) |
| Source code (GitHub repo) | **Not yet public** | <https://github.com/Snowfishh/Seaglass_V2> (to be made public). Publish `main` only. Documents written before 15 October 2026 cite earlier commit hashes; the [commit map](../reviews/assistant-attribution-2026-10-15/commit-map.txt) gives the current ones. Before submitting, confirm that the exact submitted commit is publicly readable while signed out. The older source packages built locally under the Git-ignored `artifacts/` folder (28 Sep 2026) are superseded by the repository itself. |
| Conversation history | **Satisfied: authentic export** | [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md) (6 real sessions) |
| ≥3 chat screenshots | **Open, pending** | [`chat-proof/excerpts/`](chat-proof/excerpts/) holds 3 authentic *transcript exports* (not UI screenshots); organiser acceptance unknown |
| Demo video (optional, 5–8 min) | Not produced | Script available in [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) |
| Live URL (optional) | Not published — prepared only | By default the application accepts loopback requests only. An opt-in hosted demo mode (`ASPIRE_HOSTED_DEMO=true`, [deploy note](../../deploy/huggingface/README.md), [security notes](../security.md#hosted-demo-mode-opt-in)) can run it as a Hugging Face Docker Space. That mode accepts the listed host only, runs the offline provider over the fictional fixture, and keeps the CSRF and HTTPS Origin checks behind the proxy. All visitors share one instance: revocation, sync and upstream-change actions are global and visible to everyone, the audit log records every visitor's queries, and all state resets on restart. Not deployed; the Docker image has not been built |

**Why the screenshot row is still open.** Product-use proof has to be *authentic*. The real
conversation logs **are** available locally and were exported verbatim (item 1). The row itself
asks for "screenshots of your chat logs", which means the chat surface. The three images supplied
are faithful renders of the real transcript, clearly labelled as exports. Swapping in application
screenshots or manufacturing chat images would be fabrication, and that has **not** been done.

**Evidence links for reviewers.** Historical `artifacts/` and `var/` references point to local,
Git-ignored evidence, not to files in the repository. The current source code and test fixtures
are all in the repository, and the [current verification report](../reviews/submission-checklist-2026-10-13/README.md)
states what was re-run. That does not independently verify historical live results or complete
pending human acceptance.

## 5. Review history — 28 September 2026

<details>
<summary>Historical technical review and scoped human findings</summary>


*Historical record. Current figures are in §3.4 and current attachment status is in §4; the
`artifacts/` paths below are local, Git-ignored evidence and are not in the repository.*

This addendum superseded the earlier current-status metrics at the time; dated earlier evidence remains history.
The audited suite passes **436 tests**, with **91.72%** statement coverage including evaluation
code (harness 85.95%, release gate 95.74%). Offline policy evaluation is 22/22; lexical top-5
8/12. Simulated grounding is 3 cases / 5 claims / 5 supported / 0 unsupported / 1 abstention,
with all live fields null. Playbook 1.4.0/schema 2 has 16 valid attacks, 4 benign controls,
1 unscored limitation and 1 invalid control. Availability loss remains 2/3.

Current raw evidence: `artifacts/redteam-prompt4-2026-09-28/audited/clean-final/` contains the
aggregate and per-case companion; `api-rehearsal.json` retains actual loopback HTTP and audit rows.
Human findings remain pending. The six-session history is present; **the chat-screenshot item stays open**
until the account holder provides at least three literal chat-surface screenshots. Transcript
exports and Seaglass screenshots are not substitutes. Live acceptance is unverified; product-use
proof is incomplete; **submission status is not ready**.

The new source manifest and package live under `artifacts/redteam-prompt4-2026-09-28/`, with
`package-summary.json` outside the archive recording its hash and size. Previous packages are
preserved. The tarball does not ship its own byte size. Nothing is pushed, deployed, published
or submitted. See stage report §18 and Prompt 5 in `docs/workbuddy-red-team-prompt-sequence.md`.


### Prompt 4 human findings and final snapshot — 2026-09-28

The account holder reviewed both packets: **A/B/C/D are scoped human passes**. Original
findings and follow-up findings are preserved in `artifacts/redteam-prompt4-2026-09-28/`
(`HUMAN-FINDINGS-2026-09-28.md`, `HUMAN-FOLLOWUP-FINDINGS-2026-09-28.md`). D covers this
HTTP unsupported-claim refusal; B covers one synthetic extractive normal HTTP request; C covers
the same packet's pre/post read. The latest closing addendum documents the packet dependency
locally and awaits any human expansion of C. These passes do not establish synthesis quality,
live acceptance, audit completeness or independent checkpoint/key custody.

The authoritative code verification is `artifacts/redteam-prompt4-2026-09-28/final-reviewed/`:
**438 passed / 91.73% statement coverage**, **58 focused tests**, Ruff and `pip check` exit 0.
The release gate and its per-case companion are in `final-reviewed/clean-final/`. The companion
now reports denominators (22 declared / 21 valid executed / 1 invalid) and each query's request ID
and audit metadata. RT-007 remains unexecuted; attachment carriers are uncovered. RT-016/018
remain measured availability losses. One ingestion seed and no action-tool surface remain explicit
limits. Playbook 1.4.0/schema 2 and the attack-only denominators are unchanged.

`api-followup-audited.json` is a separate synthetic loopback HTTP execution: one normal
`POST /api/queries` returned 200 with permitted citations; a saved packet returned 200 before
revocation and 404 afterward; the refusal returned 502 with stored `error_code: unsupported_claim`.
All 29 local tenant audit rows are retained, including metadata and surrounding requests.
`verify-local-audit.py` reproduces the local HMAC check. **Completeness remains unproven**; there is
no independent checkpoint. Packet audit rows still omit the target packet ID; the client trace
records the target URL. Neither the normal HTTP control nor RT-021 establishes synthesized-answer
quality. RT-009 and the HTTP refusal are different executions with different request IDs.

The final isolated implementation defect failed on RT-009; all copied source hashes were restored
and the restored-copy gate passed (`final-defect-record.json`). The Python `NetworkGuard` is an
IP-socket connect guard, not process-wide isolation. Promptfoo remains `not_run` because an approved
pinned dependency path is absent and exact-runner egress is unverified.

Four states: **simulated implementation — bounded local contracts verified; live acceptance —
unverified; product-use proof — incomplete; submission status — not ready**. The six-session export
exists; **at least three literal CodeBuddy/WorkBuddy chat-surface screenshots are still missing**.
The three supplied images were inspected: their banners identify rendered transcript exports, so zero qualify as literal chat-surface screenshots. G0/G4/G5 acceptance gaps remain open.
Final manifest/package: `artifacts/redteam-prompt4-2026-09-28/source-manifest.json` and
`github-package/aspire-internal-brain/`; archive bytes/hash appear only in the external
`package-summary.json`. Previous packages and historical sections are preserved. Nothing was
pushed, deployed, published or submitted.

</details>

## Asset regeneration

Run `python docs/submission/render_assets.py` from an environment with local Playwright and
Chromium. It renders the committed SVGs at all four cover sizes and the diagram without
rewriting their layouts. The older ignored `var/render-submission-assets.py` contains a stale
template and must not be used to regenerate these assets.

The cover SVGs embed the sea-glass artwork generated with the built-in image tool and retain
editable text. The design prompt specified a navy background, four glass document tiles
connected to a central shield, empty space for the title, and no generated text or logos.
Both SVGs and all four PNG sizes use the same refreshed design.
