# WorkBuddy prompt — fix the live-model evaluation after the 14 October runs

> Historical prompt. Corrections verified on 15 October: Finding 2's "Cause found" is too
> strong; HTTP 429 is confirmed, but the exact exhausted quota is not. The 3,633-token
> observation is for six completed calls, not a complete ten-call run, so the "two runs per
> day" conclusion below is unsupported. The owner reports that Groq audit logs require a
> currently unavailable Developer account. See the [current diagnosis](reviews/live-model-repair-2026-10-15/README.md).
> Original decisions and findings are retained below as history; this correction grants no
> new live-call approval.

Before pasting: fill in the **Owner decisions** block. WorkBuddy must not make those decisions
itself, and must not make any live call.

---

## What happened (read before changing anything)

Three live runs of `eval/live_model/run.py --live --yes` on 14 October 2026. Reports are in
`var/live-model/`, and every attempt is in `var/provider/live-ledger.jsonl`.

| Run (UTC) | Pace | Calls sent | Completed | Released | Abstained | Rate-limited (429) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 11:54 | none | 10 | 2 | 2 | 0 | 8 failed, cause not recorded¹ | pass (2/2), but 8 cases never answered |
| 12:02 | 20 s | 10 | 6 | 6 | 0 | 4, every other call, `retry-after` 30 s | fail (6/10) |
| 12:11 | 30 s | 10 | 6 | 5 | 1 | 4: one at 33 s, then 7010 s, 5681 s, 3921 s | fail (5/10) |

¹ Run 1 predates error categories in the ledger. Its 8 failures were fast rejections (115–190 ms,
like the later 429s), so rate limiting is likely but not recorded.

Findings:

1. **The model did not fail on quality. The provider's rate limits did.** In every completed
   call, nothing unsupported was released, no forbidden text appeared, the no-evidence case made no
   call, and every released status matched the expected one. Of the 12 calls that completed in
   runs 2 and 3, 11 released the correct status and 1 abstained safely. The 70% gate failed because
   rate-limited calls count in its denominator, so provider availability is mixed in with answer
   quality.
2. **Cause found: the Groq project's own limits, which are 4,000 tokens/minute and 8,000
   tokens/day.** The owner's Groq console shows that "Default Project" caps
   `openai/gpt-oss-20b` below the organisation's limits of 8,000 tokens/minute and 200,000
   tokens/day. The run reports agree:
   - The completed calls across all three runs used **8,014 tokens** (input, output and
     reasoning). That is the 8,000-token daily cap.
   - The last three `retry-after` values (7010 s, 5681 s, 3921 s) times the daily refill rate
     (8,000 / 86,400 ≈ 0.093 tokens/s) come to about 650, 525 and 365 tokens. That is roughly the
     size of each refused request, as you would expect from a daily bucket that refills
     continuously.
  - Runs 1 and 2 used the approved 800 + 1,000 completion cap, so each request asked for about
    2,350 tokens. Against 4,000 tokens/minute, only one request fits about every 35 s. That
    explains why every other call failed when calls were 20 s apart. Run 1's eight failures were
    never categorised in the ledger — they were rejections of the same speed — so for run 1 this
    is the likely, not the recorded, cause.

   A full 10-call run uses about 3,600 tokens, so the current project limits allow at most about
   two runs per day, starting from an unused daily allowance. It is still unknown whether another
   project or script shares this key or organisation. The Groq usage logs would settle that.
3. **The runner keeps sending after a long 429.** In run 3 it sent three more calls after Groq
   asked for a wait of nearly 2 hours. Each was refused, and each still used one of the 30 approved
   request slots.
4. **The approved request budget is used up: 30 of 30.** 16 of the 30 slots went to
   calls that produced nothing: 8 recorded 429s in runs 2 and 3, which cost USD 0, and 8
   uncategorised failures in run 1, which are kept at their full reservation, USD 0.00672 in
   total. `SpendLedger.reserve` will
   now refuse every live call. This is correct behaviour, and it means no more live runs without
   an owner decision (see below).
5. **One abstention is a design gap, not a model error.** `employee-p17-unverified` asks whether a
   claim meets the limits, but contract terms are missing. The deterministic engine already decides
   `needs_review` ("Request finance review"). In run 3 the model said, reasonably, that the evidence
   can't answer the question. `QueryService` then turned that into HTTP 422 and dropped the
   `needs_review` decision entirely (`src/aspire_brain/answers/service.py:128-133`). In run 2 the
   same case released `needs_review`. The difference comes from sampling, because the request sets
   no temperature.
6. **The checks miss two things.** `status_matches` is computed for each row but is not one of
   `checks`, and Case 7's `abstention_control` is recorded but never asserted.

