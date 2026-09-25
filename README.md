# Aspire Internal Brain

A working local P0 knowledge assistant for a **fictional Singapore contractor travel workflow**. It retrieves permitted evidence, evaluates explicit policy rules for a case date, returns cited evidence packets, and records verifiable audit events. It does not approve or execute spending.

The runtime uses FastAPI, Pydantic, SQLite/FTS5, Jinja2 and small browser JavaScript. Answers run in `offline_extractive` mode with no model credentials or outbound inference. Live Tencent inference, production authentication and public deployment remain future work.

## Start locally

Run from this project root. The implementation was developed with Python 3.14; the project declares Python 3.12 or newer. Python 3.12 was unavailable on the verification machine, so that interpreter is not claimed as tested. Exact resolved third-party versions are in `requirements.lock`.

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

`init-demo` creates missing `.env`, separate signing/audit keys in `var/`, and the synthetic database. It preserves existing configuration and data; repeated seeding is idempotent. An incompatible schema or conflicting immutable version fails explicitly. No automatic database deletion occurs. See [PyCharm and Windows setup](docs/pycharm.md).

## Verify and demonstrate

```bash
python -m pytest --cov=aspire_brain --cov-report=term-missing
python -m ruff check src tests
python -m aspire_brain.cli evaluate --offline
python -m aspire_brain.cli audit-checkpoint --tenant demo-a --output artifacts/audit-head.json
python -m aspire_brain.cli audit-verify --tenant demo-a
python -m aspire_brain.cli audit-verify --tenant demo-a --checkpoint artifacts/audit-head.json
```

The evaluation writes actual scenario results into ignored `artifacts/`; use [the evaluation guide](eval/README.md) to interpret them. Verification results and any remaining work are recorded in [progress](docs/progress.md). A checkpoint becomes an independent anchor only when retained outside the database's mutable trust boundary.

Follow [the demonstration script](docs/demo.md) for employee/finance differences, historical policy, a real conflict, citations, packet export and audit inspection. The interface has four views: **Ask**, **Sources**, **Policy history** and **Audit trail**.

## Core responsibilities

- **Retrieval:** server-resolved active principals, tenant/role ACL predicates before ranking and top-k, stable chunk locators, FTS5 lexical search with a labelled authorised-only fallback, and fresh source/packet access checks.
- **Policy:** immutable imported versions, end-exclusive effective dates, structured rule evidence, scoped explicit precedence, decimal monetary comparisons, conflict detection and safe missing-evidence outcomes.
- **Audit:** transactionally serialized tenant HMAC chains, durable query attempts and final packet commits, minimised auditor views, checkpoint export, alteration detection and explicit completeness limits.
- **Answers:** deterministic outcomes with actual evidence excerpts, validated citations, owner-restricted stored packets, provider timeouts and explicit failure for unavailable external modes.

Direct standard-library `sqlite3` is a deliberate deviation from the suggested SQLAlchemy stack. Small repository services use parameterized SQL, explicit transactions and SQLite FTS5 directly; this keeps the prototype's authorization and audit commit boundaries visible. No ORM is needed for P0.

See [architecture](docs/architecture.md), [security boundaries](docs/security.md) and [Tencent/organiser integration status](docs/integration-checklist.md). The local model is a demonstration identity system; it is not production SSO, universal injection protection, or an audit compliance certification.
