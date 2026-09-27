# Product-use proof — two distinct required items (page 35)

Page 35 of `project requiement.pdf` contains **two separate things**, and they must not be
conflated. This file previously conflated them; the correction is recorded in
`docs/workbuddy-reconciliation-2026-09-27.md` and stage report §15.

## Item 0 — the general proof gate (preamble, not the table)

> **Proof of product usage is mandatory: chat screenshots, API call logs, or a written
> development-process description. Without proof, the project will not proceed to scoring.**

This is a gate, satisfied by **any one** of: chat screenshots, API call logs, or a written
development-process description.

## Items 1 and 2 — the submission table (separately Required)

The table below the preamble lists **two independent Required rows**. A written
development-process description satisfies Item 0; it does **not** satisfy Item 1 or Item 2.

| # | Table item (Required) | Wording in the PDF |
|---|---|---|
| 1 | CodeBuddy / WorkBuddy **Conversation History** | "The CodeBuddy / Workbuddy chat history used during the project development process" |
| 2 | **Chat history** — minimum 3 screenshots | "Minimum of 3 screenshots of your chat logs from CodeBuddy or WorkBuddy during the development process" |

## Status after this pass

| Item | Status | Evidence |
|---|---|---|
| 0 — general proof gate | **Satisfied** (written development-process description, and authentic history export) | `prompt.md`, `docs/workbuddy-next-prompt.md`, and the history below |
| 1 — Conversation History | **Satisfied — authentic export** | [`chat-proof/conversation-history/`](chat-proof/conversation-history/INDEX.md) — 6 genuine sessions exported verbatim from the local WorkBuddy/CodeBuddy session logs |
| 2 — ≥3 chat-log screenshots | **Open — pending** | Three **authentic transcript exports** exist in [`chat-proof/excerpts/`](chat-proof/excerpts/); see the caveat below |

### What was exported (authentic, not authored)

The development conversation history was exported directly from the genuine local session
transcripts stored by the product under `~/.workbuddy-ai/projects/**/*.jsonl`. Every line is a
recorded turn; nothing was written, paraphrased or generated for the export. Redaction replaced
only the local home directory with `~` and masked token-shaped strings.

| # | Session title | Stage | Records |
|---|---|---|---|
| 1 | Add source-specific contract types and tests | G1 source contracts | 246 |
| 2 | Extend G1 simulator for four-platform coverage | G1 four-platform simulator | 445 |
| 3 | Implement G2 deterministic sync milestone | G2 deterministic sync | 429 |
| 4 | Implement G3 platform routing and ranking | G3 routing and ranking | 686 |
| 5 | Implement G4 grounded-answer provider and audit | G4 grounded provider and audit | 875 |
| 6 | Close G3/G4 gaps and package G5 rehearsal | G5 gap closure and packaging | 779 |

### Caveat on Item 2 (do not overclaim)

The three images under `chat-proof/excerpts/` are **transcript exports rendered from the
authentic logs**. They are:

- **not** screenshots of the application UI, and
- **not** synthetic or generated chat images.

Each carries a visible header stating exactly that. They are offered as faithful chat-log
evidence. **Whether the organiser accepts a transcript export in place of a literal UI
screenshot is unknown.** Until that is confirmed, Item 2 is **open**, and the submission remains
**incomplete**. Capturing the literal app surface (macOS `⌘⇧4` on the open conversation) is the
account holder's action and would close Item 2 without ambiguity.

**Never fabricate chat content.** Application screenshots (of the project running) are still
**not** a substitute for chat evidence.

## If you want literal UI screenshots (closes Item 2)

1. Open the WorkBuddy/CodeBuddy desktop app and locate the six sessions above.
2. For each stage, scroll to a turn showing **both** your instruction and the assistant's work.
3. Capture with `⌘⇧4` / `⌘⇧5`, keeping the window chrome and workspace name in frame.
4. Save as PNG into `docs/submission/chat-proof/ui-screenshots/`:
   - `ui-01-requirement-crosscheck.png`
   - `ui-02-defect-repro-and-test-first.png`
   - `ui-03-verification-and-scope.png`
5. Redact keys, tokens and personal data — without removing the evidence that the work happened.

## Acceptance check before submission

- [x] Item 0: general proof gate has an authentic written description and history export.
- [x] Item 1: the conversation history is exported from the genuine session logs.
- [ ] Item 2: three **literal UI screenshots** of the chat surface (transcript exports may or may
      not be accepted — unknown).
- [ ] No secret, token or personal datum is visible.
- [ ] The screenshots are the **actual chat surface**, not application screenshots and not
      synthetic images.

Until Item 2 is closed, the submission package is **incomplete** regardless of the state of the
code.
