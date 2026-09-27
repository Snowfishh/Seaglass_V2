# Submission package — Aspire Internal Brain

This is the reviewable page-35 package for the Aspire challenge
(*The Internal Brain — Building a Context-Aware Enterprise Knowledge System with RBAC, Security
Logging & Audit Trail*, `project requiement.pdf` pp. 15–19; submission rules pp. 35–38).

Everything below is **prepared locally and not published**. No remote push, deployment or
submission has been performed. Page 35 carries **two separately Required proof items**, which are
distinct from its general proof gate:

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

**Business architecture.** A single governed path: *ask → authorize → scope → retrieve → rank →
budget → compose → gate → release → audit*. Each stage has one owner module and one failure mode,
and every stage is observable in the answer packet so a reviewer can see what happened without
reading code.

**Technical architecture.** FastAPI + Pydantic + SQLite/FTS5 + Jinja2, one local process, four
simulated platforms, no external model or platform API connected. The full layered view, including
the three trust boundaries, is in
[architecture-trust-boundary.svg](architecture-trust-boundary.svg)
(rendered: [PNG](architecture-trust-boundary.png)). The layers are:

1. **Sources** — four platforms, four permission models, simulated.
2. **Ingestion & index** — per-platform adapters, a unified FTS5 index that keeps the ACL beside
   every record, tombstones/revisions as explicit state, and a declared freshness budget.
3. **Authorization & retrieval** — identity and roles read server-side at query time; a tenant/ACL
   predicate that runs *before* ranking and top-k; question-driven routing; a half-open event-time
   window; a per-platform cap applied **after** scope so it cannot hide a recent match behind older
   ones; deterministic cross-platform ranking; and a bounded context budget that records its drops.
4. **Provider & release** — `offline_extractive` (default) quotes permitted evidence;
   `fake_grounded` composes from permitted evidence only; a live runtime is refused unless it is
   both enabled and entitled. A claim is released only as an **exact contiguous span of one cited
   source's text**; otherwise the answer is refused, no packet is written and no evidence is
   released.
5. **Audit & governance** — a per-tenant HMAC-SHA256 chain, AES-GCM protected payloads,
   tenant-scoped retention over encrypted payloads only, checkpoint anchoring that reports
   `chain_valid` separately from `completeness_unproven`, and an officer inquiry that reconstructs
   and searches protected queries with signed, tenant- and filter-bound pagination.

**How prompts drive the generation.** Prompting appears at two distinct levels, and they must not
be conflated:

