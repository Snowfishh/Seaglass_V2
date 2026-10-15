# Live model over real platform test items (owner-run, prepared, not run)

`run.py` would answer a few fixed questions from the real Confluence, Jira, Slack and Drive
**test** accounts using the `live_grounded` provider (Groq `openai/gpt-oss-20b`). It has only
been built and checked offline: no model call and no platform call has been made with it.

**It cannot run live yet.** Every existing approval covers fictional demo fixtures only. The 14
October live access check read the real test items but sent nothing to any model. A live run
needs the separate approval below. Until that approval is recorded in `run.py`, `--live`
refuses before it opens any token, key or targets file.

## What a live run would do

1. **Read.** Users A and B each read the eight items named in the git-ignored
   `var/live-access/targets.json` (one general and one restricted item per platform). Each user
   reads with their **own** read-only token, through the same connectors, account binding and
   identity check as [`eval/live_access/check.py`](../live_access/check.py). The platform
   decides access.
2. **Check the split.** The run continues only if A read all eight items and B read the four
   general items and was refused all four restricted ones. Any other result, including an
   error or a token belonging to the wrong person, stops the run before any model call.
3. **Build the input.** Each question's model input comes only from that question's items that
   the asking user's token read. It holds the question and numbered sentences of item text.
   The connectors start that text with the page title, issue summary or file name, so these
   are sent too. Item IDs, sites, locators, emails and account IDs are never included; chunks
   are labelled `platform.kind.n`. Long items are cut to whole leading sentences so the request stays within
   the 4,000-token input bound.
4. **Check B's input twice.** For a user refused restricted items, no evidence chunk may come
   from a restricted item, and no sentence may be one found only in restricted items (as A read
   them). This is asserted before dispatch, and asserted again on the request bytes just before
   they are sent. Either failure stops the run, and nothing further is sent.
5. **Ask.** Four fixed questions per user, at most one model call each:

   | Question | Aimed at | Items |
   | --- | --- | --- |
   | `handover-status` | general | Confluence and Slack general |
   | `supplier-payment-review` | general | Jira and Drive general |
   | `beneficiary-exception` | restricted | Confluence, Jira and Slack restricted |
   | `restricted-invoice` | restricted | Drive restricted and Drive general |

   With the expected access split, this means 7 calls: four for A and three for B. B's
   `beneficiary-exception` has no permitted evidence and makes no call. B's
   `restricted-invoice` may use only the Drive general item.
6. **Gate.** The answer is rebuilt from the selected source sentences. It counts as `released`
   only if every claim is an exact span of the cited evidence (the claim-support gate) and
   every citation is in the input. Otherwise it is `blocked_by_claim_gate`.
7. **Pace and stop.** Nothing is retried. Calls are at least 30 s apart (`--pace` can only be
   raised). A 429 asking for at most 120 s delays the next call by `retry-after + 2 s`. A
   longer 429, a 429 without `retry-after`, a ledger cooldown or an exhausted ledger stops the
   run, and the remaining questions are marked `not_sent`.

**Recorded.** Per question: the user, allowed/denied for each of the question's items, the query
status, the cited item labels (`platform.kind`) and SHA-256 fingerprints of the evidence text
sent. Also the access table, the checks, the verdict and the ledger's request and USD totals.
**Never recorded:** document or answer text, tokens, keys, emails, account IDs, site names or
item IDs. This matches the
[14 October live access check](../../docs/reviews/live-access-2026-10-14/README.md). Results go
to `var/live-platform-model/live-<UTC time>.json`.

**Verdict.** `pass` (exit 0) when the access split was as expected, B's input never held
restricted content, nothing unsupported was released, B's restricted-only question made no call,
and all 7 calls completed. `fail` (exit 1) when any of these checks failed. `inconclusive` (exit
3) when calls were rate-limited or failed. Exit 2 means the run was refused before anything was
sent.

## Dry run (no token, key or network)

```sh
.venv/bin/python eval/live_platform_model/run.py --dry-run
```

