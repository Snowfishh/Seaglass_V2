# Codex master prompt — build the Aspire Internal Brain skeleton

Paste this entire document into your Codex coding session with the PyCharm project folder open, or ask Codex to read this file and carry it out. Place the companion `plan.md` in the same project root. This prompt requests implementation of **P0**, not just another plan and not the complete production system.

---

You are my senior Python engineer and implementation partner. Build a working, testable project skeleton for **Aspire Internal Brain**, a permission-aware enterprise knowledge assistant. I will develop and debug it in **PyCharm**.

Use permission-aware knowledge retrieval as the project backbone. Make **policy versioning and conflict detection** and a **verifiable audit engine** the two key supporting components. Build real behaviour for all three. An empty scaffold or a UI displaying invented results is not sufficient.

## 1. Read the project and proceed

1. Inspect the working directory, applicable `AGENTS.md`, existing configuration, installed Python, Git status and relevant existing code. Use `rg` for file/text discovery when available. Preserve unrelated files and uncommitted work.
2. Read `plan.md`. Treat the current user’s instructions and applicable higher-priority instructions as authoritative. If `plan.md` is unavailable, continue with this prompt’s defaults and record the missing file.
3. State the chosen architecture, main assumptions and a short S0–S8 checklist, then start implementation. Do not stop after describing what you would build.
4. Make routine reversible engineering choices yourself. Missing API keys, cloud access, a detailed organiser brief or optional assets must not block the offline core. Record those gaps accurately.
5. Do not rewrite the project into a different stack if compatible working code already exists. Explain a necessary deviation briefly and preserve the same behavioural/security contracts.
6. Use small coherent changes; inspect failures and fix their causes. Do not weaken permission checks, delete failing security tests or fabricate outputs to make a milestone appear complete.
7. Do not deploy publicly, create paid resources, send messages, execute financial transactions, or alter account permissions. This task authorises local implementation and ordinary local verification.
8. If a session limit prevents completion, save exact implemented/partial/blocked status and next steps in `docs/progress.md`. On resumption inspect that checkpoint and continue; do not regenerate completed work.

## 2. Product objective and scope

The public Aspire challenge concerns an internal enterprise knowledge system with RBAC, security logging and an audit trail. Build an assistant that answers operational questions using only evidence the current principal can read, selects the policy effective on the case date, identifies bounded rule conflicts and missing evidence, and produces a cited evidence packet with an audit reference.

Use a **fictional Singapore contractor travel-expense workflow** to make the architecture demonstrable. All identities, documents, limits and contract details are synthetic. This is an internal knowledge workflow; it does not approve or execute spending.

P0 must include:

- A locally runnable Python application and browser interface.
- Server-resolved demo principals, tenant isolation, RBAC and document ACLs.
- Real ingestion of controlled local fixtures, chunking, lexical retrieval and citations.
- Immutable document versions, effective-date selection and explicit structured policy rules.
- Bounded conflict detection and honest abstention/review outcomes.
- Structured audit events, a chained integrity mechanism, checkpoint export and verification.
- Actual offline evidence-based responses, protected packet views/exports and a provider interface.
- Meaningful behavioural tests, demonstration fixtures, a reproducible install and PyCharm instructions.

Defer to P1: verified live Tencent inference, broader retrieval/answer evaluation, and submission packaging. Defer beyond this skeleton: OCR, real finance APIs, payments/card actions, public uploads, enterprise connectors, production SSO, arbitrary policy extraction, model training, a vector-database service and public deployment. Do not add these simply because a framework supports them.

## 3. Default technology and repository

Prefer Python 3.12 with a project `.venv`, FastAPI, Pydantic, SQLAlchemy/SQLite, SQLite FTS5, Jinja2 with CSS/minimal JavaScript, pytest, HTTPX and Ruff. Keep one application process and one local database. No Node frontend, Docker or GPU should be necessary for P0.

