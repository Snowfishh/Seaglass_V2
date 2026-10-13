# 5E fixed synthetic service request — 2026-10-10

Review supplement, 2026-10-12: [human checklist](HUMAN-ACCEPTANCE.md),
[bounded G4 re-audit](G4-REAUDIT-2026-10-12.md) and
[read-only evidence checks](review-evidence-2026-10-12.json) now distinguish
recorded hashes from retained response bodies, parsed output from safe release,
irretrievable external disclosure, historical test snapshots and unresolved
acceptance evidence. Human review remains pending.

The corrected single live attempt passed: Groq and the service returned
**HTTP 200**, the exact synthetic answer and citation passed local validation,
and **one packet was persisted and read back**. There were zero retries or
fallbacks. The response reported 274 input tokens and 56 completion tokens,
including 11 reasoning tokens; the usage-and-rate calculation is **$0.00003735**,
not a vendor billing receipt. The frozen source hashes and local HMAC audit chain
verified after execution. Restarting the entry point refused before credential
read or dispatch and left the ledger, result and audit count unchanged.
See `corrected-live-observation.json` and `corrected-verification.json`.

The original single live attempt failed: Groq returned **HTTP 400** and the
service returned **502**. There was no retry and no packet was persisted or
readable. Usage and actual billing remain unknown; **$0.0003072** is retained as
uncertain cost. The original source snapshot and HMAC audit chain verified after
the attempt. See `live-observation.json` and the full local result linked below.
The local result did not retain the provider error message. A subsequent
read-only inspection found a GroqCloud request-log row with the same model and
displayed attempt time reporting `response_format`: `uniqueItems is not supported`.
This is an indirect diagnosis: the original vendor request ID is null and its
discarded response body cannot be compared to that row. Exact request-level
attribution remains unverified. The historical observation and correction remain
preserved in `http-400-diagnosis.json`.

