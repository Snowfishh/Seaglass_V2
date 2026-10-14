"""Small offline four-platform path with current source grants and protected packets."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from aspire_brain.answers.service import QueryError
from aspire_brain.auth import AccessDenied
from aspire_brain.models import Evidence, StrictModel
from aspire_brain.platforms.routing import (
    ContextBudget,
    apply_budget,
    explicit_override_decision,
    rank_candidates,
    route_question,
)
from aspire_brain.providers import (
    LIVE_PROVIDER_MODES,
    LOCAL_PROVIDER_MODES,
    OfflineExtractiveProvider,
    ProviderInput,
    ProviderOutput,
    runtime_record_for,
)
from aspire_brain.providers.claims import evaluate_claim_support
from aspire_brain.providers.live import ProviderAbstained

Platform = Literal["confluence", "jira", "slack", "drive"]
FailureCategory = Literal["timeout", "rate_limited", "expired_access", "unavailable"]
SourceKind = Literal[
    "issue",
    "channel_message",
    "thread_message",
    "dm",
    "space_page",
    "space_page_restricted",
    "folder_file",
    "folder_file_restricted",
]
ALL_PLATFORMS = ("confluence", "jira", "slack", "drive")

#: A per-platform retrieval cap applied **after** authorization and **after** the requested
#: event-time scope, and scored with the same cross-platform scorer used for the final
#: selection. A binding cap is reported, so the packet never claims every permitted candidate
#: was ranked. It exists only to bound work on a large corpus; the final selection is the
#: explicit :class:`ContextBudget`.
DEFAULT_RETRIEVAL_CAP = 50


def _hash_valid(record):
    return hashlib.sha256(record.text.encode("utf-8")).hexdigest() == record.content_sha256


class SimulatedSource(StrictModel):
    platform: Platform
    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: SourceKind
    version_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=5000)
    locator: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    thread_id: str | None = None
    source_updated_at: datetime
    #: The message/event creation time, distinct from the last update time. Time-scoped
    #: retrieval uses this and never substitutes ``source_updated_at``.
    event_at: datetime | None = None

    @field_validator("source_updated_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Source update time needs a timezone")
        return value

    @field_validator("event_at")
    @classmethod
    def event_timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Event time needs a timezone")
        return value

    @model_validator(mode="after")
    def validate_identity_and_hash(self):
        platform_kind = {
            "jira": {"issue"},
            "slack": {"channel_message", "thread_message", "dm"},
            "confluence": {"space_page", "space_page_restricted"},
            "drive": {"folder_file", "folder_file_restricted"},
        }
        allowed = platform_kind.get(self.platform, set())
        if self.source_kind not in allowed:
            raise ValueError("Source kind does not belong to platform")
        if self.source_kind == "thread_message" and not self.thread_id:
            raise ValueError("Slack thread ID is required")
        if self.source_kind != "thread_message" and self.thread_id is not None:
            raise ValueError("Unexpected thread ID")
        if not _hash_valid(self):
            raise ValueError("Source content hash mismatch")
        return self


class SourceFailure(StrictModel):
    category: FailureCategory


class AccessDecision(StrictModel):
    platform: Platform
    source_id: str
    version_id: str
    principal_id: str
    allowed: bool
    reason: Literal["allowed", "denied"]
    permission_revision: int


class SimulatedPlatformState:
    """Replace grant sets on changes; permission checks use current simulator state."""

    def __init__(self, *, records, principal_map,
                 confluence_space_grants=None, confluence_page_grants=None,
                 jira_project_grants=None, jira_issue_grants=None,
                 slack_channel_grants=None, slack_thread_grants=None, slack_dm_grants=None,
                 drive_folder_grants=None, drive_file_grants=None,
                 last_successful_sync, freshness_budget_seconds):
        self.lock = RLock()
        self.records = {(record.platform, record.source_id): record for record in records}
        if len(self.records) != len(records):
            raise ValueError("Duplicate simulated source ID")
        self.principal_map = {person: dict(mapping) for person, mapping in principal_map.items()}
        self.confluence_space_grants = self._copy_grants(confluence_space_grants or {})
        self.confluence_page_grants = self._copy_grants(confluence_page_grants or {})
        self.jira_project_grants = self._copy_grants(jira_project_grants or {})
        self.jira_issue_grants = self._copy_grants(jira_issue_grants or {})
        self.slack_channel_grants = self._copy_grants(slack_channel_grants or {})
        self.slack_thread_grants = self._copy_grants(slack_thread_grants or {})
        self.slack_dm_grants = self._copy_grants(slack_dm_grants or {})
        self.drive_folder_grants = self._copy_grants(drive_folder_grants or {})
        self.drive_file_grants = self._copy_grants(drive_file_grants or {})
        self.last_successful_sync = dict(last_successful_sync)
        self.freshness_budget_seconds = dict(freshness_budget_seconds)
        if any(type(value) is not int or value <= 0
               for value in self.freshness_budget_seconds.values()):
            raise ValueError("Freshness budgets must be positive seconds")
        self.failures: dict[str, SourceFailure] = {}
        self.permission_revision = 0

    @staticmethod
    def _copy_grants(grants):
        return {source: frozenset(accounts) for source, accounts in grants.items()}

    def _set_grant(self, field, source_id, account_id, allowed):
        if not isinstance(source_id, str) or not source_id or not isinstance(account_id, str) or not account_id:
            raise ValueError("Grant identifiers are required")
        with self.lock:
            current = getattr(self, field)
            accounts = set(current.get(source_id, frozenset()))
            if allowed:
                accounts.add(account_id)
            else:
                accounts.discard(account_id)
            setattr(self, field, {**current, source_id: frozenset(accounts)})
            self.permission_revision += 1

    def set_confluence_space_grant(self, space, account, allowed):
        self._set_grant("confluence_space_grants", space, account, allowed)

    def set_confluence_page_grant(self, page, account, allowed):
        self._set_grant("confluence_page_grants", page, account, allowed)

    def set_jira_project_grant(self, project, account, allowed):
        self._set_grant("jira_project_grants", project, account, allowed)

    def set_jira_issue_grant(self, issue, account, allowed):
        self._set_grant("jira_issue_grants", issue, account, allowed)

    def set_slack_channel_grant(self, channel, account, allowed):
        self._set_grant("slack_channel_grants", channel, account, allowed)

    def set_slack_thread_grant(self, thread, account, allowed):
        self._set_grant("slack_thread_grants", thread, account, allowed)

    def set_slack_dm_grant(self, dm, account, allowed):
        self._set_grant("slack_dm_grants", dm, account, allowed)

    def set_drive_folder_grant(self, folder, account, allowed):
        self._set_grant("drive_folder_grants", folder, account, allowed)

    def set_drive_file_grant(self, file, account, allowed):
        self._set_grant("drive_file_grants", file, account, allowed)

    def set_principal_identity(self, principal_id, platform, account_id):
        if platform not in ALL_PLATFORMS:
            raise ValueError("Unsupported simulated platform")
        with self.lock:
            mapping = {**self.principal_map.get(principal_id, {}), platform: account_id}
            self.principal_map = {**self.principal_map, principal_id: mapping}
            self.permission_revision += 1

    def set_failure(self, platform, failure: SourceFailure | None):
        if platform not in ALL_PLATFORMS:
            raise ValueError("Unsupported simulated platform")
        with self.lock:
            self.failures = ({**self.failures, platform: failure} if failure else
                             {key: value for key, value in self.failures.items() if key != platform})
            self.permission_revision += 1

    def set_last_successful_sync(self, platform, timestamp):
        if platform not in ALL_PLATFORMS or (timestamp is not None and
           (timestamp.tzinfo is None or timestamp.utcoffset() is None)):
            raise ValueError("Invalid sync state")
        with self.lock:
            self.last_successful_sync = {**self.last_successful_sync, platform: timestamp}
            self.permission_revision += 1

    def source_status(self, platform, now):
        with self.lock:
            failure = self.failures.get(platform)
            last_sync = self.last_successful_sync.get(platform)
            budget = self.freshness_budget_seconds.get(platform)
            if failure:
                state = "failed"
            elif last_sync is None or budget is None:
                state = "unknown"
            elif (now - last_sync).total_seconds() > budget or last_sync > now:
                state = "stale"
            else:
                state = "fresh"
            return {"last_successful_sync": last_sync.isoformat() if last_sync else None,
                    "freshness_budget_seconds": budget, "freshness_state": state,
                    "source_failure": failure.category if failure else None}

    def access_decision(self, principal, platform, source_id):
        with self.lock:
            record = self.records.get((platform, source_id))
            account = self.principal_map.get(principal.get("id"), {}).get(platform)
            allowed = bool(record and principal.get("active") and
                           principal.get("tenant_id") == record.tenant_id and account)
            if allowed and platform == "jira":
                allowed = (account in self.jira_project_grants.get(record.parent_id, ()) and
                           account in self.jira_issue_grants.get(record.source_id, ()))
            elif allowed and platform == "confluence":
                allowed = (account in self.confluence_space_grants.get(record.parent_id, ()) and
                           account in self.confluence_page_grants.get(record.source_id, ()))
            elif allowed and platform == "drive":
                allowed = (account in self.drive_folder_grants.get(record.parent_id, ()) and
                           account in self.drive_file_grants.get(record.source_id, ()))
            elif allowed and record.source_kind == "channel_message":
                allowed = account in self.slack_channel_grants.get(record.parent_id, ())
            elif allowed and record.source_kind == "thread_message":
                allowed = (account in self.slack_channel_grants.get(record.parent_id, ()) and
                           account in self.slack_thread_grants.get(record.thread_id, ()))
            elif allowed and record.source_kind == "dm":
                allowed = account in self.slack_dm_grants.get(record.parent_id, ())
            return AccessDecision(platform=platform, source_id=source_id,
                                  version_id=record.version_id if record else "unknown",
                                  principal_id=principal.get("id", "unknown"), allowed=bool(allowed),
                                  reason="allowed" if allowed else "denied",
                                  permission_revision=self.permission_revision)

    def can_read(self, principal, platform, source_id):
        return self.access_decision(principal, platform, source_id).allowed

    def candidates(self, principal, platform, question, *, limit=None):
        """Authorize every permitted match, scored with the shared cross-platform ranking.

        Authorization always comes first, and no destructive truncation happens here: the
        caller applies the requested event-time scope and then the bounded final selection, so
        an early cap can never hide a recent permitted match behind older ones. Scoring uses
        the same stopword-aware scorer as :func:`rank_candidates`, not a second scheme.
        ``limit`` remains available for a caller that deliberately wants a bounded page.
        """
        with self.lock:
            if self.failures.get(platform):
                return []
            permitted = []
            for (record_platform, source_id), record in self.records.items():
                if record_platform != platform or not self.can_read(principal, platform, source_id):
                    continue
                if not _hash_valid(record):
                    raise ValueError("Source integrity check failed")
                permitted.append((platform, record))
            matched = [record for score, record in rank_candidates(question, permitted)
                       if score > 0]
            return matched[:limit] if limit is not None else matched


class SimulatedQueryService:
    """G1 service; retains P0 principal and HMAC audit boundaries."""

    def __init__(self, auth, audit, state, *, provider=None, clock=None, protected_audit=None,
                 required_platforms=("jira", "slack"), budget=None,
                 retrieval_cap=DEFAULT_RETRIEVAL_CAP):
        self.auth, self.audit, self.state = auth, audit, state
        self.protected_audit = protected_audit
        self.clock = clock or (lambda: datetime.now(UTC))
        self.provider = provider or OfflineExtractiveProvider()
        # The live provider is admitted only because it is built for the approved envelope,
        # which covers sending this fictional simulated data; restricted sources never leave.
        if self.provider.mode not in LOCAL_PROVIDER_MODES | LIVE_PROVIDER_MODES:
            raise ValueError("Only offline_extractive, fake_grounded or the approved "
                             "live_grounded provider may answer simulated queries")
        # ``None`` enables question-driven routing. A tuple is an explicit override kept for
        # deterministic tests and the case demo.
        self.required_platforms = None if required_platforms is None else tuple(required_platforms)
        for platform in self.required_platforms or ():
            if platform not in ALL_PLATFORMS:
                raise ValueError(f"Unsupported required platform: {platform}")
        self.budget = budget if budget is not None else ContextBudget(max_items=8, max_chars=12000)
        if not isinstance(self.budget, ContextBudget):
            raise ValueError("Budget must be a ContextBudget")
        if type(retrieval_cap) is not int or retrieval_cap < 1:
            raise ValueError("Retrieval cap must be a positive integer")
        self.retrieval_cap = retrieval_cap
        with closing(auth.db.connect()) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS simulated_packets (
                request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                dependencies TEXT NOT NULL, packet TEXT NOT NULL)""")

    def _audit(self, principal, request_id, event_type, metadata):
        try:
            return self.audit.append(principal["tenant_id"], principal["id"],
                                     request_id, event_type, metadata)
        except Exception as exc:
            raise QueryError("Audit persistence unavailable; no evidence released", 503) from exc

    def _check(self, principal, snapshot, records):
        try:
            fresh = self.auth.principal(principal["id"])
            current = (fresh, self.auth.revisions(fresh), self.state.permission_revision)
        except AccessDenied as exc:
            raise AccessDenied("Access unavailable") from exc
        if current != snapshot or any(
            self.state.records.get((item.platform, item.source_id)) != item or
            not _hash_valid(item) or
            not self.state.can_read(fresh, item.platform, item.source_id)
            for item in records
        ):
            raise AccessDenied("Access unavailable")

    @staticmethod
    def _evidence_id(item):
        return f"{item.platform}:{item.source_id}:{item.version_id}"

    async def query(self, principal_id, question, now, *, time_windows=None):
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("Question must contain 1 to 2000 characters")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Query time needs a timezone")
        principal = self.auth.principal(principal_id)
        request_id = str(uuid4())
        self._audit(principal, request_id, "query_attempt", {"provider_mode": self.provider.mode})
        snapshot = (principal, self.auth.revisions(principal), self.state.permission_revision)
        try:
            return await self._answer(principal, request_id, question.strip(), now, snapshot,
                                      time_windows)
        except (AccessDenied, QueryError):
            self._audit(principal, request_id, "query_aborted", {"error_code": "controlled_failure"})
            raise
        except Exception as exc:
            self._audit(principal, request_id, "query_failed", {"error_code": "processing_failed"})
            raise QueryError("Simulated query failed; no evidence released", 503) from exc

    def _route(self, question):
        if self.required_platforms is None:
            return route_question(question)
        return explicit_override_decision(self.required_platforms)

    def _apply_time_scope(self, selected, time_windows):
        """Filter each platform's candidates to an explicit event-time window.

        A record with no declared ``event_at`` cannot be time-scoped; it is excluded and
        reported rather than silently matched on its last update time.
        """
        scoped, unscopable = {}, {}
        report = {"applied": bool(time_windows), "platforms": {},
                  "note": ("Time windows use each record's event/creation time (event_at). "
                           "source_updated_at is not used as a substitute.")}
        for platform, records in selected.items():
            window = (time_windows or {}).get(platform)
            if window is None:
                scoped[platform] = list(records)
                unscopable[platform] = []
                continue
            keep, out_of_window, missing_event = [], [], []
            for record in records:
                if record.event_at is None:
                    missing_event.append(self._evidence_id(record))
                elif window.contains(record.event_at):
                    keep.append(record)
                else:
                    out_of_window.append(self._evidence_id(record))
            scoped[platform] = keep
            unscopable[platform] = missing_event
            report["platforms"][platform] = {
                "start": window.start.isoformat(), "end": window.end.isoformat(),
                "basis": "event_at", "included_ids": [self._evidence_id(r) for r in keep],
                "excluded_out_of_window_ids": out_of_window, "unscopable_ids": missing_event,
            }
        return scoped, unscopable, report

    def _budget_report(self, included_records, dropped, unscopable, budget_excluded):
        return {
            "max_items": self.budget.max_items, "max_chars": self.budget.max_chars,
            "included_items": len(included_records),
            "included_chars": sum(len(item.text) for item in included_records),
            "dropped_items": len(dropped),
            "dropped_ids": [self._evidence_id(item) for _, item in dropped],
            "degraded": bool(dropped), "budget_excluded_platforms": list(budget_excluded),
            "unscopable_ids": [item for ids in unscopable.values() for item in ids],
        }

    async def _answer(self, principal, request_id, question, now, snapshot, time_windows=None):
        routing = self._route(question)
        platforms = routing["selected_platforms"]
        statuses = {platform: self.state.source_status(platform, now)
                    for platform in platforms}
        # Authorize first, with no truncation, so the event-time scope below sees every
        # permitted candidate rather than an arbitrary first page of them.
        selected = {platform: (self.state.candidates(principal, platform, question)
                               if statuses[platform]["freshness_state"] == "fresh" else [])
                    for platform in platforms}
        for platform in platforms:
            last_sync = statuses[platform]["last_successful_sync"]
            if last_sync and any(item.source_updated_at > datetime.fromisoformat(last_sync)
                                 for item in selected[platform]):
                statuses[platform] = {**statuses[platform], "freshness_state": "stale"}
                selected[platform] = []
        scoped, unscopable, time_scope = self._apply_time_scope(selected, time_windows)
        # Bound each platform's contribution *after* the event-time scope, using the same
        # scorer as the final cross-platform selection, and report any binding cap so the
        # packet never implies every permitted candidate was ranked.
        retrieval = {}
        for platform in platforms:
            ranked_platform = rank_candidates(question,
                                              [(platform, item) for item in scoped[platform]])
            truncated = len(ranked_platform) > self.retrieval_cap
            retrieval[platform] = {
                "candidates_after_scope": len(ranked_platform),
                "retained": min(len(ranked_platform), self.retrieval_cap),
                "truncated": truncated,
            }
            scoped[platform] = [item for _, item in ranked_platform[:self.retrieval_cap]]
        retrieval_report = {
            "cap_per_platform": self.retrieval_cap,
            "applied_after": "authorization_and_event_time_scope",
            "platforms": retrieval,
            "any_truncated": any(entry["truncated"] for entry in retrieval.values()),
            "note": ("A binding cap means some permitted candidates were not ranked; this packet "
                     "does not claim full coverage of the platform."),
        }
        # Rank every permitted candidate across platforms, then apply the overall budget.
        ranked = rank_candidates(
            question, [(platform, item) for platform in platforms for item in scoped[platform]],
            explicit_platforms=routing["explicit_platforms"])
        included, dropped = apply_budget(ranked, self.budget)
        included_records = [item for _, item in included]
        budget_excluded = [platform for platform in platforms
                           if scoped[platform]
                           and not any(item.platform == platform for item in included_records)]
        budget_report = self._budget_report(included_records, dropped, unscopable, budget_excluded)
        incomplete = [platform for platform in platforms
                      if statuses[platform]["freshness_state"] != "fresh"
                      or platform in budget_excluded or unscopable[platform]]
        missing = [platform for platform in platforms if not scoped[platform]]
        if missing and not incomplete:
            # A missing required source could be absent or forbidden; neither is disclosed.
            status, records = "abstained", []
        elif incomplete:
            records = included_records
            status = "partial" if records else "abstained"
        else:
            records = included_records
            status = "answered"
        # Every source identifier this packet can expose — answer evidence, citations, budget
        # drops and time-scope diagnostics — is a member of ``selected``. The saved packet
        # therefore depends on all of them, so a later revocation cannot leave a stale
        # identifier in any outward field.
        dependencies = list({(item.platform, item.source_id): item
                             for platform in platforms for item in selected[platform]}.values())
        self._check(principal, snapshot, dependencies)
        live = self.provider.mode in LIVE_PROVIDER_MODES
        runtime_record = None
        if live and records:
            # Restricted sources stay with local modes; they are never sent to an external model.
            records = [item for item in records if not item.source_kind.endswith("_restricted")]
            if not records:
                status = "abstained"
        if records:
            context = ProviderInput(
                question=question, context={"simulation_mode": "simulated"},
                evidence=[Evidence(version_id=item.version_id, chunk_id=self._evidence_id(item),
                                   text=item.text, source_locator=item.locator,
                                   content_hash=item.content_sha256, document_id=item.source_id)
                          for item in records],
                decision_summary=("Incomplete simulated cross-platform evidence; human review required."
                                  if status == "partial" else
                                  "Simulated cross-platform evidence for inspection only."),
            )
            timeout = float(getattr(self.provider, "timeout_seconds", 5.0))
            with_record = getattr(self.provider, "generate_with_record", None)
            try:
                if callable(with_record):
                    raw, runtime_record = await asyncio.wait_for(
                        with_record(context, correlation_id=request_id), timeout=timeout)
                else:
                    raw = await asyncio.wait_for(self.provider.generate(context), timeout=timeout)
                output = ProviderOutput.model_validate(raw)
            except ProviderAbstained as abstained:
                output, runtime_record = None, abstained.record
            except Exception as exc:
                raise QueryError("Provider could not produce a validated answer", 502) from exc
        if records and output is not None:
            allowed = {self._evidence_id(item): item for item in records}
            if not output.citation_ids or set(output.citation_ids) - allowed.keys():
                raise QueryError("Provider returned invalid citations", 502)
            citations = [self._citation(allowed[item]) for item in dict.fromkeys(output.citation_ids)]
            answer = output.answer
            # Grounding is checked against the cited source *text*, not the locator or the
            # document identifier: an identifier is not evidence for a factual assertion.
            claim_support = evaluate_claim_support(
                answer=answer, citation_ids=list(dict.fromkeys(output.citation_ids)),
                evidence={identifier: item.text for identifier, item in allowed.items()},
                locators={identifier: item.locator for identifier, item in allowed.items()},
                notices=[context.decision_summary], provider_mode=self.provider.mode,
                mode="live" if live else "simulated")
            if not claim_support["all_supported"] or claim_support["denominator"] == 0:
                raise QueryError("Provider answer contains unsupported claims; "
                                 "no evidence released", 502)
        else:
            citations = []
            if records:
                status = "abstained"
                answer = ("The model judged the permitted evidence insufficient; "
                          "human review required.")
            else:
                answer = "Incomplete permitted cross-platform evidence; human review required."
            claim_support = evaluate_claim_support(
                answer=answer, citation_ids=[], evidence={}, provider_mode=self.provider.mode,
                mode="live" if live and runtime_record is not None else "simulated",
                abstained=True)
        self._check(principal, snapshot, dependencies)
        packet = {
            "request_id": request_id, "query_status": status, "answer": answer,
            "citations": citations, "required_platforms": list(platforms),
            "incomplete_platforms": incomplete if incomplete else missing,
            "source_status": statuses, "simulation_mode": "simulated",
            "provider_mode": self.provider.mode, "audit_event_id": "pending",
            "routing": routing, "context_budget": budget_report, "time_scope": time_scope,
            "retrieval": retrieval_report,
            "claim_support": claim_support,
            "provider_runtime": (runtime_record or runtime_record_for(
                self.provider, correlation_id=request_id)).model_dump(mode="json"),
        }
        return self._persist(principal, request_id, packet, records, snapshot, question,
                             dependencies)

    @staticmethod
    def _citation(item):
        return {"platform": item.platform, "source_id": item.source_id,
                "source_kind": item.source_kind, "version_id": item.version_id,
                "content_sha256": item.content_sha256, "locator": item.locator,
                "parent_id": item.parent_id, "thread_id": item.thread_id,
                "source_updated_at": item.source_updated_at.isoformat(),
                "event_at": item.event_at.isoformat() if item.event_at else None}

    def _persist(self, principal, request_id, packet, records, snapshot, question, dependencies):
        # ``dependencies`` covers every source identifier the packet can expose, not just the
        # answer evidence, so ``packet()`` re-authorizes the diagnostic fields too.
        dependency_rows = [(item.platform, item.source_id, item.version_id, item.content_sha256)
                           for item in dependencies]
        try:
            with self.state.lock, closing(self.auth.db.connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check(principal, snapshot, dependencies)
                retrieved_keys = {(item.platform, item.source_id, item.version_id)
                                  for item in records}
                decisions = [
                    {"platform": item.platform, "parent_id": item.parent_id,
                     "source_id": item.source_id, "version_id": item.version_id,
                     "allowed": decision.allowed, "reason": decision.reason,
                     "retrieved": (item.platform, item.source_id, item.version_id)
                     in retrieved_keys}
                    for item in self.state.records.values()
                    if item.platform in packet["required_platforms"]
                    for decision in [self.state.access_decision(
                        principal, item.platform, item.source_id)]
                ]
                digest = self.audit.response_digest(json.dumps(packet, sort_keys=True).encode())
                metadata = {"response_digest": digest, "query_status": packet["query_status"],
                            "source_count": len(records), "provider_mode": self.provider.mode}
                if self.protected_audit is not None:
                    metadata["operation"] = "simulated_protected_query"
                event_id = self.audit.append_in_transaction(
                    connection, principal["tenant_id"], principal["id"], request_id,
                    "query_completed", metadata,
                )
                final = {**packet, "audit_event_id": event_id}
                if self.protected_audit is not None:
                    self.protected_audit.store_in_transaction(
                        connection, principal["tenant_id"], request_id, event_id,
                        {"subject_id": principal["id"], "question": question, "packet": final,
                         "retrieved_ids": [self._evidence_id(item) for item in records],
                         "decisions": decisions},
                    )
                connection.execute("INSERT INTO simulated_packets VALUES (?,?,?,?,?)", (
                    request_id, principal["tenant_id"], principal["id"],
                    json.dumps(dependency_rows), json.dumps(final),
                ))
            return final
        except (AccessDenied, QueryError):
            raise
        except Exception as exc:
            raise QueryError("Audit/packet persistence unavailable; no evidence released", 503) from exc

    def packet(self, principal_id, request_id):
        principal = self.auth.principal(principal_id)
        snapshot = (principal, self.auth.revisions(principal), self.state.permission_revision)
        with self.state.lock, closing(self.auth.db.connect()) as connection:
            row = connection.execute(
                "SELECT dependencies,packet FROM simulated_packets WHERE request_id=? "
                "AND tenant_id=? AND owner_id=?",
                (request_id, principal["tenant_id"], principal["id"]),
            ).fetchone()
            if row is None:
                raise AccessDenied("Not found")
            records = []
            for platform, source_id, version_id, content_sha256 in json.loads(row["dependencies"]):
                record = self.state.records.get((platform, source_id))
                source_status = self.state.source_status(platform, self.clock())
                last_sync = source_status["last_successful_sync"]
                if (record is None or record.version_id != version_id or
                    record.content_sha256 != content_sha256 or
                    not _hash_valid(record) or
                    source_status["freshness_state"] != "fresh" or
                    record.source_updated_at > datetime.fromisoformat(last_sync) or
                    not self.state.can_read(
                    principal, platform, source_id
                )):
                    raise AccessDenied("Not found")
                records.append(record)
            self._check(principal, snapshot, records)
            return json.loads(row["packet"])
