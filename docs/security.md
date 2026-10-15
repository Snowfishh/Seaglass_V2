# Security boundaries and limitations

This local demo uses fictional data and selectable personas. The selector does not verify
a person's real identity. Anyone who controls the operating-system account, database,
keys or importer can change the trusted environment. Public deployment needs a real
identity provider, protected storage and secrets, hardened hosting and removal of demo
identities.

## Identity, sessions and HTTP

The allowlisted persona endpoint accepts a user ID only. Current roles, tenant and active state are read server-side for protected requests. Signed Starlette sessions use a locally generated secret, HttpOnly cookies and `SameSite=Strict`. Session-changing requests need a CSRF token and exact same origin; host checks accept loopback hostnames. The selector additionally verifies the direct client's loopback address. Disabled identities cannot select a session or read protected resources. Unknown and inaccessible source/packet IDs use the same outward failure.

Run with `--host 127.0.0.1 --no-proxy-headers --no-access-log`. Forwarded identity headers confer no authority; proxying the default configuration onto the internet is unsupported (the opt-in hosted demo mode below is the only exception). Local HTTP cookies do not have the Secure flag because this configuration serves loopback HTTP. Disabling `ASPIRE_DEMO_MODE` without a real identity provider fails closed for protected resources.

Sensitive responses use `Cache-Control: no-store`. Persona changes clear displayed results and obsolete in-flight browser responses. Output is inserted as text; Jinja2 escaping and a restrictive CSP avoid interpreting source/provider HTML. No unrestricted corpus directory is served. Ordinary Uvicorn access logging is disabled in the documented command to avoid unnecessary source/request URL records.

## Hosted demo mode (opt-in)

`ASPIRE_HOSTED_DEMO=true` runs the demo as one shared public instance behind a TLS-terminating proxy, such as a Hugging Face Docker Space ([deploy note](../deploy/huggingface/README.md), repository `Dockerfile`). It is off by default. When it is off, nothing above changes: only loopback hosts are accepted and only loopback clients may change persona, and `ASPIRE_ALLOWED_HOSTS` is ignored.

When it is on:

- **Hosts.** Only the exact hostnames in `ASPIRE_ALLOWED_HOSTS` are accepted. Wildcards and ports are rejected at startup, and loopback names are refused unless listed. A refused host is audited as `host_not_allowed` instead of the local `invalid_host`.
- **Personas.** Any visitor may pick a demo persona, because every visitor arrives through the proxy. Each browser session holds its own persona. The selector still authenticates nobody. The allowlist, the disabled-identity check and the server-side role lookup are unchanged.
- **Cookies and transport.** The session cookie gains `Secure`, alongside `HttpOnly` and `SameSite=Strict`, and responses carry HSTS.
- **CSRF and Origin.** Behind the proxy the app sees plain HTTP while the browser's Origin is `https://…`. In hosted mode only, the first `X-Forwarded-Proto` value is trusted as the request scheme, and it must be `https`; otherwise the state change is refused and audited as `insecure_transport`. The CSRF token and the exact `https://<allowed host>` Origin are still both required. This trust is sound only when the proxy is the sole ingress and overwrites the header. A client that could reach the app directly could set the header, but it would still need a valid session token and a matching Origin. Uvicorn runs with `--no-proxy-headers`, so the client address and the scheme in the request scope stay as received.
- **Provider and data.** Only `offline_extractive` over the fictional fixture may run. Startup is refused when any of these is configured: another provider mode, a provider service or key path, `ASPIRE_PLATFORM_SOURCE` other than `fixture`, or `ASPIRE_CONNECTORS_CONFIG`. An injected provider that is not offline is refused when the app starts. No live model, credential or real platform account is reachable.
- **Keys and storage.** The container runs `init-demo` at every start, so each start gets new session, audit and payload keys and a newly seeded database. The free tier's disk is ephemeral, so nothing survives a restart, and there are no Space secrets.

What visitors share, and what the published link should say:

- **One instance and one database for everyone.** Revocation, sync and upstream-change actions are global. A source one visitor revokes is hidden from every visitor until the next restart.
- **The audit log records every visitor's activity.** That includes query attempts and outcomes, and the protected case payloads that officer inquiries read. Anyone may choose the auditor persona and read the demo tenant's safe audit trace. Visitors should enter nothing real.
- **Restarts reset everything,** including rebuilds, sleep after inactivity and platform maintenance. The audit chain and its keys start over, so there is no continuity of evidence across restarts.
- **No framing.** `frame-ancestors 'none'` and the strict cookie stay as they are, so the app works only at its direct `*.hf.space` URL, not inside the Hugging Face Space page's iframe.

Hosted mode isn't a production deployment. It has no real identity provider, rate limiting, abuse controls, per-visitor isolation or durable audit storage.

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
| `completeness_unproven` | `false` only when an audit witness is configured, the chain and the witness both verify, every event is witnessed and any supplied checkpoint verifies. Completeness is then relative to the witness. Otherwise `true`. |
| `witness` | Whether a witness is configured, the witnessed head sequence, how many newest events are not yet witnessed, `truncation_detected` when a witnessed event is missing from the database, and `checkpoint_rollback_detected` when a supplied checkpoint no longer verifies. |
| `incomplete_requests` | Observed query or protected-read attempts with no terminal event in the inspected chain. |

The audit witness (`ASPIRE_AUDIT_WITNESS_PATH`, key at `ASPIRE_AUDIT_WITNESS_KEY_PATH`) is an append-only file, chained under its own key, that records each committed chain head right after the commit. Removing or rewriting the newest events in the database alone then fails verification, and the officer inquiry refuses to run on a chain that fails. A process that stops between a commit and the witness write leaves one unwitnessed event, which the report shows. The witness protects only as far as its storage is separate: keep it on storage the database's writers cannot change. The witness proves only its own prefix: someone who can write both stores can delete the newest events from both, with no key, and verification still passes. Someone holding both stores and both keys can rewrite both. Retain a checkpoint independently before an incident if you need to detect rollback through it. Keeping it beside the mutable database is not independent trust. Even a valid checkpoint cannot establish completeness of a later unanchored tail. Deleting an unanchored final suffix can leave a valid chain. Someone who holds both database write access and the audit key can forge a replacement chain. Protected simulated case audit payloads now use a separate AES-GCM key, but the ordinary owner-restricted packet table still stores answers in local SQLite. This prototype does not provide comprehensive encryption at rest or an immutable/compliant audit store.

Protected officer inquiry is paged rather than silently truncated. A match set larger than the page size returns `has_more` and a continuation cursor that is HMAC-signed and bound to both the tenant and the exact search filters, so a cursor cannot be replayed across tenants or against a different query. Ordering is stable on `(timestamp, request ID)`, so equal timestamps neither drop nor duplicate an entry across a page boundary. Integrity and retention state are re-checked on every page, and a cursor that fails validation is rejected rather than silently restarted. Retention is scoped to the encrypted protected payloads only: plaintext packets, exports and backups have separate lifetimes and are not covered by it.

## Adversarial seed suite (measured)

The dated measurements below are historical; current test verification is in the
[13 October report](reviews/submission-checklist-2026-10-13/README.md). `artifacts/` and
`var/` evidence references are local, Git-ignored files rather than repository
attachments. Current source and test fixtures are self-contained.

A deterministic red-team seed suite runs against both local query paths: `eval/redteam/`
(versioned, schema-validated playbook, currently **1.4.0** / schema 2; the measurement below was taken at 1.3.0 and the 1.4.0 changes are in the 28 September update further down), `tests/redteam/test_redteam_playbook.py`, the
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

`.env`, keys, database files, exports, checkpoints, virtual environments and test/runtime artifacts are ignored by Git. Configuration creates private files with mode `0600` on POSIX; keep equivalent user-only filesystem permissions on Windows. Back up the database, audit key and protected-payload key securely for recovery, while retaining trust anchors separately. Losing the audit key prevents verification of the old chain; losing the payload key prevents decryption of protected inquiry records. Key rotation and production backup policy are not automated. The connector source reads platform tokens only from a file outside the project that only its owner can read, and only when its configuration says `"allow_live": true`. Each user's token reads only that user's view; the application never holds an administrator credential, so a platform permission it was not given cannot be borrowed for another user.

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

This historical review snapshot is kept once, in section 5 of [SUBMISSION.md](submission/SUBMISSION.md), to avoid divergent copies.
