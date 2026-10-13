# G1 simulated source contract (v1)

Scope: a local, deterministic four-platform simulator, initially developed as a Jira plus
Slack slice. The project-root `project requiement.pdf` supplies the case brief on PDF pages
15–19, and the five scenario descriptions in `eval/g1-case-expectations.json` now cite it.
Access to real platform tenants is unverified. No simulator result establishes live
integration or source permission parity.

## Shared record

Every candidate has `platform`, `tenant_id`, `source_id`, `source_kind`, `version_id`,
`content_sha256`, `text`, `locator`, `parent_id`, `thread_id`, and timezone-aware
`source_updated_at`. `(platform, source_id, version_id)` identifies immutable source bytes;
`content_sha256` is SHA-256 over UTF-8 `text`. A correction creates another version.
Locators identify the original source position and are cited with the version and hash.
Parent and thread fields express source structure, not permission grants.

An active local principal must be resolved again through P0 authentication at each access
boundary. `principal_map` resolves that principal separately to each simulated platform
account in the same tenant. No browser role, source text, or provider output can populate
this map. Missing or empty identity mappings deny that platform.

`AccessDecision` contains platform, source/version, principal, `allowed`, a safe reason
category, and the permission revision. Confluence requires space and page grants; Jira
requires a current project grant **and** a current issue grant. Slack channel messages
require current channel membership; thread
messages require channel membership **and** an explicit thread grant; DMs require explicit
DM participation. Drive requires folder and file grants. A missing parent, grant set, or
identity denies access. No role has a
universal bypass. Unknown and inaccessible source identifiers have the same outward denial.
Permissions are checked before evidence is assembled for a provider, before response
release, and when a saved packet is read. A revoked contributor denies the entire saved
packet; already downloaded answers cannot be recalled. A permission revision change during
a query aborts release and requires a retry.

Each platform has `last_successful_sync`, a declared `freshness_budget_seconds`,
`freshness_state` (`fresh`, `stale`, `unknown`, or `failed`), and an optional `source_failure`
with safe category (`timeout`, `rate_limited`, `expired_access`, or `unavailable`). The
timestamps and budget are contract metadata, not a measured synchronization guarantee.
No last sync means `unknown`; a source failure means `failed`. If a required platform fails
or is stale, the result is explicitly `partial` or `abstained`, never a complete answer.
G2 must prove update visibility within a measured budget and handle pagination and retries.

The G1 packet is owner restricted, labels `simulation_mode=simulated` and
`provider_mode=offline_extractive`, and cites source identities, immutable versions/hashes,
locators, and source update times. It carries per-platform freshness/failure state and
required-source completeness. The local P0 audit chain records attempt and completion or
abort with minimised metadata; the answer stays only in the owner-restricted packet store.
The general G1 service does not retain questions. When a separate payload key is configured,
the browser case demo encrypts exact questions, answer packets and per-source decisions in a
protected table linked atomically to the HMAC completion event. Officer inquiry covers those
protected simulated case queries only. The P0 query path and any future live connectors are
outside that coverage.

## G2 synchronization contract (added 27 September 2026)

G2 separates two states the G1 simulator conflated. `platforms/sync.py` defines:

- `SimulatedUpstream` — the **upstream fixture state**: what each platform currently holds,
  exposed as an append-only change feed (`upsert`, `delete`, `acl`) with `page_size`,
  a cursor-style `since_revision`/`offset` read, and injectable `rate_limit_calls`,
  `expired` and `interrupt_after_pages` faults.
- `SyncIndex` — the **ingested/queryable snapshot**: a `SimulatedPlatformState` subclass that
  the query service reads. It adds per-platform `cursors`, `tombstones` and a `sync_log`.
  `source_status` downgrades `fresh` to `stale` while `pending_changes()` is true, so an
  un-ingested upstream change is never advertised as current.
- `Synchronizer` — pulls changes into the index. Staging is all-or-nothing: records, grants
  and tombstones are replaced, and the cursor plus `last_successful_sync` watermark advance,
  only after a complete run. `interrupted`, `rate_limited`, `partial` and `expired_access`
  runs leave records, grants, tombstones, cursor and watermark unchanged. Expired access also
  records a failure state so queries fail closed. The cursor advances only to the highest
  revision actually applied, so a change appended mid-run stays pending. Rate-limit retries
  are bounded by `max_attempts` and restart from the committed cursor with fresh staging.

Platform grant maps stay distinct: Confluence space+page, Jira project+issue, Slack
channel/thread/DM, Drive folder/file. ACL changes arrive as upstream events, so a revocation
is ingested rather than applied directly to query state.

