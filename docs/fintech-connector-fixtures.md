# Fintech connectors and offline fixture acceptance

The controlled dataset in `data/fixtures/fintech_operations/` provides fictional
workplace-style evidence for all four required source platforms. Its manifest
labels every bundle as offline and unverified live. Source locators and user IDs
are invented local identifiers; the bundle neither installs integrations nor
establishes remote API compatibility.

## Implemented components

| Component | Location | Purpose |
| --- | --- | --- |
| HTTP boundary | `src/aspire_brain/platforms/connectors/core.py` | Explicit caller credentials and identity binding; allowed HTTPS origins and read endpoints; bounded responses; no retries, redirects or environment proxy discovery |
| Four adapters | `src/aspire_brain/platforms/connectors/adapters.py` | Known Confluence pages, Jira issues, Slack channel/thread messages and Drive files normalize to immutable dated documents |
| Registry | `src/aspire_brain/platforms/connectors/__init__.py` | `connector_for(session)` selects the matching adapter |
| Fixture loader | `src/aspire_brain/platforms/connectors/offline.py` | Validates file hashes, offline labels, paths and identities; loads the existing simulated synchronization model |
| Mock HTTP bridge | `src/aspire_brain/platforms/connectors/mock_bridge.py` | Rehearses adapters through existing query, packet and audit services; refuses live sessions |
| Expected outcomes | `data/fixtures/fintech_operations/expected-outcomes.json` | Nine authored acceptance scenarios; not a live test report |

The fixture loader and HTTP adapters are separate entry points. Markdown/CSV
fixture files are local scenario evidence, not saved vendor API responses.
Adapter tests supply synthetic API-shaped responses separately. The default web
app is unchanged; it does not automatically display or ingest this new bundle.

## Run locally

From the repository root, using the existing virtual environment:

```sh
.venv/bin/python -m pytest tests/unit/test_connector_core.py tests/unit/test_platform_adapters.py tests/unit/test_connector_fixtures.py tests/integration/test_connector_mock_bridge.py tests/integration/test_connector_fintech_workflow.py -q
.venv/bin/python -m pytest --cov=aspire_brain --cov-report=term:skip-covered -q
.venv/bin/python -m pytest tests/redteam -q
```

Local verification on 13 October 2026: 862 unit/integration tests passed,
including 174 connector/fixture tests, with 92.43% overall statement coverage.
All 93 separately selected red-team tests and scoped Ruff checks passed after
these adapter changes.
The suites report an existing Starlette/httpx deprecation warning. These counts
describe offline execution in this checkout, not live API or browser evidence.

Load the scenario from Python without credentials or network access:

```python
from datetime import UTC, datetime
from pathlib import Path
from aspire_brain.platforms.connectors.offline import load_fixture_index

index = load_fixture_index(
    Path("data/fixtures/fintech_operations"),
    now=datetime(2026, 10, 12, 3, 0, tzinfo=UTC),
)
assert len(index.records) == 8
# updates=True loads runbook 1.1 instead of 1.0; never both as current records.
```

`test_connector_fintech_workflow.py` shows the complete setup with a temporary
database, fictional `user-a`/`user-b`, an authorized `officer`, the extractive
offline provider and protected audit storage. Fixture times are fixed scenario
times; audit inquiry uses the actual execution clock. Tests create temporary
local databases and never publish the fixture documents.

For adapter usage, construct `ConnectorSession` with an explicit `IdentityBinding`
and `httpx.MockTransport`, call `connector_for(session).fetch(SourceRef(...))`,
and close the session (or use its context manager). Runnable examples for all
four platforms are in `test_platform_adapters.py`; the Jira example in
`test_connector_mock_bridge.py` continues through answer creation, saved-packet
read and revocation. No configuration file or environment credential is read.

## Executed checks and expected outcomes

