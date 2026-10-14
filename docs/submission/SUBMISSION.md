# Submission package — Aspire Internal Brain

This is the reviewable submission package for the Aspire challenge
(*The Internal Brain — Building a Context-Aware Enterprise Knowledge System with RBAC, Security
Logging & Audit Trail*: section 4, "The FinTech Track", of the participant brief; submission rules
are in its section 8, "Project Submission Requirements").

This package is **prepared locally**. This audit did not publish, deploy or submit it.
Public repository access and the current remote commit could not be independently confirmed;
verify them before submission. The submission rules carry **two separately Required proof items**, which
are distinct from their general proof gate:

- **Conversation History — satisfied** by an authentic export of the six genuine development
  sessions (`chat-proof/conversation-history/`).
- **≥3 chat-log screenshots — still open.** Three *transcript exports* exist
  (`chat-proof/excerpts/`), each labelled as an exported transcript rather than a UI screenshot;
  whether the organiser accepts them for this row is **unknown**. See
  [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md).

The submission therefore remains **incomplete**.

---

## 1. Project title

**Aspire Internal Brain**

## 2. Short blurb (hard limit: under 10 words)

> Unified answers across four platforms — permission-scoped and audited.

*8 words.* Count: Unified(1) answers(2) across(3) four(4) platforms(5) permission-scoped(6)
and(7) audited(8).

## 3. Project description

### 3.1 Project overview — target scenarios, users, value proposition

**Target scenarios.** A mid-to-large engineering organisation stores the same incident in four
places at once: a Jira ticket, a Confluence runbook, a Slack thread and a Drive postmortem — each
with a different permission model, a different freshness, and no shared search. The system answers
natural-language questions by assembling context **across** those platforms while refusing to
expose anything the asker may not read.

**Users.** Three roles, with the permissions of each modelled explicitly:

| User | What they need | What the system must not do |
|---|---|---|
| Backend engineer | Status of a migration project plus blockers raised in Slack last week | Return threads from private channels they are not in |
| Contractor / external | A general answer that does not depend on restricted material | Confirm or deny that a restricted security report exists |
| Compliance officer | Reconstruct what any user asked, what was retrieved on their behalf and what was answered | Grant ordinary knowledge access merely because they hold an audit role |

**Value proposition.** The scarce asset is not retrieval — it is *permission-correct* retrieval
with a defensible record. The system makes the authorization decision a first-class, auditable
object: every source-derived field in an answer is derived from an authorized record set, and every
query attempt and outcome is written to a tamper-evident chain.

### 3.2 Real-world scenario insights — pain points, audience, core problems

**Source of the pain points.** Taken from the challenge statement itself, which reports that
employees of the modelled company "waste an estimated 30% of their workweek searching for
information" and that a 3 AM incident responder must cross-reference four systems with four
permission models. **That 30% figure is the challenge statement's premise, not a measurement made
by this project** — see §3.4 for what this project actually measured.

**Target audience.** Platform/security engineering teams at companies with heterogeneous SaaS
footprints; secondarily, compliance and internal-audit functions who currently cannot answer
"what did user X access last week" without manual log archaeology.

**Core problems solved.**

1. **Permission semantics differ per platform and must not be flattened.** Confluence is
   space+page, Jira is project-role-issue, Slack is channel-membership, Drive is file/folder-user.
   The ingestion layer keeps these differences rather than collapsing them into one ACL column.
2. **Retrieval must filter *before* the model.** Otherwise the model can leak — or be
   prompt-injected by — content the asker may not read.
3. **Permission can change between ingestion and query.** A revocation must not leave
   stale-permitted content reachable, including through a previously saved answer packet.
4. **A confident model can invent content it was never given.** The system therefore gates each
   claim against its cited source and refuses the whole answer when a claim is unsupported.
5. **An audit log that cannot prove it is complete is not an audit log.** The system separates
   "the chain is valid" from "the chain is complete" and never presents the former as the latter.

