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
| `715e048` | 2026-10-14 | feat: add live grounded provider (Groq) under the approved envelope |
| `4de765b` | 2026-10-14 | docs: describe the opt-in live provider and refresh submission visuals |
| `129f872` | 2026-10-14 | fix: separate provider availability from answer quality in the live evaluation |
| `9150bff` | 2026-10-14 | docs: align live-provider wording with the evaluation fix |
| `c535b2a` | 2026-10-14 | fix: let the application import and lock its ledger on Windows |
| `634b2b1` | 2026-10-14 | docs: record the clean-install verification of the submitted source |
| `038e172` | 2026-10-15 | chore: add WorkBuddy process records and keep local-only files out |
| `65d5ee1` | 2026-10-15 | docs: report the 14 October live runs accurately and readably |
| `59bb4ee` | 2026-10-15 | docs: add a commit hash map for earlier documents |
| `e3b08a4` | 2026-10-15 | docs: map worked examples to the five scenarios and correct stale submission facts |
| `007ed4c` | 2026-10-15 | fix: ignore generated request and audit IDs in the forbidden-text check |

Claude Code also made the later commits `d96d81d`, `3ff7f68`, `79b60f9`, `e6b6c2b`, `bf22247`, `f27f25a`, `128c7f9`, `7823b38` and `06f9a1f`, the demo-label fix `f71743d` (in a separate Claude Code session), and the
commit that recorded the final verification; `40d5a84` commits WorkBuddy's own memory notes.

WorkBuddy worked in the same checkout, and some of these commits carry its work: `129f872`
includes its Groq rate-limit header recording and cross-process cooldown, with their tests;
`65d5ee1` includes its live-run status draft and run-1 corrections, edited for readability; and
`bdd53d2` is WorkBuddy's change, committed by Claude Code. WorkBuddy's own notes are in
[`.workbuddy-ai/memory/`](../../../.workbuddy-ai/memory/).

Documents written before 15 October 2026 cite earlier commit hashes;
[commit-map.txt](commit-map.txt) gives the current hash for each.
