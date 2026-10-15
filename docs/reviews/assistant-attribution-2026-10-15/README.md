# Assistant attribution

Claude Code (Anthropic) worked on the commits below. The owner reviewed, directed and committed
each one. Other assistants' roles are described in
[SUBMISSION.md §3.3](../../submission/SUBMISSION.md#33-comprehensive-solution-design).

| Commit | Date | Subject |
| --- | --- | --- |
| `2edc2fa` | 2026-10-13 | chore: fix scan findings in tests, docs and cover |
| `1df8b97` | 2026-10-14 | feat: open on the four-platform cases page and record checklist audit |
| `42adf8c` | 2026-10-14 | feat(web): add theme toggle, status chips and policy timeline styling |
| `97f9916` | 2026-10-14 | docs: re-verify combined cleanup, audit and UI refresh tree |
| `d4f9118` | 2026-10-14 | feat: add owner-run live access check and record 16/16 result |
| `f8cf249` | 2026-10-14 | feat: add live grounded provider (Groq) under the approved envelope |
| `9cbe7b4` | 2026-10-14 | docs: describe the opt-in live provider and refresh submission visuals |
| `6225dcb` | 2026-10-14 | fix: separate provider availability from answer quality in the live evaluation |
| `f03843e` | 2026-10-14 | docs: align live-provider wording with the evaluation fix |
| `32c5af1` | 2026-10-14 | fix: let the application import and lock its ledger on Windows |
| `4e8ead4` | 2026-10-14 | docs: record the clean-install verification of the submitted source |
| `5695d93` | 2026-10-15 | chore: add WorkBuddy process records and keep local-only files out |
| `8bd4e14` | 2026-10-15 | docs: report the 14 October live runs accurately and readably |
| `4773221` | 2026-10-15 | docs: add a commit hash map for earlier documents |
| `4b07840` | 2026-10-15 | docs: map worked examples to the five scenarios and correct stale submission facts |
| `1d2ab31` | 2026-10-15 | fix: ignore generated request and audit IDs in the forbidden-text check |

Claude Code also made the later commits `411fb3a`, `7b2d630`, `568ef65`, `9777c42`, `c82a9e3`, `2589812`, `b867a57`, `27d7da8` and `3285596`, the demo-label fix `f654077` (in a separate Claude Code session), and the
commit that recorded the final verification; `9003477` commits WorkBuddy's own memory notes.

WorkBuddy worked in the same checkout, and some of these commits carry its work: `6225dcb`
includes its Groq rate-limit header recording and cross-process cooldown, with their tests;
`8bd4e14` includes its live-run status draft and run-1 corrections, edited for readability; and
`70814d6` is WorkBuddy's change, committed by Claude Code. WorkBuddy's own notes are in
[`.workbuddy-ai/memory/`](../../../.workbuddy-ai/memory/).

Documents written before 15 October 2026 cite earlier commit hashes;
[commit-map.txt](commit-map.txt) gives the current hash for each.
