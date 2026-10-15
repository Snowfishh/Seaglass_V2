# Live-model evaluation diagnosis and repair — 15 October 2026

Status: runner defects repaired and verified offline; no passing live evaluation claimed.
Base HEAD: `1a16841d20911f536c0a97d8498ac341e4100107`, with existing and concurrent uncommitted work.
This repair owns only the runner, its integration tests, its README, an annotation on the
historical WorkBuddy prompt, and this review directory. No commit or push was made.

## Confirmed causes

1. **Provider refusals prevented completion.** Runs 2 and 3 each contain four recorded HTTP 429
   failures. Their completed calls released 6/6 and 5/6 model-selected answers respectively;
   the other completed call abstained. No recorded release failed the support/forbidden-text
   checks. These partial observations do not establish overall model quality.
2. **The old runner kept dispatching during requested cooldowns.** The ledger shows new
   reservations roughly 20 seconds after a 30-second wait, and roughly 30 seconds after a
   7,010-second wait. Already-committed fixes now honor short waits and stop at long waits.
3. **The old evaluator lost failed attempts.** Run 1 has 10 ledger reservations but its report
   counts only two model calls and says pass on 2/2. Eight failed settlements lack error
   categories. Their exact cause cannot be reconstructed. Existing corrected rules give
   fail / inconclusive / inconclusive for the three saved runs.
4. **All 30 approved calls have been used.** The ledger is preserved; changing code does not
   replenish the approval. The previous owner decision was no further live runs under it.

## What remains unknown

The prior owner-provided account snapshot showed `Personal` / `Default Project`, model
`openai/gpt-oss-20b`, at 4,000 tokens/minute and 8,000/day. Those settings were not refreshed.
The saved reports total 8,014 completed tokens and long cooldowns, consistent with a restrictive
project quota, but they do not identify the exhausted bucket or concurrent consumers.

On 15 October the owner said Groq audit logs are available only with a Developer account,
which is currently unavailable. The available browser session was also signed out. No login,
account modification, quota increase, upgrade, key access, or provider request was performed.
The missing logs remain an evidence limit, not a requirement to buy a plan.
[Groq documentation](https://console.groq.com/docs/rate-limits) confirms HTTP 429 for rate limits;
its documented token headers describe TPM, so those alone would not prove daily-cap exhaustion.

## Repairs made now

- Stop the batch on a 429 with no valid retry-after. Preserve remaining slots as not_sent.
  Known short waits still pace the next distinct case; no case is retried.
- Reject negative, NaN and infinite --pace before ledger or credential access.
- Fail on unexplained/invalid sent-call failures; do not count them as completed calls that can
  hide behind enough successful answers. Known availability failures remain separate, and
  valid model abstentions retain their existing semantics.
- Correct misleading capacity guidance. Actual totals were 990 tokens / 2 completions,
  3,391 / 6, and 3,633 / 6. No complete ten-call token measurement exists. The configured
  upper bound is 45,000 tokens = 10 × (4,000 + 200 + 300), not expected usage or available quota.
  The historical prompt is annotated rather than rewriting its original decisions.

No model, approval cap, request ledger, per-call limit, retry policy or historical result changed.
The runner-level unknown-cooldown stop does not introduce a permanent cross-process lock when
Groq supplies no reset time; a future run still needs its own authorized capacity decision.

## Verification

- RED: 16 regression cases failed, 19 passed before implementation.
- GREEN: 105 focused runner/provider tests passed.
- Full shared checkout: 1,084 tests passed, 92.35% statement coverage over aspire_brain.
  This source coverage excludes the eval script; its behavior is exercised by focused tests.
- Ruff and git diff --check passed. One existing Starlette/httpx deprecation warning remains.
- Independent code/security review: no actionable findings.
- [Normal mocked run](dry-normal.json): 10/10 calls completed, pass.
- [Unknown cooldown mocked run](dry-unknown-cooldown.json): second call returns 429; only two
  calls attempted, later cases not_sent, verdict inconclusive.
- [Hashes and verification](verification.json): all three live reports and the original ledger
  are byte-identical to the pre-repair snapshot. No live calls or credential reads occurred.

## Decision needed before live verification

Keep the current provider/model and free account unless the owner chooses otherwise. A fresh
live pass requires a separately authorized batch after reviewing currently visible limits and
usage (whatever the account makes available). There is no basis to recommend buying an upgrade
or raising a particular quota from the historical data alone.

Proposed bounded option, NOT authorized or enabled: one additional batch of at most 10 calls,
fictional fixtures only, total accounting ceiling USD 0.01, same model and stricter current
4,000 input / 200 output / 300 reasoning caps, no retries, 30-second minimum pacing, stop on
long or unknown rate limits. Preserve the consumed ledger and record any new authorization
separately; never reset or silently extend the old 30-call approval. USD 0.01 is an accounting
limit, not a vendor bill guarantee. The full-cap reservation at the existing rate card is
USD 0.0045. A capacity shortfall can still make the run inconclusive; no pass is promised.

Alternative: stop at offline verification and retain live evaluation as unverified. No external
change or further charge is needed for that option.