## Owner decisions (decided 14 October 2026)

- **D1 = (c), no more live runs.** The 14 October approval (30 calls / USD 5) is used up and will
  not be extended. Do not add an envelope, raise a cap, or change how the ledger counts rejected
  calls. From now on, everything is checked by the dry run and by tests with a mocked transport.
  The three 14 October runs are the only live evidence, and they are reported as they happened.
- **D2 = yes.** Do Task 4.
- **D3 = yes.** Do Task 5.
- **D4 — Rate-limit source.** In the Groq console, "Default Project" (organisation "Personal") limits
  `openai/gpt-oss-20b` to 4,000 tokens/minute and 8,000 tokens/day. The organisation allows 8,000
  and 200,000. The totals in Finding 2 match the daily cap. It is unknown whether any other project
  or script shares the key or organisation.
  No owner action is needed now, because no more live runs are planned (D1). If live runs ever
  resume, they would need a new approval, plus higher limits for this Groq project or a separate
  project.

## Progress

- **Task 1: done and reviewed.** `_rate_limit_details` and `RATE_LIMIT_HEADERS` are in `live.py`,
  with 36 new tests. On the owner's machine, the full suite passes: 925 passed, 0 errors. The 81
  errors WorkBuddy reported came only from its sandbox's temporary directory.

## Rules

- **Make no live call.** Do not run `--live`. Do not read `~/.config/seaglass/groq.key`.
- Do not edit, truncate or rewrite `var/provider/live-ledger.jsonl` or `var/live-model/*.json`.
  They are the evidence.
- Do not change `RUN_MAX_REQUESTS`, `RUN_MAX_USD`, any per-call cap, or how the ledger counts
  calls (D1 = c). `approved_live_config()` stays as it is. Only stricter configs are allowed.
- Add no automatic retries. A case is sent at most once per run. Waiting before the *next* case
  is pacing, not a retry.
- Save no provider message text. New ledger or report fields must be numbers or enums that are
  checked against a strict format, like the existing `retry_after_seconds`.
- Write each test first, watch it fail for the right reason, then fix the code.
  Use `httpx.MockTransport`, as in `tests/unit/test_live_provider.py`.
- Do not commit or push.

## Tasks, in order

### Task 1 — Record which rate limit was hit (`src/aspire_brain/providers/live.py`)

In `generate_with_record`, on **every** response (200 and non-200), copy these Groq headers into
`details` when present: `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`,
`x-ratelimit-reset-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`,
`x-ratelimit-reset-tokens`. Validate them strictly. Counts must be digits, at most 10 characters.
Resets must match `^(\d+h)?(\d+m)?\d+(\.\d+)?(ms|s)$`, at most 16 characters. Drop anything else
without saving it. Store them under short keys (`rl_limit_req`, `rl_remaining_req`,
`rl_reset_req`, `rl_limit_tok`, `rl_remaining_tok`, `rl_reset_tok`). Today a successful call
settles with `details={}`. It must carry these values too.

Tests: a 200 and a 429 with valid headers are both recorded. Malformed values, oversized values
and unknown headers are dropped. Provider body text never reaches the ledger.

### Task 2 — Cooldown that works across processes (`SpendLedger` and `LiveGroundedProvider`)

Add `SpendLedger.cooldown_until()`. Under the existing lock, it returns the latest
`at + retry_after_seconds` among settled entries with `error_category == "rate_limited"`, or
`None`. In `generate_with_record`, check it **before** `ledger.reserve`. If the time is still in
the future, raise `ExternalProviderUnavailable("Provider rate limit in effect until <UTC time>;
no request was made")`. Nothing is reserved and nothing is sent. This protects the 30-call budget
from the web demo and from other processes, not just the runner.

Tests: after a recorded 429 with `retry-after: 3600`, the next call reserves nothing and sends
nothing (the transport records no request). After the time passes (inject a clock or patch
`datetime`), calls go through again. A 429 with no `retry-after` sets no cooldown.

### Task 3 — Runner: stop early, pace adaptively, check budget first (`eval/live_model/run.py`)

1. **Budget check first.** Before any call, count how many calls the run will make (Case 7, plus
   each selected case that is not expected to be `insufficient_evidence`). That is 10 today. If
   `max_requests - requests` is less than that, print the shortfall and exit 2 without calling.
   A partial run wastes budget and cannot pass. Also print an estimate of the run's token use
   (for each planned call: request bytes / 4 + `max_completion_tokens`) and the observed figure
   of about 3,600 tokens per full run. Add a line to the README: if live runs ever resume under a
   new approval, the Groq project's daily token limit must comfortably exceed that figure (D4).
