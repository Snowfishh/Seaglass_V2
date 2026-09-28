# Local demonstration

All people, documents, project terms and amounts in this demo are fictional. The app checks documented limits and refers unresolved cases to finance for review. It does not approve payments.

## Prepare

Follow the [README setup](../README.md), then start the server:

```bash
python -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The local persona selector is on **Ask**. Changing personas clears displayed answers. The server checks current permissions on every read.

## Simulated Aspire case and officer inquiry

Select **employee** on Ask, then open **Case demo**. The case buttons submit authenticated,
CSRF-protected requests; anonymous and demo-disabled requests cannot run them. Run Case 1 for a
question-driven answer: the service routes the migration question to **Jira and Slack**, prints
the routing basis, marks Confluence and Drive as **omitted coverage** (not evidence of absence),
shows the context-budget line, and applies a **last-7-days** window to Slack messages by their
event time while leaving Jira issues unfiltered. Case 2 runs an actual simulated
**update → sync → query** sequence for a Confluence payment runbook: the older runbook is
ingested at 12:30, the owner pushes the failover step at 13:00, a query at 13:05 reports
`stale` rather than presenting the old version as current, a sync at 13:10 ingests the update,
and the 14:05 answer contains the new step. The card distinguishes the **observed demo query**
(14:05) from the **first post-sync query** (13:10, at ingestion time), states that the earliest
correct answer is **unknown (not polled)**, prints the times against a declared 3600 s budget
and labels them `simulated_elapsed`; wall-clock and live propagation remain unmeasured. Case 3
abstains without disclosing the restricted report. Case 4 runs in fresh permission state each
time and shows the saved packet denied after a simulated revocation; the card is labelled
**"4. Permission Revocation Handling (simulated)"** and states that no live connector is
contacted, so the simulated UI cannot be read as a live permission change. The supplemental
**Case 6**
card shows the Google Drive path: a file create → sync → query, then a delete → tombstone, plus
a **real** late synchronization (mutation 13:00 → ingestion 14:10) whose query at 14:10 is
reported as an observed over-budget failure.

The supplemental **Case 7** card shows the grounded-answer path. It selects the deterministic
local `fake_grounded` provider explicitly and prints: the composed answer with citations; the
**provider runtime** recorded as `mode simulated` / `outcome not_run` with `Live request made:
false` and every live field unmeasured (service, model, endpoint, region, cost, latency); a
**claim-level support** line with a denominator, a `simulated` label, the method
(`exact_cited_span`) and each claim's verdict, with the lexical-overlap ratio labelled
**diagnostic only**; the **abstention control** (a question with insufficient permitted evidence
abstains and asserts nothing); and the statement that **`offline_extractive` remains the
default**. A claim is released only when it is an exact contiguous span of one cited source's
text, so a contradiction, a changed number or a paraphrase is refused. The card never presents a
fake-provider result as a live-model result. A provider that asserted an unsupported claim would
be refused and release no evidence.

To inspect Case 5, run Case 2 while still **employee**, switch to **auditor** on Ask, return
to Case demo and choose **Run officer inquiry**. It reconstructs the exact Case 2 question,
retrieved IDs, answer, timestamp and per-document decisions from an encrypted payload
linked to the HMAC audit event, and now also prints the **retention** window and entry cap,
the **checkpoint-anchoring** limit (whether the chain was verified through a checkpoint and how
many tail events remain unanchored) and a **pagination** line (page size, returned, total matches,
whether more remain, and whether a continuation was issued). `/api/audit/inquiry` also supports
officer searches by subject, platform, space or document, time and decision mode, and accepts
`limit` and a signed `cursor` so a result set larger than one page can be traversed completely
without loss at equal timestamps. The default `retrieved` mode shows material selected for the
answer; `denied` shows documents evaluated but withheld from the requester. Both modes cover only
protected simulated case queries. The HMAC chain's unanchored tail is not proof that the log is
complete.

To rehearse the retention path from a terminal at the runtime root:

```bash
python -m aspire_brain.cli apply-retention --tenant demo-a            # dry run: reports what would go
python -m aspire_brain.cli apply-retention --tenant demo-a --apply    # removes only encrypted payloads
```

Retention is scoped to one tenant and removes only the encrypted payload; the HMAC chain is never
truncated, so retention does not weaken tamper detection and does not turn the chain into a
completeness proof.

## Ask: general, historical and case-specific answers

Select **employee**. Use the question “What is the Singapore contractor travel cap?”, general workflow, case date `2026-09-10`, jurisdiction `SG`, worker type `contractor` and currency `SGD`. Leave project and cost centre blank. Expect a cited **250 SGD per claim** general answer from `sg-travel-v2`; the case outcome is `not_applicable`. This does not certify a contractor claim.

Change the case date to `2026-08-20`. Expect **200 SGD** from `sg-travel-v1`. `2026-08-31` still uses v1; `2026-09-01` selects v2. A version stops applying on its end date, so only v2 applies on 1 September.

Next use “Does this P17 contractor claim of SGD 220 meet the documented travel limits?” and these fields:

| Field | Value |
|---|---|
| Workflow | Contractor travel case |
| Case date | `2026-09-10` |
| Jurisdiction / worker | `SG` / `contractor` |
| Project / cost centre | `P17` / `CC-17` |
| Amount / currency | `220` / `SGD` |

As **employee**, expect `needs_review` / `undetermined` with required contract terms unverified. The packet must not disclose a hidden contract's cap, title or identifier. Changing the project to one with no accessible terms still uses the same safe missing-evidence explanation.

Switch to **finance_lead**, re-enter and submit the same P17 case. Expect `answered` / `exceeds_documented_limits`, with the permitted **150 SGD** project override from `p17-contract-v2` and relevant citations. At `150`, the outcome is `within_documented_limits`; at `150.01`, it exceeds the cap. Neither result authorises spending. The full contract case depends on declared scope; include the cost centre when it is known.

## True conflict and separate jurisdictions

As **employee**, select general workflow, date `2026-09-10`, jurisdiction `SG`, worker `contractor`, cost centre `CC-CONFLICT`, currency `SGD`, and leave project/amount blank. Expect `needs_review` / `undetermined` with conflicting rules the employee can read from `conflict-a-v1` and `conflict-b-v1`. Expand the conflict/rule details; no retrieval-score or upload-date tie-breaker chooses a winner.

Clear the cost centre, change jurisdiction to `MY` and currency to `MYR`. Expect **400 MYR** general guidance from `my-travel-v1`. Singapore's different cap does not create a conflict because it applies to a different jurisdiction.

## Sources, history and protected exports

Open an answer citation to use the **Sources** view. It displays only the exact permitted version/chunk, locator, text and content hash. Follow its document-history link to **Policy history**, or enter `sg-travel` as the logical document ID. Inspect readable states, effective dates and explicit relations. Approved historical versions remain visible. History may also show draft, future or withdrawn versions, but these are not used as evidence for the current case.

Use **Export evidence packet** on an answer. Save the request ID to inspect `/api/packets/{request_id}` or `/api/packets/{request_id}/export` while authenticated as its owner. A different principal cannot read it, including an auditor. Unknown and inaccessible source identifiers return the same error. A policy admin receives only explicit policy grants, and the other-tenant persona receives only its tenant's records.

## Audit view and checkpoints

Switch to **auditor**, navigate to **Audit trail**, and load events. Expect a limited trace for the current tenant with request IDs, sequences and a chain-verification result. The auditor role alone does not unlock evidence packets or knowledge documents. A query attempt lacking a final outcome appears in integrity diagnostics.

In a terminal at the runtime root:

```bash
python -m aspire_brain.cli audit-checkpoint --tenant demo-a --output artifacts/audit-head.json
python -m aspire_brain.cli audit-verify --tenant demo-a
python -m aspire_brain.cli audit-verify --tenant demo-a --checkpoint artifacts/audit-head.json
```

Verification without a checkpoint checks the observed chain but cannot establish completeness. Verification with a checkpoint checks the chain through that checkpoint; it cannot establish completeness after that point. Copy a checkpoint into independently protected storage before treating it as a trust anchor. Do not alter the working database to demonstrate tampering: automated tests use isolated databases for modified entries, deletion, sequence changes, concurrency and rollback checks.

## Revocation and automated scenarios

Revocation is a controlled local operator action. Use a disposable runtime root when demonstrating it so the main fixture remains available. From the repository root:

```bash
python -m aspire_brain.cli --root artifacts/revocation-demo init-demo --fixtures data/demo
python -m aspire_brain.cli --root artifacts/revocation-demo revoke-source --version p17-contract-v2
```

For the full browser demonstration, run the server with `artifacts/revocation-demo` as its working directory and create a finance P17 packet before the revocation command. Retain its request/citation identifiers. Fresh source and whole-packet reads must fail; an in-flight revision change must abort with a retry outcome. Re-seeding must preserve deliberate metadata changes. Material downloaded before revocation cannot be recalled.

Run the labelled scenarios and the regression suite:

```bash
python -m aspire_brain.cli evaluate --offline
python -m aspire_brain.cli evaluate-grounding --offline
python -m pytest --cov=aspire_brain --cov-report=term-missing
```

See [evaluation interpretation](../eval/README.md) and the [current stage report](stage-report-2026-09-27.md) for results and remaining gaps. The [earlier checkpoint](progress.md) is historical. Fake-provider and sentinel tests cover specific scenarios; they do not establish live-model safety or security in all conditions. The grounding evaluation writes `artifacts/g4-claim-support.json` with a denominator and a `simulated` label; it is a fake-provider result, not a live-model result.

## Prompt 4 observed review state — 28 September 2026

The existing simulated Case 4 wording is preserved. Fresh loopback HTTP rehearsal passes
cross-tenant filtering, a 404 saved-packet denial after revocation, and a 502 refusal of a forged
but cited claim. Raw response and audit rows are saved in
`artifacts/redteam-prompt4-2026-09-28/api-rehearsal.json`. These are fictional local fixtures.
No live platform or model acceptance is established. The human review packet is pending actual
attributed findings; neither this application surface nor a transcript export substitutes for
the three literal CodeBuddy/WorkBuddy chat screenshots required by page 35.


### Prompt 4 human findings and final snapshot — 2026-09-28

The account holder reviewed both packets: **A/B/C/D are scoped human passes**. Original
findings and follow-up findings are preserved in `artifacts/redteam-prompt4-2026-09-28/`
(`HUMAN-FINDINGS-2026-09-28.md`, `HUMAN-FOLLOWUP-FINDINGS-2026-09-28.md`). D covers this
HTTP unsupported-claim refusal; B covers one synthetic extractive normal HTTP request; C covers
the same packet's pre/post read. The latest closing addendum documents the packet dependency
locally and awaits any human expansion of C. These passes do not establish synthesis quality,
live acceptance, audit completeness or independent checkpoint/key custody.

The authoritative code verification is `artifacts/redteam-prompt4-2026-09-28/final-reviewed/`:
**438 passed / 91.73% statement coverage**, **58 focused tests**, Ruff and `pip check` exit 0.
The release gate and its per-case companion are in `final-reviewed/clean-final/`. The companion
now reports denominators (22 declared / 21 valid executed / 1 invalid) and each query's request ID
and audit metadata. RT-007 remains unexecuted; attachment carriers are uncovered. RT-016/018
remain measured availability losses. One ingestion seed and no action-tool surface remain explicit
limits. Playbook 1.4.0/schema 2 and the attack-only denominators are unchanged.

`api-followup-audited.json` is a separate synthetic loopback HTTP execution: one normal
`POST /api/queries` returned 200 with permitted citations; a saved packet returned 200 before
revocation and 404 afterward; the refusal returned 502 with stored `error_code: unsupported_claim`.
All 29 local tenant audit rows are retained, including metadata and surrounding requests.
`verify-local-audit.py` reproduces the local HMAC check. **Completeness remains unproven**; there is
no independent checkpoint. Packet audit rows still omit the target packet ID; the client trace
records the target URL. Neither the normal HTTP control nor RT-021 establishes synthesized-answer
quality. RT-009 and the HTTP refusal are different executions with different request IDs.

The final isolated implementation defect failed on RT-009; all copied source hashes were restored
and the restored-copy gate passed (`final-defect-record.json`). The Python `NetworkGuard` is an
IP-socket connect guard, not process-wide isolation. Promptfoo remains `not_run` because an approved
pinned dependency path is absent and exact-runner egress is unverified.

Four states: **simulated implementation — bounded local contracts verified; live acceptance —
unverified; product-use proof — incomplete; submission status — not ready**. The six-session export
exists; **at least three literal CodeBuddy/WorkBuddy chat-surface screenshots are still missing**.
The three supplied images were inspected: their banners identify rendered transcript exports, so zero qualify as literal chat-surface screenshots. G0/G4/G5 acceptance gaps remain open.
Final manifest/package: `artifacts/redteam-prompt4-2026-09-28/source-manifest.json` and
`github-package/aspire-internal-brain/`; archive bytes/hash appear only in the external
`package-summary.json`. Previous packages and historical sections are preserved. Nothing was
pushed, deployed, published or submitted.
