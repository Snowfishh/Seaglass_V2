# Integration status

The application runs offline. Its Confluence, Jira, Slack and Drive sources are
simulated, and answers use evidence excerpts or the local grounded provider. No live
platform or model connection has been verified. See the
[stage report](stage-report-2026-09-27.md) for current evidence.

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
| Platform accounts | Access to all four platforms is unknown | Authorised test tenants and verified permission semantics |
| Synchronization | Deterministic simulated create/update/delete/ACL sync with a declared budget; live propagation unmeasured | Create/update/delete and permission changes measured against a stated freshness budget on a live tenant |
| Model service | `offline_extractive` default; local `fake_grounded` mode available; live provider `not_run` | Account-entitled service, current documentation, endpoint, model and authentication method |
| Credits and region | Unverified | Applicable credits, cost limits and processing location |
| Credentials | Local session, audit and payload keys only | Ignored environment settings or a secret manager for an approved live connection |
| Live smoke test | Not run | An authorised synthetic request with safe result metadata |
| Failure handling | Local tests cover timeouts and invalid output | Bounded transport retries, rate limits and safe error handling |
| Answer quality | Deterministic **exact-cited-span** claim-support check over a fake provider (denominator recorded); no live-model result | Claim support, citation accuracy, abstention and failure examples from actual responses |
| Deployment | Local demo only | Production identity, protected storage, removal of demo personas and deployment approval |

Unsupported provider modes return an error. A live provider requires explicit enablement **and** a
confirmed entitlement; without both, construction is refused before any request. The model
interface grants no tools, filesystem access or action execution. Application code controls
permissions and policy outcomes. Citation validation checks IDs **and** whether each claim is an
exact cited span of its source (a deterministic local rule, not semantic entailment). Review
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

## Groq provider preparation — 28 September 2026

The account holder selected **Groq only** as the external inference service. Stage 5A is
documentation and read-only reconnaissance: it designs `GroqGroundedProvider` and records the
feasibility assessment, but **implements nothing, installs nothing, retrieves no credential and
makes no inference request**.

- Design: [Groq provider preparation](groq-provider-preparation-2026-09-28.md)
- Machine-readable: [acceptance/test matrix](../artifacts/prompt5a-groq-preparation-2026-09-28/acceptance-test-matrix.json),
  [vendor facts](../artifacts/prompt5a-groq-preparation-2026-09-28/groq-vendor-facts-2026-09-28.json),
  [provenance](../artifacts/prompt5a-groq-preparation-2026-09-28/provenance.json)
- Review packet (**unsigned**): [human review packet](../artifacts/prompt5a-groq-preparation-2026-09-28/human-review-packet.md)

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
