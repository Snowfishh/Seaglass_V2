# WorkBuddy prompt — honest development-process paragraph (14 October 2026)

Before pasting: check and correct the **Facts to confirm** block. WorkBuddy must not add
facts that are not in that block or in the files it is told to read.

---

## Task

Rewrite one bullet in `docs/submission/SUBMISSION.md`, §3.3 "Comprehensive solution design":
the bullet that starts with `*Development level (how this project was built).*` (around line 153).
The current text says "Development was driven by WorkBuddy/CodeBuddy prompts". That is only
partly true: git history and local worktrees show that other AI coding assistants were also used.
Replace it with an accurate account that a judge could check against the repository.

## Read first, in this order

1. `Project requiement.pdf`, §8 "Project Submission Requirements": the project must be "built on
   at least one of the products CodeBuddy or WorkBuddy", and proof of use is mandatory. Nothing in
   §8 forbids other tools. Do not quote more than one short phrase from it.
2. `docs/submission/SUBMISSION.md`: all of §3.3 for tone and context, and §5 (around lines 300–310)
   for the current product-use-proof status.
3. `docs/submission/chat-proof/conversation-history/INDEX.md`: the six exported WorkBuddy sessions
   (G1–G5) and the note that real chat-UI screenshots are still missing.
4. `prompt.md`, `docs/workbuddy-next-prompt.md` and `docs/workbuddy-red-team-prompt-sequence.md`:
   the prompts that drove the WorkBuddy sessions.
5. `docs/submission/CHAT-PROOF-INSTRUCTIONS.md`: what the chat proof is supposed to show.
6. `docs/reviews/submission-checklist-2026-10-13/README.md`, rows a3 and a4: why the current proof
   is incomplete.
7. Read `docs/reviews/assistant-attribution-2026-10-15/README.md` to see which commits Claude Code worked on, and run
   `git log --reverse --format='%h %ad %s' --date=short` to see their dates.

## Facts to confirm (owner edits this block before sending)

- WorkBuddy drove the core build from about 23 September to early October 2026: source
  contracts, the four-platform simulator, deterministic sync, routing and ranking, the grounded
  provider and audit, and gap closure (milestones G1–G5, six exported sessions).
- OpenAI Codex was used for separate worktree experiments, the 13–14 October
  submission-checklist audit.
- Claude Code was used on 13–14 October for review, scan-fix cleanup, integration of the audit
  fixes, the web UI refresh and re-verification (commits listed in the assistant attribution record).
- The owner reviewed, directed and committed all changes.


## Rules

- Change only that one bullet. Do not edit §5 history, the conversation exports or any other file.
- State only facts from the confirmed block or the files above. No percentages or time shares
  unless the owner supplies them.
- Lead with WorkBuddy's real role (the core build, with the exported sessions as evidence), then
  name the other assistants and what they did, in one or two sentences.
- Keep the existing working-pattern sentence (requirement plus evidence, PDF cross-check before
  implementation, tests that fail for the right reason before a fix, report update after each
  milestone). Say which tool it applied to.
- Do not claim the chat-UI screenshots exist. They are still missing.
- Keep the links to `prompt.md`, `docs/workbuddy-next-prompt.md` and `CHAT-PROOF-INSTRUCTIONS.md`
  working (relative paths from `docs/submission/`).
- Plain English, about 120–180 words, same Markdown bullet style as the surrounding text.
- Do not commit or push.

## When done, report

1. The new bullet text.
2. A list of each factual claim in it, with the file or command that supports it.
3. The output of `git diff --stat` (only `docs/submission/SUBMISSION.md` should change).
4. The output of `grep -rniE "driven by (WorkBuddy|CodeBuddy)|built (entirely|solely|only) (with|on)" README.md docs/submission`.
   Report any other place that still overstates WorkBuddy's role; do not change those places
   without asking.
