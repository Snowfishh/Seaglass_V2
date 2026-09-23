import asyncio
import hashlib
import hmac
import json
from urllib.parse import quote
from uuid import uuid4

from aspire_brain.auth import AccessDenied
from aspire_brain.knowledge import Retriever
from aspire_brain.models import Citation, Evidence, EvidencePacket, QueryRequest
from aspire_brain.policies import PolicyEngine
from aspire_brain.providers import OfflineExtractiveProvider, ProviderInput, ProviderOutput

SCOPE_NOTICE = (
    "Based only on evidence available to this requester now and effective on the case date "
    "(Asia/Singapore). This is not spending approval. Human finance review remains required."
)


class QueryError(RuntimeError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class QueryService:
    def __init__(self, db, auth, audit, provider=None):
        self.db, self.auth, self.audit = db, auth, audit
        self.provider = provider or OfflineExtractiveProvider()
        self.retriever = Retriever(db)
        self.timeout_seconds = 5.0
        with db.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS packets (
                request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                dependencies TEXT NOT NULL, context TEXT NOT NULL, packet TEXT NOT NULL,
                acl_revision INTEGER NOT NULL, content_revision INTEGER NOT NULL)""")

    def _audit(self, principal, request_id, event_type, metadata):
        try:
            return self.audit.append(principal["tenant_id"], principal["id"],
                                     request_id, event_type, metadata)
        except Exception as exc:
            raise QueryError("Audit persistence unavailable; no evidence released", 503) from exc

    def _snapshot(self, principal):
        fresh = self.auth.principal(principal["id"])
        return (fresh, self.auth.revisions(fresh))

    def _check_snapshot(self, principal, snapshot):
        try:
            if self._snapshot(principal) != snapshot:
                raise QueryError("Access or content changed; retry the request")
        except AccessDenied as exc:
            raise QueryError("Access or content changed; retry the request") from exc

    async def query(self, principal, request: QueryRequest):
        principal = self.auth.principal(principal["id"])
        request_id = str(uuid4())
        self._audit(principal, request_id, "query_attempt", {"provider_mode": self.provider.mode})
        snapshot = self._snapshot(principal)
        try:
            packet, dependencies = await self._assemble(principal, request_id, request, snapshot)
            return self._persist(principal, request, packet, dependencies, snapshot)
        except QueryError as exc:
            self._audit(principal, request_id, "query_aborted", {"error_code": "controlled_failure"})
            raise exc
        except Exception as exc:
            self._audit(principal, request_id, "query_failed", {"error_code": "processing_failed"})
            raise QueryError("Request could not be completed; no evidence released", 503) from exc

    async def _assemble(self, principal, request_id, request, snapshot):
        context = request.context.model_dump(mode="json")
        scope = {key: value for key, value in context.items() if value is not None}
        rules = self.retriever.all_rules(principal, context["case_date"], scope)
        decision = PolicyEngine().evaluate(rules, context)
        passages = self.retriever.search(
            principal, request.question, context["case_date"], scope, top_k=5, max_chars=5000
        )
        evidence = self._evidence(principal, passages, rules)
        dependencies = sorted({item.version_id for item in evidence})
        self._audit(principal, request_id, "policy_decision", {
            "query_status": decision["query_status"], "case_outcome": decision["case_outcome"],
            "version_ids": dependencies, "rule_ids": [rule["id"] for rule in rules],
            "chunk_ids": [item.chunk_id for item in evidence], "provider_mode": self.provider.mode,
        })
        self._check_snapshot(principal, snapshot)
        provider_input = ProviderInput(question=request.question, context=context, evidence=evidence,
                                       decision_summary=decision["summary"])
        try:
            raw = await asyncio.wait_for(self.provider.generate(provider_input), self.timeout_seconds)
            output = ProviderOutput.model_validate(raw)
            allowed = {item.chunk_id: item for item in evidence}
            if set(output.citation_ids) - allowed.keys():
                raise ValueError("Unsupported citation")
            if evidence and not output.citation_ids:
                raise ValueError("Evidence-bearing answer requires citations")
        except Exception as exc:
            self._audit(principal, request_id, "provider_error", {"error_code": "invalid_or_timeout",
                                                                 "provider_mode": self.provider.mode})
            raise QueryError("Provider could not produce a validated answer", 502) from exc
        self._check_snapshot(principal, snapshot)
        citations = [self._citation(allowed[cid]) for cid in dict.fromkeys(output.citation_ids)]
        packet = EvidencePacket(
            request_id=request_id, query_status=decision["query_status"],
            case_outcome=decision["case_outcome"], answer=output.answer,
            case_date=request.context.case_date, citations=citations,
            applied_rules=decision["applied_rules"], conflicts=decision["conflicts"],
            missing_evidence_categories=decision["missing_evidence_categories"],
            review_route=decision["review_route"], provider_mode=self.provider.mode,
            scope_notice=SCOPE_NOTICE, audit_event_id="pending",
        )
        return packet, dependencies

    def _evidence(self, principal, passages, rules):
        # Structured rules use the entire authorized catalogue, independently of search top-k.
        sources = [self.auth.source(principal, rule["version_id"], rule["source_chunk_id"])
                   for rule in rules]
        unique = {}
        for item in [*sources, *passages]:
            values = {key: item[key] for key in Evidence.model_fields}
            unique[values["chunk_id"]] = Evidence.model_validate(values)
        evidence = list(unique.values())
        if len(evidence) > 40 or sum(len(item.text) for item in evidence) > 10000:
            raise QueryError("Available evidence exceeds the bounded context; request human review")
        return evidence

    @staticmethod
    def _citation(item):
        return Citation(document_version_id=item.version_id, chunk_id=item.chunk_id,
                        source_locator=item.source_locator, safe_excerpt=item.text[:1600],
                        source_url=f"/sources/{quote(item.version_id, safe='')}/"
                                   f"{quote(item.chunk_id, safe='')}")

    def _persist(self, principal, request, packet, dependencies, snapshot):
        try:
            with self.db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                # Lock excludes concurrent metadata writers through final packet/audit commit.
                self._check_snapshot(principal, snapshot)
                for version_id in dependencies:
                    if not self.auth.readable(principal, version_id):
                        raise QueryError("Access or content changed; retry the request")
                digest = hmac.new(self.audit.key, packet.model_dump_json().encode(),
                                  hashlib.sha256).hexdigest()
                event_id = self.audit.append_in_transaction(
                    connection, principal["tenant_id"], principal["id"], packet.request_id,
                    "query_completed", {"response_digest": digest,
                                        "query_status": packet.query_status,
                                        "case_outcome": packet.case_outcome,
                                        "provider_mode": packet.provider_mode},
                )
                final = packet.model_copy(update={"audit_event_id": event_id}).model_dump(mode="json")
                connection.execute("INSERT INTO packets VALUES (?,?,?,?,?,?,?,?)", (
                    packet.request_id, principal["tenant_id"], principal["id"],
                    json.dumps(dependencies), request.context.model_dump_json(), json.dumps(final),
                    *snapshot[1],
                ))
            return final
        except QueryError:
            raise
        except Exception as exc:
            raise QueryError("Audit/packet persistence unavailable; no evidence released", 503) from exc

    def packet(self, principal, request_id):
        principal = self.auth.principal(principal["id"])
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM packets WHERE request_id=? AND tenant_id=? AND owner_id=?",
                (request_id, principal["tenant_id"], principal["id"]),
            ).fetchone()
        if row is None or any(not self.auth.readable(principal, version_id)
                              for version_id in json.loads(row["dependencies"])):
            raise AccessDenied("Not found")
        return json.loads(row["packet"])
