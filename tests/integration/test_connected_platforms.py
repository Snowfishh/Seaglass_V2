"""The connector path end to end: discovery, ingestion, sync, query, re-check and the web app.

Every platform is the offline fake in ``fake_platforms``, reached through the real connectors
over ``httpx.MockTransport``. No network, no credential file and no live account is used.
"""

import asyncio
import json
import secrets
import socket
import threading
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from fake_platforms import ACCOUNTS, FakePlatforms
from fastapi.testclient import TestClient

from aspire_brain.answers.service import QueryError
from aspire_brain.audit import AuditWriter
from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.config import ConfigurationError, Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app
from aspire_brain.platforms.connected import (
    ConnectorConfigError,
    build_upstreams,
    load_connector_config,
    load_tokens,
)
from aspire_brain.platforms.routing import ContextBudget
from aspire_brain.platforms.runtime import connector_runtime
from aspire_brain.platforms.simulated import SimulatedQueryService
from aspire_brain.web.cases import run_typed_query, typed_service

ROOT = Path(__file__).resolve().parents[2]
RESTRICTED_TEXT = ("Cedar Quay", "12,480", "fraud review")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Connector test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


class ManualClock:
    mode = "wall_clock"

    def __init__(self, fake):
        self.fake = fake

    def now(self):
        return self.fake.now


def write_config(tmp_path, fake):
    path = tmp_path / "connectors.json"
    path.write_text(json.dumps(fake.targets()))
    tokens = tmp_path / "private" / "tokens.json"
    tokens.parent.mkdir()
    tokens.write_text(json.dumps(fake.tokens))
    tokens.chmod(0o600)
    return path, tokens


def make_runtime(tmp_path, fake, *, interval=0):
    path, _ = write_config(tmp_path, fake)
    config = load_connector_config(path, project_root=ROOT)
    return connector_runtime(config, fake.tokens, sync_interval_seconds=interval,
                             transport_for=fake.transport_for, clock=ManualClock(fake))


@pytest.fixture
def system(tmp_path):
    db = Database(tmp_path / "connected.db")
    db.initialize()
    db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
    audit = AuditWriter(db.path, secrets.token_bytes(32))
    audit.initialize()
    fake = FakePlatforms()
    runtime = make_runtime(tmp_path, fake)
    runtime.sync_all("startup")
    return AuthService(db), audit, fake, runtime, db


def ask(system, principal, question):
    auth, audit, _, runtime, _ = system
    return asyncio.run(run_typed_query(auth, audit, principal, question, runtime=runtime))


def cited(result):
    return {citation["source_id"] for citation in result["packet"]["citations"]}


# -- discovery and ingestion ------------------------------------------------------------

def test_discovery_reads_every_item_each_user_can_see_with_their_own_token(system):
    _, _, fake, runtime, _ = system
    index = runtime.index
    assert {key[0] for key in index.records} == {"confluence", "jira", "slack", "drive"}
    assert ("confluence", "202") in index.records and ("drive", "fileRes") in index.records
    # Slack thread replies are followed, and stay inside their channel and thread.
    replies = [record for record in index.records.values() if record.source_kind == "thread_message"]
    assert any("Callback logs" in record.text for record in replies)
    a, b = ({"id": user, "tenant_id": "fintech-demo", "active": True} for user in ("user-a", "user-b"))
    for platform, source_id in (("confluence", "202"), ("jira", "OPS-2"), ("drive", "fileRes")):
        assert index.can_read(a, platform, source_id)
        assert not index.can_read(b, platform, source_id)
    gres = [key for key, record in index.records.items() if record.parent_id == "GRES"]
    assert gres and all(index.can_read(a, *key) and not index.can_read(b, *key) for key in gres)
    # Each platform keeps its own grant model.
    assert index.confluence_space_grants["OPS"] == {"acct-a", "acct-b"}
    assert index.confluence_page_grants["202"] == {"acct-a"}
    assert index.slack_channel_grants["GRES"] == {"UAAA"}
    assert {user for user, _ in fake.requests} == {"A", "B"}


