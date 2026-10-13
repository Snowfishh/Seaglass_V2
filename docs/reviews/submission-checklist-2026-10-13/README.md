# Submission checklist audit — 13–14 October 2026

Audit began and verification ran on 13 October; final review continued on 14 October
(Singapore client date).

The cleanup fixes are substantially correct **on `cleanup/scan-fixes` at
`3d1de94e46c26543fae5fe72d8fa8f587fd7d9d3`**. They are not present on `main` at
`a41cdaecb58a62d539e622b1d5f3e0937fd6a29c`. The additional fixes described below
belong to the isolated `submission-checklist-audit/Seaglass` worktree; they are
uncommitted. Neither branch has been merged or pushed by this audit.

The supplied HTML is an earlier checklist snapshot, not execution authorization.
Its stored completion list contains only a1/c4/e5, and its footer already warns
that cleanup changes were unmerged. The user's pasted completion claims were
checked against the cleanup branch rather than inferred from checkbox state.
The participant brief was read locally: section 4 describes the challenge,
section 8 distinguishes the conversation export from three required chat UI
screenshots, and section 9 gives the 16 October submission date. The brief does
not establish a closing hour or timezone; the HTML's 23:59 Singapore countdown
is an assumption that the account holder should confirm in the submission portal.

## Verified execution

Two tracked-source archives were extracted without ignored `artifacts/`,
`var/`, `.env`, key files or the original checkout's runtime databases. Tests ran
on this Mac with Python 3.14.2 and the existing installed virtual-environment
dependencies. This establishes source/fixture portability, not a fresh dependency
installation or an independently rebuilt environment.

| Snapshot / check | Observed result | Evidence |
| --- | --- | --- |
| Original main, isolated target-contract tests | 10 failed, 34 passed; all ten fail on the missing ignored manifest | [baseline contract log](baseline-contract.log) |
| Unmodified cleanup branch, full unit/integration selection | 862 passed; 92.43% package statement coverage | [branch log](branch-tests.log), [coverage](branch-coverage-summary.json) |
| Unmodified cleanup branch, red-team selection | 93 passed | [branch red-team log](branch-redteam.log) |
| Landing-page regression before implementation | 2 failed, 19 passed for missing `/ask` and home redirect | [RED log](home-red.log) |
| Landing-page regression and case routes after implementation | 26 passed | [GREEN log](home-green.log) |
| Candidate after route change, full unit/integration selection | **863 passed; 92.45%** package statement coverage (3994 / 4320 statements) | [final log](final-tests.log), [coverage](final-coverage-summary.json) |
| Candidate red-team selection | **93 passed** | [final red-team log](final-redteam.log) |
| Configured Ruff selection | Passed over `src`, `tests`, `eval` | [lint log](ruff.log) |
| Extra, unconfigured lint rules | 45 advisory findings: 24 RUF059, 19 RUF100, 2 B008 | [optional lint log](optional-lint.log) |
| Installed dependency consistency | `pip check`: no broken requirements | [dependency log](pip-check.log) |
| Browser smoke | Root redirects to cases; employee selection and fixed Jira/Slack question work; no page errors | [browser result](browser-smoke.json) |
| Assets | Four cover dimensions and diagram regenerated; SVG geometry and rendered images inspected | [render log](render-assets.log) |

The browser smoke used a disposable fictional database, random test keys and a
loopback listener; browser routing blocked other URLs. It is a narrow smoke
check, not complete browser E2E or live connector/model evidence. Existing
Starlette/httpx deprecation warnings remain. Test/coverage counts describe the
selected suites, not every challenge requirement. See [source snapshot](source-snapshot.json)
for exact tested source, fixture, dependency-declaration and documentation hashes.
Published logs replace local home/temp prefixes; full coverage reports are retained
locally with hashes in their summaries to keep this audit bundle small. Original logs remain in the
temporary verification directory. Historical provider snapshots and ledgers
were neither rewritten nor executed.