### 3.3 Comprehensive solution design

**Business architecture.** The successful path is *ask → resolve identity → authorize and retrieve
→ project bounded context → call provider → treat output as untrusted → validate and recheck →
commit audit event and packet atomically → return*. The audit path also receives ingress denials,
query attempts, controlled aborts and provider failures. Failed requests have no answer packet to
inspect; their safe audit events and HTTP result are separate evidence.

**Technical architecture.** FastAPI + Pydantic + SQLite/FTS5 + Jinja2 run locally. The travel-policy
route uses SQLite/FTS5; the four-platform simulator has a separate in-memory index and simulated
sync. Offline connector fixtures and mock HTTP adapters now exercise that platform path. A separate
owner-run, read-only check on 14 October 2026 confirmed the four adapters against real test
accounts with per-user tokens (16/16, restricted items refused to the second user; see the
[live access check](../reviews/live-access-2026-10-14/README.md)); the adapters are still not wired
into the application. Local providers remain the default. An opt-in `live_grounded` mode
connects Groq for fictional demo data only: the model selects which permitted evidence sentences
answer the question, and the answer is rebuilt from those exact sentences. An earlier, separately
injected 5E service path made fixed fictional Groq requests. The directed execution
view and its three labelled boundary crossings are in
[architecture-trust-boundary.svg](architecture-trust-boundary.svg)
(rendered: [PNG](architecture-trust-boundary.png)). Read it as follows:

1. **Outside the service** — the browser supplies an untrusted request. Confluence, Jira, Slack
   and Drive are external source platforms. The read-only connectors have been checked against
   real test accounts with per-user tokens, but they are not wired into the application, so there
   is no live ingestion, sync or revocation edge. The current source path uses local simulated
   fixtures and mock HTTP reads inside the controlled process. At trust boundary 1, source prose
   is data; controlled metadata sets ACLs and approval.
2. **Inside the service** — session/CSRF checks and server-owned identity precede authorization.
   The service uses a local FTS5 policy store and a separate in-memory platform snapshot;
   platform ACLs remain distinct, tombstones/revisions are explicit simulated state, and the
   declared 3600-second freshness budget is measured on a simulated clock. Bounded HTTP connector
   reads have been rehearsed with mock transport; live sync and revocation are unverified.
   In four-platform retrieval, the tenant/ACL predicate runs *before* ranking and top-k.
   Question-driven routing selects platforms; a half-open event-time window scopes records;
   a per-platform cap applies **after** scope so it cannot hide a recent match behind older
   ones. Cross-platform ranking is deterministic, and a bounded context budget records its drops.
3. **Provider call / trust boundary 2** — the service projects a question and bounded permitted
   evidence. `offline_extractive` (default) quotes permitted evidence;
   `fake_grounded` composes from permitted evidence only; neither makes an external call. The
   opt-in `live_grounded` provider is built only for the approved Groq target and limits, with a
   key file outside the project and a file-locked spend ledger; anything else is refused before a
   request. It sends only the question and permitted evidence split into numbered sentences, never
   identity, tenant, roles, ACLs, audit or document identifiers, or locators; on the platform path,
   restricted-classified sources are withheld. Every attempt is reserved in the ledger before any
   byte is sent, and there are no retries. The earlier, separately injected 5E preflight sent a
   fixed fictional question, permitted source text and citation ID, system instruction, model
   settings and schema to Groq. It observed one corrected HTTP 200 and readable packet, with human
   acceptance pending.
4. **Provider return / trust boundary 3** — the returned answer and citation IDs are untrusted.
   From `live_grounded`, the model returns only sentence numbers or an abstention; the provider
   rebuilds the answer from those exact sentences behind service-authored labels, so model-written
   prose never reaches the user. An abstention releases no model-selected sentences: on a
   `needs_review` or `insufficient_evidence` decision the service releases its own deterministic
   decision with no citations, and an answerable decision still fails closed.
   The service validates the typed output and citation membership; each claim must match a
   **complete cited source sentence or complete colon tail**, normalized for case and whitespace.
   It rechecks access before an atomic packet/audit write. A timeout, spend-limit refusal,
   invalid selection or citation, or unsupported claim fails before packet persistence. This gate
   cannot retract already transmitted provider input.