def test_a_container_one_user_cannot_browse_leaves_the_others_views_intact(tmp_path):
    fake = FakePlatforms()
    fake.add_project("SEC", {"SEC-1": "Sanctions screening hold for Cedar Quay"}, readers=("A",))
    targets = fake.targets()
    targets["containers"]["jira"] = ["OPS", "SEC"]
    fake.targets = lambda: targets
    runtime = make_runtime(tmp_path, fake)
    runs = {run["platform"]: run for run in runtime.sync_all("startup")}
    # B is refused the SEC project; that is B's empty view, not a failed Jira crawl.
    assert runs["jira"]["outcome"] == "completed"
    assert runtime.index.upstream["jira"].last_poll["outcome"] == "completed"
    a, b = ({"id": user, "tenant_id": "fintech-demo", "active": True} for user in ("user-a", "user-b"))
    assert runtime.index.can_read(a, "jira", "SEC-1")
    assert not runtime.index.can_read(b, "jira", "SEC-1")
    assert runtime.index.can_read(b, "jira", "OPS-1")
    assert ("B", "/rest/api/3/project/SEC") in fake.requests
    assert ("B", "/rest/api/3/search/jql") in fake.requests  # for OPS only


def test_text_read_with_one_users_credential_is_never_granted_to_another(tmp_path):
    fake = FakePlatforms()
    fake.pages["101"]["views"] = {
        "A": "Escalate a payment that stays processing for more than 30 minutes. "
             "Restricted note: Cedar Quay is on the watch list."}
    runtime = make_runtime(tmp_path, fake)
    runtime.sync_all("startup")
    index = runtime.index
    assert index.upstream["confluence"].last_poll["content_variants"] == 1
    a, b = ({"id": user, "tenant_id": "fintech-demo", "active": True} for user in ("user-a", "user-b"))
    # The index keeps one copy (A's, read first) and grants it only to the user who saw it.
    assert "watch list" in index.records[("confluence", "101")].text
    assert index.confluence_page_grants["101"] == {"acct-a"}
    assert index.can_read(a, "confluence", "101")
    assert not index.can_read(b, "confluence", "101")
    # Once the views agree again, B gets the page back at the next sync.
    del fake.pages["101"]["views"]
    fake.edit_page("101", fake.pages["101"]["body"])
    runtime.sync_all("scheduled")
    assert index.can_read(b, "confluence", "101")
    assert "watch list" not in index.records[("confluence", "101")].text


def test_typed_answers_follow_each_platforms_permissions(system):
    allowed = ask(system, "user-a", "Why is the Cedar Quay payment held?")
    assert allowed["packet"]["query_status"] in {"answered", "partial"}
    assert "202" in cited(allowed)
    assert "beneficiary details changed" in allowed["packet"]["answer"]
    denied = ask(system, "user-b", "Why is the Cedar Quay payment held?")
    body = json.dumps(denied)
    for text in RESTRICTED_TEXT:
        assert text not in body.replace("Why is the Cedar Quay payment held?", "")
    assert not {"202", "fileRes", "OPS-2"} & cited(denied)


# -- freshness ------------------------------------------------------------------------------

def test_a_platform_edit_is_answered_after_the_next_sync_and_measured(system):
    _, _, fake, runtime, _ = system
    before = ask(system, "user-b", "What is the escalation threshold for processing payments?")
    assert "30 minutes" in before["packet"]["answer"]
    fake.edit_page("101", "Escalate a payment that stays processing for more than 15 minutes.")
    # Before a sync the indexed copy is out of date; the query-time check notices and withholds it.
    pending = ask(system, "user-b", "What is the escalation threshold for processing payments?")
    assert "30 minutes" not in pending["packet"]["answer"]
    assert "confluence" in pending["packet"]["incomplete_platforms"]
    fake.tick(4)
    run = next(run for run in runtime.sync_all("scheduled") if run["platform"] == "confluence")
    assert run["outcome"] == "completed" and run["updated"] == 1
    after = ask(system, "user-b", "What is the escalation threshold for processing payments?")
    assert "15 minutes" in after["packet"]["answer"]
    measurement = next(m for m in runtime.status()["measurements"] if m.get("source_id") == "101")
    assert measurement["basis"] == "platform_modified_time"
    assert measurement["propagation_seconds"] == 240 and measurement["within_budget"] is True


def test_an_edit_made_during_the_crawl_is_measured_from_the_crawls_end(tmp_path):
    fake = FakePlatforms()
    serve = fake.handle
    mid_crawl = {"armed": False}

    def handle(request):
        # The page is edited a minute into the crawl, just before the crawler reads it.
        if mid_crawl["armed"] and request.url.path.endswith("/101"):
            mid_crawl["armed"] = False
            fake.tick(1)
            fake.edit_page("101", "Escalate a payment that stays processing for more than 15 minutes.")
        return serve(request)
    fake.handle = handle
    runtime = make_runtime(tmp_path, fake)
    runtime.sync_all("startup")
    fake.tick(2)
    mid_crawl["armed"] = True
    runtime.sync_all("scheduled")
    assert mid_crawl["armed"] is False
    measurement = next(m for m in runtime.status()["measurements"] if m.get("source_id") == "101")
    # Measured from the start of the crawl this was -60 s and passed as within budget.
    assert measurement["propagation_seconds"] == 0
    assert all(m["propagation_seconds"] >= 0 for m in runtime.status()["measurements"])


