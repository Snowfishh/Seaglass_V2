"""Owner-run live access check, exercised offline against a fake four-platform server."""

import base64
import importlib.util
import json
import secrets
import socket
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_access_check", ROOT / "eval/live_access/check.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)

WHEN = "2026-10-12T01:00:00.000Z"
TOKENS = {user: {"atlassian": secrets.token_urlsafe(16), "slack": "xoxp-" + secrets.token_hex(8),
                 "drive": secrets.token_urlsafe(16)} for user in ("A", "B")}
ACCOUNTS = {"A": {"atlassian": "acct-a", "slack": "UAAA", "drive": "perm-a"},
            "B": {"atlassian": "acct-b", "slack": "UBBB", "drive": "perm-b"}}
TARGETS = {
    "atlassian_site": "https://demo.atlassian.net",
    "slack_workspace_id": "T123",
    "users": {user: {"atlassian_email": f"{user.lower()}@example.com",
                     "atlassian_account_id": ACCOUNTS[user]["atlassian"],
                     "slack_user_id": ACCOUNTS[user]["slack"],
                     "drive_permission_id": ACCOUNTS[user]["drive"]} for user in ("A", "B")},
    "items": {
        "confluence": {"general": {"id": "101", "parent": "OPS"},
                       "restricted": {"id": "202", "parent": "OPS"}},
        "jira": {"general": {"id": "OPS-1", "parent": "OPS"},
                 "restricted": {"id": "CASE-2", "parent": "CASE"}},
        "slack": {"general": {"id": "CGEN"}, "restricted": {"id": "GRES"}},
        "drive": {"general": {"id": "fileGen", "parent": "folder1"},
                  "restricted": {"id": "fileRes", "parent": "folder1"}},
    },
}
RESTRICTED = {"202", "CASE-2", "GRES", "fileRes"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _user(request):
    header = request.headers["authorization"]
    scheme, value = header.split(" ", 1)
    credential = base64.b64decode(value).decode().split(":", 1)[1] if scheme == "Basic" else value
    return next(user for user, tokens in TOKENS.items() if credential in tokens.values())


def fake_server(b_can_read_restricted=False):
    def handler(request):
        user, path = _user(request), request.url.path
        blocked = user == "B" and not b_can_read_restricted
        if path in {"/wiki/rest/api/user/current", "/rest/api/3/myself"}:
            return httpx.Response(200, json={"accountId": ACCOUNTS[user]["atlassian"]})
        if path.startswith("/wiki/rest/api/content/"):
            page = path.rsplit("/", 1)[1]
            if blocked and page in RESTRICTED:
                return httpx.Response(404)
            return httpx.Response(200, json={
                "id": page, "type": "page", "status": "current", "space": {"key": "OPS"},
                "version": {"number": 1, "when": WHEN}, "title": "Handover",
                "body": {"storage": {"value": "<p>Fictional handover.</p>"}}})
        if path.startswith("/rest/api/3/issue/"):
            key = path.rsplit("/", 1)[1]
            if blocked and key in RESTRICTED:
                return httpx.Response(404)
            return httpx.Response(200, json={"key": key, "fields": {
                "summary": "Fictional task", "description": None, "updated": WHEN,
                "project": {"key": key.split("-")[0]}, "status": {"name": "To Do"}}})
        if path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user_id": ACCOUNTS[user]["slack"],
                                             "team_id": "T123", "url": "https://demo.slack.com/"})
        if path == "/api/conversations.info":
            channel = request.url.params["channel"]
            if blocked and channel in RESTRICTED:
                return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
            return httpx.Response(200, json={"ok": True, "channel": {
                "id": channel, "is_im": False, "is_mpim": False,
                "is_private": channel in RESTRICTED, "is_member": True}})
        if path == "/api/conversations.history":
            return httpx.Response(200, json={"ok": True, "has_more": False, "messages": [
                {"type": "message", "ts": "1760230000.000100", "text": "Fictional update."}]})
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"permissionId": ACCOUNTS[user]["drive"]}})
        if path.startswith("/drive/v3/files/"):
            file_id = path.split("/")[4]
            if blocked and file_id in RESTRICTED:
                return httpx.Response(404)
            if request.url.params.get("alt") == "media":
                return httpx.Response(200, text="Fictional invoice.")
            return httpx.Response(200, json={
                "id": file_id, "name": "file.md", "mimeType": "text/markdown",
                "parents": ["folder1"], "trashed": False, "version": "3", "modifiedTime": WHEN})
        return httpx.Response(500)
    return httpx.MockTransport(handler)