| Scenario | Expected local result | Test evidence |
| --- | --- | --- |
| Identity / HTTP errors | Wrong identity stops before content; 403/404 share an outward error; expired access and rate limits fail without retry | Core and adapter unit tests, including real session plus mocked HTTP for all four platforms |
| Fixture integrity | Reject tampering, traversal, missing offline labels and invalid ACLs | Fixture unit tests |
| Ordinary cross-platform query | Cite all four platforms; restricted names, IDs and amounts absent from packet and provider context | `test_ordinary_cross_platform_evidence_and_no_hidden_metadata` |
| Handover / runbook | Three manual-review payments; 30 minutes before update, 15 after sync; pending sync abstains | `test_handover_fact_and_runbook_revision_require_synchronization` |
| Restricted case | A receives supporting evidence; B's actual case question abstains with no citations or provider dispatch | Authorized case and unanswerable-question tests |
| Loss / fraud questions | Source excerpts qualify USD 12,480 as held payment, not confirmed loss; fraud is not established | Actual financial-question tests |
| Fabricated financial conclusions | Unsupported loss, fraud and budget claims rejected before saving a packet | Fabricating-provider test |
| Missing budget | Actual budget question abstains under the configured four-platform completeness policy | Unanswerable-question test |
| Revocation | After both source grants are revoked and synced, new retrieval abstains and saved packet read is denied | Case-revocation test; mock HTTP bridge also tests remote-shaped 404 revocation |
| Audit | Ordinary inquiry denied; officer reconstructs query, answer and access decisions; chain validates | Officer reconstruction test |

These are service-level workflow tests, not new browser automation. The offline
provider returns source excerpts for inspection. Passing the missing-budget
case demonstrates conservative completeness-based abstention, not a general
semantic detector for unanswered questions. The expected-outcomes file also
specifies details (such as every queue total and next action) for human evaluation;
do not equate a test count with every natural-language requirement being proven.

## Acceptance sequence

1. Check each manifest SHA-256 against its file bytes and reject invalid paths,
   identities, source kinds, versions or integrity values.
2. Retrieve as `user-a` and `user-b`. B must not receive restricted case/invoice
   contents or metadata. Check model-bound context as well as the visible answer.
3. Ask the cross-platform status question in `expected-outcomes.json`. Preserve
   the distinction between a 09:30 queue snapshot, later workbook evidence and
   an actual completed payment. Cite the sources that support each statement.
4. Apply only the runbook revision 1.1 update. Verify current results contain the
   15-minute threshold and partner-reference closure condition.
5. Revoke A's access to both restricted records. Recheck new queries, direct
   source reads and previously saved packets. Prior user knowledge cannot be
   retroactively erased.
6. Ask the loss, fraud and missing-budget questions. Answers must distinguish
   evidence from inference and acknowledge absent permitted evidence.
7. Use the authorized audit workflow to reconstruct decisions without giving an
   ordinary user access to restricted audit records.

## What passing means

Offline tests establish only the behaviours they actually execute. Fixture
loading and ACL filtering alone do not establish answer support, HTTP behaviour,
packet persistence controls or audit completeness. Treat the expected-outcomes
file as acceptance criteria until corresponding execution evidence exists.

Live closure additionally requires live verification of these adapters, user identity mapping,
upstream permission checks and observed update/revocation enforcement across all
four platforms. Measure publication and permission-change times independently;
authored fixture clocks are not live latency measurements. The restricted
invoice deliberately shares the case's audience so duplicated facts do not
bypass the case-revocation test.

## Remaining live integration work and limits

The adapter code is implemented but live compatibility is unverified. Live
closure still needs server-owned identity mappings, real account/token setup,
an application integration path and independently observed upstream permissions,
updates, deletions and revocation. A live `ConnectorSession` requires an explicit
`allow_live=True` and caller-supplied credential; this switch is not user consent,
and the mock bridge rejects such a session. Do not send real records through the
simulated bridge. Do not accept identity bindings from untrusted request JSON.

Reads are requester-scoped, with identity checked on each fetch. The repeated check
is retained because a TTL cache would delay detection of a changed or revoked
credential; no batch-fetch contract exists yet. This is not ACL
enumeration or proof that admin/service-account access matches an ordinary user.
The offline bridge only rechecks cached permissions after explicit `refresh`;
it is not a live revocation cache or a background synchronizer.
Returned documents must match the requested source/parent (or Slack workspace,
channel and selected thread). An uncertain refresh clears old records, including
when an adapter raises an unexpected exception.

