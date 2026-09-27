# G1 local verification — 25 September 2026

The baseline checkout had a modified `plan.md` and untracked P0 deliverables; none were
removed or overwritten. Existing `artifacts/pytest-final.txt` recorded 148 P0 tests and
92.56% coverage. A fresh pre-change run in this checkout passed 148 tests. The supplied
stage report's 149-test result belongs to a different worktree.

The source contract and five independent scenario expectations were written before the
simulator. The exact case brief was not present here; `docs/g1-access-status.json` records
brief availability and unknown real-platform access. Each case detail is labelled as
inferred from the supplied report. G1 implements only the Jira-plus-Slack simulated slice.

## Behavioral evidence

| Guarantee | Test evidence |
|---|---|
| One permitted offline packet cites both Jira and Slack with version, hash and locator | `test_permitted_answer_cites_both_sources_and_omits_forbidden_text` |
| Incomplete project, issue, channel, thread, DM or identity grants fail closed | `test_each_parent_or_child_grant_is_required`; `test_dm_access_is_separate_and_incomplete_identity_denies` |
| Forbidden matching source text is absent from provider input and output | `test_permitted_answer_cites_both_sources_and_omits_forbidden_text` |
| Revocation is checked before provider input, before response, and on packet read | `test_recheck_before_provider_input_aborts_racing_revocation`; `test_recheck_before_response_aborts_provider_time_revocation`; `test_revocation_after_ingestion_blocks_new_query_and_saved_packet` |
| Failed or stale required source is explicitly incomplete; source update after sync is stale | `test_required_platform_failure_is_explicit_partial_or_abstaining`; `test_stale_required_platform_cannot_produce_complete_answer`; `test_source_update_after_last_sync_is_explicitly_incomplete` |
| Owner packet reads fail if source checking fails, principal is disabled, or source version/hash changes | `test_saved_packet_denied_when_platform_access_cannot_be_rechecked`; `test_saved_packet_denied_after_local_principal_is_disabled`; `test_changed_source_version_blocks_saved_packet`; `test_saved_packet_denied_if_source_bytes_no_longer_match_hash` |
| Final audit failure does not store or release a packet | `test_final_audit_failure_does_not_release_or_store_packet` |

The initial G1 test run failed at collection because `aspire_brain.platforms` did not
exist. After implementation, the first 13 tests passed. Review found a version-ID collision;
its new reproducer failed with only the Slack citation, then passed after citation keys
included platform and source ID. Separate stale-source and packet-read failure tests also
preceded their fixes. The final run used:

```text
.venv/bin/python -m pytest --cov=aspire_brain --cov-report=term-missing
168 passed, 1 warning; 92.07% statement coverage
.venv/bin/python -m ruff check src tests
All checks passed!
git diff --check
passed
```

The warning is Starlette's existing HTTPX TestClient deprecation. The ignored
`artifacts/g1-simulated-packet.json` is an example packet generated from a temporary local
database: status `answered`, citation platforms `jira` and `slack`, and an HMAC audit
verification that returned `chain_valid=true` during the run. Its audit event ID is from
that temporary database, so this JSON is an example output rather than a durable audit
export.

Unfinished case work: Confluence and Drive, real platform access and live connector
semantics, update/delete and permission synchronization with measured freshness, live LLM
and claim-support evaluation, and the protected officer inquiry. No submission or remote
publication was performed.
