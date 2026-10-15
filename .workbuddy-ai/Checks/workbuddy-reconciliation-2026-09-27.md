# Step 1 — handoff reconciliation (27 September 2026, second pass)

Scope: execute the baseline in [`docs/workbuddy-next-prompt.md`](workbuddy-next-prompt.md),
independently resolve its five flagged mismatches, and settle the page-35 product-use-proof
question. Everything below was re-derived from the tree in this pass; no dated number was copied
into a current result without re-running its supporting check.

**Snapshot.** All results in this file cover the working tree at HEAD
`113b98ab8795c1b1e7d6ef6915065172f279128c` **plus the uncommitted G0–G5 work** (the tree was
already dirty; it stayed dirty). Where a result covers an earlier or later snapshot that is said
explicitly.

---

## 0. PDF digest and pages

```text
$ shasum -a 256 "project requiement.pdf"
becf449ce534fab6507f85f38aa50b85b210774cd578cdd2880c4240f71ab785  project requiement.pdf
```

Matches the digest previously verified. **The PDF did not change.** Pages 15–19 and 35–38 were
re-extracted with `pdftotext -layout` and re-read.

Page 35 separates a **general proof gate** ("chat screenshots, API call logs, or a written
development-process description") from **two separately Required table rows**: the
CodeBuddy/WorkBuddy *Conversation History*, and a minimum of *3 screenshots of your chat logs*.
Page 19's technical examples are guidance, not a mandatory technology choice. Organiser
acceptance of a simulator and the exact cutoff remain **unknown**.

---

## 1. Baseline commands, exit codes and results

| Check | Command | Exit | Result |
|---|---|---:|---|
| Focused G5 regressions | `.venv/bin/python -m pytest tests/integration/test_g5_regressions.py tests/integration/test_g5_audit_retention.py -q` | 0 | **55 passed**, 1 warning |
| Full suite + coverage | `COVERAGE_FILE=/private/tmp/seaglass-reconcile.cov .venv/bin/python -m pytest --cov=aspire_brain --cov-report=term-missing --cov-report=json:… -q` | 0 | **373 passed**, 1 warning, **92.72 %** statement coverage |
| Ruff | `.venv/bin/python -m ruff check src tests` | 0 | `All checks passed!` |
| Dependency consistency | `.venv/bin/python -m pip check` | 0 | `No broken requirements found.` |
| Offline evaluation | `.venv/bin/python -m aspire_brain.cli evaluate --offline` | 0 | **22/22 passed**; `lexical_retrieval 8/12` |
| Grounding evaluation | `.venv/bin/python -m aspire_brain.cli evaluate-grounding --offline` | 0 | `method=exact_cited_span`; denominator `{cases: 3, claims_evaluated: 5}`; 5 supported, 0 unsupported, 1 abstention; control detected; **all live fields null** |

Versions: Python 3.14.2, pytest 9.1.1, ruff 0.16.8, coverage configured with `fail_under = 80`.

> **Environment note (reproducibility).** The default pytest base temp dir
> (`/private/var/folders/…/pytest-of-<user>`) is not writable under this sandbox, which produced
> **248 spurious errors**. The suite was re-run with an in-project base temp
> (`TMPDIR=$PWD/var/pytest-basetemp --basetemp=$PWD/var/pytest-basetemp`), which is why the
> commands above carry that flag. The 248-error run is a sandbox artefact, not a code failure.

Artifacts saved this pass (dated, old files preserved):

```text
artifacts/g5-reconcile-2026-09-27/pytest-full.txt              ← new 373-pass transcript
artifacts/g5-reconcile-2026-09-27/coverage.json                ← coverage for that run
artifacts/g5-reconcile-2026-09-27/evaluate-offline.json
artifacts/g5-reconcile-2026-09-27/evaluate-grounding-offline.json
artifacts/g5-reconcile-2026-09-27/*.previous.*                 ← preserved prior snapshots
```

---

## 2. Mismatch A — 373-pass review result vs the 367-pass transcript

**Resolved.** The current tree collects **373** tests and passes **373**. The saved
`artifacts/g5/pytest-full.txt` ends `367 passed … 92.72%`.

The decisive check is the per-file coverage table: it is **byte-identical** between the two runs.

```text
$ diff <(sed -n '/tests coverage/,/^TOTAL/p' artifacts/g5/pytest-full.txt) \
       <(sed -n '/tests coverage/,/^TOTAL/p' artifacts/g5-reconcile-2026-09-27/pytest-full.txt)
(coverage tables identical)      # TOTAL 2790 statements, 203 missed, 92.72% in both
```

**Conclusion.** Same source snapshot, same statement counts, same coverage. The transcript's
*test count* is stale by exactly 6 tests — it was captured before 6 tests were added to the run
(the `test_g5_audit_retention.py` file collects 6). It is **not** evidence of 373 and must not be
cited as such.

- Superseded transcript preserved: `artifacts/g5/pytest-full.txt` (367).
- Dated replacement: `artifacts/g5-reconcile-2026-09-27/pytest-full.txt` (373).
- Coverage moved **down** 0.02 pt vs the pre-fix G4 baseline (92.74 % → 92.72 %); it is still
  above the project's own ≥80 % floor, and the decrease is **not** described as an improvement.

---

## 3. Mismatch B — 111-file manifest vs 103-file summary

**Resolved by recomputation, and the count is a moving target.** `var/g5-manifest.py` walks
`git ls-files --cached --others --exclude-standard`, skipping `artifacts/`, `var/` and caches.

```text
artifacts/g5/manifest-summary.txt        103   (stale — written before later docs existed)
artifacts/g5/source-manifest.json        111   (at its 21:56 save time)
recomputed in this pass                  113
```

The two-file increase is explained exactly:

```text
+ docs/rag-red-team-assessment-2026-09-27.md
+ docs/workbuddy-red-team-prompt-sequence.md
~ docs/workbuddy-next-prompt.md               (hash changed after 21:56)
```

`whitespace_clean: true`, `whitespace_problem_count: 0` in every snapshot — the tracked **and**
untracked whitespace scan is clean. Because the manifest **includes this prompt**, editing the
prompt necessarily invalidates the manifest's own hash; the summary is therefore regenerated
*after* the documentation edits are final (see §6).

---

## 4. Mismatch C — archive file-count convention and contents

```text
$ ls -l artifacts/g5/aspire-internal-brain-src.tar.gz   →  867,438 bytes
$ tar -tzf … | grep -v '/$' | wc -l                     →  117 regular files
$ tar -tzf … | grep -i PACKAGE-MANIFEST                 →  …/PACKAGE-MANIFEST.json
```

`PACKAGE-MANIFEST.json` records `file_count: 116`, i.e. **the package excluding the manifest
itself**. The convention is the defect, not the contents: the manifest was counted before it was
added to the package. Corrected convention: the package contains **117 regular files, including
`PACKAGE-MANIFEST.json`**; the manifest will state this explicitly.

Secret scan of the archive — the only match is the intended, safe example file:

```text
$ tar -tzf … | grep -Eai '\.env$|\.key$|\.pem$|\.db$|\.sqlite|\.log$|\.pyc$|/\.git/|requiement\.pdf'
aspire-internal-brain/.env.example      ← expected, contains names only, no secrets
```

No `.env`, key, `.pem`, database, log, bytecode, `.git` or organiser-PDF entry is present. The
archive is regenerated after the docs are final (§6).

---

## 5. Mismatch D — 380×216 cover vs an exact-16:9 rendition

```text
380×216 = 95/54 = 1.7593     exact 16:9 = 1.7778     Δ = 0.0185
```

Page 35 **requires** 16:9 and **recommends** 380×216. Those are not the same ratio. The
recommended-size version is kept; exact 16:9 renditions were added and both are labelled.

| File | Size | Ratio | Note |
|---|---|---|---|
| `cover-16x9-380x216.png` | 380×216 | 95:54 | PDF's recommended size — **not** exactly 16:9 |
| `cover-16x9-384x216.png` | 384×216 | **exact 16:9** | new, meets the stated ratio requirement |
| `cover-16x9-768x432.png` | 768×432 | **exact 16:9** | new, 2× rendition |
| `cover-16x9-760x432.png` | 760×432 | 95:54 | previous larger rendition |

---

## 6. Mismatch E — the architecture diagram's "12,000+ pages" label

The architecture SVG placed **"12,000+ pages"** under the Confluence box inside a section headed
*"1 · Heterogeneous sources (simulated)"*. 12,000+ pages is the challenge statement's
**Company A** scale, not this fixture's size. A reviewer could read it as a measured simulation.

Correction applied to `docs/submission/architecture-trust-boundary.svg` (old copy preserved):

```text
- 12,000+ pages
+ challenge premise: 12,000+ pages
+ Scale note: "12,000+ pages" and "30% of the workweek" are the challenge statement's
  Company A premises, not this fixture's measured size. The simulated corpus is far smaller.
```

`architecture-trust-boundary.png` was re-rendered (2800×2320, 2× scale).

---

## 7. Product-use proof (page 35) — corrected, and still incomplete

The previous `CHAT-PROOF-INSTRUCTIONS.md` **conflated** the general proof alternative with the
two separately-Required table items. That document has been corrected in place; the prior version
is preserved at `artifacts/g5-reconcile-2026-09-27/CHAT-PROOF-INSTRUCTIONS.previous.md`.

The actual WorkBuddy/CodeBuddy conversation surface **is** available on this machine: the genuine
session transcripts live under `~/.workbuddy-ai/projects/**/*.jsonl`. Six development sessions
were exported **verbatim** (no authored content, redacted only for the home path and
token-shaped strings) to `docs/submission/chat-proof/conversation-history/`.

| # | Session title | Stage | Records |
|---|---|---|---|
| 1 | Add source-specific contract types and tests | G1 source contracts | 246 |
| 2 | Extend G1 simulator for four-platform coverage | G1 four-platform simulator | 445 |
| 3 | Implement G2 deterministic sync milestone | G2 deterministic sync | 429 |
| 4 | Implement G3 platform routing and ranking | G3 routing and ranking | 686 |
| 5 | Implement G4 grounded-answer provider and audit | G4 grounded provider and audit | 875 |
| 6 | Close G3/G4 gaps and package G5 rehearsal | G5 gap closure and packaging | 779 |

**Item 1 — Conversation History: satisfied (authentic export).**

**Item 2 — ≥3 chat-log screenshots: still open.** Three images were rendered from the authentic
transcripts (`chat-proof/excerpts/chat-0{1,2,3}-*.png`). Each carries a visible header stating it
is an **exported transcript, not a UI screenshot and not a synthetic image**. Whether the
organiser accepts a transcript export for the literal "screenshots of your chat logs" row is
**unknown**; therefore Item 2 is recorded as **open / pending**, and the submission remains
**incomplete**. No chat content was fabricated; no application screenshot is used as chat proof.

---

## 8. Snapshot ledger

| Claim | Snapshot it covers | Source artifact |
|---|---|---|
| 373 passed / 92.72 % | HEAD `113b98a` + dirty tree, this pass | `artifacts/g5-reconcile-2026-09-27/pytest-full.txt` |
| 367 passed / 92.72 % | earlier snapshot, **stale test count** | `artifacts/g5/pytest-full.txt` (preserved) |
| 55 focused regressions | this pass | command output above |
| manifest 113 files, 0 whitespace problems | after Step-1 doc edits | `artifacts/g5/source-manifest.json` |
| manifest 111 files | 21:56 save time | `artifacts/g5-reconcile-2026-09-27/source-manifest.previous.json` |
| manifest summary 103 files | stale | `artifacts/g5-reconcile-2026-09-27/manifest-summary.previous.txt` |
| archive 867,438 B / 117 files | 22:00 snapshot | `artifacts/g5/aspire-internal-brain-src.tar.gz` |
| live connectors / latency / entitlement / organiser acceptance / cutoff | **unknown** | not evidenced |

## 9. Still open after Step 1

- Item 2 of page 35 (literal UI chat screenshots) — open; submission incomplete.
- G3/G4 **not** declared fully closed; G5 **not** complete; project **not** submission-ready.
- Live connectors, propagation latency, model entitlement, organiser acceptance, eligibility and
  the exact cutoff remain **unknown**.
