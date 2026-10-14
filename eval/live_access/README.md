# Live platform access check (owner-run)

Reads one general and one restricted item per platform as test users A and B, using each
person's own token. Pass means: **A reads both items; B reads the general item and is refused
the restricted one.** Results keep allowed/denied, an error category, a document count and a
content hash. No document text, tokens or email addresses are written or printed.

This is a read-only check of the existing connectors against real APIs. It does not load the
data into the demo, and it sends nothing to any AI model.

## 1. Prepare the test data

- Use fictional content only.
- Slack: `#demo-beneficiary-review` must be a **private** channel with A in it and B not. The
  connector treats public channels as readable by everyone in the workspace. Keep each channel
  under 100 messages, with plain text only: no files, attachments or block-only messages.
- Drive: the connector reads Google Docs and `.txt`, `.csv` and `.md` files. Upload the
  reconciliation sheet as `.csv` or a Google Doc, not `.xlsx`. Put both files in one folder and
  share only the general file with B.
- Confluence and Jira: if your plan can't restrict a single page or issue, put the restricted
  item in its own space or project that B can't access.
- Each document must be under 5,000 characters.

## 2. Tokens (never commit, paste into chat, or share)

Copy `tokens.example.json` to `~/.config/seaglass/live-access-tokens.json`, fill it in, then run
`chmod 600` on it. The script refuses a token file that other users can read or that sits inside
this repository.

- **Atlassian (Confluence and Jira):** sign in as each user at
  `id.atlassian.com` → Security → API tokens and create a classic API token (one per user).
  Scoped tokens use a different API host, which the connector does not accept.
- **Slack:** create one app in the test workspace with these **User Token Scopes**:
  `channels:read`, `channels:history`, `groups:read`, `groups:history`. Install it as A and
  copy the User OAuth Token (`xoxp-…`). Then add B as an app collaborator, sign in as B, install
  again and copy B's token. Bot tokens (`xoxb-…`) are refused.
- **Google Drive:** in the Google OAuth 2.0 Playground, sign in as each user (one at a time,
  e.g. in a private window), authorise only `https://www.googleapis.com/auth/drive.readonly`,
  and copy the access token. These expire after about an hour, so get them just before running.

Revoke all of these tokens after the submission.

## 3. Fill in the targets and run

`var/live-access/targets.json` is a git-ignored copy of `targets.example.json`. Fill in the site
URL, emails and item IDs, then look up each user's account IDs. If Jira is on a different
Atlassian site from Confluence, set `jira_site` too; A and B must belong to both sites.

```sh
.venv/bin/python eval/live_access/check.py discover
```

Copy the printed IDs into `targets.json`, then run the check:

```sh
.venv/bin/python eval/live_access/check.py check
```

Add `--platform slack` (repeatable) to check one platform at a time. Each run saves
`var/live-access/results-<UTC time>.json`.

## Reading the results

| Observed | Meaning |
| --- | --- |
| `allowed` | The connector read the item as that user |
| `denied` | The platform refused or hid the item. Missing and forbidden look the same, on purpose |
| `error: expired_access` | Token wrong, expired or revoked |
| `error: identity_mismatch` | The token belongs to a different person than the targets file says, or is a Slack bot token |
| `error: unsupported_content` | File type or Slack message format the connector can't read |
| `not_configured` | A value is still missing; the `missing:` line says which |

A `denied` result for user A on the restricted item usually means A was not given access, or
the ID or parent (space, project or folder) is wrong.
