"""Fully in-process synthetic target for a *future, approved* Promptfoo run.

Status: this file is part of a **reviewed design**. Promptfoo was not installed or executed
(see ``DATA-FLOW-REVIEW.md`` and ``STATUS.json``).

Why in-process rather than a localhost listener: the target opens **no socket at all**, so there
is no port to reach and nothing to firewall. It seeds a disposable SQLite database from the
synthetic demo fixtures and answers one question through the same ``QueryService`` the API path
uses. That is strictly stronger than binding ``127.0.0.1``.

Promptfoo's Python provider interface::

    def call_api(prompt: str, options: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]

The returned ``output`` is deliberately **answer text plus citation identifiers only**. No packet
body, no provider input and no audit metadata is exposed to the tool.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aspire_brain.answers import QueryService  # noqa: E402
from aspire_brain.audit import AuditWriter  # noqa: E402
from aspire_brain.auth import AuthService  # noqa: E402
from aspire_brain.db import Database  # noqa: E402
from aspire_brain.models import QueryRequest  # noqa: E402
from aspire_brain.providers import OfflineExtractiveProvider  # noqa: E402

DEMO_MANIFEST = ROOT / "data" / "demo" / "manifest.json"
DEMO_PRINCIPALS = ROOT / "data" / "demo" / "principals.json"


def _answer(question: str, principal_id: str = "employee") -> dict:
    """Run one question against a disposable database. No network, no persistence outside it."""
    with tempfile.TemporaryDirectory(prefix="promptfoo-local-target-") as directory:
        db = Database(Path(directory) / "target.db")
        db.initialize()
        db.seed(DEMO_MANIFEST, DEMO_PRINCIPALS)
        audit = AuditWriter(db.path, secrets.token_bytes(32))
        audit.initialize()
        auth = AuthService(db)
        service = QueryService(db, auth, audit, provider=OfflineExtractiveProvider())
        request = QueryRequest.model_validate({
            "question": question,
            "context": {"workflow_id": "general", "case_date": "2026-09-10",
                        "jurisdiction": "SG", "worker_type": "contractor", "currency": "SGD"},
        })
        try:
            packet = asyncio.run(service.query(auth.principal(principal_id), request))
        except Exception as exc:                                       # noqa: BLE001
            # A refusal is a legitimate target response, not a harness failure.
            return {"output": f"REFUSED: {type(exc).__name__}", "citations": []}
        # The /api/queries packet cites a document version and chunk, not a platform triple.
        citations = []
        for citation in packet.get("citations") or []:
            item = citation if isinstance(citation, dict) else citation.model_dump()
            citations.append(item.get("document_version_id") or item.get("chunk_id"))
        return {"output": packet.get("answer") or "", "citations": citations}


def call_api(prompt: str, options=None, context=None):  # noqa: ARG001
    """Promptfoo Python-provider entry point."""
    result = _answer(prompt)
    return {
        "output": result["output"],
        "metadata": {"provider_mode": "offline_extractive", "simulated": True,
                     "citations": result["citations"],
                     "note": "synthetic fixture; not a live model and not a product claim"},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(call_api("What is the contractor travel cap for project P17?"), indent=2))
