# Live platform check of the integrated path (owner-run)

The [live access check](../live_access/README.md) showed on 14 October 2026 that each connector
reads one known item correctly as user A and user B. This check goes further. It runs the code the
web application runs with `ASPIRE_PLATFORM_SOURCE=connectors`: discovery with each user's own
token, the synchronizer, the shared index, the query service with its query-time re-check, and
saved-answer reads. It sends nothing to any AI model.

It reuses the live access setup: the same test data, `var/live-access/targets.json` and the token
file at `~/.config/seaglass/live-access-tokens.json`. Google Drive access tokens expire after about
an hour, so get fresh ones just before you run it.

## What it reads

For each platform, the containers come from the parents of the items in `targets.json`: the
Confluence space key, the Jira project key, the Drive folder and the Slack workspace. Each user
lists everything they can see in those containers. On Slack that means every channel they belong
to, with thread replies.

Keep the test containers small. Discovery reads at most 200 items per container and 100 messages
per channel, and fails rather than truncating.

## The three steps

```sh
.venv/bin/python eval/live_platform/check.py ingest
```

Syncs all four platforms, then asks three questions as A and as B. A pass needs positive
evidence, not only the absence of a leak, so an empty workspace, an unreachable platform or a run of
abstentions fails:

| Row | Pass condition |
| --- | --- |
| `sync`, per platform | The sync completed and indexed at least one record; a platform missing from the configuration fails |
| `coverage`, per platform | The general item in `targets.json` is readable by A and B; the restricted item by A and not by B |
| `query`, general question | Answered (or partial) with at least one citation, for both users; B cites nothing restricted |
| `query`, restricted question | A cites a restricted item (the positive control); B cites none |
| `answer_coverage` | The citations of all answers together span all four platforms |

The default questions match the fictional fintech test data. If your accounts hold different
content, pass your own with `--questions questions.json`, a JSON list of
`{"question": "...", "kind": "general"}` or `"kind": "restricted"` entries.

```sh
.venv/bin/python eval/live_platform/check.py freshness --phrase "standby failover drill"
```

When prompted, add a sentence containing the phrase to the general Confluence page and save it.
The script syncs every 60 seconds (`--poll`) and reports how many wall-clock seconds passed before
an answer quoted the phrase, next to the delay measured from Confluence's own modified time to the
end of the sync that ingested it. Pass means within one hour.

```sh
.venv/bin/python eval/live_platform/check.py revocation --question "Why is the Cedar Quay payment held?"
```

Ask a question that A answers from the restricted Confluence page. When prompted, remove A's access
to that page. The script then checks, without syncing first, that the page is no longer quoted and
that A's earlier saved answer is closed. After a sync it checks that A's grant is gone from the
index. Give A access back afterwards if you want to repeat it.

## What is saved

Each step writes `var/live-platform/<step>-<UTC time>.json` with outcomes, counts, timings and
short hashes of the questions. No document text, tokens, emails or item IDs are written.

## Running the web app against the real accounts

Create a configuration that points at the targets file, then start the server with the connector
source:

```sh
printf '{"targets_file": "var/live-access/targets.json", "allow_live": true}\n' > var/connectors.json
```

```sh
ASPIRE_PLATFORM_SOURCE=connectors ASPIRE_CONNECTORS_CONFIG=var/connectors.json .venv/bin/python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

The first sync runs in the background after start-up. Until it finishes, the Case demo page shows
every platform as `unknown` and typed questions return no answer. User A and User B map to the A
and B accounts in `targets.json`.

## Offline tests

[`tests/integration/test_live_platform_check.py`](../../tests/integration/test_live_platform_check.py)
runs all three steps against a stateful fake of the four APIs
([`fake_platforms.py`](../../tests/integration/fake_platforms.py)), and
[`test_connected_platforms.py`](../../tests/integration/test_connected_platforms.py) covers the
connector source in the web app. Passing them shows the code behaves as described against that
fake. It does not show the real platforms respond the same way; that is what this check is for.
