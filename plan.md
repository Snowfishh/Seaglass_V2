# Aspire Internal Brain — project skeleton and delivery plan

Prepared: 23 September 2026. Working environment: PyCharm; Python application developed and tested locally.

## 1. Project decision

Build a permission-aware enterprise knowledge assistant. **Authorised retrieval is the backbone; policy versioning, conflict detection, and an audit engine support every answer.**

The product helps an employee understand which internal guidance applies to a particular operational question, what evidence supports the answer, and when a human needs to resolve uncertainty. Its output is a cited evidence packet, not permission to execute a payment or change a card limit.

The organiser’s public event page identifies Aspire’s challenge as an internal knowledge system with RBAC, security logging, and an audit trail, and lists **16 October 2026** as the submission deadline. The page does not establish the exact cutoff time, full judging rubric, mandatory runtime services, or submission-file requirements. Verify those against the participant brief before finalising the submission. [S1]

This plan implements the direction selected in the conversation. It does not reuse the earlier reports’ rankings, perfect scores, performance claims, or claims of regulatory compliance.

### What makes this useful

The intended distinction is an inspectable workflow: **who can see the evidence, which policy applied on the relevant date, whether the evidence conflicts, and how the answer was produced**. These are design goals to demonstrate, not claims that permission-aware search or audit logging are new inventions.

## 2. Scope and assumptions

| Item | Planning assumption |
|---|---|
| Developer capacity | One student developer, assisted by Codex; no assumed three-person team |
| Hardware | Ordinary laptop; the previously discussed M4 MacBook Air with 16 GB is sufficient as a planning target; verify the actual environment |
| Working style | Small reviewable milestones in PyCharm; no local model training or GPU requirement |
| Data | Synthetic documents and identities only; fictional company policies clearly labelled |
| Initial corpus | About 12 logical documents / 16–20 versions, plus deterministic test fixtures |
| Demo workflow | Singapore contractor travel-expense guidance, with structured case fields |
| Supported ingestion | Local Markdown/text plus validated JSON metadata through a CLI |
| Skeleton outcome | A running application with real retrieval, access checks, policy logic, audit verification, and tests |
| Language generation | Offline extractive/template mode first; a provider interface for a later verified Tencent runtime integration |
| Estimates | Focused engineering hours, including review and debugging; not model generation time or guaranteed completion time |

**Do not add to the skeleton:** OCR, bank integrations, payment execution, card-limit changes, autonomous tool use, public document uploads, Slack/Drive connectors, SSO, model training, vector-database infrastructure, or a general legal-policy reasoning engine. These would compete with the core demonstration.

## 3. Demonstration and expected behaviour

Use the same fictional case throughout: a contractor proposes a **SGD 220 travel claim for project P17 on 10 September 2026**.

| Scenario | Expected behaviour |
|---|---|
| Employee asks for the general travel cap | Cite the applicable general policy: SGD 250 per claim after 1 September |
| Employee asks whether this contractor claim is within all applicable limits | Return `needs_review`: the public workflow requires verified contract terms, which this principal cannot establish from available evidence; reveal no restricted title, value, or existence count |
| Finance lead asks about the same case | Retrieve an authorised contract addendum limiting P17 to SGD 150, apply its explicit approved override, and report that SGD 220 exceeds the documented limit |
| User changes the expense date to 20 August | Select the old SGD 200 general policy, subject to the same contract-evidence requirements |
| Two equally authoritative applicable rules disagree | Show a conflict to principals who can read both sources; return `needs_review`; do not choose by similarity score or latest upload |
| Document contains instructions to reveal confidential records | Treat it as untrusted source text; no tool execution, role changes, or unauthorised retrieval; record the tested outcome without promising universal injection resistance |
| Auditor inspects the query | Show permitted operational metadata and integrity status; audit access does not automatically grant access to source documents or answer bodies |
| A contributing source is revoked after an answer | Subsequent source and packet requests are denied; no claim that a previously downloaded copy can be recalled |

All caps, dates, contracts, roles, and approval routes above are **synthetic fixtures**, not Aspire’s real policies.

## 4. Architecture and stack

Use a small Python modular monolith: one backend process, one local database, one browser interface.

