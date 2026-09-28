# Aspire Internal Brain

A local knowledge assistant that answers questions using sources the user is allowed to read. Each answer includes citations and an audit record.

The demo includes a fictional Singapore travel-policy workflow and simulated Confluence, Jira, Slack and Google Drive sources. It uses FastAPI, Pydantic, SQLite/FTS5, Jinja2 and a small amount of JavaScript. Answers quote permitted evidence by default (`offline_extractive`); a supplemental grounded mode composes answers from permitted evidence only. No external model or platform API is connected.

## Start locally

The verified environment is **Python 3.14.2 on macOS 15.6.1, Apple Silicon**, using `.venv/bin/python` (checked 27 September 2026). Package metadata allows Python 3.12 or newer, but other Python versions have not been verified. Dependencies are pinned in `requirements.lock`.

Run these commands from the repository root. If `.venv` already exists, skip its creation and activate it.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m aspire_brain.cli init-demo
python -m aspire_brain.cli doctor
python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), select **employee**, and submit the prefilled general-cap question. Keep the same host throughout the browser session; session-changing requests require a matching origin and CSRF token. The demo persona selector is intentionally local and must not be exposed through a proxy or public listener.

`init-demo` creates missing configuration, separate session/audit/payload keys, and the demo database. Repeating it preserves existing settings and data; incompatible schemas or conflicting document versions produce an error. Run it after upgrading an older checkout to create a missing payload key. See [PyCharm and Windows setup](docs/pycharm.md).

## Verify and demonstrate

```bash
python -m pytest --cov=aspire_brain --cov-report=term-missing
python -m ruff check src tests
python -m aspire_brain.cli evaluate --offline
python -m aspire_brain.cli evaluate-grounding --offline
python -m aspire_brain.cli audit-checkpoint --tenant demo-a --output artifacts/audit-head.json
python -m aspire_brain.cli audit-verify --tenant demo-a
python -m aspire_brain.cli audit-verify --tenant demo-a --checkpoint artifacts/audit-head.json
```

The evaluation saves results in the Git-ignored `artifacts/` directory; see [the evaluation guide](eval/README.md). The [current stage report](docs/stage-report-2026-09-27.md) records results and remaining work. The earlier [P0 checkpoint](docs/progress.md) covers the original travel-policy demo. Checkpoint export refuses to overwrite an existing file: choose a new filename when repeating it, and keep a copy in independently protected storage.

Follow [the demonstration script](docs/demo.md) for employee and finance views, policy history, conflicts, citations, packet export and audit inspection. The **Case demo** includes the five synthetic Aspire examples — now with question-driven platform routing, cross-platform ranking, an explicit context budget and time-scoped retrieval — plus a supplemental Drive synchronization case and a supplemental grounded-answer case. The officer inquiry requires the auditor persona.

## How it works

- **Retrieval:** checks identity and source permissions before ranking results, then checks access again when an answer or saved packet is read. Per-platform retrieval authorizes first, then applies the question's event-time scope, and only then applies a bounded cap before cross-platform ranking, so a cap can never hide a recent permitted match behind older ones.
- **Policy:** selects rules for the case date and scope, applies explicit overrides, and flags conflicts or missing evidence for review.
- **Audit:** records query attempts and outcomes in a tamper-evident HMAC chain. Authorised officers can reconstruct protected simulated queries and search them by user, platform, document and time, paging through a result set with a signed continuation cursor. An explicit, tenant-scoped retention policy removes old encrypted payloads without touching the chain.
- **Answers:** combines evidence excerpts with citations. A grounded provider composes an answer from permitted evidence only, and each claim is released only when it is an exact contiguous span of its cited source's text. Saved packets are restricted to their owner and depend on continued access to every contributing source; a revoked source cannot survive in the answer, citations, time-scope or budget metadata.

SQLite transactions keep answer storage and its final audit event together. Parameterized SQL makes permission filtering explicit without an ORM.

## Current limits

The persona selector is for local demonstrations. Platform routing is a small deterministic keyword heuristic, not semantic question understanding, and cross-platform ranking is lexical. The simulated synchronization sequence uses a declared one-hour budget and an injected clock. The leakage assessment covers a bounded local fixture and does not establish timing non-disclosure for a real deployment. The grounded provider is local: it releases a claim only when the claim is an exact contiguous span of one cited source's text, which is **bounded extractive support, not entailment** — a paraphrase a reader would accept is correctly refused, and the reported lexical-overlap ratio is a diagnostic proxy rather than the release gate. It is a fake-provider result, **not** a live-model result. A real model runtime would need explicit enablement plus a confirmed entitlement, and none is connected here, so the live provider is recorded as `not_run` with null fields. Retention removes only encrypted payloads; audit verification can detect certain changes but cannot prove that every event was recorded. Travel-policy results do not authorise spending. A deterministic, schema-validated red-team suite (`eval/redteam/`, playbook 1.2.0) runs 21 synthetic cases over both local query paths and exits nonzero when a case misses its declared oracle, an invalid case is undeclared or an attack succeeds without being explicitly accepted — `failures: []` is oracle agreement, not a security verdict. Both paths enforce the same source-derived claim-support release gate: an exact cited span is bounded extractive support, not entailment, and it says nothing about source truth.

See [architecture](docs/architecture.md), [security boundaries](docs/security.md) and [integration status](docs/integration-checklist.md) for details.

## Review update — 28 September 2026, Prompt 4

The earlier Current limits paragraph is retained. Its 1.2.0 count is superseded by playbook
**1.4.0**, schema **2**: 22 cases, including 16 valid attacks, 4 benign controls, 1 unscored
source-truth limitation and 1 deliberately invalid control. See stage report §18 for the new
aggregate/companion evidence pair and 436-test result. This remains a simulated local prototype;
live acceptance is unverified, product-use proof is incomplete and submission status is not ready.


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
