# Security boundaries and limitations

This local demo uses fictional data and selectable personas. The selector does not verify
a person's real identity. Anyone who controls the operating-system account, database,
keys or importer can change the trusted environment. Public deployment needs a real
identity provider, protected storage and secrets, hardened hosting and removal of demo
identities.

## Identity, sessions and HTTP

The allowlisted persona endpoint accepts a user ID only. Current roles, tenant and active state are read server-side for protected requests. Signed Starlette sessions use a locally generated secret, HttpOnly cookies and `SameSite=Strict`. Session-changing requests need a CSRF token and exact same origin; host checks accept loopback hostnames. The selector additionally verifies the direct client's loopback address. Disabled identities cannot select a session or read protected resources. Unknown and inaccessible source/packet IDs use the same outward failure.

Run with `--host 127.0.0.1 --no-proxy-headers --no-access-log`. Forwarded identity headers confer no authority; proxying the demo onto the internet is unsupported. Local HTTP cookies do not have the Secure flag because this configuration serves loopback HTTP. Disabling `ASPIRE_DEMO_MODE` without a real identity provider fails closed for protected resources.

Sensitive responses use `Cache-Control: no-store`. Persona changes clear displayed results and obsolete in-flight browser responses. Output is inserted as text; Jinja2 escaping and a restrictive CSP avoid interpreting source/provider HTML. No unrestricted corpus directory is served. Ordinary Uvicorn access logging is disabled in the documented command to avoid unnecessary source/request URL records.

## Evidence authorization

Tenant/ACL predicates execute before FTS ranking and top-k. The fallback obtains authorised rows before local scoring. Rules come from the complete authorised catalogue, so conflict detection does not rely on retrieving two passages by chance. Source reads, version history and exports re-check access independently of the interface. Administrative/auditor roles do not grant implicit knowledge access.

Packets are owner-restricted and inherit all contributing source restrictions. If any source is revoked, the entire saved packet is denied. Every source-derived outward field is derived from the same authorized, dependency-checked record set: answer text, citations, time-scope metadata and context-budget metadata. A revoked or out-of-window source therefore cannot survive in a budget-dropped identifier list or any other diagnostic field, and an abstained packet exposes no answer dependencies. A revoked source's identifier, count or existence is never disclosed; a revoked read and an unknown read remain indistinguishable. Tenant ACL/content revisions and fresh principal state are checked before provider generation, during provider execution and before final persistence; detected changes abort with a retry outcome. The packet and successful audit event commit together. This does not recall material already delivered to a browser, downloaded, or sent to an authorised processor before revocation. No shared answer cache or multi-turn memory is implemented.

Missing and inaccessible required contract terms use the same explanation. Hidden source names, identifiers, caps and counts must not appear in unauthorized packets or conflict details. The public workflow can say that contract terms are required without disclosing whether a particular hidden contract exists.

## Trusted imports and untrusted text

Only controlled local fixture metadata can establish approval state, ACLs, structured rules or precedence. Version contents and source hashes remain stable. Imports validate tenant links, intervals, exact decimal values, supported scope keys and relationship graphs. There is no arbitrary web upload endpoint.

Source text cannot grant access or execute tools. The offline provider may quote a
malicious passage that the user is allowed to read, but treats it as escaped text.
Tests check that restricted sentinel text stays out of provider input and responses;
they do not establish protection against every possible injection. The design gives a
future external model no tools, filesystem access or action channel.

## Audit guarantees

A durable query attempt precedes generation; successful evidence-bearing outcomes require a committed final event. Audit-write failures produce controlled errors. An interrupted attempt remains visible in the verifier's incomplete-request list. Ordinary audit metadata excludes full questions, source bodies, answers and secrets. Response digests are keyed with a separate domain. P0 reproduction uses `EvidencePacket.model_dump_json()` UTF-8 bytes with `audit_event_id` normalized to `pending`; the protected simulator uses sorted JSON bytes with the same normalized field and verifies that digest during officer inquiry. Chain verification alone does not automatically compare every stored packet body against its response digest. The auditor HTTP event view is a minimised tenant trace and does not expose packet bodies or source grants; the separate protected inquiry is audit-role-only.