5. **Audit on every path** — ingress identity/CSRF refusals write `access_denied`; query attempts
   precede retrieval. On `QueryService` provider/gate failures, `provider_error` precedes
   `query_aborted`; the four-platform simulator records `query_aborted` without that extra event.
   Success commits `query_completed` and the packet in one transaction before return. If audit
   persistence itself fails, the service refuses release and cannot guarantee the missing event.
   Governance uses a per-tenant HMAC-SHA256 chain, AES-GCM protected payloads,
   tenant-scoped retention over encrypted simulated-case payloads only, local checkpoints that
   report `chain_valid` separately from `completeness_unproven`, and an officer inquiry for
   protected simulated queries with signed, tenant- and filter-bound pagination. Ordinary saved
   packets are plaintext SQLite records outside that encrypted-payload retention policy.

**Status of the intended live system (14 October 2026).** The opt-in `live_grounded` provider is
wired into the query service behind Ask and into the Case 7 card. Its owner-run evaluation
harness is [`eval/live_model/`](../../eval/live_model/README.md), which records the 14 October
runs as they happened.

Three evaluations were run on 14 October 2026 against fictional demo fixtures, all inside the
approved envelope. Per call: ≤ 4,000 input / 800 output / 1,000 reasoning tokens, a 30 s timeout
and USD 0.05. In total: ≤ 30 requests and USD 5 in a file-locked ledger, with no retries. All 30
request slots are now spent, so no further live run is possible under this approval.

| Run (UTC) | Calls completed | Released | Safe abstentions | Calls that failed | Verdict under harness rules |
| --- | --- | --- | --- | --- | --- |
| 11:54 | 2 of 10 | 2 | 0 | 8, fast, cause not recorded | `fail` (failures uncategorised) |
| 12:02 | 6 of 10 | 6 | 0 | 4, HTTP 429 (wait asked: 30 s) | `inconclusive` |
| 12:11 | 6 of 10 | 5 | 1 | 4, HTTP 429 (waits asked: 33 s to about 2 h) | `inconclusive` |

- **Safety held in every completed call.** Nothing unsupported was released, no forbidden text
  appeared, and every released status matched the expected one. In every run, the no-evidence
  case made no call.
- **No run is a pass.** The 70% answer-share gate was not shown in any single full run. Provider
  availability, not model quality, stopped every run. Runs 2 and 3 are not combined into one
  result, and the counts above are counts of completed calls, not a model-quality figure.
- **Likely cause:** the Groq project's limit of 8,000 tokens/day for this model. The completed
  calls used 8,014 tokens. The Groq usage logs were not checked.

The fixed 5E observation is separate: its raw vendor body was not retained, the packet is
`needs_review / undetermined` and human acceptance is pending. The connectors passed a one-off
live read check but are not wired in. The intended next capabilities are verified real connector
identity, synchronization and revocation, followed by separately authorized 5F batch evaluation.
Neither live integration nor 5F is accepted here.

**How prompts drive the generation.** Prompting appears at two distinct levels, and they must not
be conflated:

