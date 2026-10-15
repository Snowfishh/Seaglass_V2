# Integration status

The application runs offline by default. Its Confluence, Jira, Slack and Drive sources come from
a fictional fixture, and answers use evidence excerpts or the local grounded provider. Since
15 October 2026 the same four-platform index can instead be filled from real accounts through the
HTTP connectors (`ASPIRE_PLATFORM_SOURCE=connectors`); that path is tested offline against a fake
of all four APIs, and its [owner-run check](../eval/live_platform/README.md) has not been run.
Separately, a read-only [live access check](reviews/live-access-2026-10-14/README.md) on
14 October 2026 confirmed the four HTTP connectors against real test accounts (16/16). See the
[current verification report](reviews/submission-checklist-2026-10-13/README.md) for the
13 October test snapshot. The separate 5E experiment made two bounded synthetic Groq attempts
(HTTP 400, then corrected HTTP 200); it does not establish a general live application path.
The [stage report](stage-report-2026-09-27.md) and dated sections below are historical.
The current red-team playbook is 1.4.0 / schema 2; older versions and counts below describe
their dated snapshots. `artifacts/` and `var/` references are local, Git-ignored evidence,
not repository attachments. Current source and test fixtures are self-contained.

## Organiser requirements

The root `project requiement.pdf`, reviewed on 27 September 2026, contains the Aspire
case on pages 15–19 and submission rules on pages 35–38. Page 35 requires an original
project built with CodeBuddy or WorkBuddy, proof of use, development conversation history
and at least three chat screenshots. It also requires a title, a blurb under ten words,
a project description and a 16:9 cover image. Video and a live project link are optional.

Page 37 also mentions Miora. Until the organiser clarifies the difference, follow the
stricter page-35 wording. The PDF lists 16 October 2026 as submission day; the cutoff
time and timezone remain unknown. Registration, eligibility and acceptance of a simulated
demo still need confirmation. Development-tool credits do not establish access to an
application inference service.

## Before connecting live services

| Item | Current status | Required evidence |
|---|---|---|
| Platform accounts | Test accounts exist on all four platforms; the 14 October read check passed 16/16 | The owner-run integrated check (`eval/live_platform/check.py ingest`) |
| Synchronization | A sync loop every 300 s against a 3,600 s budget, on the fixture or the connectors; propagation recorded in real elapsed time; live propagation not yet measured | `eval/live_platform/check.py freshness` and `revocation` against the real accounts |
| Model service | `offline_extractive` default; local `fake_grounded` mode available; live provider `not_run` | Account-entitled service, current documentation, endpoint, model and authentication method |
| Credits and region | Unverified | Applicable credits, cost limits and processing location |
| Credentials | Local session, audit and payload keys only | Ignored environment settings or a secret manager for an approved live connection |
| Live smoke test | General app path not run; two separate bounded synthetic attempts are recorded in [the experiment review](reviews/stage5e-preflight-2026-10-10/README.md), with human acceptance pending | A separately authorised runtime evaluation with safe result metadata |
| Failure handling | Local tests cover timeouts and invalid output | Bounded transport retries, rate limits and safe error handling |
| Answer quality | Deterministic **complete cited quotation** check over a fake provider (denominator recorded); no live-model result | Claim support, citation accuracy, abstention and failure examples from actual responses |
| Deployment | Local demo only | Production identity, protected storage, removal of demo personas and deployment approval |

Unsupported provider modes return an error. A live provider requires explicit enablement **and** a
confirmed entitlement; without both, construction is refused before any request. The model
interface grants no tools, filesystem access or action execution. Application code controls
permissions and policy outcomes. Citation validation checks IDs **and** whether each claim is an
complete source sentence or complete colon tail (case and whitespace normalised;
a deterministic quotation rule, not semantic entailment). Review
[security boundaries](security.md) before sending information to an external processor.

## Reference history

