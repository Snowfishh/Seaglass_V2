# WorkBuddy output review — 27 September 2026

The reported G3 results reproduce, but passing tests do not close every acceptance gap.
During this review the shared checkout advanced to G4. The final handoff therefore preserves
that newer implementation and requires the confirmed G3/G4 fixes below before G5 packaging.
This review changed documentation and saved independent probes; it did not fix application code.

## Verified evidence and scope

- Root PDF SHA-256: `becf449ce534fab6507f85f38aa50b85b210774cd578cdd2880c4240f71ab785`.
  Pages 15–19 and 35–38 were reread. Technical examples are chosen acceptance targets;
  page 19 permits alternatives and page 35 calls challenge-specific submission items optional.
  Product-use proof, conversation history and at least three authentic chat screenshots remain
  required submission items. Organiser acceptance of simulation and the exact cutoff are unknown.
- Earlier G3 state: **277 passed, 92.22% statement coverage**, reproducing the supplied claim.
  The saved G3 transcript, measurements, browser harness and fourteen-assertion result exist.
  Case 2 really observes the updated answer at ingestion time; Case 6 really executes a late
  simulated synchronization and query. Earliest visibility and live latency remain unmeasured.
- Newer G4 state: **318 passed, 92.74% statement coverage** in a fresh independent run.
  Ruff passes. `pip check` passed; it checks dependency consistency, not vulnerabilities.
  One existing Starlette TestClient deprecation warning remains. Original offline scenarios:
  **22/22 passed** in the isolated review runtime before the G4 refresh.
- New coverage files: `artifacts/codex-review-20260927-coverage.json` (G3) and
  `artifacts/codex-review-20260927-g4-coverage.json` (G4). The same full-suite command was used
  with a unique `COVERAGE_FILE` and JSON output for each snapshot:
  `.venv/bin/python -m pytest --cov=aspire_brain --cov-report=term-missing --cov-report=json:<path> -q`.
- A real browser interaction verified employee Cases 1, 2, 3, 4 and 6, including omitted
  coverage, event-time scope, corrected freshness labels, denied output and saved-packet
  revocation. This is a separate manual rehearsal, not a new claim of 14 automated assertions.
  Following the explicit updated G4 request, a fresh CUA browser rehearsal also reproduced
  **16/16 rendered checks** for Case 7/runtime/claims/abstention, Cases 1/2/6 and officer
  Case 5/retention/anchoring. Its record is `artifacts/codex-review-20260927-g4-browser.json`.
  It used browser UI actions rather than rerunning WorkBuddy's original Playwright harness.
  Application screenshots are not product-use proof.
- Temporary demo: `http://127.0.0.1:8771/cases`, with isolated runtime
  `/private/tmp/seaglass-review-20260927-au6f6uo2`. The server was restarted after G4 appeared
  so subsequent page loads use current code. It is intentionally left running for human review.
  It is a localhost demonstration, not publication or a live connector. Current server PID:
  `3568`, tool session `63110`; stop that dedicated process with Ctrl+C or `kill 3568`
  after checking that the PID still belongs to this server.

The updated G4 summary was checked separately: the three focused test files contain
10 + 14 + 13 = **37 tests**, all covered by the passing full suite. A fresh
`evaluate-grounding --offline` run reproduced **3 cases / 5 claims**, 5 supported by the
proxy, 0 unsupported, 1 abstention and the detected negative control; saved as
`artifacts/codex-review-20260927-grounding.json`. The claimed changed-path 91-test run is
present in the stage report; the full run covers those files without rerunning that exact
subset. The earlier coverage-combine sandbox failure is historical source material, not an
independently reproduced failure: both review coverage runs succeeded in the sandbox.

## Confirmed findings

The reproducible probe is `artifacts/codex-review-20260927-probes.py`; run it with
`.venv/bin/python artifacts/codex-review-20260927-probes.py` from the project root.
Results are retained in `artifacts/codex-review-20260927-probes.json`. All probe databases
are disposable under `/private/tmp`; no shared application data was modified.

| Priority | Finding and evidence | Required correction |
|---|---|---|
| P1 | **Saved metadata bypasses revocation.** In `platforms/simulated.py`, `_persist()` records dependencies only for answer evidence, while `_budget_report()` and `_apply_time_scope()` expose other source IDs. After a one-item query, revoking Jira issue `OPS-17` makes `can_read` false, yet `packet()` still returns `jira:OPS-17:OPS-17:v1` in `dropped_ids`. | Recheck every outward-facing source reference, or move sensitive diagnostic IDs to officer-only payloads. Cover budget drops, out-of-window/unscopable metadata, abstained packets and in-flight changes. |
| P1 | **Lexical support accepts contradictory claims.** `providers/claims.py` removes negation through `STOPWORDS` and accepts 60% token overlap. The probes mark `Failover is enabled` supported by `Failover is not enabled` (1.0), `900 SGD` supported by `100 SGD` (0.75), and `Alice approved Bob` supported by `Bob approved Alice` (1.0). `SimulatedQueryService` relies on `all_supported` before release. An end-to-end injected provider returned `900 SGD` against `100 SGD` evidence; the service returned `answered`, `all_supported=true`, and persisted that incorrect answer. The code labels this a proxy, but the stronger assertion that unsupported claims fail closed is not established. | Use a conservative, verifiable support contract for the local provider, such as exact source spans with service-controlled formatting. Add adversarial controls; report semantic entailment as unmeasured unless separately established. |
| P2 | **Candidate truncation precedes time scope and final ranking.** `SimulatedPlatformState.candidates(limit=5)` runs before `_apply_time_scope()` and `rank_candidates()`. Five old equal-scoring Slack records exclude a sixth readable recent record; the query abstains with `degraded=false` and zero reported drops. Candidate scoring also retains stopwords before G3's stopword-free ranking. | Authorize, apply event-time scope, then apply consistent ranking and documented bounds. If retrieval must cap earlier, expose safe truncation/coverage semantics and avoid claiming all permitted candidates were ranked. |
| P2 | **Officer search cannot continue past its first 100 matches.** `ProtectedAuditStore.inquire()` returns `matches[:100]` and `has_more`, with no cursor/offset argument or continuation field in the HTTP interface. A 101-query fixture returns 100 entries and `has_more=true`. | Provide deterministic, tenant-bound pagination with stable tie-breaking and no loss at equal timestamps; retain integrity checks on every page. |

## Existing work and remaining boundaries

Encrypted exact-question/full-answer reconstruction, allow/deny decisions and subject/platform/
space/document/time filters existed before G4. G4 now adds `audit/retention.py`, retention
operations, a local `fake_grounded` provider, runtime gates and Case 7. These should be repaired
and extended only where evidence shows a gap, not rebuilt.

Retention currently targets encrypted audit payloads through an explicit operator action.
It does not erase plaintext answers in ordinary packet tables or backups, and protected inquiry
still covers simulated case queries only. Preserve those limits in the package and make the
runbook identify when retention is actually applied. Local checkpoint export/verification
already exists; independently protected anchoring remains a separate, unverified boundary.
The live transport is unimplemented even after entitlement gates pass; a fake-provider success
cannot complete the original live G4 acceptance criterion.

The original audit subagent completed its G2/G4 scope comparison. A second code-review agent
and the pagination follow-up hit their usage limit; the findings above were subsequently
verified directly with source inspection and the saved probes. No completed independent
security sign-off is claimed. No live provider/platform, spend, credential change, publication
or submission was performed.

The updated [next prompt](workbuddy-next-prompt.md) makes these corrections prerequisites,
preserves the newer G4 work, and then proceeds to the local G5 rehearsal and submission draft.
