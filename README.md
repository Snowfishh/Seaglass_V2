# Aspire Internal Brain

An incident can leave its status in Jira, its discussion in Slack, its runbook in Confluence and its postmortem in Drive. People need to connect those records while keeping private material private.

Seaglass is a local demonstration of that workflow. It finds records the current user may read, returns cited evidence and records the question, access decisions and answer for audit review.

The demo includes a fictional Singapore travel-policy workflow and simulated Confluence, Jira, Slack and Google Drive sources. It uses FastAPI, Pydantic, SQLite/FTS5, Jinja2 and a small amount of JavaScript. Answers quote permitted evidence by default (`offline_extractive`); a supplemental grounded mode composes answers from permitted evidence only. In these default local modes the application calls no external model or platform API. An opt-in `live_grounded` mode connects Groq for fictional demo data only: the model receives the question and numbered permitted evidence sentences, and returns only which sentences answer it (or abstains). The answer is rebuilt from those exact sentences and re-checked before release, so model-written prose never reaches the user. It runs inside fixed token and spend limits recorded in a file-locked ledger, with no retries. The three owner-run evaluations on 14 October 2026 are recorded as they happened ([live model evaluation](eval/live_model/README.md)); provider rate limits stopped every run, so no model-quality result is claimed. Bounded platform connectors are tested offline with fixtures and mock HTTP ([connector fixtures](docs/fintech-connector-fixtures.md)). On 14 October 2026 a separate owner-run, read-only check of those connectors against real Confluence, Jira, Slack and Google Drive test accounts passed 16/16: two users with their own tokens, and on each platform the second user was refused the restricted item ([live access check](docs/reviews/live-access-2026-10-14/README.md)). The connectors are still not wired into the web application, which does not ingest or answer from those accounts. Before that mode existed, a separate experiment harness made two bounded synthetic Groq attempts: the first returned HTTP 400 and the corrected attempt returned HTTP 200 ([5E review](docs/reviews/stage5e-preflight-2026-10-10/README.md)).

## Start locally