The earlier 24 September review consulted the [event page](https://luma.com/26fqf3hy),
[CodeBuddy product page](https://intl.cloud.tencent.com/products/acc?lang=en) and
[Hunyuan compatibility examples](https://cloud.tencent.com/document/product/1729/111007).
That review recorded a Hunyuan-to-TokenHub migration notice. These links have not been
rechecked in this documentation edit; verify the current service documentation and
account access before choosing an endpoint or model.

## Next work

Follow the G0–G5 sequence in [the delivery plan](../plan.md). G2 synchronization, G3 question
routing, cross-platform ranking, bounded context and time-scoped retrieval, and G4's
entitlement-gated grounded provider, claim-level support evaluation and protected-audit retention
and search are locally implemented and measured for the simulated contract. A 27 September review
found four reproducible gaps (revoked-source metadata, false claim support, candidate truncation
before time scope, and officer-inquiry truncation); all four are now fixed with regression tests,
plus a retention/completion-claim reconciliation — see §14 of the
[stage report](stage-report-2026-09-27.md). A later pass added a deterministic adversarial seed
suite over both query paths (`eval/redteam/`, playbook 1.2.0, 21 cases: 20 valid and 1 declared
invalid) and reconciled the handoff mismatches — see §15 and the
[boundary map](redteam-boundary-map-2026-09-27.md). A later pass closed the one cross-path gap:
`POST /api/queries` now enforces the same source-derived claim-support release gate as the
simulated path, and RT-009 is an expected block — see §16. A further pass repaired the outcome
oracle (goal-specific, with separate consequence counts and an explicit `limitation` class), moved
the playbook to **1.3.0** (22 cases: 21 valid and 1 declared invalid, plus a new ingestion case
RT-022), and wired it into one deterministic local release gate (`eval/redteam/release_gate.py`) —
see §17. Promptfoo was reviewed but **not run** (`eval/redteam/promptfoo/STATUS.json`). The live
runtime remains `unknown`/`not_run`.

The remaining G5 item is the **mandatory product-use proof** on page 35, which has two separately
Required rows. The conversation history row is now **satisfied** by a verbatim export of six
genuine development sessions; the **minimum-3-chat-screenshots row is still open** because only
labelled transcript exports exist, not literal screenshots of the chat surface. No local tool can
manufacture that proof. The reviewable submission package is prepared. Use the
[WorkBuddy handoff](workbuddy-next-prompt.md) to continue. Publication and submission require
separate authorization.

## Prompt 4 acceptance audit — 28 September 2026

See stage report §18.5 and `docs/g1-access-status.json`: G1–G3 meet bounded simulated criteria;
G0 account/organiser decisions, G4's real model-request criterion and G5 acceptance/proof remain
open. The four states are **simulated implementation**, **live acceptance (unverified)**,
**product-use proof (incomplete)** and **submission status (not ready)**. The genuine six-session
history is present; three literal chat-surface screenshots and attributed human findings have
not yet been received. Account-holder intent is not completed evidence.

Promptfoo is not_run because no approved pinned dependency path exists. Static tests can use
deterministic assertions without a local model, but the exact runner has not been egress-reviewed.
The Python socket guard cannot isolate Node. Nothing was installed, published or submitted.


### Prompt 4 human findings and final snapshot — 2026-09-28

This historical review snapshot is kept once, in section 5 of [SUBMISSION.md](submission/SUBMISSION.md), to avoid divergent copies.

## Historical Groq provider preparation — 28 September 2026

The following records the plan on that date. Current bounded experiment evidence is in
[the later provider review](reviews/stage5e-preflight-2026-10-10/README.md); it does not
provide a general live application path. The local evidence paths below are ignored files.

The account holder selected **Groq only** as the external inference service. Stage 5A is
documentation and read-only reconnaissance: it designs `GroqGroundedProvider` and records the
feasibility assessment, but **implements nothing, installs nothing, retrieves no credential and
makes no inference request**.

- Design: [Groq provider preparation](groq-provider-preparation-2026-09-28.md)
- Machine-readable: acceptance/test matrix (local: `../artifacts/prompt5a-groq-preparation-2026-09-28/acceptance-test-matrix.json`),
  vendor facts (local: `../artifacts/prompt5a-groq-preparation-2026-09-28/groq-vendor-facts-2026-09-28.json`),
  provenance (local: `../artifacts/prompt5a-groq-preparation-2026-09-28/provenance.json`)
- Review packet (**unsigned**): human review packet (local: `../artifacts/prompt5a-groq-preparation-2026-09-28/human-review-packet.md`)

**Model service row, updated only to observed evidence.** Official Groq documentation checked on
28 September lists `openai/gpt-oss-20b` and `openai/gpt-oss-120b` as production and
`openai/gpt-oss-safeguard-20b` as preview. Strict JSON schema is supported by 20B and 120B;
Safeguard is best-effort only. The **account's entitlement, exact rate limits, ZDR setting and
inference region remain unverified**, and no pinned `groq` dependency exists in this checkout, so
the model-service row is still `not_run`. The recommended minimal route is one quotation-only
20B target across stages 5A–5F then 5J, with optional 5G/5H/5I skipped by default.

No acceptance status is upgraded by this stage. G0/G4/G5 remain open for their own remaining
criteria; G4's real synthetic model request is *designed for*, not met. Nothing was pushed,
deployed, published or submitted.
