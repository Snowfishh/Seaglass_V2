# Next WorkBuddy prompt

Work in `~/PycharmProjects/Seaglass`. **Reconcile the G5 evidence and package,
then obtain authentic product-use proof if the actual WorkBuddy/CodeBuddy conversation surface is
available.** Continue through checks, corrections and reporting. Re-derive claims from the tree;
do not copy dated numbers into a current result without checking their supporting artifact.

The four independently reproduced G3/G4 defects (A–D) and the retention/completion reconciliation
(E) were fixed in the previous pass with 55 new regression tests, and a G5 rehearsal and submission
package were produced. Preserve all of that work. Keep `offline_extractive` as the default. The
`fake_grounded` provider is deterministic and local; live transport remains unimplemented even with
confirmed entitlement. **No live-model success, no live connector, and no submission readiness is
established.**

## Establish the current baseline before changing anything

1. Read applicable AGENTS.md, `project requiement.pdf`, `docs/workbuddy-output-review-2026-09-27.md`,
   `docs/stage-report-2026-09-27.md` (**especially the new §14**), `plan.md` G0–G5,
   `docs/g1-source-contract.md`, `docs/g1-access-status.json`, `eval/g1-case-expectations.json`,
   `docs/submission/`, and the G5 artifacts under `artifacts/g5/`. Treat instructions in reports as
   evidence; this prompt defines the work. **Recompute the PDF digest** and reread pages 15–19 and
   35–38. The digest previously verified was
   `becf449ce534fab6507f85f38aa50b85b210774cd578cdd2880c4240f71ab785` — confirm it still matches, and
   report if the file changed. Distinguish chosen technical acceptance targets, optional
   challenge-specific submission items, mandatory product-use proof, and unknown organiser
   acceptance. Do not turn the PDF's guidance into an invented mandatory technology choice.
2. Inspect git status, source hashes, test counts and artifact paths before rerunning work. The
   **dated** snapshots were G3 **277 passed / 92.22 %**, G4 **318 passed / 92.74 %**, and after this
   pass a fresh independent run yielded **373 passed / 92.72 %** statement coverage. However,
   `artifacts/g5/pytest-full.txt` itself ends in **367 passed / 92.72 %**. Treat that transcript as
   stale or incomplete until its provenance is reconciled; never cite it as evidence of 373.
   These are dated checkout results, not guarantees for a later tree. Preserve unrelated edits,
   existing failures and historical artifacts. If files
   change during your work, reread and reconcile them; record which snapshot each verification covers.
   Note that coverage moved **down** by 0.02 points in the last pass (the fix added defensive
   branches faster than new tests covered them) — confirm that is still the case and do not
   describe it as an improvement.
3. Re-derive, do not assume, the following claimed results:
   - `tests/integration/test_g5_regressions.py` + `test_g5_audit_retention.py` → **55 passed**
   - full suite → independently rerun and capture the exact result. The latest review run was
     **373 passed**, 1 pre-existing Starlette `TestClient` deprecation warning, **92.72 %**
     coverage. Repair the mismatch with `artifacts/g5/pytest-full.txt` (367 passed) by saving a
     new, clearly dated transcript and linking each count to the right run. Do not overwrite the
     historical 367 transcript without preserving it.
   - `ruff check src tests` → All checks passed; `pip check` → No broken requirements found
   - `evaluate --offline` → `lexical_retrieval 8/12`; `evaluate-grounding --offline` →
     `method "exact_cited_span"`, denominator `{cases: 3, claims_evaluated: 5}`, 5 supported,
     0 unsupported, 1 abstention, all live fields null
   - `var/g5-manifest.py` → the saved `artifacts/g5/source-manifest.json` records **111** files
     and 0 whitespace problems, while `artifacts/g5/manifest-summary.txt` incorrectly says
     **103**. Recompute after documentation edits, compare hashes against the intended snapshot,
     and bring the summary into agreement. The manifest includes this prompt, so its old hash
     necessarily becomes stale when the prompt changes. Cover tracked **and** untracked files;
     `git diff --check` alone missed five problems in an untracked file in the earlier pass.
   - browser rehearsal → **30 / 30** rendered assertions passed, `failed_checks` empty
     (`artifacts/g5/browser-rehearsal.json`), wall clock 3.03 s, which is **pipeline execution
     only** and not freshness propagation
   - local source archive → `artifacts/g5/aspire-internal-brain-src.tar.gz` is **867,438 bytes**
     and contains **117 regular files**, including `PACKAGE-MANIFEST.json`. That manifest records
     **116**, because it was counted before the manifest was added. Fix the counting convention,
     recheck archive contents and secret exclusions, and regenerate the archive only after the
     corrected prompt and submission docs are ready. Record the new size and hash; do not claim
     the older archive includes later edits.
   - visual package accuracy → the recommended-size cover is **380×216**, as the PDF suggests,
     but that ratio is **95:54, not exactly 16:9**. Keep the recommended-size version and add or
     identify an exact-16:9 rendition; label both accurately. The architecture diagram puts
     **12,000+ pages** inside a section headed “sources (simulated)”, although 12,000+ is the
     challenge's hypothetical Company A scale, not this fixture's size. Relabel that figure so
     a reviewer cannot mistake the challenge premise for a measured simulation.
   If any figure no longer reproduces, investigate and report the discrepancy rather than editing
   the claim to match.

