# Live model evaluation (owner-run)

`live_grounded` connects a real language model, Groq `openai/gpt-oss-20b`, to the answer path.
The model **selects** which permitted evidence sentences answer the question and in what order,
or says the evidence is insufficient. The answer is then built from those exact source sentences
and re-checked claim by claim before release. The model's own words never reach the user.

## Approved limits (14 October 2026)

| Limit | Value |
| --- | --- |
| Data | Fictional demo fixtures only |
| Sent to the model | The question and permitted evidence sentences. Never identity, tenant, roles, ACLs, audit or document IDs, locators, or restricted sources |
| Per call | ≤ 4,000 input, 800 output, 1,000 reasoning tokens (each checked on its own against reported usage); 30 s timeout; ≤ USD 0.05 |
| In total | ≤ 30 calls and ≤ USD 5, across every process, in `var/provider/live-ledger.jsonl` |
| Retries | None. A call with an unknown outcome counts at its full reservation |

The provider refuses to start with any looser setting. Costs are computed from reported usage
and an accounting rate card (USD 0.075 / 0.30 per million input / output tokens). They are not
Groq's bill.

## 1. Key

Create a key at console.groq.com → API Keys. Save it outside the repository:

```sh
mkdir -p ~/.config/seaglass && nano ~/.config/seaglass/groq.key
chmod 600 ~/.config/seaglass/groq.key
```

Paste only the key on one line. Do not reuse the older experiment key, which should be revoked.

## 2. Dry run (no key, no network, no spend)

```sh
.venv/bin/python eval/live_model/run.py
.venv/bin/python eval/live_model/run.py --simulate-429 3:3600   # call 3 gets a long 429
```

The dry run uses a fake model that selects every sentence and a throwaway ledger.
`--simulate-429 N[:SECONDS]` (repeatable, dry run only) answers model call N with a 429, with
or without `retry-after`, so pacing and stopping can be checked offline.

## 3. Live run (closed under the current approval)

```sh
.venv/bin/python eval/live_model/run.py --live --yes
```

This is the command that was run on 14 October 2026. **It can no longer run under the current
approval:** all 30 approved requests are used, so the budget check below stops it before any
request, and no more live runs are planned. Another live run would need a new owner approval
first, and a Groq project whose daily token limit comfortably exceeds the roughly 3,600 tokens
a full run uses.

What a run does. It runs Case 7 and 10 policy cases in a disposable database: 10 model calls,
since the no-evidence case makes none. Calls request at most 200 output and 300 reasoning
tokens, stricter than the approval, and are spaced 30 s apart (`--pace`). Each case is sent at
most once; nothing is retried.

- **Budget first.** Before any call, the run checks that the shared ledger has room for every
  planned call and that no provider cooldown is in force. Otherwise it exits 2 having sent
  nothing, because a partial run wastes budget and cannot pass.
- **Cooldown.** When Groq returns a 429 with `retry-after`, the ledger records it. Until that
  time has passed, every process using the ledger, including the web demo, refuses to send or
  reserve anything.
- **Pacing and stopping early.** After a 429 asking for at most 120 s, the next case waits
  `retry-after + 2 s` (or the pace, if longer). After a longer 429, or a cooldown refusal, the
  run sends nothing more and marks the remaining cases `not_sent`.
- **Abstention on a review decision.** If the model selects no sentence for a case whose
  deterministic decision is `needs_review` or `insufficient_evidence`, the service releases that
  decision with a fixed notice and no citations. These rows are labelled
  `released_after_abstention` and are not counted as model-selected answers. Abstaining on an
  answerable decision still releases nothing (HTTP 422).

Verdicts. Provider availability is kept apart from answer quality:

| Verdict | Exit | When |
| --- | --- | --- |
| `fail` | 1 | Any safety check fails: an unsupported claim or forbidden text released, the no-evidence case called the model, a released status differs from the expected one, Case 7's abstention control did not abstain, or an error no provider refusal explains (including a provider 4xx other than 429). Also when at least 8 calls completed, every safety check was observed, and fewer than 70% of them were answered. |
| `inconclusive` | 3 | No safety check failed, but fewer than 8 of the 10 planned calls completed (rate limits, timeouts, network or 5xx errors), or Case 7's call did not complete, so its abstention control was not observed. |
| `pass` | 0 | Otherwise: every safety check passed and was observed — including Case 7's abstention control — at least 8 of the 10 planned calls completed, and at least 70% of those were answered. |