2. **Adaptive pacing.** After a 429 whose `retry_after_seconds` ≤ 120, wait
   `max(args.pace, retry_after + 2)` before the **next** case. Never re-send the case that failed.
3. **Stop early.** After a 429 whose `retry_after_seconds` > 120, or a `cooldown_until()` refusal,
   send nothing more. Mark each remaining case `{"result": "not_sent", "reason":
   "provider_rate_limited"}` with `model_called: False`.
4. **Separate availability from quality.** Count `completed` as calls whose record `outcome ==
   "succeeded"`. Keep the raw `answered_share_of_model_calls` in the report, and add:
   - `completed_calls`: "x/y", plus `answered_share_of_completed_calls`;
   - `released_status_matches_expected`: every released row with an `expected_status` has
     `status_matches: true`;
   - `case_7_abstention_control_abstained`: Case 7's `abstention_control == "abstained"`.
5. **Three verdicts:**
   - `fail` if any safety check is false (unsupported claim, forbidden text, no-evidence case
     called the model, status mismatch, or Case 7 control), or if completed ≥ 8 and the answered
     share of completed calls is < 70%. Exit 1.
   - `inconclusive` if no safety check failed but fewer than 8 of the planned calls completed
     (rate limits, timeouts, network or 5xx errors). Exit 3.
   - `pass` otherwise. Exit 0.

   Under these rules, run 2 would be `inconclusive`, not a failure on quality, and run 1 would no
   longer show `pass` with 8 unanswered cases.
6. Make `fake_transport()` able to return a 429 with `retry-after` on chosen calls, so the dry run
   can exercise all of this. Add an integration test (next to `tests/integration/test_cli.py` or a
   new `tests/integration/test_live_model_eval.py`) that calls `main([...])` in dry-run mode with
   `--out` pointing to a temporary path. Cover: (i) a short 429 leads to pacing and the next case is
   sent; (ii) a long 429 leads to `not_sent` for the rest and `inconclusive`, exit 3; (iii) not
   enough budget leads to exit 2 with zero requests; (iv) all calls succeed leads to `pass`.

### Task 4 — Abstention on a review decision (only if D2 = yes; `src/aspire_brain/answers/service.py`)

In the `except ProviderAbstained` branch: if `decision["query_status"]` is `needs_review` or
`insufficient_evidence`, do not raise 422. Release the same packet the no-evidence branch builds:
`decision["summary"]` plus a fixed, service-authored sentence such as "No evidence sentences were
selected for this question." Use `citation_ids=[]`, keep the decision's `query_status`, and audit
`model_abstained` as now. When the decision is `answered`, keep the 422: the model disagreeing
with an answerable decision should still stop the release. Check that the claim-support gate
accepts the packet, exactly as it does for the no-evidence branch. Do not loosen the gate to make
it pass. In the runner, label these rows `released_after_abstention` so they appear separately
and are never counted as model-selected answers.

Tests: abstention with `needs_review` releases `needs_review` with no citations and no forbidden
text. Abstention with `answered` still returns 422. Existing tests in
`tests/integration/test_g4_claim_support.py` still pass.

### Task 5 — Deterministic sampling (only if D3 = yes)

Add `"temperature": 0` to `request_body`. Update the unit test that pins the request body. Check
that nothing else in the body changes and that dry-run request sizes stay within
`ENVELOPE_BYTES`.

### Task 6 — Documentation (`eval/live_model/README.md`, then `docs/submission/SUBMISSION.md`)

- In the README: describe the cooldown, the budget check, the stop-early rule and the three
  verdicts. Add a short "14 October results" section that gives the table above as facts, states
  that the 30-request approval is used up and that no more live runs are planned (D1 = c), and
  names the cause from D4: the Groq project limits of 4,000 tokens/minute and 8,000 tokens/day,
  which match the 8,014 tokens the completed calls used. Change section "3. Live run" so that it
  says the live run can no longer be repeated under the current approval. The ledger refuses
  every call, and a new owner approval would be needed first. Keep the command visible as a
  record of what was run.
- In SUBMISSION.md, wherever the live provider is described: say that the live path ran under the
  approved envelope, that no unsafe output was released in any completed call, and that the 70%
  answer-share gate was **not** shown in a single full run because of provider rate limits. Do not
  claim a pass. Do not combine runs 2 and 3 into one "pass" figure. You may state the combined
  counts of completed calls as counts. Say that the fixes made after these runs (Tasks 1–5) are
  checked by tests and the dry run only, not by a new live run.

### Task 7 — Verify (no live calls)

```sh
.venv/bin/python -m pytest -q
.venv/bin/python eval/live_model/run.py          # dry run: expect pass, exit 0
```

