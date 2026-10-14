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
into the application. A separately injected 5E service path made fixed fictional
Groq requests; the ordinary application provider factory remains offline. The directed execution
view and its three labelled boundary crossings are in
[architecture-trust-boundary.svg](architecture-trust-boundary.svg)
(rendered: [PNG](architecture-trust-boundary.png)). Read it as follows:

1. **Outside the service** — the browser supplies an untrusted request. Confluence, Jira, Slack
   and Drive are intended external source-platform domains; no live source API edge is verified.
   The current source path uses local simulated fixtures and mock HTTP reads inside the controlled
   process. At trust boundary 1, source prose is data; controlled metadata sets ACLs and approval.
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
   `fake_grounded` composes from permitted evidence only. The ordinary `live_grounded` factory
   still refuses construction. The separately injected 5E preflight sent a fixed fictional
   question, permitted source text and citation ID, system instruction, model settings and schema
   to Groq. It observed one corrected HTTP 200 and readable packet, with human acceptance pending.
4. **Provider return / trust boundary 3** — the returned answer and citation IDs are untrusted.
   The service validates the typed output and citation membership; each claim must match a
   **complete cited source sentence or complete colon tail**, normalized for case and whitespace.
   It rechecks access before an atomic packet/audit write. A timeout, invalid citation or
   unsupported claim fails before packet persistence. This gate cannot retract already transmitted
   provider input.
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

**Status of the intended live system (13 October 2026).** The fixed 5E observation does not
validate a general live provider or any platform connector. Its raw vendor body was not retained;
the packet is `needs_review / undetermined` and human acceptance is pending. The intended next
capabilities are verified real connector identity, synchronization and revocation, followed by
separately authorized 5F batch evaluation. Neither live integration nor 5F is accepted here.

**How prompts drive the generation.** Prompting appears at two distinct levels, and they must not
be conflated:

- *Product level (the system's own instructions).* The grounded mode is driven by a constrained
  composition instruction whose rules are structural, not stylistic: reason only over the evidence
  blocks provided; every sentence must be traceable to exactly one cited source; introduce no new
  entity, number or relationship; emit an explicit notice when permitted evidence is insufficient
  rather than filling the gap. Those rules are then **enforced after generation** by the
  complete-cited-quotation gate, so the instruction is a first-line control and the gate is the backstop —
  a prompt alone is never treated as a guarantee.
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
  the web UI refresh and re-verification. The owner
  reviewed, directed and committed all of it.
  The working pattern was: state the requirement and its evidence, require a PDF-to-evidence
  cross-check before implementation, demand tests that fail for the right reason before a fix, and
  require the report to be updated after each milestone — the pattern applied in the WorkBuddy
  sessions. That prompt discipline is itself part of the submission — see
  [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md), where the three literal chat-surface
  screenshots it lists remain outstanding.

**Key design trade-offs** (also on the diagram):

| Trade-off | Choice made | Cost accepted |
|---|---|---|
| Claim support: lexical overlap vs bounded quotation | Complete cited sentence or complete colon tail | Paraphrase that a reader would accept is **refused**; this checks quotation boundaries, not source truth or entailment |
| Pre-provider filtering vs post-filtering | Filter before the model | Requires permission state at query time; more work per request |
| Retrieval breadth vs a hard cap | Cap applied **after** event-time scope | A cap can never hide recency, but a very large permitted set is still truncated (and says so) |
| Simulated vs live integration | Local baseline, a separate fixed 5E synthetic provider control and a separate 16/16 live connector read check | Live reads are verified only for single known items; no live ingestion, propagation, general model-quality or production-capacity claim can be made |
| Audit "valid" vs "complete" | Report both, never merge | Reviewers see `completeness_unproven` where a weaker system would claim completeness |

### 3.4 Business value

**Measured in this checkout** (denominators stated; re-runnable from the repository). The test
count and coverage rows were verified on a clean tracked snapshot on 14 October 2026 under
Python 3.14.2 using shared installed dependencies, not a fresh dependency installation; full
browser E2E was not run (see the [14 October test log](../reviews/live-access-2026-10-14/README.md#test-suite-at-this-commit) and the earlier [checklist verification report](../reviews/submission-checklist-2026-10-13/README.md)). The other rows come from
the 27–28 September simulated snapshot and have not been re-run since:

| Measure | Result | Denominator / basis |
|---|---|---|
| Automated tests passing | **870** unit/integration + **93** red-team | selected suites, 0 failures on clean tracked snapshot (14 Oct 2026); no full browser E2E |
| Statement coverage over `aspire_brain` | **92.48 %** | whole package (floor 80 %), 14 Oct 2026 |
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

**Honest scope statement.** Apart from the 13 October test and coverage rows, the §3.4
measurements above describe the earlier **simulated, local** snapshot. The separate fixed 5E synthetic
request is documented under `docs/reviews/stage5e-preflight-2026-10-10/`. No live platform
connector, measured live propagation, general entitled provider runtime or organiser acceptance
has been established. The default local provider path still records live fields as `not_run`.

---

## 4. Required attachments — status

| Required item | Status | Location / note |
|---|---|---|
| Project title | **Ready** | §1 |
| Short blurb (<10 words) | **Ready** | §2 (8 words) |
| Project description | **Ready** | §3 |
| Cover image, 16:9 | **Ready** | Recommended size [`cover-16x9-380x216.png`](cover-16x9-380x216.png) (95:54 — the PDF's recommended size, *not* exactly 16:9); **exact 16:9**: [`cover-16x9-384x216.png`](cover-16x9-384x216.png), [`cover-16x9-768x432.png`](cover-16x9-768x432.png) |
| Architecture + trust-boundary diagram | **Ready** | [`architecture-trust-boundary.png`](architecture-trust-boundary.png) / [SVG](architecture-trust-boundary.svg) |
| Demo walkthrough | **Ready** | [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) (long form: [`docs/demo.md`](../demo.md)) |
| Source code (GitHub repo) | **Publication verification pending** | <https://github.com/Snowfishh/Seaglass>. The cached local tracking ref is older than the reviewed cleanup branch; live repository reads returned 404 through the connector. Confirm the intended commit and signed-out public access before submitting. The older locally built source packages under the Git-ignored `artifacts/` folder (28 Sep 2026) are superseded by the repository itself. |
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