Check dependency compatibility from the available environment/current official documentation. Create `pyproject.toml` and a `requirements.lock` with exact third-party versions actually resolved and tested. Do not invent package versions, hashes or lockfile contents. If network restrictions prevent installation, preserve a runnable design and mark the affected verification as blocked; never report unrun tests as passing.

Use the following logical layout, adapting filenames only when an existing project warrants it:

```text
plan.md
prompt.md
README.md
pyproject.toml
requirements.lock
.env.example
.gitignore
src/aspire_brain/
    main.py
    config.py
    cli.py
    db/
    auth/
    knowledge/
    policies/
    audit/
    answers/
    providers/
    web/
        templates/
        static/
data/demo/
    documents/
    manifest.json
    principals.json
tests/
    unit/
    integration/
eval/
    cases.jsonl
    README.md
docs/
    architecture.md
    security.md
    demo.md
    pycharm.md
    integration-checklist.md
    progress.md
artifacts/                 # ignored generated reports/checkpoints
var/                       # ignored local database/runtime state
```

Treat this tree as responsibility boundaries, not a requirement to create empty files. Use plain services and explicit dependencies; avoid a generic agent framework or microservices. Do not serve the `data`, `var` or `artifacts` directories as public static content.

## 4. Data and trusted metadata

Implement validated models for:

- **Principal:** stable ID, tenant ID, active state and server-stored roles.
- **Document:** stable logical ID, tenant, document type and owner metadata.
- **DocumentVersion:** immutable version ID, content/hash, publication time/state, effective interval, explicit scope, optional supersedes link and ACL reference.
- **Chunk:** stable ID, version ID, text, content hash and source locator such as heading plus paragraph number.
- **PolicyRule:** rule key, typed value, unit/currency, applicability, source passage and optional explicit approved override relation.
- **QueryRun/EvidencePacket:** owner and tenant, context, contributing version/chunk/rule IDs, validated answer fields, provider/configuration metadata and audit reference.
- **AuditEvent:** schema version, tenant-local sequence, UTC timestamp, request ID, principal ID, event type, minimised metadata, previous HMAC and current HMAC.
- **Tenant revisions:** transactional `acl_revision` and `content_revision` values.

Document bodies are untrusted data. Only the controlled fixture/import path may set ACLs, policy publication status, structured rule values and precedence. Never parse instructions in retrieved text as application configuration. Link each structured rule to evidence that a reviewer can inspect.

Use immutable content for versions; record publication/ACL changes as separate controlled state changes with audit events. Imports create new versions. Reject cross-tenant links, malformed dates, duplicate conflicting IDs, missing ACLs and cyclic override/supersession relations. Do not overwrite an old document silently.

Support idempotent initialization and seeding. Use a schema-version check; either provide migrations appropriate to the implementation or clearly reject an incompatible local database. Never drop user data automatically. No arbitrary web upload endpoint is needed.

## 5. Authorization: make these invariants real

Implement a central authorization service and a request context resolved on the server. Enforce tenant match, active identity, role grants and document/version ACLs. Deny by default.

Seed these personas:

| Persona | Role/access expectation |
|---|---|
| Employee | Staff guidance explicitly granted to employees |
| Finance lead | Staff guidance plus explicitly granted finance and P17 contract records |
| Policy admin | Explicitly granted policy records; no automatic finance-document access |
| Auditor | Tenant audit metadata; knowledge access still requires separate source grants |
| Other-tenant principal | Its own tenant only |
| Disabled principal | No protected access |

Give chunks exactly their parent version’s access restrictions. Do not grant a bypass merely because a principal has an administrative role.

### Local identity simulation

For P0 only, implement a clearly labelled local demo persona selector. Its endpoint accepts only an allowlisted seeded user ID, resolves that identity server-side and creates an integrity-protected session using a maintained session mechanism. Do not accept caller-supplied role or tenant headers. Re-read active status/roles on requests, rather than trusting stale session claims.