def test_an_old_page_that_becomes_visible_is_not_measured_as_a_late_update(tmp_path):
    fake = FakePlatforms()
    fake.add_page("404", "Archived settlement note", "Settlement cut-off moved to 16:00.",
                  readers=())
    runtime = make_runtime(tmp_path, fake)
    runtime.sync_all("startup")
    assert ("confluence", "404") not in runtime.index.records
    fake.tick(120)
    fake.pages["404"]["readers"].update({"A", "B"})
    runtime.sync_all("scheduled")
    assert ("confluence", "404") in runtime.index.records
    # The page did not change; it became visible. Its two-hour age is not a propagation delay.
    assert not [m for m in runtime.status()["measurements"] if m.get("source_id") == "404"]
    assert all(m["within_budget"] for m in runtime.status()["measurements"])


def test_a_new_page_is_discovered_without_knowing_its_id(system):
    _, _, fake, runtime, _ = system
    fake.add_page("303", "Failover runbook", "Enable failover to the standby region before restart.")
    assert ("confluence", "303") not in runtime.index.records
    runtime.sync_all("scheduled")
    assert ("confluence", "303") in runtime.index.records
    result = ask(system, "user-b", "How do I enable failover to the standby region?")
    assert "303" in cited(result)


def test_an_index_past_its_budget_is_stale_and_not_quoted(system):
    _, _, fake, runtime, _ = system
    fake.tick(61)
    status = runtime.status()["platforms"]
    assert {entry["freshness_state"] for entry in status.values()} == {"stale"}
    result = ask(system, "user-b", "What is the escalation threshold for processing payments?")
    assert result["packet"]["query_status"] == "abstained"
    assert result["packet"]["citations"] == []


def test_a_failed_crawl_publishes_nothing_and_keeps_the_last_good_index(system):
    _, _, fake, runtime, _ = system
    records = dict(runtime.index.records)
    fake.remove_reader("A")
    fake.rate_limited_users.add("B")
    runs = runtime.sync_all("scheduled")
    assert {run["outcome"] for run in runs} == {"rate_limited"}
    assert all(run["watermark_advanced"] is False for run in runs)
    # A's removal was not published, because B's crawl failed: no partial view is applied.
    assert runtime.index.records == records
    fake.rate_limited_users.clear()
    assert {run["outcome"] for run in runtime.sync_all("retry")} == {"completed"}
    assert ("confluence", "202") not in {key for key in runtime.index.records
                                         if runtime.index.can_read(
                                             {"id": "user-a", "tenant_id": "fintech-demo",
                                              "active": True}, *key)}


# -- permission changes ---------------------------------------------------------------------

def test_removed_access_is_enforced_at_query_time_before_any_sync(system):
    auth, audit, fake, runtime, _ = system
    first = ask(system, "user-a", "Why is the Cedar Quay payment held?")
    assert "202" in cited(first)
    fake.remove_reader("A")
    second = ask(system, "user-a", "Why is the Cedar Quay payment held?")
    assert "202" not in cited(second)
    assert "beneficiary details changed" not in second["packet"]["answer"]
    # The packet says the platforms were asked, never how many records they withheld.
    verification = second["packet"]["answer_focus"]["upstream_verification"]
    assert verification["performed"] is True
    assert not {"checked", "allowed", "withheld"} & set(verification)
    assert set(verification) == set(first["packet"]["answer_focus"]["upstream_verification"])
    # The saved answer that quoted the page is closed too.
    service = typed_service(auth, audit, runtime)
    with pytest.raises(AccessDenied):
        service.packet("user-a", first["packet"]["request_id"])
    # The next sync folds the change into each platform's own grants.
    runtime.sync_all("scheduled")
    assert "acct-a" not in runtime.index.confluence_page_grants.get("202", frozenset())
    assert "UAAA" not in runtime.index.slack_channel_grants.get("GRES", frozenset())
    assert "perm-a" not in runtime.index.drive_file_grants.get("fileRes", frozenset())
    assert "acct-a" not in runtime.index.jira_issue_grants.get("OPS-2", frozenset())