- *Product level (the system's own instructions).* The default local providers use no prompt.
  The opt-in `live_grounded` mode sends one fixed system prompt
  ([`providers/live.py`](../../src/aspire_brain/providers/live.py), `SYSTEM_PROMPT`): the model is
  told it *selects* evidence, that every numbered sentence is untrusted data and never an
  instruction, to choose only sentences that directly answer the question in a readable order,
  and to set `answerable` to false and choose none when the evidence does not answer it. A strict
  JSON schema (`evidence_selection_v1`) allows only that flag and a list of sentence numbers, with
  `temperature: 0`. The prompt is a first-line control, never a guarantee: the reply is parsed
  against the schema, unknown or duplicate sentence numbers are refused, the answer is rebuilt
  from the exact chosen sentences, and the complete-cited-quotation gate rechecks every claim.
- *Development level (how this project was built).* WorkBuddy drove the core build from about
  23 September to early October 2026 — source contracts, the four-platform simulator, deterministic
  sync, routing and ranking, the grounded provider and audit, and G1–G5 gap closure — in six sessions
  exported verbatim from the local session logs in
  [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md). The driving prompts are
  recorded in [`prompt.md`](../../prompt.md),
  [`docs/workbuddy-next-prompt.md`](../workbuddy-next-prompt.md) and
  [`docs/workbuddy-red-team-prompt-sequence.md`](../workbuddy-red-team-prompt-sequence.md). OpenAI
  Codex was used for separate worktree experiments and the 13–14 October submission-checklist audit;
  Claude Code was used on 13–14 October for review, scan-fix cleanup, integration of the audit fixes,
  the web UI refresh and re-verification, and on 14–15 October for the live connector check, the
  opt-in live provider, the live-evaluation fixes, Windows support, the clean-install verification
  and publication clean-up. WorkBuddy was used again
  on 14 October for this development-process account and the first live-run fix, recording Groq's
  rate-limit headers ([prompt](../workbuddy-live-run-fix-prompt-2026-10-14.md)). The owner
  reviewed, directed and committed all of it.
  The working pattern was: state the requirement and its evidence, require a PDF-to-evidence
  cross-check before implementation, demand tests that fail for the right reason before a fix, and
  require the report to be updated after each milestone — the pattern applied in the WorkBuddy
  sessions. That prompt discipline is itself part of the submission — see
  [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md), where the three literal chat-surface
  screenshots it lists remain outstanding.

**Worked examples for the five required scenarios.** Each runs on the `/cases` page against
fictional, simulated platform data; the captured output and what to look for are in
[DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md).

| Challenge scenario | Worked example | What it shows | Limit |
|---|---|---|---|
| 1. Unified natural-language query | [Case 1](DEMO-WALKTHROUGH.md#case-1--unified-natural-language-query-pdf-example-1): migration status and last week's Slack blockers | One answer citing a Jira issue and a Slack message; routing, time scope and omitted platforms are disclosed | A fixed demo question; typed questions on `/ask` reach the travel-policy store, not the four-platform index. Routing is a keyword heuristic |
| 2. Data freshness | [Case 2](DEMO-WALKTHROUGH.md#case-2--data-freshness-pdf-example-2): the 13:00 runbook update | The updated runbook with the new failover step, synced in 600 s against a declared 3,600 s budget; [Case 6](DEMO-WALKTHROUGH.md#case-6--supplemental-google-drive-deletion-and-a-real-late-sync) reports an over-budget sync as a failure | Simulated clock and sync; no live ingestion. The earliest correct answer is reported as unknown, not assumed |
| 3. Permission enforcement (negative case) | [Case 3](DEMO-WALKTHROUGH.md#case-3--correct-permission-enforcement-negative-case-pdf-example-3): the contractor and the Q3 breach report | An abstention that neither reveals nor confirms the restricted report | Simulated platform ACLs |
| 4. Live permission change | [Case 4](DEMO-WALKTHROUGH.md#case-4--live-permission-change-handling-pdf-example-4): revoke, then reopen a saved answer | The saved packet is denied after revocation; no revoked source survives in any field | Revocation is simulated, not received from a platform |
| 5. Audit inquiry | [Case 5](DEMO-WALKTHROUGH.md#case-5--audit-inquiry-pdf-example-5): what `employee` accessed in the payment-gateway Confluence space | The exact question, retrieved IDs, answer and per-document decisions, with timestamps | One platform per inquiry; chain validity is reported separately from unproven completeness |

**Key design trade-offs** (also on the diagram):

| Trade-off | Choice made | Cost accepted |
|---|---|---|
| Claim support: lexical overlap vs bounded quotation | Complete cited sentence or complete colon tail | Paraphrase that a reader would accept is **refused**; this checks quotation boundaries, not source truth or entailment |
| Pre-provider filtering vs post-filtering | Filter before the model | Requires permission state at query time; more work per request |
| Retrieval breadth vs a hard cap | Cap applied **after** event-time scope | A cap can never hide recency, but a very large permitted set is still truncated (and says so) |
| Simulated vs live integration | Local baseline by default; an opt-in live model that only selects permitted sentences, on fictional data; a separate fixed 5E synthetic provider control and a separate 16/16 live connector read check | Live reads are verified only for single known items; no live ingestion, propagation, general model-quality or production-capacity claim can be made |
| Audit "valid" vs "complete" | Report both, never merge | Reviewers see `completeness_unproven` where a weaker system would claim completeness |

### 3.4 Business value

**Measured in this checkout** (denominators stated; re-runnable from the repository). The test
count and coverage rows were verified on 14 October 2026 by exporting the commit with
`git archive` and installing it fresh from `requirements.lock` under Python 3.14.7; full browser
E2E was not run (see the [clean-install verification](../reviews/freeze-2026-10-14/README.md)).
The other rows come from the 27–28 September simulated snapshot and have not been re-run since:

| Measure | Result | Denominator / basis |
|---|---|---|
| Automated tests passing | **954** unit/integration + **93** red-team | 0 failures on a fresh install of the exported commit (14 Oct 2026); no full browser E2E |
| Statement coverage over `aspire_brain` | **92.37 %** | whole package, all 1,047 tests (floor 80 %), 14 Oct 2026 |
| Live connector read check | **16 / 16** | 4 platforms × 2 users × 2 items, real test accounts, per-user tokens; B refused all 4 restricted items (14 Oct 2026) |
| Permission/leakage regression tests | **55** new | 49 finding regressions + 6 audit/retention |
| Deterministic adversarial seed suite | **22 cases** — 21 valid, 1 deliberate invalid control | `eval/redteam/` (playbook 1.4.0, schema 2); 16 valid attacks, 4 benign controls, 1 unscored limitation, 0 benign false positives |
| Adversarial outcomes observed | 4 `attack_not_retrieved`, 8 `attack_retrieved_but_blocked`, 0 `attack_succeeded`, 1 `availability_preserved`, 2 `availability_degraded`, 1 `ingestion_inert` | RT-009 is an **expected block**; RT-011 is an unscored `limitation`; RT-016/RT-018 are **measured availability degradation**, never a blanket "blocked" |
| Deterministic local release gate | **9 / 9 hard checks pass**, exit 0, `network_attempts []` | `eval/redteam/release_gate.py` (1 reviewed noncritical threshold: `availability_loss` 2/3); a clean run passes and an induced implementation defect fails with an RT-009 packet |
| Offline retrieval evaluation | **8 / 12** cases | `evaluate --offline` (22/22 labelled cases passed) |
| Grounding evaluation | 5 supported, 0 unsupported, 1 abstention | `{cases: 3, claims_evaluated: 5}` |
| Officer inquiry traversal | every match, no loss/duplication | paged against a >100-match fixture |
| Revoked-source disclosure | 0 source IDs survive in answer, citations, time-scope or budget metadata | regression fixture |
| Loopback API rehearsal | 3 / 3 as expected | cross-tenant sentinel, revocation/saved-packet read, forged citation on `/api/queries` (raw audit rows with request ID, sequence and event type retained) |

**Clearly defined impact (hypotheses, not measured here).** The following are proposed benefits and
are **explicitly hypotheses** — this project has not run a user study and cannot quantify them:

- *H1 — search-time reduction.* If the challenge statement's "30 % of the workweek searching"
  premise holds for a target organisation, permission-correct cross-platform answers could recover a
  material share of it. **Unmeasured.**
- *H2 — fewer permission incidents.* Filtering before the model should reduce answer-leakage
  incidents relative to post-filtering designs. **Unmeasured; no incident data exists.**
- *H3 — audit effort reduction.* Reconstructing an access question via officer inquiry replaces
  manual log archaeology. **Unmeasured; no baseline captured.**
- *H4 — disclosure-quality gain.* Distinguishing "unknown" from "inaccessible" outward while
  logging the difference internally reduces metadata side-channels. **Demonstrated on a bounded
  local fixture only.**

**Honest scope statement.** Apart from the test, coverage and live connector rows, the §3.4
measurements above describe the earlier **simulated, local** snapshot. The separate fixed 5E synthetic
request is documented under `docs/reviews/stage5e-preflight-2026-10-10/`. No live platform
ingestion, measured live propagation, published live model evaluation or organiser acceptance
has been established. The default local provider path still records live fields as `not_run`.
Two interface limits remain: the four-platform page runs the fixed demo questions above rather
than typed ones, and an officer inquiry covers one platform at a time.

---

## 4. Required attachments — status

| Required item | Status | Location / note |
|---|---|---|
| Project title | **Ready** | §1 |
| Short blurb (<10 words) | **Ready** | §2 (8 words) |
| Project description | **Ready** | §3 |
| Cover image, 16:9 | **Ready — required by brief p. 35** | Design refreshed 14 October 2026. **Preferred upload, exact 16:9**: [`cover-16x9-768x432.png`](cover-16x9-768x432.png); compact: [`cover-16x9-384x216.png`](cover-16x9-384x216.png). Recommended-size alternatives: [`380×216`](cover-16x9-380x216.png), [`760×432`](cover-16x9-760x432.png) (95:54, slightly different from 16:9). |
| Architecture + trust-boundary diagram | **Ready** | [`architecture-trust-boundary.png`](architecture-trust-boundary.png) / [SVG](architecture-trust-boundary.svg) |
| Demo walkthrough | **Ready** | [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) (long form: [`docs/demo.md`](../demo.md)) |
| Source code (GitHub repo) | **Not yet public** | <https://github.com/Snowfishh/Seaglass> (private; update this link if a new repository is used). Publish `main` only. Documents written before 15 October 2026 cite earlier commit hashes. Confirm signed-out public access to the exact submitted commit before submitting. The older locally built source packages under the Git-ignored `artifacts/` folder (28 Sep 2026) are superseded by the repository itself. |
| Conversation history | **Satisfied — authentic export** | [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md) (6 genuine sessions) |
| ≥3 chat screenshots | **Open — pending** | [`chat-proof/excerpts/`](chat-proof/excerpts/) holds 3 authentic *transcript exports* (not UI screenshots); organiser acceptance unknown |
| Demo video (optional, 5–8 min) | Not produced | Script available in [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) |
| Live URL (optional) | Not published | The application accepts loopback requests only, by design; a public link would need a deployment decision |

**Why the screenshot row is still open.** Product-use proof must be *authentic*. The genuine
conversation logs **are** available locally and were exported verbatim (Item 1). The literal
"screenshots of your chat logs" row asks for the chat surface itself; the three images supplied
are faithful renders of the authentic transcript, explicitly labelled as exports. Substituting
application screenshots or manufacturing chat images is fabrication and is **not** done.

**Evidence links for reviewers.** Historical `artifacts/` and `var/` references point to local,
Git-ignored evidence rather than repository attachments. Current source code and test fixtures
are self-contained in the repository; the [current verification report](../reviews/submission-checklist-2026-10-13/README.md) states what was rerun.
This does not independently verify historical live results or complete pending human acceptance.

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