Events are chained with HMAC-SHA256 over canonical payloads, domain/schema context, tenant, sequence and previous HMAC. The audit secret is separately generated from the session secret and stored outside SQLite. Transactional append plus unique tenant/sequence constraints prevent concurrent writers from independently claiming the same sequence. The verifier checks content, links and sequence continuity, not incidental row-return order. No audit update/delete endpoint exists.

Interpret verifier fields separately:

| Field | Meaning |
|---|---|
| `chain_valid` | The currently observed sequence and HMAC links validate with this key. |
| `verified_through_checkpoint` | The supplied checkpoint matches the observed valid chain through its declared sequence. |
| `completeness_unproven` | The prototype cannot establish that every event that should exist was recorded, especially after the last independent anchor. |
| `incomplete_requests` | Observed query or protected-read attempts with no terminal event in the inspected chain. |

Retain a checkpoint independently before an incident if you need to detect rollback through it. Keeping it beside the mutable database is not independent trust. Even a valid checkpoint cannot establish completeness of a later unanchored tail. Deleting an unanchored final suffix can leave a valid chain. Someone who holds both database write access and the audit key can forge a replacement chain. Protected simulated case audit payloads now use a separate AES-GCM key, but the ordinary owner-restricted packet table still stores answers in local SQLite. This prototype does not provide comprehensive encryption at rest or an immutable/compliant audit store.

Protected officer inquiry is paged rather than silently truncated. A match set larger than the page size returns `has_more` and a continuation cursor that is HMAC-signed and bound to both the tenant and the exact search filters, so a cursor cannot be replayed across tenants or against a different query. Ordering is stable on `(timestamp, request ID)`, so equal timestamps neither drop nor duplicate an entry across a page boundary. Integrity and retention state are re-checked on every page, and a cursor that fails validation is rejected rather than silently restarted. Retention is scoped to the encrypted protected payloads only: plaintext packets, exports and backups have separate lifetimes and are not covered by it.

## Adversarial seed suite (measured)

A small deterministic red-team seed suite runs against both local query paths:
`eval/redteam/` (versioned, schema-validated playbook), `tests/integration/test_redteam_playbook.py`,
and the report `artifacts/redteam/redteam-report.json`. It is synthetic-fixture only — no model
judge, no network, no imported numeric threshold. See
[the boundary map](redteam-boundary-map-2026-09-27.md) and stage report §15.

Measured: 12 cases (11 valid, 1 deliberately invalid control retained in the denominator),
9 valid attacks and 2 benign controls. Observed `attack_not_retrieved` 4,
`attack_retrieved_but_blocked` 3, `attack_succeeded` 2, `inconclusive` 0, benign false positives 0.

Two results must not be over-read:

* **A blocked attack is not proof of resistance to unknown attacks.** It means the payload did not
  reach an outward field in *that* fixture.
* **Exact-span support is bounded extractive support, not truth verification.** A permitted but
  wrong source is released faithfully when the claim is an exact span of it (RT-011).

**Recorded open gap.** `POST /api/queries` (`QueryService`) validates citation *membership* only and
has **no claim-support gate**, so a forged-but-cited claim is released and persisted. The simulated
path refuses the same provider output. This asymmetry is reproduced over loopback HTTP and asserted
as-is by the suite (RT-009) so that fixing it is a deliberate, visible change. It is **not** fixed
in this pass.

## Local operations and remaining work

`.env`, keys, database files, exports, checkpoints, virtual environments and test/runtime artifacts are ignored by Git. Configuration creates private files with mode `0600` on POSIX; keep equivalent user-only filesystem permissions on Windows. Back up the database, audit key and protected-payload key securely for recovery, while retaining trust anchors separately. Losing the audit key prevents verification of the old chain; losing the payload key prevents decryption of protected inquiry records. Key rotation and production backup policy are not automated.

The offline provider needs no credentials. Unsupported provider modes return an error.
Tests with substitute providers cover malformed output, invalid citations and timeouts.
Before live use, verify account access and processing region, protect credentials, bound
retries and costs, evaluate actual answers, and obtain approval for credit use. See the
[integration checklist](integration-checklist.md).