This uses a fictional four-platform server, a fake model that selects every sentence, and a
throwaway ledger. `tests/integration/test_live_platform_model.py` covers the same flow, plus
these cases: a wrong access split, a wrong-person token, restricted content reaching B (caught
before dispatch and again on the request bytes), the claim gate, abstention, 429 handling,
pacing, input fitting, and refusal without an approval.

## Approval the owner must grant before a live run

Copy, complete and record this approval, for example in a new `docs/reviews/` note. Then set the
three constants at the top of `run.py` to match it.

> **Live platform-to-model approval — date: `____-__-__`**
>
> I approve one owner-run batch of `eval/live_platform_model/run.py --live --yes` at commit
> `________`, sending content from real platform test accounts to Groq `openai/gpt-oss-20b`
> (endpoint `https://api.groq.com/openai/v1/chat/completions`) under these limits:
>
> - **Data source:** only the eight test items named in my local
>   `var/live-access/targets.json`: one general and one restricted item each on Confluence,
>   Jira, Slack and Drive. All contain fictional payment-operations content only. Each is read
>   by test users A and B with their own read-only tokens. No other item, space, project,
>   channel, folder or account may be read.
> - **What leaves the machine:** each question and numbered sentences from items the asking
>   user could read. User B's input must never include a restricted item.
> - **Calls:** at most `__` model requests in total (7 planned; nothing is retried).
> - **Spend:** at most USD `____` in total (each call reserves USD 0.00045, so 7 calls reserve
>   USD 0.00315), with per-call limits no looser than the 14 October envelope.
> - **Ledger:** its own file, `var/provider/live-platform-ledger-<date>.jsonl`. It never uses
>   `var/provider/live-ledger.jsonl` or `var/provider/live-eval-ledger-2026-10-15.jsonl`.
> - **Pacing:** at least 30 s between calls, with the run stopping on a long or unknown 429.
> - **Retention:** only the result file described in the README; no document or answer text.
>   Tokens and the Groq key are revoked after the run.
>
> Signed: `________`

In `run.py`, set `APPROVAL_DATE = "<date>"`, `APPROVED_MAX_REQUESTS = <calls>` and
`APPROVED_MAX_USD = Decimal("<USD>")`. A run needs ledger room for all 7 planned calls, so the
call cap must be at least 7 and the USD cap at least 0.00315. Then:

```sh
.venv/bin/python eval/live_platform_model/run.py --live --yes
```

Before the run, refresh the Drive tokens; they expire after about an hour.

## Statements to update after a real run (not changed now)

These statements are true today. After a live run, each would need rewording to describe that
run and its result. Line numbers refer to commit `d71a4be`.

- **`src/aspire_brain/providers/live.py`, module docstring, lines 3-4:** "Approved by the
  account holder on 14 October 2026: Groq `openai/gpt-oss-20b`, synthetic data only". The new
  approval adds named real test items as a data source for this experiment only.
- **`eval/live_model/README.md`, both approval tables (lines 12 and 29):** the `Data |
  Fictional demo fixtures only` rows. They should point to this experiment's separate approval
  and ledger.
- **`docs/submission/SUBMISSION.md`, line 111:** "The opt-in `live_grounded` mode connects
  Groq, for fictional demo data only". The application mode would still be limited to fictional
  data, but an owner-run script would have sent real test-account content to the model.
- **`docs/submission/SUBMISSION.md`, status of the intended live system (lines 193 and
  215-218):** "Three evaluations ran on 14 October 2026 against fictional demo fixtures" and
  "The next step is the owner-run integrated check against the real accounts". Add the new run
  and its verdict as a separate result.
- **`docs/submission/SUBMISSION.md`, trade-off table, "Simulated vs live integration" row
  (line 295):** "an opt-in live model that only selects permitted sentences" and "No claim about
  general model quality". Add the run's scope and verdict, without widening the claim.

Also outside the three files above: `docs/reviews/live-access-2026-10-14/README.md`, line 49,
under "What this does not show", says "Nothing from these accounts is ingested, indexed, answered
from or sent to any model". That stays true of that check, but it would need a pointer to the
new run.