| Layer | Choice | Reason and boundary |
|---|---|---|
| Runtime | Python 3.12, project `.venv` | Conservative target; check installed interpreter and dependency compatibility |
| Web/API | FastAPI and Pydantic | Typed request/response contracts and central dependencies |
| UI | Jinja2 templates, CSS, minimal JavaScript | One Python project and one server; no separate frontend build. FastAPI documents template support. [S3] |
| Persistence | SQLite with SQLAlchemy | Easy local startup; schema-version check and idempotent seed command |
| Search | SQLite FTS5 lexical search behind a `Retriever` interface | Working baseline before adding semantic retrieval; check FTS5 availability. [S4] |
| Policy engine | Typed Python rules plus immutable policy-version records | Transparent date, scope, and precedence decisions |
| Audit | Structured events, per-tenant HMAC chain, verification CLI | Demonstrate detectable tampering within an explicit threat model |
| Generation | `AnswerProvider`; offline implementation and external-provider boundary | The application remains usable without credentials |
| Quality tools | pytest, HTTPX test client, Ruff | Behavioural tests for the security and domain contracts |
| Packaging | `pyproject.toml`, exact tested dependency lock, `.env.example` | Reproducible setup without committed secrets |

FTS5 is a retrieval engine, **not an access-control system**. The repository query must join authorised document/version identifiers and apply tenant and ACL predicates before returning candidates or applying the final result limit. The application must not fetch unrestricted top-k results and then rely on the model to hide them. Do not expose global match counts or search scores that describe inaccessible records.

If FTS5 is unavailable, implement a labelled deterministic lexical scorer over the already-authorised corpus for this small demo. Never silently remove the permission predicate to make search work.

### Request path

```mermaid
flowchart TD
    A[Question and case context] --> B[Resolve principal and permissions]
    B --> C[Retrieve authorised evidence]
    C --> D[Resolve applicable policy rules]
    D --> E[Build cited evidence packet]
    E --> F[Validate and recheck access]
    F --> G[Commit outcome and return]
    B --> H[Audit events]
    D --> H
    G --> H
```

Audit the attempt before external generation or evidence disclosure. Commit the final outcome before returning the answer. The diagram summarises responsibilities; it does not permit audit writes to be best effort.

## 5. Core contracts

### 5.1 Identity and permissions

Use tenant isolation plus RBAC and document ACLs. Source text, request-body fields, and LLM outputs cannot assign roles.

| Principal | Knowledge access | Additional capability |
|---|---|---|
| `employee` | Explicitly granted staff guidance | Own permitted evidence packets |
| `finance_lead` | Staff guidance plus explicitly granted finance/project records | Same packet rules; no universal admin bypass |
| `policy_admin` | Staff guidance and explicitly granted policy records | Policy metadata inspection; no automatic access to finance secrets |
| `auditor` | Staff guidance and explicitly granted documents | Tenant audit metadata and integrity results; source ACLs still apply |
| Other-tenant user | Only that tenant’s grants | Negative test for tenant isolation |
| Disabled user | None | Negative test for principal revocation |

Every active demo principal has an explicit role set stored on the server. A chunk inherits its document-version ACL. Reject incomplete ACL metadata, unknown principals, cross-tenant references, and disabled accounts by default.

P0 uses **local demo identity switching**, visibly labelled. A loopback-only demo endpoint accepts a seeded user ID and creates a server-validated session; it never accepts roles or tenant claims from the browser. Session integrity, CSRF protection for session changes, safe rendering, and no-store response headers are still required. The selector is an impersonation aid, not production authentication. When demo mode is off, protected routes fail closed until a real identity provider is supplied. Public hosting is outside P0.

Enforce access in retrieval, source viewing, policy history, conflict details, packet exports, and audit views. Unknown and inaccessible source IDs return the same outward response. Recheck principal status and ACL/content revision before any external provider call and before returning a completed packet; if relevant state changed, discard the result and require a retry. Describe the remaining in-flight revocation limitation honestly.

Do not add answer caches or conversation memory in P0. Any later implementation must isolate tenants and principals, include permission/content revisions, and revalidate derived content. OWASP’s guidance supports server-side, deny-by-default permission checks on each request; the detailed contracts here are this project’s design decisions. [S5]

### 5.2 Documents and policy versions

Minimum entities:

- `Principal`: ID, tenant, active state, role assignments.
- `Document`: logical ID, tenant, document type, ownership metadata.
- `DocumentVersion`: immutable version ID/content/hash, publication state, publication timestamp, valid-from/to dates, scope, optional supersedes link, provenance and ACL reference.
- `Chunk`: version ID, stable chunk ID, source locator and text hash.
- `PolicyRule`: version ID, rule key, typed value/unit/currency, explicit applicability and optional approved override reference.
- `QueryRun` / `EvidencePacket`: owner, tenant, case context, contributing versions/chunks, rule trace, validated output and run configuration.
- `AuditEvent`: sequence, request ID, event type, safe metadata and chain fields.
- Tenant `acl_revision` and `content_revision` counters updated transactionally on relevant changes.

Version content stays immutable; any publication-state or ACL changes are separate controlled metadata changes with audit events. A new document import creates a version rather than overwriting old text.

Separate the **case date** from the **query time**. For this prototype, historical queries mean “which policy was effective on the case date, using the documents available now.” This is not full reconstruction of what an employee knew at that historical time.

Use half-open effective intervals `[valid_from, valid_to)` and a documented business timezone (`Asia/Singapore` for demo dates). Draft and withdrawn versions are not applicable. Keep publication approval separate from the supersession relationship: a previously approved version superseded today can still apply to an earlier case date. A future policy cannot apply early.

Only trusted fixture/CLI metadata defines role grants, policy approval status, rule values, and precedence. Documents may describe instructions but cannot configure the application. Imported rules should point to the supporting source passage. Show the structured rule beside its evidence so a reviewer can check that relationship.

### 5.3 Conflict detection

Implement a bounded rule engine, not unrestricted natural-language contradiction detection.

1. Select authorised approved policy records relevant to the declared workflow, case date, and explicit scope.
2. Load all relevant authorised rule metadata, not only the top-k search snippets; then retrieve supporting passages.
3. Validate the workflow’s required rule/evidence categories. Missing or inaccessible required evidence produces the same generic unresolved outcome.
4. Normalise typed rule keys, units, currency, applicability, and dates.
5. Apply an explicitly authorised override/supersession relation only within its declared scope. Validate tenant consistency and reject cycles.
6. If overlapping equally authoritative rules disagree and no declared precedence resolves them, report the conflicting accessible sources and request human review.

Distinguish a normal historical change, a documented scoped exception, a true unresolved conflict, missing evidence, and incomparable values. For example, different currencies are not automatically contradictory; differing jurisdictions may not overlap.

Validate finite nonnegative expense amounts and limits, coherent dates, permitted currencies, and allowed scope keys. A field containing the word `limit` is not a validation strategy. General policy prose may be retrieved, but unsupported semantic conflicts remain outside the P0 claim.

### 5.4 Evidence packets and generation

Return structured fields including:

`request_id`, `query_status`, `case_outcome`, `answer`, `case_date`, `citations`, `applied_rules`, `conflicts`, `missing_evidence_categories`, `review_route`, `provider_mode`, `scope_notice`, and `audit_event_id`.

Allowed `query_status`: `answered`, `needs_review`, `insufficient_evidence`. A separate `case_outcome` is `within_documented_limits`, `exceeds_documented_limits`, `undetermined`, or `not_applicable`. None means an authorised business approval.

Each citation resolves to an immutable version and exact chunk/source locator. Validate every citation against the authorised context. Never fabricate a source, quote, confidence percentage, or model response. A valid citation ID proves provenance linkage, not that every generated claim is semantically supported; P1 evaluation must check that separately.

An evidence packet inherits the restrictions of **all** contributing sources and is owner-restricted in P0. Recheck those dependencies before showing or exporting it. If any dependency is no longer readable, deny the whole saved packet rather than attempting to redact already-derived prose. Audit metadata uses a separate minimised view.

The offline answer provider must assemble meaningful answers from actual retrieved evidence and computed rules. It must not return a hard-coded answer based on the demo question. Label it `offline_extractive`. External text is an optional explanation layer; deterministic code retains control of permissions, policy outcomes, conflict status, and permitted citations. Keep source text separate from application instructions and give the model no tools. OWASP describes prompt injection as a risk requiring layered mitigation, not a solved problem. [S6]

### 5.5 Audit engine

Record query attempts, authentication/access denials, authorised evidence references, policy decisions, provider mode/failure, output hashes, final status, and administrative changes. Avoid raw questions, full answers, document bodies, secrets, and sensitive account details in routine logs. Keep packet content in its separately protected store.

Each per-tenant event includes a schema version, sequence, UTC timestamp, request ID, principal ID, event type, minimal metadata, previous HMAC, and current HMAC. Use canonical JSON and HMAC-SHA256 with a generated secret outside the database. Serialize appends transactionally so concurrent requests cannot fork the chain. Do not expose an update/delete event API.

