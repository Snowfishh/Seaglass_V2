# Live platform access check — 14 October 2026

**Result: 16 / 16 checks passed** at 10:29:55–10:30:10 UTC, run by the account holder on their
own Mac (Python 3.14.2) with [`eval/live_access/check.py`](../../../eval/live_access/check.py).
Saved output: [results-20261014T103010Z.json](results-20261014T103010Z.json)
(SHA-256 `a5687c54fea5ef77ef4c9c7e4662171e1af98d27fb4d52601af538d45b60a07b`).

## What was tested

The four existing HTTP connectors (`src/aspire_brain/platforms/connectors/`) read real
Confluence, Jira, Slack and Google Drive test accounts. Two test users, A and B, each used
their **own** read-only credential:

- Atlassian: a per-user API token. Confluence and Jira were on two separate Atlassian Cloud sites.
- Slack: a per-user `xoxp` token with `channels:read`, `channels:history`, `groups:read` and
  `groups:history`. Bot tokens are refused.
- Drive: a per-user OAuth access token limited to `drive.readonly`.

Each platform had one general item and one restricted item, populated with fictional
payment-operations content. Expected: A reads both; B reads the general item and is refused
the restricted one. The connector also confirmed on every read that the token belonged to the
expected account (`identity_mismatch` otherwise).

| Platform | How B was restricted | A general | A restricted | B general | B restricted |
| --- | --- | --- | --- | --- | --- |
| Confluence | Page restriction (admin and A only) in a shared space | allowed, 1 page | allowed, 1 page | allowed, 1 page | **denied** |
| Jira | Issue not visible to B | allowed, 1 issue | allowed, 1 issue | allowed, 1 issue | **denied** |
| Slack | Private channel; B not a member | allowed, 3 messages | allowed, 1 message | allowed, 3 messages | **denied** |
| Drive | File in a folder not shared with B | allowed, 1 doc | allowed, 1 doc | allowed, 1 doc | **denied** |

"Denied" means the platform refused or hid the item. The connector reports missing and
forbidden items identically, so B learns nothing about whether the restricted item exists.

## What was recorded

Per read: allowed or denied, an error category if any, the number of documents returned and
a SHA-256 fingerprint of their text. No document text, tokens, email addresses, account IDs,
site names or item IDs were saved. Item IDs and account IDs stayed in the git-ignored
`var/live-access/targets.json`; tokens were kept outside the repository.

For the general item, A and B received identical content on Confluence, Slack and Drive. On
Jira, the fingerprints for the same issue differed between A's and B's reads (one second
apart). Both reads succeeded; the cause, such as a concurrent edit or per-user rendering of the
issue description, was not investigated.

## What this does not show

- **Not integrated.** The web application and the case demo still use the in-memory simulator.
  Nothing from these accounts is ingested, indexed, answered from or sent to any model.
- **Single known items only.** Each read fetched one item by ID. Search, listing, pagination
  across a workspace, rate-limit behaviour and large content were not exercised.
- **No change detection.** Revocation and updates were not observed over time. Re-running the
  check after a permission change would show a new result, but the application does not detect
  changes on its own.
- **Two users, one run.** This is a functional check, not a security assessment of the platforms
  or of administrator or service-account access.

## Test suite at this commit

The committed tree was extracted with `git archive` (no ignored `artifacts/` or `var/`) and
tested on 14 October 2026 with the same Python 3.14.2 environment: **870 unit/integration tests
passed, 92.48% statement coverage** (3,995 / 4,320) and **93 red-team tests passed**; Ruff
clean. The 7 new tests cover the live-check script against a fake four-platform server and
make no network calls. [Test log](clean-snapshot-tests.log).

## Reproduce

See [eval/live_access/README.md](../../../eval/live_access/README.md). The script's offline
tests are in [tests/unit/test_live_access_check.py](../../../tests/unit/test_live_access_check.py).