def test_expected_access_split_passes_on_all_platforms_without_storing_text():
    rows = live.check(TARGETS, TOKENS, transport=fake_server())
    assert len(rows) == 16
    assert all(row["pass"] for row in rows), rows
    assert {row["observed"] for row in rows if row["user"] == "B" and row["item"] == "restricted"} == {"denied"}
    dumped = json.dumps(rows)
    assert "Fictional" not in dumped and "example.com" not in dumped
    assert not any(token in dumped for tokens in TOKENS.values() for token in tokens.values())


def test_b_reading_restricted_items_fails():
    rows = live.check(TARGETS, TOKENS, transport=fake_server(b_can_read_restricted=True))
    failed = [row for row in rows if not row["pass"]]
    assert {(row["platform"], row["user"], row["item"]) for row in failed} == {
        (platform, "B", "restricted") for platform in live.PLATFORMS}


def test_token_for_the_wrong_person_is_an_error_not_a_denial():
    swapped = TOKENS | {"B": TOKENS["A"]}
    rows = live.check(TARGETS, swapped, platforms=("jira",), transport=fake_server())
    b_rows = [row for row in rows if row["user"] == "B"]
    assert {row.get("error") for row in b_rows} == {"identity_mismatch"}
    assert not any(row["pass"] for row in b_rows)


def test_unfilled_template_values_are_reported_not_called():
    targets = json.loads((ROOT / "eval/live_access/targets.example.json").read_text())
    tokens = json.loads((ROOT / "eval/live_access/tokens.example.json").read_text())
    rows = live.check(targets, tokens, transport=httpx.MockTransport(
        lambda request: pytest.fail("No request expected")))
    assert {row["observed"] for row in rows} == {"not_configured"}
    assert all(row["missing"] for row in rows)


def test_discover_returns_own_identifiers():
    rows = live.discover(TARGETS, TOKENS, transport=fake_server())
    assert all(row["result"] == "ok" for row in rows)
    by_key = {(row["platform"], row["user"]): row for row in rows}
    assert by_key[("slack", "B")]["slack_user_id"] == "UBBB"
    assert by_key[("slack", "B")]["slack_workspace_id"] == "T123"
    assert by_key[("drive", "A")]["drive_permission_id"] == "perm-a"
    assert by_key[("jira", "A")]["atlassian_account_id"] == "acct-a"


def test_token_file_must_be_private_and_outside_repository(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(TOKENS))
    path.chmod(0o644)
    with pytest.raises(live.SetupError, match="chmod 600"):
        live.load_tokens(path)
    path.chmod(0o600)
    assert live.load_tokens(path) == TOKENS
    with pytest.raises(live.SetupError, match="outside the repository"):
        live.load_tokens(ROOT / "eval/live_access/tokens.example.json")


def test_jira_can_live_on_its_own_atlassian_site():
    hosts = []
    inner = fake_server()

    def handler(request):
        hosts.append((request.url.path.split("/")[1], request.url.host))
        return inner.handle_request(request)
    targets = TARGETS | {"jira_site": "https://jira-demo.atlassian.net"}
    rows = live.check(targets, TOKENS, platforms=("jira", "confluence"),
                      transport=httpx.MockTransport(handler))
    assert all(row["pass"] for row in rows), rows
    assert {host for prefix, host in hosts if prefix == "rest"} == {"jira-demo.atlassian.net"}
    assert {host for prefix, host in hosts if prefix == "wiki"} == {"demo.atlassian.net"}


def test_token_file_permissions_are_not_checked_on_windows(tmp_path, monkeypatch):
    # Windows reports POSIX group/other bits for every file; the check would always refuse.
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(TOKENS))
    path.chmod(0o644)
    monkeypatch.setattr(live.os, "name", "nt")
    assert live.load_tokens(path) == TOKENS