Limits are deliberate: known IDs only; 1 MiB HTTP response and 5,000-character
normalized document limits. Larger content fails explicitly as `content_too_large`
rather than being silently truncated; chunking would require a source/version and
downstream evidence contract. Slack reads at most 10 pages/100 raw messages, with
explicit thread requests and no recursive history expansion. Its default page size
is 15 for compatibility with restricted app tiers; `SlackConnector(session,
page_size=100)` is available only when the application's tier permits it. Join and
leave events are skipped and counted in sanitized logs; unknown content-bearing
subtypes still fail the fetch. Page size is restricted to 1–100, and the overall
100-message bound counts raw messages across all pages, including skipped events.
Attachments/files and blocks-only messages (empty or absent text) fail the entire
Slack fetch with `unsupported_content`, even when earlier messages were readable;
they are not silently skipped. Blocks are not independently extracted; supported
messages use their text field. Missing or wrongly typed text without a supported
representation remains an invalid response. Slack workspace URLs must be under
`*.slack.com`. Derived reply locators include `thread_ts` and `cid`; live navigation
has not been verified.

Info, note, tip, warning and code Confluence macros are extracted from their visible
bodies and `title` parameters; configuration parameters such as `language` and
`collapse` are skipped. Code macro/plain-text bodies and `<pre>` retain indentation,
blank lines and trailing whitespace; ordinary prose still receives whitespace
normalization. Table `colgroup`/`col` elements are treated as layout only and may
not contain unrepresented content. `ac:link` supports local plain/rich labels,
page titles and user identifiers without fetching linked targets. Links without
a supported label, image links, unknown macros and `ac:adf-extension` remain
unsupported; no claim is made that all Cloud editor panels use a supported format.
Rich table structure and link destinations are not reconstructed.

Jira media/unsupported ADF nodes, Slack DMs and Drive PDFs/Sheets are rejected.
Jira reads summary, description and status, not comments or attachments.
Drive requires a known direct parent folder, including for Shared Drive files; nested ancestry and
files without a verifiable parent require separate live validation. OAuth
installation/refresh, discovery, live sync scheduling, retries, large-file chunking
and tenant admin UI are not implemented here. Credential values must never be
stored in this fixture bundle or committed.

## Adapter follow-up regression evidence

The follow-up cases were derived from the reported indentation, missing macro
title, table/link, Slack representation and page-size issues. The adapter test
target was run before each implementation change: the three RED runs reported
9 failed/74 passed, 5 failed/89 passed and 6 failed/95 passed for the intended
defects. The final adapter target passed all 101 cases, including exact multiline
code/pre output, title/CDATAs, unknown or malformed structures, local link labels
and whole-fetch Slack failures. The final coverage command above passed all
862 unit/integration tests; the separately selected 93 red-team tests and scoped
Ruff checks passed as well. No Git checkpoint was created for these already
untracked connector/test/document files; RED/GREEN evidence is recorded here.

These checks ran under Python 3.14.2. The code-macro CDATA regression remains in
the normal suite and should also run on the deployment's Python patch version;
this run does not verify every Python version allowed by `requires-python`.

API contracts referenced during adapter development:

- [Confluence content](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content/) and [users](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-users/)
- [Confluence storage examples](https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html) document link labels and resource identifiers; this Data Center reference does not establish Cloud response compatibility.
- [Jira Cloud REST v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- Slack [auth.test](https://docs.slack.dev/reference/methods/auth.test/), [conversations.info](https://docs.slack.dev/reference/methods/conversations.info/), [history](https://docs.slack.dev/reference/methods/conversations.history/) and [replies](https://docs.slack.dev/reference/methods/conversations.replies/)
- Slack [permalink examples](https://docs.slack.dev/reference/methods/chat.getPermalink/) show the reply timestamp in the archive path and the parent timestamp/channel in query parameters.
- Drive [files](https://developers.google.com/workspace/drive/api/reference/rest/v3/files), [export](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export) and [about](https://developers.google.com/workspace/drive/api/reference/rest/v3/about)