The verified environment is **Python 3.14 on macOS 15.6.1, Apple Silicon**: development used 3.14.2, and on 14 October 2026 a fresh install under 3.14.7 passed the full suites. Package metadata allows Python 3.12 or newer. On 13 October 2026 the offline unit and integration tests that do not need FastAPI or httpx also passed under Python 3.13; the full suite has not been run on other versions. Dependencies are pinned in `requirements.lock`.

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

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) to reach the **Case demo**. Follow its **Travel-policy demo / choose persona** link to [/ask](http://127.0.0.1:8000/ask), select **employee**, and submit the prefilled general-cap question; return to **Case demo** to run the simulated four-platform cases. Keep the same host throughout the browser session; session-changing requests require a matching origin and CSRF token. The demo persona selector is intentionally local and must not be exposed through a proxy or public listener.

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

The evaluation saves results in the Git-ignored `artifacts/` directory; see [the evaluation guide](eval/README.md). Historical `artifacts/` and `var/` evidence references describe local, ignored files and are not downloadable repository attachments. The current source and test fixtures are self-contained in the repository. Current status and measured results are in [the submission package](docs/submission/SUBMISSION.md). The [27 September stage report](docs/stage-report-2026-09-27.md) and the earlier [P0 checkpoint](docs/progress.md) are kept as history. Checkpoint export refuses to overwrite an existing file: choose a new filename when repeating it, and keep a copy in independently protected storage.

Follow [the demonstration script](docs/demo.md) for employee and finance views, policy history, conflicts, citations, packet export and audit inspection. The **Case demo** includes the five synthetic Aspire examples — now with question-driven platform routing, cross-platform ranking, an explicit context budget and time-scoped retrieval — plus a supplemental Drive synchronization case and a supplemental grounded-answer case. The officer inquiry requires the auditor persona.

## How it works

- **Retrieval:** checks identity and source permissions before ranking results, then checks access again when an answer or saved packet is read. Per-platform retrieval authorizes first, then applies the question's event-time scope, and only then applies a bounded cap before cross-platform ranking, so a cap can never hide a recent permitted match behind older ones.
- **Policy:** selects rules for the case date and scope, applies explicit overrides, and flags conflicts or missing evidence for review.
- **Audit:** records query attempts and outcomes in a tamper-evident HMAC chain. Authorised officers can reconstruct protected simulated queries and search them by user, platform, document and time, paging through a result set with a signed continuation cursor. An explicit, tenant-scoped retention policy removes old encrypted payloads without touching the chain.
- **Answers:** combines evidence excerpts with citations. A grounded provider composes an answer from permitted evidence only, and each claim is released only when it matches one complete sentence of its cited source, or the complete part of that sentence after a colon (case and whitespace normalised). Saved packets are restricted to their owner and depend on continued access to every contributing source; a revoked source cannot survive in the answer, citations, time-scope or budget metadata.

SQLite transactions keep answer storage and its final audit event together. Parameterized SQL makes permission filtering explicit without an ORM.

## Current limits

The persona selector is for local demonstrations. The four-platform page runs fixed demo questions; typed questions on `/ask` reach the travel-policy store only, and an officer inquiry covers one platform at a time. Platform routing is a small deterministic keyword heuristic, not semantic question understanding, and cross-platform ranking is lexical. The simulated synchronization sequence uses a declared one-hour budget and an injected clock. The leakage assessment covers a bounded local fixture and does not establish timing non-disclosure for a real deployment. The grounded provider is local: it releases a claim only when the claim matches one complete sentence (or complete colon tail) of one cited source, which is **bounded extractive support, not entailment** — a paraphrase a reader would accept is correctly refused, and the reported lexical-overlap ratio is a diagnostic proxy rather than the release gate. It is a fake-provider result, **not** a live-model result. Local runs record the live provider as `not_run` with null fields. The opt-in `live_grounded` mode needs explicit enablement, a confirmed entitlement, the approved target and limits, a key file outside the project and a spend ledger; anything else is refused before a request is made. Retention removes only encrypted payloads; audit verification can detect certain changes but cannot prove that every event was recorded. Travel-policy results do not authorise spending. A deterministic, schema-validated red-team suite (`eval/redteam/`, playbook 1.4.0, schema 2) runs 22 synthetic cases (21 valid, 1 deliberately invalid control) over both local query paths and exits nonzero when a case misses its declared oracle, an invalid case is undeclared or an attack succeeds without being explicitly accepted — `failures: []` is oracle agreement, not a security verdict. Both paths enforce the same source-derived claim-support release gate: a complete cited quotation is bounded extractive support, not entailment, and it says nothing about source truth.

See [architecture](docs/architecture.md), [security boundaries](docs/security.md) and [integration status](docs/integration-checklist.md) for details.

## Status — 13 October 2026

- **Tests:** on 14 October 2026, commit `06a7e00` (cited earlier as `4889bf3`; see the [commit map](docs/reviews/assistant-attribution-2026-10-15/commit-map.txt)) was exported with `git archive` and installed fresh from `requirements.lock` under Python 3.14.7: 954 unit/integration tests and 93 red-team tests passed, with 92.37% statement coverage, and the quick start, offline evaluations, audit verification and server smoke check all succeeded. Browser end-to-end flows were not included. See the [clean-install verification](docs/reviews/freeze-2026-10-14/README.md) and the earlier [checklist verification report](docs/reviews/submission-checklist-2026-10-13/README.md).
- **Red-team playbook:** 1.4.0, schema 2 — 16 valid attacks, 4 benign controls, 1 unscored source-truth limitation and 1 deliberately invalid control.
- **Scope:** a simulated local prototype. Live platform integration and a general live model provider are not established.
- **Submission:** see [SUBMISSION.md](docs/submission/SUBMISSION.md) for the package and its open items. The 28 September review history is kept in its section 5.