Verification must detect modified records, broken links, sequence gaps, and manipulation of the claimed sequence order. Ordinary database row-return order is not itself an audit property. **Tail truncation and full rollback require a trusted previously recorded head/sequence checkpoint**; without one, report that completeness cannot be established. An anchor covers its recorded sequence, not a later unanchored tail. Provide checkpoint export and verification, and explain that a same-machine checkpoint is demonstrative, not independent anchoring. Someone controlling both the database and signing key can forge a new chain.

Describe the result as a **tamper-evident prototype under stated assumptions**, not immutable storage, encryption, or regulatory certification. Log the attempt before disclosure; if audit persistence fails, return a controlled error instead of an unaudited success. A durable attempt without an outcome remains visibly incomplete.

## 6. Repository deliverables

Use `src/aspire_brain/` with packages for `auth`, `knowledge`, `policies`, `audit`, `answers`, `providers`, `web`, and shared `db`/`config` contracts. Keep these as modules in one application, not microservices.

| Deliverable | Required content |
|---|---|
| `README.md` | Fresh setup, offline run, architecture, capabilities and limits |
| `pyproject.toml`, `requirements.lock` | Actual compatible dependencies and reproducible install; no guessed lock data |
| `.env.example`, `.gitignore` | Configuration names; exclude secrets, databases, local output and virtual environments |
| `src/aspire_brain/` | Functional backend, templates, static assets, CLI and provider contracts |
| `data/demo/` | Synthetic Markdown/text, JSON manifests, identities, ACLs and policy rules |
| `tests/` | Behavioural unit/integration tests and independent expected scenario outcomes |
| `docs/architecture.md` | Trust boundaries, data flow and trade-offs |
| `docs/security.md` | Threat model, invariants and assurance limitations |
| `docs/demo.md` | Reproducible demonstration with expected outcomes |
| `docs/pycharm.md` | Interpreter, working directory, module run/debug and test settings |
| `docs/integration-checklist.md` | Tencent service evidence, account/region/access checks, runtime status |
| `docs/progress.md` | Implemented/partial/blocked status, tests actually run and next task |
| `eval/cases.jsonl` | Versioned gold cases, expected evidence/rules and permitted outcomes |
| `eval/README.md` | Metrics, fixture limitations, run commands and actual-results location |

Retain this `plan.md` and the companion `prompt.md` in the repository root. Do not generate another generic plan in place of building the skeleton.

## 7. Task breakdown and estimates

P0 is the scope the master prompt should implement. Estimates assume reasonable Python familiarity and successful package installation. Tests for each contract are included in the relevant task; S8 integrates them.

| ID | Work and concrete output | Depends on | Focused hours | Completion gate |
|---|---|---|---:|---|
| S0 | Inspect repo, confirm brief gaps, create environment/configuration, check Tencent access prerequisites | — | 2–3 | Local app starts; unknown requirements and integration blockers are recorded |
| S1 | Models, schema check, validated fixture import, stable IDs, seed CLI | S0 | 3–4 | Repeat seeding is safe; old versions and source hashes remain intact |
| S2 | Demo sessions, tenant/RBAC/ACL checks, source access and revocation state | S1 | 4–6 | Employee, finance, disabled and other-tenant tests pass |
| S3 | ACL-filtered lexical search, chunk locators and source endpoints | S2 | 4–6 | Real permitted retrieval works; forbidden text never reaches provider context |
| S4 | Effective-date selection, typed rules, explicit overrides and conflicts | S1–S3 | 4–6 | Current/historical, override, missing evidence and true-conflict cases pass |
| S5 | Audit append/verify/checkpoint, safe metadata, failure behaviour | S2; S4 event contracts | 4–6 | Mutation, gap, ordering and checkpoint-based truncation checks work |
| S6 | Query orchestration, offline answers, validated packets, provider interface | S3–S5 | 3–5 | One complete case produces a cited, auditable packet |
| S7 | Ask, sources, policy history and audit pages; role switching | S6 | 3–5 | Demo can be run through the browser with visible scope and mode labels |
| S8 | Regression scenarios, fresh-install check, PyCharm guide, demo and handoff | S0–S7 | 3–5 | P0 definition of done is met, or blockers are stated precisely |
| **P0 total** | **Working offline skeleton** | | **30–46** | |