def test_the_query_time_recheck_runs_off_the_event_loop_within_a_time_budget(system, monkeypatch):
    _, _, _, runtime, _ = system
    original = runtime.verifier
    on_loop_thread = []

    def recording(principal, records):
        on_loop_thread.append(threading.current_thread() is threading.main_thread())
        return original(principal, records)
    monkeypatch.setattr(runtime, "verifier", recording)
    assert "202" in cited(ask(system, "user-a", "Why is the Cedar Quay payment held?"))
    # Blocking connector calls never run on the thread that drives the event loop.
    assert on_loop_thread == [False]
    monkeypatch.setattr(runtime, "verifier", original)
    # Once the budget is spent, the remaining records are withheld rather than served unchecked.
    ticks = iter(range(0, 10_000, 100))
    monkeypatch.setattr(runtime, "_monotonic", lambda: next(ticks))
    assert cited(ask(system, "user-a", "Why is the Cedar Quay payment held?")) == set()


def test_a_revoked_item_leaves_no_identifier_in_the_diagnostics_before_any_sync(system):
    auth, audit, fake, runtime, _ = system
    # A one-item budget drops the restricted page into the budget diagnostics.
    service = SimulatedQueryService(auth, audit, runtime.index, required_platforms=None,
                                    clock=runtime.clock.now, verifier=runtime.verifier,
                                    budget=ContextBudget(max_items=1, max_chars=12000))
    first = asyncio.run(service.query("user-a", "payment", runtime.clock.now()))
    assert "confluence:202:1" in first["context_budget"]["dropped_ids"]
    fake.remove_reader("A")
    second = asyncio.run(service.query("user-a", "payment", runtime.clock.now()))
    budget = second["context_budget"]
    assert "confluence:202:1" not in budget["dropped_ids"]
    assert budget["dropped_items"] == len(budget["dropped_ids"])
    assert not any(":202:" in identifier or "OPS-2" in identifier or "fileRes" in identifier
                   or "GRES" in identifier for identifier in budget["dropped_ids"])
    # The saved answer that named the page is closed too, although it never cited it.
    assert "202" not in {citation["source_id"] for citation in first["citations"]}
    with pytest.raises(AccessDenied):
        service.packet("user-a", first["request_id"])
    assert service.packet("user-a", second["request_id"]) == second


def test_a_saved_answer_stays_readable_while_its_sources_are_unchanged(system):
    auth, audit, _, runtime, _ = system
    result = ask(system, "user-b", "What is the escalation threshold for processing payments?")
    service = typed_service(auth, audit, runtime)
    assert service.packet("user-b", result["packet"]["request_id"]) == result["packet"]


# -- configuration ------------------------------------------------------------------------------

def test_live_reads_need_explicit_opt_in_and_a_private_token_file(tmp_path):
    fake = FakePlatforms()
    path, tokens = write_config(tmp_path, fake)
    config = load_connector_config(path, project_root=ROOT)
    with pytest.raises(ConnectorConfigError, match="allow_live"):
        build_upstreams(config, fake.tokens)
    tokens.chmod(0o644)
    with pytest.raises(ConnectorConfigError, match="owner"):
        load_tokens(tokens, project_root=ROOT)
    tokens.chmod(0o600)
    assert load_tokens(tokens, project_root=ROOT) == fake.tokens
    with pytest.raises(ConnectorConfigError, match="outside the project"):
        load_tokens(tokens, project_root=tmp_path)


def test_the_live_access_targets_file_doubles_as_connector_configuration(tmp_path):
    targets = json.loads((ROOT / "eval/live_access/targets.example.json").read_text())
    for user, profile in targets["users"].items():
        profile.update(atlassian_account_id=f"acct-{user}", slack_user_id=f"U{user}",
                       drive_permission_id=f"perm-{user}")
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({**targets, "slack_workspace_id": "T999",
                                        "items": {platform: {kind: {**item, "parent": f"{platform}-{kind}"}
                                                             for kind, item in items.items()}
                                                  for platform, items in targets["items"].items()}}))
    config_path = tmp_path / "connectors.json"
    config_path.write_text(json.dumps({"targets_file": str(targets_path), "allow_live": True}))
    config = load_connector_config(config_path, project_root=ROOT)
    assert set(config.principals) == {"user-a", "user-b"}
    assert config.containers["slack"] == ("T999",)
    assert config.containers["drive"] == ("drive-general", "drive-restricted")
    assert config.allow_live is True