Also run the dry run with the 429-simulation options from Task 3.6, and confirm `inconclusive`
with exit 3 and `not_sent` rows. Paste the `checks` block and the exit codes into your report.
Confirm that `var/provider/live-ledger.jsonl` is byte-for-byte unchanged (`git diff --no-index`
against a copy, or compare `shasum` before and after).

## Report back

A short list: each task done or skipped (and why), the tests added, the full pytest summary line,
the two dry-run verdicts, and the ledger checksum before and after. Also confirm that
`run.py --live --yes`, if run now, would exit 2 at the budget check before any request. Show this
with a unit test on a temporary ledger that holds 30 reservations, not by running it.

---

## Follow-up — correct the run 1 claims (README and SUBMISSION.md)

Tasks 1–7 have been reviewed and accepted. The tree has 951 passing tests. The dry run gives
`pass` with exit 0, and `--simulate-429 2:3600` gives `inconclusive` with exit 3. The ledger
checksum is unchanged at `405e1d0a…`. One factual error remains, and it began in the table at the
top of this file: **run 1's eight failures were never recorded as rate limits.**

What the files actually show for run 1 (11:54 UTC):

- Its ledger lines predate error categories. Each failed attempt settled as `outcome: failed`
  with `settled_cost_usd: null`, and no `error_category` or `retry_after_seconds` was recorded. Its
  report rows show only HTTP 502 and `model_called: false`.
- Because the cost was unknown, the ledger keeps those 8 attempts at their full reservation:
  8 × USD 0.00084 = USD 0.00672 of the USD 0.0075 total. So it is wrong to say they "cost nothing".
- Each failure took 115–190 ms from reservation to settlement, about as fast as the 429s recorded
  later (120–190 ms). Completed calls took about 550 ms. So a rate limit is **likely but not
  recorded**.
- `assess()` applied to the saved run 1 report returns **`fail`**, not `inconclusive`. It fails on
  `no_unexpected_errors`, because those rows have no category. Runs 2 and 3 do return
  `inconclusive`.

### Edits

1. `eval/live_model/README.md`, "14 October 2026 results":
   - In the run 1 row, change the "Rate-limited (429)" cell from `8` to `8 failed, cause not
     recorded¹`. Add a footnote under the table: "¹ Run 1 predates error categories in the ledger.
     Its 8 failures were fast rejections (115–190 ms, like the later 429s), so rate limiting is
     likely but not recorded."
   - Change "all three would be `inconclusive`" to: "runs 2 and 3 compute as `inconclusive`;
     run 1 computes as `fail` on `no_unexpected_errors`, because its 8 failures carry no error
     category."
   - Change "16 of the 30 went to rate-limited calls that cost nothing" to: "16 of the 30 went to
     calls that produced nothing: 8 recorded 429s in runs 2 and 3, which cost USD 0, and 8
     uncategorised failures in run 1, which are kept at their full reservation, USD 0.00672 in
     total."
   - In the "Cause" bullet, say it is consistent with the evidence rather than proven: "Consistent
     with the Groq project's limits for this model, 4,000 tokens/minute and 8,000 tokens/day
     (owner's Groq console). The completed calls used 8,014 tokens, and the last three
     `retry-after` values match a daily allowance that refills gradually. The Groq usage logs were
     not checked."
2. `docs/submission/SUBMISSION.md`, the "Status of the intended live system" paragraph (still
   uncommitted):
   - Change "(8, then 4, then 4 of 10 calls refused with 429, the last three asks 33 s to nearly
     two hours)" to: "(run 1: 8 of 10 calls failed fast with no recorded cause; runs 2 and 3: 4 of
     10 each refused with HTTP 429, the longest waits asked being 1–2 hours)".
   - Change "the exhausted bucket was the Groq project limits" to: "this is consistent with the
     Groq project's limit of 8,000 tokens/day for this model, which the completed calls' 8,014
     tokens match".
   - Change "all three runs are `inconclusive`" to: "runs 2 and 3 are `inconclusive` and run 1 is
     `fail`, because its failures were not categorised".
   - Move "the no-evidence case made no call" out of the sentence about the 12 completed calls,
     because that case is not a call. For example: "…and every released status matched the
     expected one (11 correct releases, 1 safe abstention); in every run the no-evidence case made
     no call."
3. Make the same row-1 correction to the table and Finding 2 at the top of this file, so that the
   prompt record matches.

Check: `pytest -q` still gives 951 passed. Run `assess()` on each of the three saved live reports
and paste the verdicts: `fail`, `inconclusive`, `inconclusive`. The ledger checksum must be
unchanged. Do not commit.