- *Product level (the system's own instructions).* The grounded mode is driven by a constrained
  composition instruction whose rules are structural, not stylistic: reason only over the evidence
  blocks provided; every sentence must be traceable to exactly one cited source; introduce no new
  entity, number or relationship; emit an explicit notice when permitted evidence is insufficient
  rather than filling the gap. Those rules are then **enforced after generation** by the
  exact-cited-span gate, so the instruction is a first-line control and the gate is the backstop —
  a prompt alone is never treated as a guarantee.
- *Development level (how this project was built).* Development was driven by WorkBuddy/CodeBuddy
  prompts, recorded in [`prompt.md`](../../prompt.md) and
  [`docs/workbuddy-next-prompt.md`](../workbuddy-next-prompt.md). The working pattern was: state the
  requirement and its evidence, require a PDF-to-evidence cross-check before implementation, demand
  tests that fail for the right reason before a fix, and require the report to be updated after each
  milestone. That prompt discipline is itself part of the submission — see
  [CHAT-PROOF-INSTRUCTIONS.md](CHAT-PROOF-INSTRUCTIONS.md).

**Key design trade-offs** (also on the diagram):

| Trade-off | Choice made | Cost accepted |
|---|---|---|
| Claim support: lexical overlap vs exact quotation | Exact contiguous cited span | Paraphrase that a reader would accept is **refused** — lower recall, no false support |
| Pre-provider filtering vs post-filtering | Filter before the model | Requires permission state at query time; more work per request |
| Retrieval breadth vs a hard cap | Cap applied **after** event-time scope | A cap can never hide recency, but a very large permitted set is still truncated (and says so) |
| Simulated vs live integration | Simulated, with the live path refused rather than faked | No live latency, entitlement or model-quality claim can be made |
| Audit "valid" vs "complete" | Report both, never merge | Reviewers see `completeness_unproven` where a weaker system would claim completeness |

### 3.4 Business value

**Measured in this checkout** (denominators stated; re-runnable from the repository):

| Measure | Result | Denominator / basis |
|---|---|---|
| Automated tests passing | **391** | full suite, 0 failures |
| Statement coverage over `aspire_brain` | **92.72 %** | whole package (floor 80 %) |
| Permission/leakage regression tests | **55** new | 49 finding regressions + 6 audit/retention |
| Deterministic adversarial seed suite | **12 cases** — 11 valid, 1 deliberate invalid control | `eval/redteam/`; 9 valid attacks, 2 benign controls, 0 benign false positives |
| Adversarial outcomes observed | 4 `attack_not_retrieved`, 3 `attack_retrieved_but_blocked`, 2 `attack_succeeded` | both `attack_succeeded` cases are recorded open gaps (RT-009, RT-011) |
| Offline retrieval evaluation | **8 / 12** cases | `evaluate --offline` (22/22 labelled cases passed) |
| Grounding evaluation | 5 supported, 0 unsupported, 1 abstention | `{cases: 3, claims_evaluated: 5}` |
| Officer inquiry traversal | every match, no loss/duplication | paged against a >100-match fixture |
| Revoked-source disclosure | 0 source IDs survive in answer, citations, time-scope or budget metadata | regression fixture |
| Loopback API rehearsal | 3 / 3 as expected | cross-tenant sentinel, revocation/saved-packet read, forged citation on `/api/queries` |

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

**Honest scope statement.** All of the above is a **simulated, local** result. No live platform
connector, no live propagation latency, no entitled model runtime and no organiser acceptance has
been established. The live provider is recorded as `not_run` with null fields.

---

## 4. Required attachments — status

| Page-35 item | Status | Location / note |
|---|---|---|
| Project title | **Ready** | §1 |
| Short blurb (<10 words) | **Ready** | §2 (8 words) |
| Project description | **Ready** | §3 |
| Cover image, 16:9 | **Ready** | Recommended size [`cover-16x9-380x216.png`](cover-16x9-380x216.png) (95:54 — the PDF's recommended size, *not* exactly 16:9); **exact 16:9**: [`cover-16x9-384x216.png`](cover-16x9-384x216.png), [`cover-16x9-768x432.png`](cover-16x9-768x432.png) |
| Architecture + trust-boundary diagram | **Ready** | [`architecture-trust-boundary.png`](architecture-trust-boundary.png) / [SVG](architecture-trust-boundary.svg) |
| Demo walkthrough | **Ready** | [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) (long form: [`docs/demo.md`](../demo.md)) |
| Source code (GitHub repo) | **Prepared locally, not published** | `artifacts/g5/github-package/` (140 files on disk; manifest lists 139) + `aspire-internal-brain-src.tar.gz` (byte size in `PACKAGE-MANIFEST.json`) |
| Conversation history | **Satisfied — authentic export** | [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md) (6 genuine sessions) |
| ≥3 chat screenshots | **Open — pending** | [`chat-proof/excerpts/`](chat-proof/excerpts/) holds 3 authentic *transcript exports* (not UI screenshots); organiser acceptance unknown |
| Demo video (optional, 5–8 min) | Not produced | Script available in [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) |
| Live URL (optional) | Not published | A localhost-only review server is running; a public link requires authorization |

**Why the screenshot row is still open.** Product-use proof must be *authentic*. The genuine
conversation logs **are** available locally and were exported verbatim (Item 1). The literal
"screenshots of your chat logs" row asks for the chat surface itself; the three images supplied
are faithful renders of the authentic transcript, explicitly labelled as exports. Substituting
application screenshots or manufacturing chat images is fabrication and is **not** done.