Generate a secret locally; do not use a hard-coded signing key. Use HttpOnly cookies, suitable SameSite settings, CSRF protection for session-changing requests, and origin/host checks. Bind to loopback in documented run commands. Disable demo endpoints outside the explicit local-demo configuration, and reject non-loopback access to the demo selector. Do not trust forwarded identity headers. If demo mode is disabled and a real identity provider is absent, fail closed. Document that proxying the local demo onto the internet is unsupported.

### Retrieval and every derivative

1. Filter tenant and ACL predicates in the repository/search query **before returning candidate content and before the final top-k limit**. Do not load unrestricted top-k passages into the orchestrator and filter afterwards.
2. Unauthorised text must not enter prompts, rerankers, summaries, user responses or ordinary logs. Use a provider-input spy to verify this boundary.
3. Validate access again for source URLs, version history, conflict details, evidence packets and export routes. Inaccessible and unknown source IDs should have the same outward response.
4. Do not expose inaccessible document names, snippets, IDs, raw match counts or conflict details in messages to the requester. Avoid dumping ORM objects or provider errors into responses.
5. Packets inherit all contributing source restrictions and are owner-restricted in P0. If any dependency is no longer readable, deny the whole saved packet. Auditor privileges grant safe audit metadata, not the packet body.
6. Capture revisions at query start; recheck before external generation and before final persistence/response. Abort with a controlled retry outcome if access or relevant content changed. Document that data already delivered or sent to an authorised processor cannot be recalled.
7. Do not implement shared answer caches or multi-turn memory in P0. Clear displayed answers when changing demo personas and send no-store headers for sensitive pages/API responses.

Do not rely on hiding buttons, prompt instructions, an LLM judge, redaction after generation or a front-end role dropdown to enforce access.

## 6. Knowledge retrieval

Implement stable chunking and source locators for the small Markdown/text corpus. Use parameterised database operations, bounded inputs, and safely constructed FTS queries; raw user text must not become SQL or unchecked FTS syntax.

Implement a `Retriever` interface and a real FTS5 lexical retriever. Apply ACL joins in the search query and validate returned records. Detect FTS5 support in `doctor`. If unavailable, provide an explicitly labelled lexical fallback operating only over already-authorised chunks. Do not call the lexical baseline semantic search.

The result must contain allowed chunk text, document/version identifiers, locators and content hashes. Keep global ranking statistics out of public responses. Start with a configurable small top-k and maximum context size.

For structured case evaluation, query the relevant **authorised rule catalogue** as well as text search. All applicable rules for a required category must be considered; conflict detection cannot depend on whether both conflicting passages happened to appear in top-k. Only then select the associated permitted passages for explanation.

General questions may return cited passages/extractive answers. If there is no adequate evidence, say so. A general answer about a cap must not be presented as certification that every requirement for a contractor claim has been satisfied.

## 7. Temporal policy selection and bounded conflicts

Implement explicit request context: workflow ID, case date, jurisdiction, worker type, project/cost-centre where applicable, expense amount and currency. Do not infer decisive fields silently from ambiguous prose; ask for missing case inputs through a structured review outcome.

Define the prototype’s historical semantics: **policy effective on the case date, from evidence available to the system now**. Query time and publication time are separate metadata. Do not claim bitemporal reconstruction of what was known in the past.

Use `[valid_from, valid_to)` intervals with an optional open end. Interpret business dates in `Asia/Singapore` for the fixture. Exclude drafts, future-effective records and withdrawn policies. Keep approval status separate from supersession: a previously approved version may still apply to an earlier case date after being superseded.

Implement these deterministic operations:

1. Select readable approved versions by date and explicit applicability.
2. Check the public workflow’s required evidence/rule categories.
3. Compare typed rules only when their scopes overlap and units/currencies are compatible.
4. Resolve precedence only through a validated, explicit approved override/supersedes relationship within its declared scope. Do not choose by upload date, filename, retrieval score or a generic “latest wins” rule.
5. Report unresolved competing values when equally authoritative rules overlap and no approved relation resolves them.
6. Distinguish historical change, valid scoped override, true conflict, missing evidence and incomparable rules.

Use finite decimal-compatible values for money; reject negative values, NaN/infinity and invalid coercions. Validate intervals and allowed scope keys. Currency conversion and unrestricted natural-language contradiction detection are outside P0.

Missing and inaccessible required evidence must yield the same safe explanation. The workflow manifest may publicly say that contractor terms are required; it must not reveal whether a hidden contract exists. Conflict explanations may include only sources readable by that principal. Every response should scope its conclusion to the evidence available to the requester.

## 8. Evidence packets and provider boundary

Implement a query orchestrator that calls authorization, retrieval, policy resolution, answer assembly, validation and audit services in an explicit sequence.

The public result schema must include:

```text
request_id
query_status: answered | needs_review | insufficient_evidence
case_outcome: within_documented_limits | exceeds_documented_limits |
              undetermined | not_applicable
answer
case_date
citations[]: document_version_id, chunk_id, source_locator, safe excerpt
applied_rules[]
conflicts[]
missing_evidence_categories[]
review_route
provider_mode
scope_notice
audit_event_id
```

The required business outcome and conflict status come from deterministic code. “Within documented limits” is not an approval. Required human review remains explicit.

Provide an `AnswerProvider` protocol and a functional `OfflineExtractiveProvider`. It should assemble an answer from actual retrieved passages and rule outcomes. No canned string selected by matching the demonstration question. Display `offline_extractive` mode in the interface and result metadata.

Represent a future external provider with an isolated adapter/configuration boundary. Do not add an empty implementation that silently succeeds. If it is not implemented or lacks configuration, fail explicitly when selected; ordinary offline mode must still work.

For an eventual live provider:

- Pass only permitted, bounded evidence and necessary synthetic case context.
- Treat source content as untrusted; clearly separate it from application instructions.
- Expose no tools, filesystem access, arbitrary URLs or executable actions to the model.
- Request structured output and validate it with typed schemas.
- Validate citations against the exact permitted context; construct source URLs server-side.
- Do not allow provider output to change ACLs, policy status, conflict decisions or computed monetary comparisons.
- Reject malformed/unsupported output or fall back only with an explicit labelled outcome and audit event. Never silently disguise an offline response as a live success.
- Enforce timeouts, bounded retries and input/output limits; record safe failure metadata without secrets.

A citation that names a valid source can still misrepresent it. Document that semantic support needs evaluation on actual live responses. Keyword filters and secondary LLM judges are not authorization controls or proofs of injection immunity.

## 9. Audit implementation and honest guarantees

Implement a dedicated audit writer. At minimum record query attempts, access denials, authorised source/version references, policy decisions, provider mode/errors, response digest, result status and controlled metadata changes.

Do not put full prompts, answers, source bodies, API keys or other secrets in ordinary logs. Use safe IDs, categories and keyed digests where appropriate. Keep protected packet content separate. Give auditors a minimised tenant-scoped representation.

Use per-tenant monotonic sequences and canonical serialization. A suitable construction is HMAC-SHA256 over a domain/schema tag, tenant ID, sequence, previous HMAC and canonical event payload. Exclude the current HMAC from its own input. Use a separate generated audit secret, not the session secret, and keep it outside the database. Use constant-time comparisons where applicable.

Serialize append operations in a database transaction with uniqueness constraints so concurrent requests cannot fork the chain. Do not provide update/delete audit endpoints. Chain-verification order is sequence order, not timestamp order. Test manipulation of claimed sequence/link data; ordinary database row-return order is not a meaningful integrity property.

Implement:

- Verification of event content, sequence continuity and links.
- A checkpoint containing tenant, schema/key identifier, sequence and head HMAC.
- Verification against an explicitly supplied trusted checkpoint.
- Clear integrity results separating “chain valid,” “verified through checkpoint,” and “completeness unproven.”

A previously anchored checkpoint detects rollback/truncation through that checkpoint; it cannot prove completeness of a later unanchored tail. A checkpoint kept with the same mutable database is not independent trust. If an attacker has both database write access and the HMAC key, a forged replacement chain is possible. Do not use “immutable,” “encrypted,” or “compliant” to describe this prototype.

Write a durable attempt before external generation or evidence disclosure, and commit the final outcome before returning the packet. If audit persistence fails, return a controlled error, not an unaudited success. A durable attempt without a final outcome should remain visibly incomplete. Test this behaviour.

## 10. Fixture design: implement these outcomes

Create about 12 logical documents with 16–20 versions; add small dedicated test fixtures when useful. Include general policies, finance-only evidence, project terms, staff guidance, historical/future/draft versions and an untrusted document containing a prompt-injection attempt. Label the entire corpus fictional.

Use stable IDs with these authoritative expected cases:

| Case | Required result |
|---|---|
| General SG contractor travel policy v1 | SGD 200 per claim, effective 1 Jan–31 Aug 2026; store end-exclusive 1 Sep |
| General policy v2 | SGD 250 per claim from 1 Sep 2026; explicit relationship to v1 |
| P17 contract addendum | Finance-readable SGD 150 cap with an explicit scoped override of the general cap; no global override |
| Employee asks the general cap on 10 Sep | Answer 250 with the v2 citation |
| Employee asks whether P17 contractor claim 220 on 10 Sep meets all limits | `needs_review` / `undetermined`; required contract terms cannot be verified from available evidence; no hidden value/title disclosure |
| Finance asks the same case | Correctly apply cap 150; `answered` / `exceeds_documented_limits`; cite relevant readable sources and show the review route |
| General-cap question dated 20 Aug | Use v1 and answer 200; do not accidentally use the new version |
| Separate cost-centre with two approved equal-priority rules | Seed unequal overlapping values with no precedence; return an actual conflict |
| Two different non-overlapping jurisdictions | Do not report a conflict merely because values differ |
| Same policy on exact effective-date boundary | Select the new version; never both solely because of inclusive-end error |
| Relevant-looking restricted document with unique sentinel text | Employee query, provider context and packet contain no sentinel |
| Untrusted document requests secret disclosure or a role change | No authority change or action execution; no restricted evidence becomes available |
| Cross-tenant ID guess / inactive identity | Denied by server checks |
| Revoked contributing source | Subsequent packet/source access denied; in-flight revision change aborts output |

The true-conflict fixture should be a validly ingested set of contradictory rules, not malformed metadata that would merely fail parsing. The public workflow must require contract verification regardless of whether a restricted contract happens to exist. Do not leak its existence by changing the missing-evidence wording.

## 11. Browser and API contract

Build four practical views:

1. **Ask:** question, case fields, selected demo persona, answer/review state, citations and scope notice.
2. **Sources:** permitted source text with exact version and locator; no unrestricted corpus browser.
3. **Policy history:** readable versions, dates, explicit overrides and readable conflict details.
4. **Audit:** authorised operational metadata, request trace and integrity-check result.

Use plain styling, readable spacing and status labels. Make the core workflow clear before polishing visuals. Escape untrusted source text and generated output; do not render raw model HTML or use unsafe template filters. Keep browser errors free of sensitive stack traces.

Provide equivalent typed routes such as:

