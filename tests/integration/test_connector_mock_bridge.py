"""Mock HTTP adapter records must traverse existing permission/answer/audit contracts."""

import asyncio
import json
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.platforms.connectors import connector_for
from aspire_brain.platforms.connectors.core import (
    ConnectorDocument,
    ConnectorError,
    ConnectorSession,
    IdentityBinding,
    SourceRef,
)
from aspire_brain.platforms.connectors.mock_bridge import MockConnectorState, MockSource
from aspire_brain.platforms.simulated import SimulatedQueryService

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 4, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network")
    monkeypatch.setattr(socket.socket, "connect", denied)


def jira_payload(text):
    return {"id": "10001", "key": "OPS-1", "fields": {
        "project": {"key": "OPS"}, "summary": "Payment investigation", "status": {"name": "Open"},
        "updated": "2026-10-12T03:00:00Z", "created": "2026-10-12T02:00:00Z",
        "description": {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}}}


def test_mock_connector_to_service_revocation_and_no_stale_packet(tmp_path):
    current = {"visible": True, "text": "Payment review is pending."}
    def handler(request):
        if request.url.path.endswith("/myself"):
            return httpx.Response(200, json={"accountId": "acct-a"})
        if not current["visible"]:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=jira_payload(current["text"]))
    db = Database(tmp_path / "bridge.sqlite")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    with ConnectorSession(platform="jira", base_url="https://fixture.atlassian.net",
                          binding=IdentityBinding("demo-a", "employee", "acct-a"),
                          credential=secrets.token_urlsafe(24), auth_user="a@example.invalid",
                          transport=httpx.MockTransport(handler)) as session:
        state = MockConnectorState("demo-a", (MockSource(connector_for(session),
                                    (SourceRef("jira", "OPS-1", "OPS"),)),))
        state.refresh(NOW)
        service = SimulatedQueryService(AuthService(db), audit, state, clock=lambda: NOW,
                                        required_platforms=("jira",))
        packet = asyncio.run(service.query("employee", "What is pending for payment review?", NOW))
        assert "Payment review is pending." in packet["answer"]
        assert packet["simulation_mode"] == "simulated"
        assert service.packet("employee", packet["request_id"])["request_id"] == packet["request_id"]
        current["visible"] = False
        state.refresh(NOW)
        with pytest.raises(AccessDenied):
            service.packet("employee", packet["request_id"])
        denied = asyncio.run(service.query("employee", "What is pending for payment review?", NOW))
        assert denied["citations"] == []
        assert "OPS-1" not in json.dumps(denied)
        assert audit.verify("demo-a")["chain_valid"] is True


def test_bridge_rejects_live_mode_and_cross_tenant_before_fetch():
    class Session:
        mode = "live"
        platform = "jira"
        binding = IdentityBinding("demo-a", "employee", "acct-a")
    class Connector:
        session = Session()
        def fetch(self, ref):
            pytest.fail("Must not fetch")
    with pytest.raises(ConnectorError, match="network_disabled"):
        MockConnectorState("demo-a", (MockSource(Connector(), (SourceRef("jira", "OPS-1", "OPS"),)),))
    Session.mode = "offline_mock"
    with pytest.raises(ConnectorError, match="identity_mismatch"):
        MockConnectorState("demo-b", (MockSource(Connector(), (SourceRef("jira", "OPS-1", "OPS"),)),))


def test_failed_refresh_does_not_leave_old_data_marked_fresh():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429)
    with ConnectorSession(platform="jira", base_url="https://fixture.atlassian.net",
                          binding=IdentityBinding("demo-a", "employee", "acct-a"),
                          credential=secrets.token_urlsafe(24), auth_user="a@example.invalid",
                          transport=httpx.MockTransport(handler)) as session:
        state = MockConnectorState("demo-a", (MockSource(connector_for(session),
                                    (SourceRef("jira", "OPS-1", "OPS"),)),))
        with pytest.raises(ConnectorError, match="rate_limited"):
            state.refresh(NOW)
        assert state.source_status("jira", NOW)["freshness_state"] == "failed"
        assert not state.records
        assert len(calls) == 1


