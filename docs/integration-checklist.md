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
suite over both query paths (`eval/redteam/`, 12 cases) and reconciled the handoff mismatches — see
§15 and the [boundary map](redteam-boundary-map-2026-09-27.md). One cross-path gap remains open and
recorded: `POST /api/queries` has no claim-support gate. The live runtime remains
`unknown`/`not_run`.

The remaining G5 item is the **mandatory product-use proof** on page 35, which has two separately
Required rows. The conversation history row is now **satisfied** by a verbatim export of six
genuine development sessions; the **minimum-3-chat-screenshots row is still open** because only
labelled transcript exports exist, not literal screenshots of the chat surface. No local tool can
manufacture that proof. The reviewable submission package is prepared. Use the
[WorkBuddy handoff](workbuddy-next-prompt.md) to continue. Publication and submission require
separate authorization.