| Method/path | Behaviour |
|---|---|
| `GET /health` | Minimal liveness information; no secrets or corpus inventory |
| `GET /api/session` | Current server-resolved identity and demo status |
| `POST /api/demo/session` | Local-only allowlisted persona selection; no role fields |
| `POST /api/queries` | Validated question/context, full controlled workflow |
| `GET /api/sources/{version_id}/{chunk_id}` | Fresh access check and permitted evidence |
| `GET /api/policies/{document_id}/versions` | Only readable history |
| `GET /api/packets/{request_id}` | Owner plus all contributing-source permission checks |
| `GET /api/packets/{request_id}/export` | Protected JSON evidence-packet export |
| `GET /api/audit/events` | Tenant-scoped audit metadata for the audit role |

Reject unexpected security-sensitive request fields. Keep arbitrary file paths and URLs out of source routes. Error handling and pagination must not reveal inaccessible inventory.

## 12. CLI and PyCharm developer experience

Implement these commands, or equally explicit documented equivalents:

- `python -m aspire_brain.cli init-demo`: create missing local configuration/secrets and initialise/seed safely; preserve existing files/data.
- `python -m aspire_brain.cli doctor`: check configuration without printing secrets, schema compatibility, FTS5, writable paths and provider mode.
- `python -m aspire_brain.cli evaluate --offline`: execute labelled cases and write actual JSON/Markdown results into ignored `artifacts/`.
- `python -m aspire_brain.cli audit-checkpoint --tenant demo-a --output artifacts/audit-head.json`: create an explicit checkpoint.
- `python -m aspire_brain.cli audit-verify --tenant demo-a`: report chain integrity and the limitation without an anchor.
- `python -m aspire_brain.cli audit-verify --tenant demo-a --checkpoint artifacts/audit-head.json`: verify against the supplied anchor.

Add controlled import/revocation commands only as needed for the demonstration and tests. Do not expose them to the model as tools. Protect secrets with appropriate local file permissions, and ignore `.env`, database files, generated packets, checkpoints and virtual environments in Git.