def test_unexpected_adapter_failure_clears_previously_readable_cache():
    class Session:
        mode = "offline_mock"
        platform = "jira"
        binding = IdentityBinding("demo-a", "employee", "acct-a")
    class Connector:
        session = Session()
        broken = False
        def fetch(self, ref):
            if self.broken:
                raise RuntimeError("private adapter diagnostic")
            return (ConnectorDocument("jira", "OPS-1", "issue", "1", "Pending review.",
                                      "https://fixture.atlassian.net/browse/OPS-1", "OPS", NOW),)
    connector = Connector()
    state = MockConnectorState("demo-a", (MockSource(connector, (SourceRef("jira", "OPS-1", "OPS"),)),))
    state.refresh(NOW)
    assert state.can_read({"id": "employee", "tenant_id": "demo-a", "active": True}, "jira", "OPS-1")
    connector.broken = True
    with pytest.raises(ConnectorError, match="invalid_response") as error:
        state.refresh(NOW)
    assert "private" not in str(error.value)
    assert not state.records
    assert state.source_status("jira", NOW)["freshness_state"] == "failed"


@pytest.mark.parametrize("source_id,parent_id", [("SECRET-1", "SECRET"), ("OPS-1", "SECRET")])
def test_bridge_rejects_adapter_records_outside_requested_reference(source_id, parent_id):
    class Session:
        mode = "offline_mock"
        platform = "jira"
        binding = IdentityBinding("demo-a", "employee", "acct-a")
    class Connector:
        session = Session()
        def fetch(self, ref):
            return (ConnectorDocument("jira", source_id, "issue", "1", "Private data.",
                                      "https://fixture.atlassian.net/browse/SECRET-1", parent_id, NOW),)
    state = MockConnectorState("demo-a", (MockSource(Connector(), (SourceRef("jira", "OPS-1", "OPS"),)),))
    with pytest.raises(ConnectorError, match="invalid_response"):
        state.refresh(NOW)
    assert not state.records


@pytest.mark.parametrize("source_id,parent_id,thread,workspace,allowed", [
    ("CDEMO:1791768601.000001", "CDEMO", "1791768600.000001", "TDEMO", True),
    ("COTHER:1791768601.000001", "CDEMO", "1791768600.000001", "TDEMO", False),
    ("CDEMO:1791768601.000001", "COTHER", "1791768600.000001", "TDEMO", False),
    ("CDEMO:1791768601.000001", "CDEMO", "1791768602.000001", "TDEMO", False),
    ("CDEMO:1791768601.000001", "CDEMO", "1791768600.000001", "TOTHER", False),
])
def test_slack_bridge_contains_channel_thread_and_workspace(source_id, parent_id, thread, workspace, allowed):
    class Session:
        mode = "offline_mock"
        platform = "slack"
        binding = IdentityBinding("demo-a", "employee", "acct-a", "TDEMO")
    class Connector:
        session = Session()
        def fetch(self, ref):
            return (ConnectorDocument("slack", source_id, "thread_message", "1", "Pending.",
                                      "https://app.slack.com/client/TDEMO/CDEMO", parent_id,
                                      NOW, event_at=NOW, thread_id=thread),)
    ref = SourceRef("slack", "CDEMO", workspace, "1791768600.000001")
    state = MockConnectorState("demo-a", (MockSource(Connector(), (ref,)),))
    if allowed:
        state.refresh(NOW)
        assert state.can_read({"id": "employee", "tenant_id": "demo-a", "active": True}, "slack", source_id)
    else:
        with pytest.raises(ConnectorError, match="invalid_response"):
            state.refresh(NOW)
        assert not state.records