After P0, schedule these separately. The master prompt must not describe them as completed merely because interfaces exist.

| ID | P1 work | Focused hours | Completion gate |
|---|---|---:|---|
| M1 | Implement and exercise one verified Tencent runtime provider, timeouts and error handling | 4–8 | Actual synthetic request succeeds; model/endpoint/region and limitations are recorded |
| M2 | Improve retrieval on paraphrases; add semantic retrieval only if the lexical baseline demonstrably misses needed evidence | 3–5 | Measured retrieval improvement without breaking access controls |
| M3 | Evaluate live answer support, abstention, conflicts and adversarial cases | 3–5 | Report actual denominators, failures and examples for the tested provider |
| M4 | Rehearse demo, prepare submission materials, verify organiser requirements | 3–5 | Reproducible demonstration and complete submission checklist |
| **P1 additional total** | | **13–23** | |

**Budget arithmetic:** P0 + P1 = **43–69 hours**. Allow 25% contingency: approximately **54–87 hours total**. P0 alone with that contingency is approximately **38–58 hours**. These totals exclude production SSO, public deployment, procurement delays, and major learning time. A developer new to FastAPI, SQL, and testing may need 1.5–2 times the base hours.

Do not divide hours mechanically by team size. If teammates join, split UI/fixtures and evaluation after agreeing interfaces; permissions, policy semantics, and integration still need shared review.

### First two working days: feasibility checkpoint

Spend about **6–10 focused hours** on S0/S1 and the smallest part of S2/S3: start the app, seed employee/finance identities, retrieve one permitted document, block one restricted document, and record the actual Tencent access situation. This is an early checkpoint, not a promise to complete the whole skeleton in 48 elapsed hours. Bring a small end-to-end smoke test forward from later tasks; it is included in their estimates.

## 8. Calendar example to the announced deadline

Assume work starts **24 September 2026**. This is a proposed schedule, not a known personal availability calendar.

| Dates | Target |
|---|---|
| 24–26 Sep | S0–S2; complete the small feasibility checkpoint; resolve account/access questions early |
| 27–29 Sep | S3–S4; retrieval and temporal/conflict behaviour |
| 30 Sep–2 Oct | S5–S6; verifiable audit and complete evidence packets |
| 3–4 Oct | S7–S8; usable offline skeleton and reproducible setup |
| 5–7 Oct | M1; verified live provider integration |
| 8–10 Oct | M2–M3; focused quality improvement and measured evaluation |
| 11–13 Oct | M4; freeze scope, rehearse, prepare submission |
| 14–15 Oct | Final integration/submission buffer; contingency should also be distributed through earlier dates |
| 16 Oct | Announced deadline; exact time/timezone must be checked, so aim to submit before this date |

Across 24 September–15 October, the full budget averages about **2.5–4 focused hours per calendar day**. At 10 hours/week, P0 alone takes roughly 4–6 weeks with contingency; that capacity would require reducing scope or adding help to fit the announced deadline. Protect assessment periods by reducing optional work first, not by removing permission or audit checks.

## 9. PyCharm workflow

1. Create/open a normal project folder, for example `aspire-internal-brain`, and place both Markdown files in its root.
2. Configure a project virtual environment and select its interpreter. On macOS, the interpreter is normally `.venv/bin/python`. PyCharm documents both creation and reuse of local virtual environments. [S2]
3. Open your existing Codex coding session against that same folder. Paste the complete `prompt.md`, or instruct it to read that file and execute it. The prompt is independent of any particular PyCharm plugin or paid IDE feature.
4. Let Codex inspect the repository and implement P0. Review the first working permission-filtered query before expanding the UI.
5. Use the generated `docs/pycharm.md` to create a normal Python module run configuration for `uvicorn`, with parameters `aspire_brain.main:app --host 127.0.0.1 --port 8000`, project root as working directory, and the project interpreter. Disable automatic reload when debugging if it interferes with breakpoints.
6. Run pytest using the same interpreter. Keep secrets in the ignored `.env`; never put them in the prompt, source files, shared run configurations, screenshots, or reports.

