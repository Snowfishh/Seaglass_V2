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

A deterministic red-team seed suite runs against both local query paths: `eval/redteam/`
(versioned, schema-validated playbook **1.3.0**), `tests/integration/test_redteam_playbook.py`, the
deterministic release gate `eval/redteam/release_gate.py`, and the report
`artifacts/redteam-prompt3-2026-09-28/release-gate.json`. It is synthetic-fixture only — no model
judge, no network, no imported numeric threshold. The harness is a **gate**: it exits nonzero when a
case misses its declared oracle, an invalid case is undeclared, an attack succeeds without being
explicitly accepted, or a **critical consequence** (disclosure, forbidden provider input,
forged/unsupported release, permission/packet violation) is observed — even when explicitly
accepted. See [the boundary map](redteam-boundary-map-2026-09-27.md) and stage report §16–§17.

Measured (playbook 1.3.0): 22 cases (21 valid, 1 deliberately invalid control retained in the
denominator), 16 valid attacks, 4 benign controls and 1 unscored source-truth limitation (RT-011).
The oracle is goal-specific: an attack is scored by whether its declared objective materialised in an
outward field, and RT-016/RT-018 are reported as **measured availability degradation**, never as a
blanket "blocked". Observed `attack_not_retrieved` 4, `attack_retrieved_but_blocked` 8,
`attack_succeeded` 0, `availability_preserved` 1, `availability_degraded` 2, `ingestion_inert` 1,
`inconclusive` 0, benign answered normally 4, benign false positives 0, benign wrong answers 0;
`failures: []`, `gate.passed: true`, and separate consequence counts `disclosure` 0,
`forbidden_provider_input` 0, `forged_or_unsupported_release` 0, `permission_or_packet_violation` 0,
`availability_loss` 2 (within the reviewed baseline — **not** zero).

Two results must not be over-read:

* **A blocked attack is not proof of resistance to unknown attacks.** It means the payload did not
  reach an outward field in *that* fixture.
* **Exact-span support is bounded extractive support, not truth verification.** A permitted but
  wrong source is released faithfully when the claim is an exact span of it (RT-011, whose
  `source_truth` is recorded `unknown`).

**Cross-path gap closed (§16.2).** `POST /api/queries` (`QueryService`) previously validated
citation *membership* only and released a forged-but-cited claim. Both paths now enforce the **same**
source-derived claim-support release gate, so a forged-but-cited claim is refused on both and no
packet is persisted. RT-009 was a recorded open gap and is now an **expected block**, reproduced
over loopback HTTP (HTTP 502, no packet, `provider_error` + `query_aborted`). Closing the gap is a
deliberate, visible change recorded in §16 — not a passing test in isolation.

## Local operations and remaining work

`.env`, keys, database files, exports, checkpoints, virtual environments and test/runtime artifacts are ignored by Git. Configuration creates private files with mode `0600` on POSIX; keep equivalent user-only filesystem permissions on Windows. Back up the database, audit key and protected-payload key securely for recovery, while retaining trust anchors separately. Losing the audit key prevents verification of the old chain; losing the payload key prevents decryption of protected inquiry records. Key rotation and production backup policy are not automated.

The offline provider needs no credentials. Unsupported provider modes return an error.
Tests with substitute providers cover malformed output, invalid citations and timeouts.
Before live use, verify account access and processing region, protect credentials, bound
retries and costs, evaluate actual answers, and obtain approval for credit use. See the
[integration checklist](integration-checklist.md).

## Prompt 4 evidence update — 28 September 2026

Playbook 1.4.0 / schema 2 gives benign controls `benign_answered_normally` and RT-011
`unscored_limitation` (source_truth unknown). Current aggregate/companion reports are in
`artifacts/redteam-prompt4-2026-09-28/audited/clean-final/`. Ten hard checks pass, including
before/after source-hash stability; critical consequences fail unconditionally. RT-016/018
remain two measured availability losses, not resistance claims. The raw companion is synthetic
evidence; the RT-021 answer/citation sample is minimized, not a generic sanitized export.

NetworkGuard is a Python IP-socket connect guard. Its empty attempt list covers only guarded
Python connect/connect_ex/create_connection calls, not process-wide isolation, DNS, UDP, native
code or subprocesses. One inert ingestion fixture and no action-tool surface limit scope.
Promptfoo remains not_run because the approved pinned dependency is absent; no model-graded
finding influences this gate. Full local verification passed 436 tests, with changed harness
85.95% and release gate 95.74% statement coverage. Human sign-off remains pending; live
acceptance is unverified and submission status is not ready.


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