The README should support this fresh offline setup once files exist:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m aspire_brain.cli init-demo
python -m aspire_brain.cli doctor
python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000
```

Document the Windows equivalent and any verified deviations. Make package data such as templates available reliably from the installed project, not accidentally only from one working directory.

In `docs/pycharm.md`, explain selecting `.venv/bin/python` on macOS, opening the project root, running module `uvicorn` with the parameters above, loading local configuration, using the same interpreter for pytest, and disabling reload if it interferes with debugging. Use a normal Python run configuration so special FastAPI IDE features are not prerequisites. Do not assume a specific Codex extension is installed.

## 13. Tests and evaluation

Write expected outcomes independently of the implementation, using fixture facts above. Prefer parameterised behavioural tests and API integration tests over tests that mirror internal helper code. Include positive access and useful-answer tests as well as denials.

Required coverage:

- Role and tenant boundaries across retrieval, sources, policy history, packets and audit views.
- Missing ACL metadata, unknown/disabled identities and forged client role claims.
- Unauthorised sentinel absence in provider inputs, answers and ordinary logs.
- Date boundaries, historical versions, draft/future/withdrawn cases and explicit scoped overrides.
- True conflict versus valid exception, distinct jurisdictions and missing/inaccessible required evidence.
- Malformed context, negative/non-finite monetary values, invalid date ranges and cross-tenant links.
- Invalid citation IDs and provider attempts to override computed status.
- Role switching/revocation, stored packet access and permission/content revision changes.
- Audit modification, middle deletion, ordering/sequence manipulation and concurrent appends.
- Tail truncation against a retained checkpoint, and an honest “completeness unproven” result without one.
- Audit-store failure; no successful evidence-bearing response bypasses logging.
- Offline operation with no API credentials and no outbound model request.
- Provider timeout/malformed-output behaviour using a controlled fake, clearly separate from actual live-model testing.
- Fresh seed/run path and essential rendered page/source escaping behaviour.

Do not add a fixed test-count quota or thousands of superficial tests. Run the relevant tests and lint checks, fix material failures, and stop optional testing once the stated risks are covered. Never mark skipped/unavailable live tests as passed.

Produce a small scenario evaluation report with actual case counts and results. Separate deterministic policy correctness, retrieval quality and eventual live answer quality. No invented >99% accuracy, universal zero-leakage claims, performance promises or unsupported confidence intervals. A canary test demonstrates the tested boundary, not comprehensive security against every attack.

## 14. Tencent and organiser verification

Treat these as starting sources, then verify the current account-specific details:

- [Event, challenge and deadline](https://luma.com/26fqf3hy)
- [Hunyuan compatible API documentation](https://cloud.tencent.com/document/product/1729/111007)
- [CodeBuddy product description](https://intl.cloud.tencent.com/products/acc)

The public event lists 16 October 2026 as the submission deadline; exact cutoff and detailed requirements still need verification. Do not assume the event’s named developer tools are automatically application inference APIs or that their credits apply to Hunyuan.

In `docs/integration-checklist.md`, track: required participant tool usage, selected runtime service, official API documentation, endpoint/model/authentication method, account entitlement, deployment/processing region, secret handling, a synthetic live smoke-test result and remaining blockers. Never copy credentials into the document.

For this P0 task, implement the adapter boundary and meaningful offline mode. A live call is optional and should run only when the user has explicitly enabled/configured the live integration. Do not consume credits by default. An untested adapter is “not live-verified,” not “integrated.” Missing access should not interrupt the rest of the skeleton.

## 15. Execution order and estimated effort

Follow the companion plan’s stages. These are human engineering estimates, not a mandate to wait that long or an assurance that all work fits one model session.

| Stage | Output | Estimated focused hours |
|---|---|---:|
| S0 | Repository/environment/configuration and integration prerequisites | 2–3 |
| S1 | Models, validated fixtures, seed CLI and stable IDs | 3–4 |
| S2 | Demo sessions and permission boundaries | 4–6 |
| S3 | Authorised retrieval and source citations | 4–6 |
| S4 | Version/date selection and bounded conflicts | 4–6 |
| S5 | Audit append, integrity verification and checkpoint | 4–6 |
| S6 | Query orchestration, real offline packet and provider contract | 3–5 |
| S7 | Four usable browser views | 3–5 |
| S8 | Integrated regression checks, documentation and handoff | 3–5 |
| **P0 total** | **Working offline skeleton** | **30–46** |

Maintain a runnable application after each meaningful milestone. Bring forward a minimal two-persona retrieval demonstration within the first 6–10 focused hours, then deepen the policy/audit behaviour. Record actual blockers and estimate changes; do not silently broaden scope.

The later P1 work is approximately 13–23 additional hours; the combined budget with 25% contingency is approximately 54–87 hours. P0 alone with contingency is approximately 38–58 hours. A new developer may need substantially more learning time. Keep P1 and production features labelled as future work.

## 16. Definition of done and final handoff

Before declaring P0 complete, verify:

1. A fresh environment can install, initialise, start and run the offline workflow using the documented commands.
2. Employee and finance personas produce the fixture’s different, correctly scoped evidence packets.
3. The historical-policy and true-conflict cases are computed from data and rules.
4. Source, history and packet routes enforce server-side access independently of the UI.
5. The audit verifier detects the required alterations and states checkpoint limitations accurately.
6. The relevant tests and lint checks have actually run successfully, or precise remaining blockers are disclosed.
7. Secrets and sensitive runtime artifacts are excluded from tracked files.
8. Live-provider, production-auth and deployment gaps are documented honestly.

Finish with a concise handoff containing:

- What was implemented, grouped by retrieval, policy/conflicts, audit and interface.
- Exact startup and test commands that were verified.
- Actual test/evaluation outcomes, including skips or failures.
- Where to find the PyCharm guide and demonstration script.
- Remaining integration blockers and the next three concrete tasks with estimated effort.

Begin with repository inspection now, then implement P0. Do not return only a proposal.
