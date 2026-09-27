# RAG red-team and gatekeeping assessment

27 September 2026. Scope: the current Seaglass checkout, including its uncommitted files. This is an assessment and proposed plan; it does not change the project's G0–G5 status or claim live validation.

## Verdict

Seaglass has substantial **local, simulated gatekeeping**. It does not yet have a mature **continuous RAG red-team program** or production gatekeeping. The distinction matters: the local controls are real code and tests, while the four-platform corpus, identity selector, synchronization clock, grounded provider and officer inquiry are simulated or bounded. No live platform connector or entitled live model request has been demonstrated.

This checkout was independently verified for this assessment: **373 tests passed**, **92.72% statement coverage**, and Ruff passed. Those results establish regression health within the tested scope, not resistance to unknown attacks. The tree was already dirty before this assessment. The older `artifacts/g5/pytest-full.txt` has a different test count; the current run is the basis for the numbers above.

## Sources and usable ideas

| Source | Useful idea | Fit for Seaglass now |
|---|---|---|
| [Promptfoo repository](https://github.com/promptfoo/promptfoo), [RAG guide](https://www.promptfoo.dev/docs/red-team/rag/), [configuration](https://www.promptfoo.dev/docs/red-team/configuration/) | Declarative attack targets, indirect prompt-injection and RAG-poisoning probes, attribution and authorization checks, reports, CI integration. | **High** as a test harness around an isolated local API and seeded corpus. First retain a deterministic Python suite so critical assertions do not depend on an LLM judge. |
| [Rosanci's RAG red-team article](https://blog.csdn.net/Rosanci/article/details/166601810) | Organize cases by **carrier** (query, corpus, retrieval manipulation) and **goal** (injection, extraction, answer manipulation, denial of service); retain seed cases and variants, measure attack success, detection recall and false positives, then gate regressions. It highlights hidden PDF text, metadata, Unicode, split chunks and repeated-document flooding. | **High** for the attack taxonomy and shadow-corpus rehearsal. Its mini framework uses a mock RAG and mock detector, so its reported attack success is illustrative, not Seaglass evidence. Its suggested numeric thresholds and regex/LLM detectors require calibration against benign cases and independent review. |
| [Vespa repository](https://github.com/vespa-engine/vespa), [hybrid/chunk guide](https://docs.vespa.ai/en/rag/working-with-chunks.html) | Combine lexical and vector retrieval, filtering and configurable ranking over chunks; test candidate generation and ranking separately. | **Conditional** when corpus size or measured recall justifies replacing SQLite FTS5. It does not supply application authorization or prompt-injection protection. |
| [Qdrant repository](https://github.com/qdrant/qdrant), [multitenancy](https://qdrant.tech/documentation/tutorials/multiple-partitions/), [filtering](https://qdrant.tech/documentation/search/filtering/) | Tenant payload indexes, hard search filters, dense/sparse/hybrid retrieval and sharding. | **Conditional** for semantic retrieval at scale. Tenant filters must be injected by trusted server code and checked again before context assembly and packet read. Test approximate-search recall and stale-index deletion/revocation behavior. |
| [Infisical repository](https://github.com/Infisical/infisical) | Centralized secrets, rotation, short-lived credentials, leak scanning, machine identities and audit trails. | **Later**, when real connectors, model credentials and deployment exist. Keep local generated keys separate now; a vault does not replace per-user authorization. |
| [JuiceFS repository](https://github.com/juicedata/juicefs), [architecture](https://juicefs.com/docs/community/architecture/), [encryption caveats](https://juicefs.com/docs/community/security/encryption/) | Shared POSIX corpus storage on metadata service plus object storage, with snapshots/backups and encryption options. | **Later**, if multiple workers need a large shared corpus. Encryption does not cover its client cache or all metadata; filesystem ACLs do not implement source-platform permissions. |

Promptfoo's [data-handling documentation](https://www.promptfoo.dev/docs/red-team/troubleshooting/data-handling/) requires particular care: some generation and grading paths are hosted; `redteam poison` sends complete documents to a remote endpoint and has no local fallback. A private corpus must not be sent through that path without a separate data-handling decision. Use synthetic documents and an isolated target for the first integration, pin the tool version, disable telemetry where appropriate, and record which generator, grader and target made external requests.

## Current controls, with limits

| Boundary | Current evidence | Limit |
|---|---|---|
| Identity and retrieval | `src/aspire_brain/knowledge/retrieval.py`, `auth/__init__.py`: tenant/ACL filtering before FTS ranking; source reads recheck authorization. | Demo personas are not real authentication. Source-platform grants are simulated. |
| Runtime query gate | `src/aspire_brain/answers/service.py`: bounded evidence, permitted citations, snapshot checks around provider call, owner/dependency checks on saved packets, atomic packet/audit commit. | This main query path checks citation IDs but does **not** call the exact-span claim-support evaluator. The configured external model path is unavailable. |
| Simulated cross-platform gate | `src/aspire_brain/platforms/simulated.py`: source status, scoped/authorized candidates, context budget, repeated revocation checks, unsupported-claim refusal and packet dependencies. `providers/claims.py` uses exact cited spans. | Exact spans are bounded extractive support, not truth or entailment. A poisoned but readable source can still supply a false exact span. |
| Audit and privacy | `src/aspire_brain/audit/`: chained events, protected simulated audit payloads, authorized paged inquiry, retention for protected payloads. | No independent external anchor or comprehensive encrypted packet/backups policy; officer inquiry does not cover every query path. |
| Evaluation | `eval/cases.jsonl` and `tests/`: one explicit injection case, sentinel checks, denial/revocation, contradiction and citation regressions. `pyproject.toml` enforces an 80% code-coverage floor. **Updated 2026-09-27:** a versioned, schema-validated attack playbook now exists — `eval/redteam/` (12 cases: 11 valid, 1 deliberate invalid control; 9 valid attacks, 2 benign controls) with a four-value attack-success vocabulary, an explicit false-positive set (benign controls, 0 false positives), per-case evidence and a loopback rehearsal. See `docs/redteam-boundary-map-2026-09-27.md` and stage report §15. | Still **no** automated mutation campaign and **no** CI red-team release gate. Code coverage is not attack coverage, and a blocked attack is not proof of resistance to unknown attacks. The playbook is synthetic-fixture only. |

`docs/security.md` and `docs/stage-report-2026-09-27.md` describe the prototype boundaries in more detail. Their `simulated`/`live`/`unknown` labels should remain as recorded.

## Architecture to build

```text
Trusted connector identity/ACL metadata ──► normalized source record + revision/hash
                                             │
Untrusted source text ──► parser/metadata isolation ──► quarantine/review ──► index
                                                                   │
User session ──► server-derived tenant/grants ──► filtered retrieval ──► freshness +
     revocation check ──► bounded, provenance-tagged context ──► provider ──► claim/citation +
     allowed-entity output checks ──► recheck ──► atomic packet/audit persistence
                                                                   │
Versioned red-team playbook ──► isolated shadow corpus/API ──► deterministic judges +
     reviewed model judges ──► per-case failures, ASR and benign false positives ──► CI gate
```

Treat source text, titles, metadata and tool results as untrusted data. Only trusted connector metadata can set grants, approval, precedence and source status. Injection scanning should produce risk evidence and a review/quarantine decision, not silently promote a scanner score into authorization. The core leak oracle should compare all outbound fields and provider inputs with an allowlist derived from the test principal and source dependencies; pattern-only DLP is a supplementary signal.

## Prioritized implementation plan and exit checks

1. **First: Make an auditable attack baseline.** Add a versioned playbook under `eval/` with case ID, carrier, goal, principal, tenant, injected source, expected authorized sources, success oracle, severity, seed/variant lineage and fixture hash. Start with query injection, readable poisoned source, forbidden cross-tenant source, forged citation, false policy, keyword-stuffed duplicates, hidden/Unicode text, chunk-split payload, revocation during a query and oversized inputs. Run each case in a fresh isolated state. Record valid-attack denominator, attack success, detected/blocked cases, benign false positives, and reason for inconclusive results. **Exit:** every critical leak/permission case is a deterministic fail-on-regression test; report schema and evidence hashes are reproducible.
2. **First: Close gate asymmetry.** Apply the same source-derived output validation to every answer path, including `/api/queries`; keep policy calculations and grants outside the model. Assess whether the exact-span rule is appropriate for each path and add explicit abstention/human-review states where it cannot support an answer. **Exit:** an unsupported or wrongly cited response is refused through both service boundaries, with no packet and a visible aborted audit attempt.
3. **Next: Exercise corpus poisoning and retrieval hijack.** Use a shadow corpus to test parser output (including hidden PDF text and metadata), source revision/hash, duplicate flooding, rank displacement, stale tombstones, conflicting sources and benign lookalikes. Add quarantine with a review path for suspicious new material. **Exit:** reports distinguish `attack_not_retrieved`, `attack_retrieved_but_blocked`, `attack_succeeded`, and `inconclusive`; the benign set quantifies review burden.
4. **Next: Add a reproducible merge gate.** Run the deterministic suite in CI on changes to ingestion, retrieval, permissions, context assembly, providers and output. Fail on any critical cross-tenant disclosure, unauthorized tool/action, stale-revoked source release or fabricated citation. Gate other rates against a documented, reviewed baseline with denominators and confidence/uncertainty notes. Add Promptfoo only as a second, pinned adversarial runner on synthetic data; model-graded findings need triage and replayable seeds. **Exit:** a deliberately reintroduced known defect fails CI, and the failure packet identifies the case and boundary.
5. **Later: Validate live integrations before production claims.** With authorized accounts, test real connector identity mapping, source grants/revocation latency, partial failures, index convergence, model behavior, processing region, secret rotation and independent audit anchoring. Compare FTS5 with Qdrant/Vespa only on a measured relevance/latency/security benchmark. Use Infisical or an equivalent secret manager and distributed storage only when deployment requirements justify them. **Exit:** each live claim has its own dated environment, source, denominator, observed result and failure record; simulated results remain separately labelled.

### Skills needed

Threat modeling across source/write/read/output boundaries; adversarial fixture and oracle design; authorization and identity propagation; retrieval evaluation and ranking; document parsing/provenance; secrets and audit operations; and CI/release engineering. The highest-value near-term skill is building **replayable attack oracles** that can tell a permission breach from a harmless quoted attack string or a bad but authorized source.

## Maturity decision

Current state: **strong simulated security-gated prototype; immature red-team program; unverified live/production gatekeeping**. The next milestone is a deterministic, versioned adversarial suite and enforced release gate, followed by separately labelled live connector/model validation. Installing a vector database, secret manager or distributed filesystem alone would not change this decision.
