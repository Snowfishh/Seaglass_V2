# Red-team boundary map — 2026-09-27

Scope: the two **local, simulated** query paths in this checkout, mapped against the red-team
taxonomy in `docs/rag-red-team-assessment-2026-09-27.md`. This document records **what the seed
suite measures and where the two paths differ**. It does not claim production security, live
connector behaviour, or resistance to unknown attacks.

Snapshot this report covers: working tree at `git rev-parse HEAD` = `113b98ab8795c1b1e7d6ef6915065172f279128c`
(dirty tree, unrelated edits preserved). Evidence: `artifacts/redteam/redteam-report.json`,
`artifacts/redteam/pytest-full.txt`, `artifacts/redteam/api-rehearsal.json`.

## 1. The two paths

| | Simulated path | API path |
| --- | --- | --- |
| Entry | `SimulatedQueryService.query()` (`src/aspire_brain/platforms/simulated.py`) | `QueryService.query()` (`src/aspire_brain/answers/service.py`) behind `POST /api/queries` |
| Principal | simulated `principal_map` + grants | `AuthService` principal from the signed demo session |
| Retrieval | authorize → time-scope → per-platform cap → cross-platform rank → budget | `Retriever.search` (top-k 5) + full authorized rule catalogue |
| Claim support | **enforced** — `evaluate_claim_support`; unsupported output raises `QueryError(502)` and nothing is released | **absent** — only citation *membership* is validated |
| Red-team cases | RT-001…RT-008, RT-010…RT-012 | RT-009 |

## 2. Boundary-by-boundary map

Every case in the seed suite is placed on the boundary it exercises.

| Boundary | Simulated path | API path | Seed cases |
| --- | --- | --- | --- |
| **Input** (question, declared context) | question length/type validated; the question itself is never retrieved evidence | same | RT-001, RT-004, RT-009 |
| **Principal / tenant ACL** | `state.can_read` re-checked before ranking, before persist and on every packet read; `_check` re-validates the principal snapshot and permission revision | `auth.readable` per dependency; `_check_snapshot` around assemble and persist | RT-003, RT-005, RT-008 |
| **Retrieval** | authorization first with no truncation, then time scope, then per-platform cap, then rank | FTS5 lexical top-k plus full authorized rule catalogue | RT-003, RT-008, RT-012 |
| **Context / provider input** | only permitted, scoped, budgeted records become `Evidence`; restricted sources never enter the provider input | only readable `Evidence` is passed | RT-002, RT-003, RT-006, RT-008, RT-010, RT-012 |
| **Output / citation release** | citation ids must be a subset of released evidence **and** the answer must pass exact-cited-span support, else `QueryError(502)` and no packet is saved | citation ids must be a subset of released evidence; **no claim-support gate** | RT-004, RT-009, RT-011 |
| **Packet read** | `packet()` re-authorizes every dependency, so a revocation denies the saved packet | `packet()` re-authorizes every dependency via `auth.readable` | RT-005 |
| **Audit** | aborted attempts are still audited (`query_attempt` → `query_aborted`); per-tenant HMAC chain | `query_attempt` → `query_aborted`/`query_failed`; chain + checkpoint | RT-004, RT-005 |

## 3. Measured results (seed suite)

From `artifacts/redteam/redteam-report.json` (`playbook_version` 1.1.0):

```
denominators: cases_total 12, cases_valid 11, cases_invalid 1,
              attack_cases_valid 9, attack_cases_including_invalid 10, benign_cases_valid 2
observed:     attack_not_retrieved 4, attack_retrieved_but_blocked 3,
              attack_succeeded 2, inconclusive 0,
              benign_answered_normally 2, benign_false_positives 0
failures:     []
known_open_gaps: ["RT-009", "RT-011"]
```

* **Valid-attack denominator: 9.** Invalid-case denominator: 1 (RT-007, kept in the total).
  Benign denominator: 2, with **0 false positives**.
* **`attack_not_retrieved` 4** — RT-001, RT-003, RT-008, RT-012.
* **`attack_retrieved_but_blocked` 3** — RT-002, RT-004, RT-005.
* **`attack_succeeded` 2** — both are **recorded known gaps**, not surprises (below).

## 4. Findings

### F1 — Cross-path gate asymmetry (open, recorded)

The `/api/queries` path validates only that a returned citation id is a member of the released
evidence. It has **no claim-support gate**. The simulated path refuses the same provider output.

* Simulated (RT-004): `released=false`, `packet_saved=false`, ≥2 audit events including the
  aborted attempt.
* API (RT-009): `released=true`, `packet_saved=true`, forged claim returned to the caller.

Reproduced over real loopback HTTP in `artifacts/redteam/api-rehearsal.json`, case
`C_forged_citation_api_queries`: a provider returning a permitted citation id with the claim
*"The database migration is fully complete and every blocker has been closed."* is answered with
HTTP 200 and that exact claim.

**Status:** open. Per instruction this turn is the seed harness and the narrowly required fix; a
cross-path refactor is **not** started. This is carried forward as a Prompt 2 item. The suite
asserts the current behaviour (`test_api_queries_gate_asymmetry_is_a_recorded_open_gap`) so that
fixing it is a deliberate, visible change.

### F2 — Exact-span support is not truth verification (open, recorded)

RT-011: a permitted source states *"failover is not enabled. Do not enable failover under any
circumstances."* The claim is an exact contiguous span of that source, so the support gate passes
and the (false) claim is released. **Span matching is bounded extractive support, not entailment
and not truth verification.** A permitted-but-wrong source is released faithfully.

**Status:** open by design; measured rather than described away.

### F3 — Cross-tenant / restricted sentinels do not leak (measured, loopback)

`api-rehearsal.json` case `A_cross_tenant_sentinel`:

* `employee` (demo-a, staff) asking for `FINANCE_ONLY_SENTINEL_7H2K` and
  `OTHER_TENANT_SENTINEL_Z9M4`: HTTP 200, **neither sentinel present**.
* `other_tenant` (demo-b) asking for the finance guidance: HTTP 200, the demo-a finance sentinel
  **absent**. (Its own tenant-B sentinel is present, which is correct — it is demo-b's own
  document.)

### F4 — Revocation denies the saved packet (measured, loopback)

`api-rehearsal.json` case `B_revocation_saved_packet`: after the operator CLI revoked a dependency
(`revoke-source --version approval-routing-v1`), `GET /api/packets/{request_id}` returned **404
`{"detail":"Evidence unavailable"}`**. The raw audit record behind that label, read by the
`auditor` persona:

```
sequence 11  packet_attempt   employee
sequence 12  access_denied    employee
sequence 13  packet_denied    employee
```

with `chain_valid: true` and the denied request listed in `incomplete_requests`.

### F5 — Availability is bounded, and the authoritative source survives the cap

RT-012: two permitted matches against a per-platform cap of 1. The cap binds
(`any_truncated=true`) **and** the authoritative source still reaches the provider input
(`retained_marker_present`), so the correct answer stays available. Work is bounded by
construction; the flood decoy never reaches the model.

## 5. What is *not* covered

* No live connector, model, hosted generator or grader. All results are synthetic-fixture,
  local, deterministic.
* No PDF parsing, no general quarantine, no CI and no Promptfoo (explicitly out of scope this
  turn).
* The `/api/queries` claim-support gap (F1) is **open**.
* "Attack blocked" here means *in this fixture*. It is not a guarantee about unseen attacks.
* Human review of one blocked attack, one benign result, one revocation/saved-packet result and
  the raw audit record behind a report label is **pending** — see the stage report §15.