`measure_freshness()` records `mutation_at`, `ingested_at`, a supplied
`first_post_sync_query_at` and `observed_answer_at` with a declared `budget_seconds`. It labels
`time_mode=simulated_elapsed` and leaves `wall_clock_seconds` and `live_propagation_seconds`
null. It also records `observed_answer_contains_update`, `first_post_sync_answer_contains_update`
and `observation_mode`, and sets `earliest_correct_answer_at=null` with
`earliest_visibility="unknown"` because no poll searched for the earliest correct answer. The
declared budget is 3600 s (within the PDF's "minutes to ~1 hour"); the Case 2 sequence shows a
600 s simulated propagation with a first post-sync query at ingestion time, and Case 6 shows a
real late sync at 4200 s reported as `over_budget`. No live platform is contacted and no live
propagation latency is measured.

## G3 routing, ranking, budget and time-scope contract (added 27 September 2026)

`platforms/routing.py` supplies the G3 primitives; the query service applies them before an
answer is assembled and records the outcome in the packet.

- **Routing** — `route_question(question, *, available=PLATFORMS)` returns a decision with a
  `basis` (`keyword_signals`, `explicit_platform_mention`, `broad_default_all` or
  `no_signal_default_all`), the per-platform `signals`, the `selected_platforms`, the
  `omitted_platforms` and a `coverage_note`. Broad and no-signal questions query every
  platform, so a keyword miss is never presented as completeness. An explicit caller tuple is
  preserved as `basis="explicit_override"` and states that routing was not applied.
- **Ranking** — `rank_candidates(question, items, *, explicit_platforms=(), limit=None)` scores
  permitted candidates across platforms as `10 × term_hits + 5 × source_id_hits + 3 if the
  platform is named`, breaking ties on `(platform, source_id)` and excluding a `STOPWORDS`
  set. Ranking sees only permitted candidates.
- **Context budget** — `ContextBudget(max_items=1–50, max_chars=100–100000)` with
  `apply_budget(ranked, budget) -> (included, dropped)`. Degradation is deterministic and the
  dropped items are recorded. A required platform excluded by the budget forces an explicit
  `partial` or `abstained` result. The service default is `max_items=8, max_chars=12000`.
- **Time scope** — `TimeWindow` is a half-open, timezone-aware `[start, end)` interval with a
  `contains()` test; `detect_time_window(question, now)` recognises "last week"/"past week"
  (7 days), "last month" (30 days), "past N days", "today" and "yesterday". The window is
  applied to each record's **event/creation** time (`event_at`); `source_updated_at` is **not**
  used as a substitute. Records with no event time in a scoped platform are marked unscopable
  and excluded rather than silently kept.

The G1 packet contract is extended, not replaced: permission checks, freshness/failure state,
required-source completeness, the owner restriction and the pre-provider, pre-response and
saved-packet rechecks are unchanged.

## G4 provider, claim-support and retention contract (added 27 September 2026)

**Grounded provider.** `providers/runtime.py` and `providers/grounded.py` add a provider behind
the existing `AnswerProvider` interface that reasons only over the **already-bounded,
already-permitted** evidence the service hands it. It cannot receive or request unreadable
content, cannot introduce a new source identifier, and cannot set an authoritative outcome field;
its output is validated against exactly the supplied evidence like any other provider.

`ProviderRuntimeConfig` is the only way to describe a real runtime. Its validator accepts a bare
HTTPS endpoint and rejects embedded credentials, a query string or a fragment, exposing a
non-secret `endpoint_host`; `is_entitled()` requires `enabled` **and**
`entitlement == "entitled"`. `configured_provider(mode, *, runtime=None)` returns
`OfflineExtractiveProvider` for the default `offline_extractive`, `GroundedAnswerProvider` for
`fake_grounded`, and for `live_grounded` first requires an entitled runtime (raising
`ProviderEntitlementError` for a missing, disabled or unentitled runtime) and then refuses with
`ExternalProviderUnavailable` because no entitled live runtime is implemented in this checkout —
no request is made. `ProviderRuntimeRecord` is bounded and all-null for a local run; the packet
carries it as `provider_runtime` with `outcome="not_run"` and `live_request_made=false`.

**Claim-level support.** `providers/claims.py` checks each claim against **one** cited source and
releases it only when the claim matches a **complete source sentence or complete colon tail**,
with case and whitespace normalised (the compatibility label remains
`SUPPORT_METHOD = "exact_cited_span"`), after stripping a service-authored citation label such as
`Evidence (locator):`. This replaces the earlier 60% single-source lexical-overlap threshold,
which accepted contradictions (for example `Failover is enabled` against `Failover is not
enabled`) because shared tokens dominated. A locator or document identifier is never accepted as
evidence for a factual assertion; a claim with no checkable tokens fails closed; a leading
inspection notice is excluded only on an **exact** match, not on an arbitrary substring. The
report carries a `denominator`, a `mode` (`simulated`/`live`), a `provider_mode` and a `method`,
and a `live` label is rejected for a local provider, so a fake-provider result can never be
presented as a live-model result. The lexical-overlap ratio is retained as a **diagnostic proxy
only** and is not the release gate. The query service enforces the verdict: an unsupported answer
raises `QueryError` (HTTP 502) and releases no evidence, and no packet is saved. The abstention
path is evaluated with an empty denominator. Exact quotation is **bounded extractive support, not
entailment**.

**Retention and authorised search.** `audit/retention.py` defines `RetentionPolicy`
(`max_age_days` 1–3650, `max_entries` 1–100000, a documented `basis`). `apply_retention(*,
tenant_id, now, apply=False)` is **tenant-scoped** and dry-run by default; `apply=True` removes
only the encrypted payload rows, never the HMAC chain, and commits the tombstone rows, the payload
deletes and a `protected_audit_retention` audit event in one transaction carrying the retention
digest. The tombstone digest is bound into the chain and cross-checked by `inquire`, so a forged
tombstone cannot explain a removed payload and an un-recorded deletion is still detected. `inquire`
reports `retention` and `checkpoint_anchoring` (`verified_through_checkpoint`,
`unanchored_tail_events`, `completeness_unproven`): the unanchored tail is never presented as a
completeness proof. Officer search filters by user, platform, space/document parent and time, and
routine metadata stays minimised. Results are **paged**: `inquire(..., limit, cursor)` returns
`limit`, `returned`, `has_more`, `next_cursor` and `total_matches`, ordered stably on
`(timestamp, request ID)`. The cursor is HMAC-signed and bound to the tenant and the exact search
filters, so it cannot be replayed across tenants or against a different query; an invalid cursor is
rejected rather than silently restarted. `DEFAULT_INQUIRY_LIMIT` is 100 and `MAX_INQUIRY_LIMIT` is
500.
