# Aspire Internal Brain

After an incident, the status sits in Jira, the discussion in Slack, the runbook in Confluence and the postmortem in Drive. Anyone answering a question about it has to pull those four together without showing people material they aren't allowed to see.

Seaglass is a local demo of that job. You ask a question. It searches only the records you may read, answers with citations, and logs the question, each access decision and the answer so an auditor can review them later.

All the data is fictional: a Singapore travel-policy workflow, plus simulated Confluence, Jira, Slack and Google Drive sources. The stack is FastAPI, Pydantic, SQLite/FTS5, Jinja2 and a little JavaScript.

## What stays local and what goes out

By default nothing leaves the machine. The default mode, `offline_extractive`, quotes permitted evidence directly. A second, supplemental mode composes an answer from permitted evidence only. Neither one calls an external model or platform API.

`live_grounded` is opt-in. It connects Groq, and only for fictional demo data. The model receives the question and the permitted evidence split into numbered sentences, and it replies with the numbers of the sentences that answer the question, or abstains. Seaglass rebuilds the answer from those exact sentences and checks it again before release, so the user never sees prose the model wrote. Each call runs under fixed token and spend limits recorded in a file-locked ledger, and nothing is retried.

The owner ran three evaluations of this mode on 14 October 2026. Provider rate limits stopped all three, so there is no model-quality result to report. The [live model evaluation](eval/live_model/README.md) records the runs as they happened.

The platform connectors are tested offline with fixtures and mock HTTP ([connector fixtures](docs/fintech-connector-fixtures.md)). On 14 October 2026 the owner also ran a separate read-only check of them against real Confluence, Jira, Slack and Google Drive test accounts. It passed 16/16. Two users each used their own token, and on every platform the second user was refused the restricted item ([live access check](docs/reviews/live-access-2026-10-14/README.md)). Since 15 October the connectors can also feed the application. With `ASPIRE_PLATFORM_SOURCE=connectors`, the four-platform index is built from those accounts, reading each user's view with that user's own token, and the same sync loop the fixture uses keeps it fresh. That path is tested offline against a fake of all four APIs. The owner-run check against the real accounts ([live platform check](eval/live_platform/README.md)) has not been run yet.

Before `live_grounded` existed, a separate experiment harness made two bounded synthetic Groq requests. The first returned HTTP 400 and the corrected one returned HTTP 200 ([5E review](docs/reviews/stage5e-preflight-2026-10-10/README.md)).

## Start locally

The tested setup is **Python 3.14 on macOS 15.6.1, Apple Silicon**. Development used 3.14.2, and on 15 October 2026 a fresh install under 3.14.7 passed the full suites. The package metadata accepts Python 3.12 or newer. On 13 October 2026 the offline unit and integration tests that don't need FastAPI or httpx also passed under Python 3.13, but the full suite hasn't been run on any other version. Dependencies are pinned in `requirements.lock`.

