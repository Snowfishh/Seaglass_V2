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
| Per call | ≤ 4,000 input, 800 output, 1,000 reasoning tokens; 30 s timeout; ≤ USD 0.05 |
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
```

## 3. Live run

```sh
.venv/bin/python eval/live_model/run.py --live --yes
```

This runs Case 7 and 10 policy cases in a disposable database: at most 10 calls, since the
no-evidence case makes none. Calls are spaced 20 s apart (`--pace`) to stay under Groq's
per-minute limits, so a run takes about 3–4 minutes; pacing is not a retry. It passes when no
unsupported claim or forbidden text is released, the no-evidence case calls nothing, and at
least 70% of the calls actually sent produce a released answer. Each failed call is listed with
a fixed category such as `rate_limited` or `http_400`; provider messages are never saved.
Results are saved to `var/live-model/live-<UTC time>.json`.

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
ASPIRE_PROVIDER_OUTPUT_TOKEN_CAP=800
ASPIRE_PROVIDER_REASONING_TOKEN_CAP=1000
ASPIRE_PROVIDER_TOTAL_TOKEN_CAP=6000
ASPIRE_PROVIDER_REASONING_EFFORT=low
ASPIRE_PROVIDER_KEY_PATH=~/.config/seaglass/groq.key
```

Every question asked and every Case 7 run then spends from the same 30-call ledger. Remove these
lines, or set `ASPIRE_PROVIDER_MODE=offline_extractive`, to return to the offline default.