## Item-by-item findings

`pass` means the stated local fix was verified within the scope described;
`concern` means partial or outstanding work; `unable-to-assess` means the audit
cannot establish the external/human fact. A branch-local pass is not a pass on
main or a claim of public availability.

| ID | Finding | Evidence, remaining work and owner |
| --- | --- | --- |
| a1 | pass | Commit a41cdae contains architecture docs, SUBMISSION and both diagram formats: four paths, rather than literally three files. Main also has an unrelated untracked process note; a historical clean-tree claim is not current evidence. |
| a2 | unable-to-assess | Cached `origin/main` is b98c981; main is 13 commits ahead of that cached ref, cleanup 14. Live GitHub repository/branch reads returned 404 through the connector; that can mean private, absent or inaccessible to this connection. Human must verify the actual URL/public access and authorize publication of the chosen tree. No push occurred. |
| a3 | concern | Transcript-rendered excerpts are not literal product UI screenshots. Human: capture at least three real CodeBuddy/WorkBuddy chat views and verify the required upload fields. |
| a4 | concern | A `.codex/worktrees` prompt identifies a checkout, not the chat product. Product chrome, real sessions and a truthful development-process note are needed; export labels alone are not independent verification. |
| a5 | pass, explanation added | All four supposedly missing paths exist as working-tree files in sibling fef5 (they are not committed in its HEAD). The conversation index now explains historical versus current layouts and preserves the transcript verbatim. This does not close a3/a4. |
| a6 | pass on cleanup | SUBMISSION links the configured GitHub repository rather than an ignored source archive. Repository visibility remains a2. |
| a7 | unable-to-assess | Human: complete and send the form after proof and source access are ready. Portal acceptance and any exact closing time remain unverified. |
| b1 | concern | The ordinary `live_grounded` factory still refuses; two bounded historical Groq attempts are a separate harness. A real application model path is substantive remaining challenge work, not a one-line enablement. Agent implementation and explicit human provider/disclosure/spend authorization are needed. |
| b2 | concern | The service accepts arbitrary questions, but the four-platform browser page posts fixed case IDs. Add a validated free-text endpoint/form over a persistent fixture index, with server-owned identities, packet reads and audit integration. Completion checks are below. |
| b3 | pass, implemented here | `/` redirects to `/cases`; the policy demo and persona selector remain at `/ask`. Regression and browser smoke checks passed. This changes the landing page only; b2 remains open. |
| b4 | pass for disclosure | README and the connector guide explicitly state that HTTP adapters are tested offline and unwired from the web app. Actual live integration remains open. Fixture-based UI integration is a separate useful next step. |
| b5 | concern | Inquiry requires one platform in both the API and protected-store filter. Implement all-platform scope with filter-bound signed cursors, deterministic pagination and existing audit/tenant checks. Agent work; no provider call is needed. |
| b6 | concern, optional | A public demo URL is optional under section 8. Local persona selection and loopback guards make deployment a separate authentication decision. Human may choose a recorded local demo; do not expose this persona selector publicly. |
| b7 | concern, partially improved | README now leads with the incident/user problem. Diagram stage labels are replaced; detailed historical findings are collapsed in SUBMISSION §5. Technical wording in engineering appendices is intentional. Human can review the pitch and agent can draft a shorter demo narration; no personal voice requirement prevents drafting. |
| c1 | pass on cleanup | The tracked fixture is byte-identical to the historical manifest (SHA-256 `294c03c2606b091ba8f1eba2147985e7afb3d5ab0124e695b499d623028c8933`). Fresh tracked snapshots pass without the ignored artifact folder. |
| c2 | concern, deferral reasonable | The fixed state path is an authorization/consumed-ledger guard in the experiment harness, not the default web runtime. A relocation is feasible offline but must preserve historical snapshots and prevent redispatch; moving source is not necessary for this submission fix. |
| c3 | concern, partial | `.env.example` is corrected. `httpx` is imported by connector code; Groq/HTTP dependencies remain pinned. Optional extras need import boundaries and no-extra installation tests. Existing lock/evidence pins are provenance to preserve, not an absolute prohibition on future refactoring. |
| c4 | pass | No orphan `live_groq` source/bytecode was found in the inspected source tree. Fresh tracked snapshots contain no ignored bytecode. |
| c5 | pass for source portability | Both branch and amended candidate were tested from clean tracked snapshots on this Mac. Counts and coverage are recorded above. Fresh dependency installation and complete browser E2E remain outside this result. |
| c6 | concern, optional | Configured lint is clean. The broader optional rules produce 45 findings, not the checklist's 29. FastAPI `Query(...)` defaults should not be changed mechanically to satisfy B008; do a separately scoped cleanup if useful. |
| d1 | pass, current metrics updated | Current README/SUBMISSION/connector guide use 863 + 93 and 92.45% for this candidate. The branch's verified 862/92.43 result and dated older counts remain explicitly historical. |
| d2 | pass for current version | Current playbook is 1.4.0/schema 2. Earlier 1.2/1.3 measurements remain labelled history rather than falsely relabelled as executions of 1.4.0. |
| d3 | pass, clarified | README distinguishes offline app, mock connector tests and two historical synthetic Groq attempts, including the original 400 and corrected 200. |
| d4 | pass for historical labelling | `plan.md` is dated historical planning. Its old calendar/checkpoints are not current delivery guidance. |
| d5 | pass for historical labelling | `docs/progress.md` is a dated historical P0 checkpoint; README points current readers to current submission/report. |
| d6 | pass on cleanup | Section numbering, brief section references, source location and obsolete review-server claim are fixed. Current measured rows are separated from historical acceptance claims. |
| d7 | pass, further duplicate fixed | The cleanup branch left one full copy in the boundary map. It is now a pointer to the single preserved human-findings block in SUBMISSION §5. |
| d8 | concern, partial fixes verified | Six conversation-index links are fixed. Active broken historical-artifact hyperlinks in the integration guide are now explicit local-only paths. Current judge-entry document links are checked. Many code-formatted historical evidence references remain; these require a publication decision, not indiscriminate link deletion. |
| d9 | concern, English navigation added | An English review index explains the internal Chinese worksheets and their pending status. Full translation or relocation is not done. Preserve exact historical review material; human chooses what belongs in the public review path. |
| d10 | pass for honest support wording | Metadata permits Python >=3.12; this audit verified full selections on 3.14.2. The branch's earlier 3.13 subset observation is attributed as earlier, not full-version certification. |
| e1 | concern, prior rationale corrected | All 15 registered worktree directories exist, including this new audit tree; the original inventory had 14. Prune dry-run returned nothing. Nine WorkBuddy branches are attached. Do not prune/delete them based on a missing-folder assumption; human reviews owners, dirty state and recovery needs individually. |
| e2 | concern, selective archive needed | `var/` contains active runtime state and consumed one-shot ledgers as well as scratch data. Do not bulk-move it. Human chooses an evidence bundle; agent inventories hashes, dependencies and active files, then archives only approved paths with repaired references. |
| e3 | concern, human publication choice | Organiser brief and assistant configuration/process-memory files remain tracked. Confirm intended public contents and any redistribution permission; review current tree and history before publishing. No privacy or rights clearance is inferred from Git ignore rules. |
| e4 | concern, preservation reasonable | Internal review/process records were not relocated. The English index reduces navigation friction; a later agent can move approved records with a link map and preserved historical hashes. Human chooses the public boundary. |
| e5 | concern for literal whole-folder cleanup | Source/root build junk is absent, but original ignored evidence trees still contain five `.DS_Store` files (four artifacts, one var). Ordinary Python caches can regenerate during verification. The submission source snapshot is clean; a claim that all ignored junk everywhere was deleted is too broad. No deletion was performed here. |
| e6 | concern, human action | Metadata only: `.env` is ignored/mode 0600; `5e test key ` is ignored/mode 0644. Contents/live status were not read. Human should rotate/revoke any live key, restrict its permissions and choose an external location; agent can update an approved path without printing/copying the value. |
| f1 | pass, native renders verified | Cover tag is separated from the platform pills. All four PNGs were regenerated locally from committed SVGs, removing reliance on the earlier Linux font rendering. 384×216 and 768×432 are exactly 16:9; 380×216 and 760×432 are 95:54. |
| f2 | pass, implemented here | Failure/return boxes now have a gap; footer text no longer collides. Diagram uses plain experiment/further-evaluation labels. SVG and PNG agree; a tracked renderer renders existing layouts without overwriting them with the old ignored template. |