The intended fresh-run contract, to be implemented and verified by Codex, is:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m aspire_brain.cli init-demo
python -m aspire_brain.cli doctor
python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000
```

`init-demo` should generate missing local secrets and seed the synthetic database without overwriting an existing configuration or deleting data. Windows users should receive the corresponding `.venv\Scripts` commands in the generated guide. These are the intended commands for the future project; this planning task has not built or executed that application.

## 10. Validation and definition of done

Write independent expected outcomes for the fixture cases before implementing the corresponding decision logic. Test the boundaries and failure modes, not every trivial getter.

| Area | Required evidence |
|---|---|
| Permissions | Allowed retrieval plus denial across tenants, roles, guessed IDs, inactive accounts, sources, policies and packets |
| Retrieval | Positive cases return expected evidence; forbidden sentinel text is absent from provider inputs and unauthorised responses/logs |
| Time/version | Old/new boundary dates, draft/future/withdrawn states and explicit history mode behave correctly |
| Conflicts | True conflict, resolved override, unrelated scopes and missing required evidence are distinguished |
| Input integrity | Invalid intervals, role claims, cross-tenant references, negative/NaN amounts and injection-like document text are handled safely |
| Audit | Durable events, append concurrency, modified/deleted/reordered entries, checkpoint verification, unsupported completeness and audit-store failure |
| Generation | Invalid citations and provider output cannot change permissions or computed policy status; offline mode is visibly identified |
| Revocation | Saved packets and source links recheck access; a changed permission revision aborts in-flight output |
| UI | All four pages work; role switching clears prior displayed results; content is escaped and sensitive responses are not cached |
| Reproducibility | Clean environment can install, seed, start, query, verify and test using documented commands |

For P1, report retrieval hit rate against labelled evidence, correct version selection, conflict precision/recall on applicable cases, supported claims/citation accuracy, appropriate abstentions, observed leakage attempts, and measured p50/p95 latency. Report the corpus, case counts, actual provider and failure examples. Do not turn a small fixture suite into a universal security guarantee or invent confidence intervals. A provider-input spy tests context isolation; it does not establish the behaviour of an untested live model.

**P0 is done when** the offline application starts, all three core modules operate, the demo works for employee/finance/auditor personas, required tests pass, and documentation accurately identifies live-provider and production-auth gaps. Empty service files, canned answers, or a polished UI over fabricated results do not meet this gate.

## 11. Tencent integration gate and scope reduction

Early in S0, verify the participant requirements and account entitlements. Tencent documents a Hunyuan API with an OpenAI-compatible interface, but that documentation alone does not prove that the team’s account, region, credits, or hackathon track can use that service. [S7] CodeBuddy is described as a coding assistant; its use during development and the application’s inference endpoint are separate integration questions. [S8]

Record the actual service, official documentation URL, endpoint, model identifier, authentication mechanism, account access, processing region, applicable participant requirement and smoke-test result. Keep credentials out of the record. Do not invent an endpoint named “Yuanbao/CodeBuddy,” assume credit interchangeability, or describe a stub as working integration.

If access is missing, finish P0 in offline mode and record a clear P1 blocker. If semantic retrieval is weak, improve the small labelled corpus and retrieval before adding infrastructure. If time is short, cut semantic retrieval, arbitrary document ingestion, policy editing UI and visual polish first. Preserve retrieval permission checks, temporal correctness, conflict handling, citation traceability and audit verification.

Public deployment is a separate decision requiring a real authentication path, protected persistence/secrets, and demo-mode removal. Do not count a local demo with a persona selector as production enterprise security.

## 12. Source notes

Official pages consulted on 23 September 2026. The detailed design, estimates and fixture values are recommendations made for this project, not organiser requirements.

- **[S1]** [Tencent Cloud hackathon event page](https://luma.com/26fqf3hy) — challenge direction and announced dates; detailed brief still required.
- **[S2]** [PyCharm: configure a virtualenv environment](https://www.jetbrains.com/help/pycharm/creating-virtual-environment.html) — project interpreter setup.
- **[S3]** [FastAPI: templates](https://fastapi.tiangolo.com/advanced/templates/) — Jinja2 integration.
- **[S4]** [SQLite FTS5 documentation](https://sqlite.org/fts5.html) — lexical full-text search capabilities; access enforcement is application work.
- **[S5]** [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) — server-side permission enforcement and least privilege.
- **[S6]** [OWASP: prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) — risk and mitigation boundaries.
- **[S7]** [Tencent Hunyuan compatible-interface examples](https://cloud.tencent.com/document/product/1729/111007) — an available documented API route, subject to account-specific verification.
- **[S8]** [Tencent Cloud CodeBuddy](https://intl.cloud.tencent.com/products/acc) — development assistant product description.