Post-attempt compatibility review (offline, 2026-10-10): the original body uses
the documented chat-completions endpoint, `openai/gpt-oss-20b`,
`max_completion_tokens`, `reasoning_effort=low`, `include_reasoning=false`, and
`response_format=json_schema` with `strict=true`. Groq documents these fields
and strict mode for this model in its [API reference](https://console.groq.com/docs/api-reference)
and [Structured Outputs guide](https://console.groq.com/docs/structured-outputs).
The inspected project log rejects `uniqueItems`; its link to the original request
is based on model and time rather than a verified request-ID match.
The guide does not establish support for the other original bound and pattern
keywords, so the corrected strict schema uses only the documented object,
string and array structure. Local `ProviderOutput` validation continues to
enforce citation uniqueness, shape, bounds and identifier syntax before the
service claim-support gate. The original response digest cannot recover the
discarded error body. The corrected candidate has a separate once-only state
directory and does not overwrite the original attempt or its proposal.

Subsequent code review added the runtime's controlled `error_category` and
allowlisted provider type, parameter and schema reason to future
`provider_attempt_result` audit events. Tests cover failed attempts, malicious
provider strings and public request rejection. This does not reconstruct or
modify the historical audit row. Raw provider messages, headers, and
credentials remain outside the audit metadata. The original runtime records
`http_error` and the attempt audit records HTTP 400, while its separate
`provider_error` row uses the broad `invalid_or_timeout` code. That historical
code does not establish a timeout and is not rewritten by the later repair.

The original proposal is preserved as `5e-preflight-candidate.json`, with its
pre-attempt verification in `verification.json` and observation in
`live-observation.json`. Those hashes describe the historical source snapshot.
The old builder entry points now refuse to overwrite that proposal; the old
`send_once.py` is blocked by its consumed ledger and source hash checks.

`build_corrected_candidate.py` reproduces `5e-corrected-candidate.json` using
the current shared envelope builder and the included reviewed template.
`send_corrected_once.py` requires the separate `corrected-verification.json`
source snapshot. The corrected body is **1,181 UTF-8 bytes**, SHA-256
`cfacdf3f9bf655f4180b9625221a9d42bd12e609edc36fe2bfed4e3a71c15f49`,
with a byte-plus-envelope bound of 2,205. Its live state directory is fixed at
`var/stage5e-corrected-2026-10-10/`; the original directory remains evidence.

The account holder explicitly authorized one request after local checks, over
the fixed fictional question and source in the candidate. The only destination is
`https://api.groq.com/openai/v1/chat/completions`, model `openai/gpt-oss-20b`.

- Input price: **$0.075 per million tokens**; output and reasoning: **$0.30 per
  million tokens**, verified against [Groq's model page](https://console.groq.com/docs/model/openai/gpt-oss-20b).
  Groq's inclusive `completion_tokens` count is charged once. Missing usage
  detail retains the full reservation as uncertain rather than inventing usage.
- `max_cost_usd=0.01`; full-cap reservation **$0.0003072**. Input cap 3,072,
  output and reasoning caps 128 each, combined `max_completion_tokens=256`.
  The original byte-plus-envelope bound was 2,356; this is not a measured token count.
- The original request was **1,332 UTF-8 bytes**, SHA-256
  `ab73c1062f8be8360ba8427b86aa7beb25832cf6143a416e28a2140bd060f7c4`.
- `groq==1.7.0`, `httpx==0.28.1`; SDK/application/HTTP retries and fallbacks
  are zero. Redirects and environment proxies are disabled. HTTP I/O timeout is
  10 seconds. Every error, including 429 or timeout, ends the attempt.
- The final transport verifies POST, exact URL/Host and the raw request bytes.
  It records a durable exclusive attempt slot in the fixed correction directory.
  Restarting cannot redispatch. Fresh
  source/permission checks and durable audit writes run before and after claiming
  the slot. A post-claim failure consumes the slot even without a network send.
- The synthetic request traverses QueryService retrieval, permission checks,
  exact quotation support, atomic packet/audit persistence and readback. Failed
  provider responses cannot produce a packet. Default configured providers remain
  offline; no general live factory or live connector is enabled.

Credentials are read only at execution from the process environment or the
account holder's identified local key file, which is ignored and unstaged.
The file is treated as data and never executed; no key enters the candidate,
verification packet, reports or audit. Historical verification records state
that the account holder confirmed revoking the exposed key and updating the
local credential before the corrected attempt. This packet contains no
independent vendor revocation evidence; that remains an account-holder assertion.

Corrected snapshot verification: **664 application tests**, **93 red-team tests**,
**92.56% total statement coverage**, Ruff, `pip check`, the release/D-DEF gates,
and both labelled offline evaluations passed. Each changed application module
exceeds 80% coverage. Dependency audit found four distinct advisories in the
pre-existing `cryptography==47.0.0` pin (seven reported entries, including
duplicates). It is now pinned to **50.0.2**, following the
[maintainer's security fixes](https://cryptography.io/en/latest/changelog/).
The corrected locked dependency audit reports zero known vulnerabilities.
Report hashes, dependency versions and 119 source-file hashes are recorded in
`corrected-verification.json`; full local reports are under
`artifacts/stage5e-corrected-2026-10-10/`.

The pre-send verification and live result retain their original hashes. After
the live run, ECC's commit hook flagged fixed mock credential strings in one
integration test. Those fixtures now use temporary random values; the full
664-test suite and Ruff passed again. `postflight-verification.json` records
that sole test-file delta and the final source hashes. Runtime code, candidate,
dependencies and both live attempt records are unchanged by this test repair.
Red-team tests were not rerun in that postflight snapshot; its 664-test result
must not be described as a new 93-test red-team run.

Original snapshot verification: **657 application tests**, **93 red-team tests**, Ruff,
`pip check`, the deterministic release/D-DEF gates and both labelled offline
evaluations passed. Changed application modules each exceed 80% statement
coverage. The dedicated 5E tests cover prices, budget, exact wire bytes, wording
rules, SDK retries, timeout/429, restart, pre/post-claim revocation, post-response
revocation, audit linkage, and mock/live reporting. RED failures were observed
before implementing the module and before repairing the audit/status defects.

The immutable proposal's `prepared_not_run` state is separate from the actual
execution record at `var/stage5e-2026-10-10/result.json`, its attempt ledger and
synthetic SQLite audit database. Review the actual result before claiming a live
success. Inference region, source truth and live connector acceptance remain
unverified. Human acceptance of the resulting observation remains pending.

The user requested a corrected rerun after the HTTP 400 diagnosis. It uses the
same fictional payload, model, endpoint and $0.01 ceiling, with one durable slot
and zero retries. The corrected live result is recorded separately at
`var/stage5e-corrected-2026-10-10/result.json`. Its successful control does not
establish live connector acceptance, inference region or source truth. Human
acceptance remains pending.

Offline usage-guard repair (2026-10-10): known input, inclusive completion and
reasoning limits, plus the output difference when completion and reasoning are
known, are now checked before returning for unknown counters. Regression tests
first reproduced five bypasses in both unit and mock QueryService paths (10
expected failures). After the repair, anomalous usage returns service 502, leaves
zero packets and rejects packet reads; runtime, audit and durable ledger retain
the full $0.0003072 uncertainty. The mock transport receives one request, with
zero retries or fallbacks, and restarting cannot dispatch again. Valid partial
usage retains uncertainty; complete valid usage still charges inclusive
completion once. All 688 application tests and 93 red-team tests pass, with
92.65% total coverage and 89.74% coverage for `preflight.py`; Ruff and `pip check`
pass. This repair used only mock dispatch and does not rerun either live attempt.
See [usage-guard-verification.json](usage-guard-verification.json) for commands
and the repaired source hashes; historical verification records above retain
their original scope.

Evidence review, 2026-10-12: the corrected result and ledger hashes still match
the saved observation; the parsed answer, permitted citations and saved packet
match the source and read-only SQLite rows. The full provider response body was
not retained for either attempt. The corrected `raw_response_sha256` is a
historically recorded digest, not recomputed raw bytes; complete raw-vs-safe
inspection remains unavailable. The direct service runner also did not retain a
raw Seaglass HTTP body. Both disclosures already occurred, and local revocation
cannot withdraw transmitted data; inference region and vendor retention/deletion
controls remain unverified. These gaps are explicit human review items.

The current 119-source manifest matches the postflight snapshot plus the
usage-guard overlay. A fresh explicitly selected offline red-team run passed
93 tests (exit 0, 7.11 seconds, one deprecation warning); its log and hash are
linked by `review-evidence-2026-10-12.json`. This is a current-snapshot rerun,
not a retroactive postflight result. Application tests were not rerun for this
prose/evidence repair; compatible saved usage-guard results remain separately
labelled. Historical attempts, ledgers, audit rows and verification files remain
unchanged. The G4 re-audit supplies a bounded criterion mapping without marking
G4 accepted or changing `needs_review / undetermined` into a business pass.
