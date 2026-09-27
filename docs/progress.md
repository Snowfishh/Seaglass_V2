# P0 verification checkpoint

Updated 25 September 2026 (Asia/Singapore). Local implementation only; no deployment,
submission, paid resource or live inference was performed.

## Completion status

- S0: environment, package configuration and public integration sources inspected.
  Python 3.14.2 is available and tested; Python 3.12 is unavailable here.
  Native sqlite3 replaces the suggested ORM to expose transaction and FTS boundaries.
- S1–S6: ingestion, authorization, temporal/conflict rules, audit, offline providers
  and protected packet orchestration are implemented with behavioral tests.
- S7: four browser views and equivalent protected API routes implemented and exercised
  in a real browser. Employee/finance differences, cleared persona-switch results,
  source inspection, history and auditor request trace were observed.
- S8: CLI, exact dependency lock, documentation, fresh installation, package-data check,
  full regression tests, evaluation and audit checkpoint verification completed.

**P0 offline skeleton is complete under the scope and limitations below.** The local
demo is not a production service. No live-provider or account-entitlement success is claimed.

## Final verification evidence

The final suite passed **148 tests, zero failures, zero skips**, with **92.56% statement
coverage**. Ruff passed. One upstream Starlette warning deprecates its HTTPX TestClient
integration; it does not fail these tests. Tests cover final audit-store failure, packet
and auditor-role revocation races, content revision changes, actual async provider timeout,
unrelated-question abstention, data validation and the required permission/audit boundaries.
All **22 labelled offline scenarios passed**; lexical top-5 retrieved all expected versions
in 8 of 12 evidence-labelled cases. Structured policy decisions use the full permitted
rule catalogue, so this retrieval limitation does not silently remove competing rules.
The source corpus contains 12 logical documents and 18 versions. Fresh setup used a
new `.venv-fresh` on Python 3.14.2 and the exact dependency wheels from `requirements.lock`.
The editable install, clean runtime initialization and doctor succeeded. A regular wheel
was also installed and exercised from outside the repository working directory: templates,
static JavaScript, sessions and an employee cap query succeeded. `pip check` found no
broken requirements. Python 3.12 and Windows were not available for runtime verification.

The real browser rehearsal verified employee general cap 250, employee P17 review,
finance P17 cap150/exceeded, citation source, version history and auditor request trace.
The observed finance trace contains attempt, policy decision and completed outcome events.
Audit verification succeeded with and without a retained checkpoint, preserving the
explicit unproven-completeness result and unanchored-tail limitation.

Generated, ignored reports:

- `artifacts/pytest-final.txt` and `artifacts/coverage.json`
- `artifacts/evaluation.json` and `artifacts/evaluation.md`
- `artifacts/browser-verification.json`
- `artifacts/audit-verification.json` and `artifacts/audit-head.json`

Git exclusions verified for `.env`, both secret files, SQLite, checkpoints, artifacts
and both virtual environments. POSIX `.env`/key permissions are 0600. Existing plan,
license and unrelated project work are preserved.

## Verified commands

From the project root, using the initialized environment:

```bash
.venv/bin/python -m aspire_brain.cli init-demo
.venv/bin/python -m aspire_brain.cli doctor
.venv/bin/python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8002 --no-proxy-headers --no-access-log
.venv/bin/python -m pytest --cov=aspire_brain --cov-report=term-missing
.venv/bin/python -m ruff check src tests
.venv/bin/python -m aspire_brain.cli evaluate --offline
.venv/bin/python -m aspire_brain.cli audit-checkpoint --tenant demo-a --output artifacts/audit-head.json
.venv/bin/python -m aspire_brain.cli audit-verify --tenant demo-a
.venv/bin/python -m aspire_brain.cli audit-verify --tenant demo-a --checkpoint artifacts/audit-head.json
```

Checkpoint export deliberately refuses to overwrite an existing anchor: choose a new
output filename when repeating it. Port 8002 was used for the final browser rehearsal
because 8001 was occupied. The normal README/PyCharm example uses port 8000.

Fresh offline installation after downloading the locked wheels was verified with:

```bash
python3 -m venv .venv-fresh
.venv-fresh/bin/python -m pip install --no-index --find-links artifacts/wheels -r requirements.lock
PIP_NO_INDEX=1 PIP_FIND_LINKS="$PWD/artifacts/wheels" .venv-fresh/bin/python -m pip install --no-deps -e .
```

Downloaded wheel caches are machine-specific ignored artifacts; the lock remains the
portable exact-version dependency record. See README for normal registry installation.

## Deliberately deferred integration

Live Tencent inference is not implemented or verified. Selecting an external provider
fails explicitly; no credentials are required for offline mode. Account entitlement,
processing region, organiser tool requirements and exact deadline cutoff remain unknown.
See `integration-checklist.md` for sources and bounded P1 tasks. Production SSO, public
deployment, arbitrary extraction/uploads and financial actions are beyond P0.