## Work that would close the substantive gaps

1. **Agent: free-text simulated four-platform workflow (b2, fixture part of b4).**
   Reuse `load_fixture_index` and `SimulatedQueryService`, with a deliberately
   chosen fixture tenant and server-owned persona mapping. The fintech fixtures
   use `fintech-demo` and `user-a/user-b`, whereas the current web demo uses
   `demo-a` and `employee`; simply connecting the textarea would produce an
   identity mismatch. Keep a service/index instance for subsequent packet reads,
   expose permission-checked packet/source routes, and record protected audit
   payloads. Test arbitrary questions, no-match abstention, multi-platform
   citations, forbidden identity/provider fields, CSRF, tenant isolation,
   restricted-name non-disclosure, revocation and saved-packet denial. Browser
   checks must exercise real typed questions, not only fixed case buttons.

2. **Agent: complete inquiry scope (b5).** Add an explicit all-platform filter
   rather than looping four independently paginated requests. Bind scope and all
   filters to the signed cursor; merge-order/deduplicate request entries and
   preserve timestamp bounds, retention, tenant/role checks and fail-closed
   behavior. Test one query covering all four platforms, paging, cursor reuse
   with altered filters, cross-tenant denial and permission-change behavior.

3. **Human then agent: general LLM path (b1).** Earlier project documents record
   Groq as the selected service; they do not authorize another request. Define
   the intended runtime, allowed disclosure, credential custody, retry behavior,
   token/cost ceilings and stop conditions. Implement the adapter behind the
   existing permission/projection/citation/claim gates and test it with fake
   transport first. Any live evaluation needs new explicit authorization and a
   new exclusive ledger; the historical ledgers are consumed. Strict quotation
   validation cannot accept free paraphrase, so a synthesis-quality goal needs a
   separate grounded-answer design and evaluation, not removal of the gate.