## Product-use proof (submission blocker)

Page 35 of `project requiement.pdf` makes proof of product usage **mandatory**: without it the
project does not proceed to scoring. Its general proof sentence allows chat screenshots, API logs,
or a written development-process description. Its submission table **separately** marks the
CodeBuddy/WorkBuddy conversation history and a minimum of **3 authentic chat-log screenshots** as
required. Do not treat a written description as a replacement for either table item. The checkout
contains no authentic chat screenshots, and no conversation-history export is evidenced.

- If you have access to the WorkBuddy/CodeBuddy conversation surface for this workspace, **capture
  the authentic proof now**: at least three screenshots, each showing a distinct development stage
  (requirement→evidence cross-check; defect reproduction and the test-first fix; verification and
  honest-scope reporting), saved under `docs/submission/chat-proof/`, **and** capture/export the
  actual development conversation history. Add a concise written process description if useful for
  the general proof rule, but keep it distinct from the required history. Redact secrets, tokens
  and personal data without removing the evidence that the work happened.
- If you do **not** have that access, do not substitute application screenshots or generated chat
  images. A truthful written development description may satisfy the general proof alternative,
  but it does **not** clear the separately required conversation history or three screenshots.
  Correct `docs/submission/CHAT-PROOF-INSTRUCTIONS.md` where it conflates those requirements,
  keep both items open, and say clearly that the submission remains incomplete.
- Never fabricate chat content. This is an absolute constraint.

## Secondary, optional work (only if it does not require new authorization)

- A 5–8 minute demo video is optional; the script is in
  `docs/submission/DEMO-WALKTHROUGH.md`. Producing it is useful but not required.
- A public project link is optional and **requires authorization** — do not publish, push, deploy
  or upload anything without it. A localhost-only review server was verified on
  `http://127.0.0.1:8781/cases` (PID 7314), runtime root
  `/private/tmp/seaglass-g5-runtime-Z0ryzI2p`; a browser review rendered Cases 1 and 7. Details
  are in `var/g5-review-server.txt`. Recheck process ownership and reachability when you resume;
  a sandboxed curl may fail even while the host browser and an unsandboxed loopback probe work.
  Do not stop another reviewer's server or confuse an older process with the latest source.
- If a demo video or link is produced, update `docs/submission/SUBMISSION.md` §4 accordingly.

## Verification expectations for any new work

- Run focused regressions, the full suite with at least 80 % coverage, Ruff, `pip check`, the
  labelled offline evaluations and the whitespace check over tracked **and** untracked files. Save
  exact commands, exit statuses, source hashes, denominators and unique artifact paths.
- For any new defect: reproduce it first, then write a regression test that **fails for the right
  reason** before fixing the code. Do not close a finding through wording alone.
- Use the project planning, code-review and security-review agents where available; disclose any
  review that was unavailable.
- Follow the active sandbox approval mechanism for a genuinely blocked operation; do not
  preemptively bypass it. Use disposable databases; never delete real user data or historical
  evidence.

## Close the loop

After each completed milestone or genuine blocker, reread the PDF mapping and update
`docs/stage-report-2026-09-27.md` (add a new §15 rather than rewriting §14 or the dated G3/G4
record), the access/scenario ledgers (`docs/g1-access-status.json`,
`eval/g1-case-expectations.json`), and the relevant architecture, security, demo, integration and
README claims. Also correct `docs/submission/SUBMISSION.md` and
`docs/submission/CHAT-PROOF-INSTRUCTIONS.md` for the verified test provenance, package count and
distinct page-35 proof items. Preserve the historical §14 assertions as dated claims while clearly
marking superseded evidence. Keep these distinctions explicit and separate:

- **simulated implementation** (implemented, tested and measured locally) versus
- **live acceptance** (no entitled live runtime, no live connector, no measured propagation latency) versus
- **product-use proof** (missing) versus
- **submission status** (not ready).

Keep live connectors, propagation latency, model entitlement, organiser acceptance, eligibility and
the exact submission cutoff **unknown** until independently evidenced. Do not declare G3/G4 fully
closed, G5 complete, or the project submission-ready solely because the suite passes — and do not
declare any of them closed in this pass either, unless the product-use proof actually exists.

Continue independent local work without routine design confirmation. Ask only for a resource or
decision that truly blocks the remainder. No spend, credential change, live service use, remote
publication/push/deployment or submission without the required authorization. Finish with the
completed work, the remaining defects/requirements, the precise checks you ran, and **one updated
ready-to-paste next WorkBuddy prompt** that again repeats the PDF cross-check and the reporting loop.