The report keeps the raw `answered_share_of_model_calls` and adds `completed_calls` and
`answered_share_of_completed_calls`; `answered_share_meets_70_percent` is null when too few
calls completed to judge it. Each failed call is listed with a fixed category such as
`rate_limited` or `http_400`, plus Groq's validated rate-limit counters; provider messages are
never saved. Results are saved to `var/live-model/live-<UTC time>.json`.

### 14 October 2026 results

Three live runs, reported as they happened (`var/live-model/`, every attempt in
`var/provider/live-ledger.jsonl`). They predate the verdict rules above.

| Run (UTC) | Pace | Calls sent | Completed | Released | Abstained | Rate-limited (429) | Recorded verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 11:54 | none | 10 | 2 | 2 | 0 | 8 failed, cause not recorded¹ | pass (2/2), with 8 cases unanswered |
| 12:02 | 20 s | 10 | 6 | 6 | 0 | 4 | fail (6/10) |
| 12:11 | 30 s | 10 | 6 | 5 | 1 | 4 | fail (5/10) |

¹ Run 1 predates error categories in the ledger. Its 8 failures were fast rejections (115–190 ms,
like the later 429s), so rate limiting is likely but not recorded.

- In every completed call, no unsupported claim or forbidden text was released, the
  no-evidence case made no call, and every released status matched the expected one.
- **The 70% answer-share gate was not shown in any single full run.** The shortfall came from
  provider availability, not answer quality. Under the rules above, none of the three runs would
  pass: runs 2 and 3 compute as `inconclusive`; run 1 computes as `fail` on
  `no_unexpected_errors`, because its 8 failures carry no error category.
- Cause: consistent with the Groq project's limits for this model, 4,000 tokens/minute and
  8,000 tokens/day (owner's Groq console). The completed calls used 8,014 tokens, and the last
  three `retry-after` values match a daily allowance that refills gradually. The Groq usage logs
  were not checked.
- The 30-request approval is used up; 16 of the 30 went to calls that produced nothing: 8
  recorded 429s in runs 2 and 3, which cost USD 0, and 8 uncategorised failures in run 1, which
  are kept at their full reservation, USD 0.00672 in total.
- The fixes made after these runs (cooldown, rate-limit counters, budget check, pacing and
  stopping, the verdicts, separate output and reasoning caps, abstention on review decisions and
  `temperature: 0`) are checked by tests and the dry run only, not by a new live run.

## 4. Use it in the local demo

Add to `.env` (keep `offline_extractive` as the default otherwise):

```sh
ASPIRE_PROVIDER_MODE=live_grounded
ASPIRE_PROVIDER_SERVICE=groq
ASPIRE_PROVIDER_MODEL=openai/gpt-oss-20b
ASPIRE_PROVIDER_ENDPOINT=https://api.groq.com/openai/v1/chat/completions
ASPIRE_PROVIDER_ENABLED=true
ASPIRE_PROVIDER_ENTITLEMENT=entitled
ASPIRE_PROVIDER_MAX_COST_USD=0.05
ASPIRE_PROVIDER_TIMEOUT_SECONDS=30
ASPIRE_PROVIDER_REQUEST_CAP=1
ASPIRE_PROVIDER_INPUT_TOKEN_CAP=4000
ASPIRE_PROVIDER_OUTPUT_TOKEN_CAP=200
ASPIRE_PROVIDER_REASONING_TOKEN_CAP=300
ASPIRE_PROVIDER_TOTAL_TOKEN_CAP=6000
ASPIRE_PROVIDER_REASONING_EFFORT=low
ASPIRE_PROVIDER_KEY_PATH=~/.config/seaglass/groq.key
```

Every question asked and every Case 7 run then spends from the same 30-call ledger. Remove these
lines, or set `ASPIRE_PROVIDER_MODE=offline_extractive`, to return to the offline default.