4. **Human: submission proof and publication (a2–a4, a7, e3, e6).** Verify real
   product screenshots and the development note, rotate/revoke any live key,
   approve public contents, then publish the intended commit and test access in
   a signed-out browser. Submit through the organiser's form and retain its
   receipt. Confirm the deadline hour in the portal. A public app URL is optional;
   a local demonstration or video can show the current bounded capability.

5. **Agent after a human scope choice: evidence packaging (d8–d9, e2–e4).**
   Build a small sanitised public bundle or explicitly keep historical evidence
   local. Inventory relative paths/hashes, preserve original raw records locally,
   review redactions, update reader-facing pointers and verify a fresh source
   snapshot. Do not treat moving files, translated checklists or automated tests
   as human acceptance of the old model experiment.

## Reproduction and assets

Using the project's installed environment from an isolated source checkout:

```sh
python -m pytest --cov=aspire_brain --cov-report=term:skip-covered -q
python -m pytest tests/redteam -q
python -m ruff check src tests eval
python -m pip check
python docs/submission/render_assets.py
```

The renderer additionally needs local Playwright/Chromium. It renders committed
SVGs and blocks HTTP resources. The ignored `var/render-submission-assets.py`
rewrites an obsolete layout and should not be used. Local rendering is not a
new live provider request, public deployment or submission.