# -- the web application on the connector source ------------------------------------------------

def test_the_web_app_answers_from_connected_platforms(tmp_path):
    fake = FakePlatforms()
    runtime = make_runtime(tmp_path, fake, interval=300)
    settings = Settings(db_path=tmp_path / "web.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                        demo_mode=True)
    with TestClient(create_app(settings, platform_runtime=runtime), base_url="http://localhost",
                    client=("127.0.0.1", 50000)) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json", ROOT / "data/demo/principals.json")
        deadline = 200
        while deadline and not runtime.runs:  # the startup sync runs off the request path
            deadline -= 1
            asyncio.run(asyncio.sleep(0.01))
        assert runtime.runs

        def headers():
            token = client.get("/api/session").json()["csrf_token"]
            return {"X-CSRF-Token": token, "Origin": "http://localhost"}
        assert client.post("/api/demo/session", json={"user_id": "user-a"},
                           headers=headers()).status_code == 200
        cases = client.get("/cases").text
        assert "CONNECTED" in cases
        answer = client.post("/api/four-platform/queries",
                             json={"question": "Why is the Cedar Quay payment held?"},
                             headers=headers()).json()
        assert "202" in cited(answer)
        assert "connected Confluence" in answer["provider_note"]
        status = client.get("/api/four-platform/status").json()
        assert status["source"] == "connectors"
        assert {entry["freshness_state"] for entry in status["platforms"].values()} == {"fresh"}
        assert client.post("/api/demo/session", json={"user_id": "fintech_admin"},
                           headers=headers()).status_code == 200
        # Upstream changes are made on the platforms themselves, not through the app.
        response = client.post("/api/four-platform/upstream-changes",
                               json={"action": "revoke_restricted"}, headers=headers())
        assert response.status_code == 409
        assert client.post("/api/four-platform/sync", headers=headers()).status_code == 200


class RecordingLiveModel:
    mode = "live_grounded"

    def __init__(self):
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        raise AssertionError("Connected content reached the live model")


def test_the_live_model_never_receives_connected_content(system, tmp_path):
    auth, audit, _, runtime, _ = system
    model = RecordingLiveModel()
    # Real accounts mark nothing restricted, so the query is refused before any dispatch.
    with pytest.raises(QueryError, match="connected accounts"):
        asyncio.run(run_typed_query(auth, audit, "user-a", "Why is the Cedar Quay payment held?",
                                    runtime=runtime, provider=model))
    assert model.calls == 0
    # The settings refuse the combination before any credential is read.
    keys = {"db_path": tmp_path / "live.db", "session_secret": secrets.token_hex(32),
            "audit_key": secrets.token_bytes(32)}
    with pytest.raises(ConfigurationError, match="fictional fixture only"):
        Settings(**keys, provider_mode="live_grounded", platform_source="connectors",
                 provider_key_path=tmp_path / "missing.key")
    # So does the application when a live provider and a connected index are handed to it.
    app = create_app(Settings(**keys, demo_mode=True), provider=model, platform_runtime=runtime)
    with pytest.raises(ConfigurationError, match="fictional fixture only"):
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)):
            pass
    assert model.calls == 0


def test_connector_runtime_rejects_an_interval_longer_than_the_budget(tmp_path):
    fake = FakePlatforms()
    path, _ = write_config(tmp_path, fake)
    config = load_connector_config(path, project_root=ROOT)
    with pytest.raises(ValueError, match="shorter"):
        connector_runtime(config, fake.tokens, sync_interval_seconds=3600,
                          freshness_budget_seconds=3600, transport_for=fake.transport_for)


def test_accounts_are_bound_to_application_principals(system):
    _, _, _, runtime, _ = system
    assert runtime.index.principal_map["user-a"] == {
        "confluence": ACCOUNTS["A"]["atlassian"], "jira": ACCOUNTS["A"]["atlassian"],
        "slack": ACCOUNTS["A"]["slack"], "drive": ACCOUNTS["A"]["drive"]}
    assert timedelta(seconds=runtime.index.freshness_budget_seconds["slack"]) == timedelta(hours=1)


def test_query_records_are_audited_with_platform_decisions(system):
    _, audit, _, _, db = system
    ask(system, "user-b", "What is the escalation threshold for processing payments?")
    with closing(db.connect()) as connection:
        events = [row[0] for row in connection.execute(
            "SELECT event_type FROM audit_events WHERE principal_id='user-b' ORDER BY sequence")]
    assert events[-2:] == ["query_attempt", "query_completed"]
