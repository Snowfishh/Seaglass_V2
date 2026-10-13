# Fictional fintech operations fixtures

**Offline fixtures only. All people, companies, transactions, metrics and
procedures are invented. These files do not describe actual Aspire operations,
policies or incidents. No live platform integration is demonstrated by them.**

The scenario follows a Singapore supplier-payment operations shift on 12 October
2026. Confluence contains the handover, runbook and restricted case; Jira tracks
status-delay investigation; Slack holds shift discussion; Drive supplies a
five-row reconciliation extract and restricted invoice evidence. The extract
covers the five processing records, not the entire 126-payment queue.

## Manifest contract

`manifest.json` has `schema_version: 1`, `mode: offline_fixture`, `fictional: true`,
`live_verified: false`, tenant `fintech-demo`, and two arrays:

- `documents`: eight initial records, including runbook revision 1.0.
- `updates`: one replacement of `conf-payment-runbook`, revision 1.1.

Each record contains `platform`, `source_id`, `source_kind`, `version_id`,
`content_file`, `content_sha256`, `locator`, `parent_id`, `thread_id`,
`source_updated_at`, `event_at`, and `allowed_principals`. File paths are relative
to this directory. SHA-256 values cover exact UTF-8 file bytes, including final
newlines. Source kinds follow the application's `SimulatedSource` vocabulary.
`fixture://` locators and identifiers are local fixture references, never actual
API identifiers, authenticated URLs or remote account mappings.

`event_at` records Slack message creation separately from source modification.
Every timestamp is authored scenario data. It proves no actual publication,
retrieval, provider call or synchronization timing.

## Access assumptions

`user-a` and `user-b` are fictional ordinary users. Both see ordinary records;
only `user-a` sees the restricted case and restricted invoice. A real setup
administrator is outside these query identities. Do not treat email reuse,
fixture labels or a locally declared ACL as evidence of upstream permissions.

The shared handover intentionally mentions a generic beneficiary-verification
work item. Restricted customer names, amounts and account labels occur only in
the case and invoice. Both restricted sources must be revoked to remove access
to the repeated customer facts. Public content is workspace-accessible in this
exercise; it is not internet-public.

## Expected outcomes and execution boundaries

`expected-outcomes.json` is an independently authored acceptance oracle. It
defines correct source access, supported facts, forbidden disclosures, revision
replacement, revocation and unsupported-answer behaviour. It is a specification,
not a report that every check has passed. An offline connector check can prove
file integrity and local ACL selection. Answer correctness, provider context,
saved-packet rechecks and audit inquiry also need application-level tests.

For a live exercise, create actual records on each platform and verify A/B access
directly first. Capture the real source IDs, authenticated principal mapping,
permission-change time and first successful enforcement observation separately.
Do not replace fixture timestamps with claims of measured latency.

Initial queries should observe the 30-minute revision. Applying the explicit
revision 1.1 update should yield a 15-minute threshold and a new partner-reference
closure requirement. Do not load both revisions as simultaneously current facts.
The procedure's invented triage threshold is not a settlement SLA.

No fixture should be uploaded, posted or sent to a model merely by being loaded.
No credentials, real customer information or externally payable instructions
belong in this directory.