Run these commands from the repository root. If `.venv` already exists, skip creating it and just activate it.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m aspire_brain.cli init-demo
python -m aspire_brain.cli doctor
python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). It lands on the **Case demo**. For the travel-policy flow, follow **Travel-policy demo / choose persona** to [/ask](http://127.0.0.1:8000/ask), pick **employee** and submit the prefilled general-cap question. Then go back to **Case demo** to run the simulated four-platform cases.

Stay on the same host for the whole browser session, because requests that change the session need a matching origin and CSRF token. The persona selector is meant for local demos. Don't expose it through a proxy or a public listener.

`init-demo` creates any missing configuration, separate session, audit, payload and audit-witness keys, and the demo database. Running it again keeps existing settings and data. It stops with an error if a schema is incompatible or a document version conflicts. After upgrading an older checkout, run it again to create any missing key. For PyCharm and Windows, see [PyCharm and Windows setup](docs/pycharm.md).

Typed four-platform questions on the Case demo page need the `user-a` or `user-b` persona, and the freshness controls under them need `fintech_admin`. An existing database needs `python -m aspire_brain.cli import-fixtures --fixtures data/demo`, or a fresh `init-demo`, to add those personas.

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

Evaluation results go to `artifacts/`, which Git ignores; [the evaluation guide](eval/README.md) explains them. Older documents point at files under `artifacts/` and `var/`. Those were local, ignored files, so you can't download them from the repository. The current source and test fixtures are all in the repository.

Checkpoint export won't overwrite an existing file. Pick a new filename each time you repeat it, and keep a copy in storage that is protected separately from this checkout.

Current status and measured results are in [the submission package](docs/submission/SUBMISSION.md). The [27 September stage report](docs/stage-report-2026-09-27.md) and the earlier [P0 checkpoint](docs/progress.md) are kept as history.

[The demonstration script](docs/demo.md) walks through the employee and finance views, policy history, conflicts, citations, packet export and audit inspection. The **Case demo** page has the five synthetic Aspire examples, which now use question-driven platform routing, cross-platform ranking, an explicit context budget and time-scoped retrieval. It also has two supplemental cases, one for Drive synchronization and one for grounded answers. The typed-question card above them searches the shared four-platform index. Under it, a panel shows each platform's sync status, and the `fintech_admin` persona can publish a runbook revision, remove a user's access to the restricted records, and sync. The officer inquiry needs the auditor persona; the Audit trail page has a search form for any user, platform, space or document.

## How it works

- **Retrieval.** Identity and source permissions are checked before anything is ranked, and access is checked again whenever an answer or saved packet is read. On each platform, retrieval authorizes first, then applies the question's event-time scope, and only then applies a fixed cap before cross-platform ranking. Because of that order, a cap can't push a recent permitted match out in favour of older ones. Routing picks the platforms a question needs, and the other platforms are searched as well. Before a record is quoted, the service asks its source again, as the asking user, whether it is still readable and unchanged, so a permission removed upstream takes effect before the next sync.
- **Synchronization.** One four-platform index is shared by every request. A sync loop refreshes it every 300 seconds against a one-hour budget. A platform past its budget, or with changes waiting, is reported stale and not quoted as current, and the time each change took to reach answers is recorded.
- **Policy.** Picks the rules for the case date and scope, applies explicit overrides, and flags conflicts or missing evidence for review.
- **Audit.** Every query attempt and outcome goes into a tamper-evident HMAC chain. A separate witness file, under its own key, records each committed chain head, so removing the newest events from the database alone is detected and completeness can be stated relative to the witness. Removing them from the database and the witness together needs no key and is caught only by a checkpoint exported after them and kept elsewhere. Authorised officers can reconstruct any query on either route, including ones stopped before an answer, and search by user, platform, space or document and time, paging through long result sets with a signed continuation cursor. An explicit, tenant-scoped retention policy deletes old encrypted payloads and leaves the chain alone.
- **Answers.** Built from evidence excerpts with citations. On the four-platform route the local answer quotes only the passages that cover the question's content terms, and it abstains with one fixed sentence when the permitted evidence covers less than 75% of them. The grounded provider writes answers from permitted evidence only, and it releases a claim only when the claim matches one complete sentence of its cited source, or the complete part of that sentence after a colon (ignoring case and whitespace). A saved packet belongs to its owner and stays readable only while every source behind it is still accessible. A revoked source can't survive in the answer, the citations, or the time-scope or budget metadata.

Answer storage and its final audit event are written in one SQLite transaction. Queries use parameterized SQL with no ORM, so the permission filter is written out in plain view.

## Current limits

- The persona selector is for local demos only.
- Typed questions use the configured provider and the shared index. With the default fixture source, its clock starts at 12 October 2026, 03:00 UTC when the server starts and then runs in real time. The numbered cases still use their own small fixtures.
- Platform routing is a small deterministic keyword heuristic, not semantic understanding of the question. Cross-platform ranking and answer coverage are lexical, so a question worded in terms the sources don't use is refused rather than answered.
- Cases 2 and 6 run their sync sequences on a simulated clock. The typed card's sync loop runs in real elapsed time.
- The connector source has not yet been run against the real accounts; that is the owner-run [live platform check](eval/live_platform/README.md). On Slack, the query-time re-check confirms channel access; an edited message is picked up at the next sync.
- An audit write verifies only the witness lines appended since the last one it checked, plus that last line, so its cost does not grow with history. A full verification (the audit report and inquiry) still re-reads the whole witness file, and the process keeps every witnessed head in memory; a production deployment would need a checkpointed or indexed witness.
- Jira's per-user project preflight is tested against mocked responses only.
- The leakage assessment covers a bounded local fixture. It doesn't show that a real deployment is free of timing leaks.
- The grounded provider is local. Its results come from a fake provider and are **not** live-model results. Local runs record the live provider as `not_run` with null fields.
- Releasing a claim only when it matches one complete cited sentence (or complete colon tail) is **bounded extractive support, not entailment**. A paraphrase a reader would accept is refused, and that refusal is intended. The lexical-overlap ratio in the output is a diagnostic proxy; it is not the release gate. Both local query paths enforce this same gate, and passing it says nothing about whether the source itself is true.
- `live_grounded` refuses before making any request unless it has explicit enablement, a confirmed entitlement, the approved target and limits, a key file outside the project and a spend ledger.
- Retention deletes encrypted payloads only. Audit verification detects edits anywhere in the chain and removal of any witnessed event. If the process stops between a database commit and the witness update, one event stays unwitnessed and verification reports it. The witness proves only its own prefix: someone who can write both files can delete the newest events from both, with no key, and verification still passes. Only a checkpoint exported after those events and kept elsewhere detects that. Rewriting both needs both keys.
- Travel-policy results do not authorise anyone to spend money.
- The red-team suite in `eval/redteam/` (playbook 1.4.0, schema 2) is deterministic and schema-validated. It runs 22 synthetic cases, 21 valid and 1 deliberately invalid control, over both local query paths. It exits nonzero when a case misses its declared oracle, when an invalid case isn't declared, or when an attack succeeds without being explicitly accepted. `failures: []` means the cases agreed with their oracles. It is not a security verdict.

[Architecture](docs/architecture.md), [security boundaries](docs/security.md) and [integration status](docs/integration-checklist.md) go into more detail.

## Status, 15 October 2026

- **Tests.** On 16 October, after the review fixes of 15 October and an incremental audit-witness append, 1,068 unit and integration tests and 93 red-team tests pass in the working tree, with 92.08% statement coverage, and the offline evaluations pass (22/22 labelled cases; grounding 5 supported, 0 unsupported). These figures come from the working tree before commit; the clean-install check has not been repeated for them. The typed card, the freshness controls, revocation and the audit search were rehearsed against a running server earlier that day, before the review fixes. Earlier that day the previous commit passed a clean install, recorded in the [clean-install verification](docs/reviews/freeze-2026-10-14/README.md).
- **Red-team playbook.** Version 1.4.0, schema 2: 16 valid attacks, 4 benign controls, 1 unscored source-truth limitation and 1 deliberately invalid control.
- **Scope.** Local by default, on fictional data. The connector source is implemented and tested offline; its owner-run check against the real accounts is pending. A general live-model evaluation has not been established.
- **Submission.** [SUBMISSION.md](docs/submission/SUBMISSION.md) has the package and the items still open. The 28 September review history is kept in its section 5.
