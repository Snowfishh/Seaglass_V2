"""A stateful, offline stand-in for the Confluence, Jira, Slack and Drive APIs.

Each item has its own reader set per platform permission model, so a test can change content or
remove a user's access "on the platform" and watch the application pick it up. Only the
endpoints the connectors call are implemented. Nothing here touches the network.
"""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta

import httpx

USERS = ("A", "B")
ACCOUNTS = {"A": {"atlassian": "acct-a", "slack": "UAAA", "drive": "perm-a"},
            "B": {"atlassian": "acct-b", "slack": "UBBB", "drive": "perm-b"}}
WORKSPACE = "T123"
START = datetime(2026, 10, 15, 1, 0, tzinfo=UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakePlatforms:
    def __init__(self):
        self.tokens = {user: {"atlassian": secrets.token_urlsafe(16),
                              "slack": "xoxp-" + secrets.token_hex(8),
                              "drive": secrets.token_urlsafe(16)} for user in USERS}
        self.now = START
        self.requests: list[tuple[str, str]] = []
        self.rate_limited_users: set[str] = set()
        self.pages = {
            "101": {"space": "OPS", "title": "Payment service runbook",
                    "body": "Escalate a payment that stays processing for more than 30 minutes.",
                    "version": 1, "when": START, "readers": {"A", "B"}},
            "202": {"space": "OPS", "title": "Restricted beneficiary case",
                    "body": "Cedar Quay payment is held because beneficiary details changed after approval.",
                    "version": 1, "when": START, "readers": {"A"}},
        }
        #: Jira project -> users who may browse it.
        self.projects = {"OPS": {"A", "B"}}
        self.issues = {
            "OPS-1": {"summary": "Investigate delayed payment callbacks", "status": "In progress",
                      "updated": START, "readers": {"A", "B"}},
            "OPS-2": {"summary": "Restricted fraud review for Cedar Quay", "status": "Open",
                      "updated": START, "readers": {"A"}},
        }
        self.channels = {
            "CGEN": {"private": False, "members": {"A", "B"}, "messages": [
                {"ts": "1760490000.000100", "text": "Payment callbacks are delayed; Engineering is investigating.",
                 "replies": [{"ts": "1760490060.000200",
                              "text": "Callback logs show the delay started at 09:00."}]}]},
            "GRES": {"private": True, "members": {"A"}, "messages": [
                {"ts": "1760490100.000300", "text": "Cedar Quay beneficiary verification is still open."}]},
        }
        self.files = {
            "fileGen": {"folder": "folder1", "name": "reconciliation.md",
                        "body": "Two processing payments still need a partner reference.",
                        "version": 3, "modified": START, "readers": {"A", "B"}},
            "fileRes": {"folder": "folder1", "name": "invoice.md",
                        "body": "Cedar Quay invoice total is USD 12,480.00.",
                        "version": 1, "modified": START, "readers": {"A"}},
        }

    # -- platform-side changes -----------------------------------------------------------

    def tick(self, minutes: int = 1):
        self.now += timedelta(minutes=minutes)

    def edit_page(self, page_id, body):
        self.tick()
        page = self.pages[page_id]
        page.update(body=body, version=page["version"] + 1, when=self.now)

    def add_page(self, page_id, title, body, readers=("A", "B")):
        self.tick()
        self.pages[page_id] = {"space": "OPS", "title": title, "body": body, "version": 1,
                               "when": self.now, "readers": set(readers)}

    def add_project(self, key, issues, readers=("A",)):
        """A second Jira project that only ``readers`` may browse."""
        self.projects[key] = set(readers)
        for issue_key, summary in issues.items():
            self.issues[issue_key] = {"summary": summary, "status": "Open", "updated": self.now,
                                      "readers": set(readers)}

    def remove_reader(self, user):
        """Take ``user`` off every restricted item on all four platforms."""
        self.pages["202"]["readers"].discard(user)
        self.issues["OPS-2"]["readers"].discard(user)
        self.channels["GRES"]["members"].discard(user)
        self.files["fileRes"]["readers"].discard(user)

    # -- configuration for the application -----------------------------------------------

    def targets(self):
        return {
            "tenant_id": "fintech-demo", "allow_live": False,
            "atlassian_site": "https://demo.atlassian.net", "slack_workspace_id": WORKSPACE,
            "users": {user: {"atlassian_email": f"{user.lower()}@example.com",
                             "atlassian_account_id": ACCOUNTS[user]["atlassian"],
                             "slack_user_id": ACCOUNTS[user]["slack"],
                             "drive_permission_id": ACCOUNTS[user]["drive"]} for user in USERS},
            "containers": {"confluence": ["OPS"], "jira": ["OPS"], "slack": [WORKSPACE],
                           "drive": ["folder1"]},
        }

    def transport_for(self, platform):
        return httpx.MockTransport(self.handle)

    # -- HTTP --------------------------------------------------------------------------

    def _user(self, request):
        scheme, value = request.headers["authorization"].split(" ", 1)
        credential = (base64.b64decode(value).decode().split(":", 1)[1] if scheme == "Basic"
                      else value)
        return next(user for user, tokens in self.tokens.items() if credential in tokens.values())

    def handle(self, request):
        user, path, params = self._user(request), request.url.path, request.url.params
        self.requests.append((user, path))
        if user in self.rate_limited_users:
            return httpx.Response(429)
        # Confluence
        if path == "/wiki/rest/api/user/current" or path == "/rest/api/3/myself":
            return httpx.Response(200, json={"accountId": ACCOUNTS[user]["atlassian"]})
        if path == "/wiki/rest/api/content":
            results = [{"id": page_id, "type": "page", "status": "current"}
                       for page_id, page in sorted(self.pages.items())
                       if page["space"] == params["spaceKey"] and user in page["readers"]]
            return httpx.Response(200, json={"results": results, "size": len(results), "_links": {}})
        if path.startswith("/wiki/rest/api/content/"):
            page = self.pages.get(path.rsplit("/", 1)[1])
            if page is None or user not in page["readers"]:
                return httpx.Response(404)
            return httpx.Response(200, json={
                "id": path.rsplit("/", 1)[1], "type": "page", "status": "current",
                "space": {"key": page["space"]}, "title": page["title"],
                "version": {"number": page["version"], "when": stamp(page["when"])},
                # ``views`` renders the page differently per user, as macros or restricted
                # sections can on a real site.
                "body": {"storage": {"value": f"<p>{page.get('views', {}).get(user, page['body'])}</p>"}}})
        # Jira
        if path.startswith("/rest/api/3/project/"):
            key = path.rsplit("/", 1)[1]
            if user not in self.projects.get(key, set()):
                return httpx.Response(404)
            return httpx.Response(200, json={"key": key})
        if path == "/rest/api/3/search/jql":
            project = params["jql"].split("=")[1].split()[0]
            if user not in self.projects.get(project, set()):
                # Jira reports an unbrowsable project as an invalid JQL value.
                return httpx.Response(400, json={"errorMessages": ["The value does not exist"]})
            issues = [{"key": key, "fields": {"project": {"key": project}}}
                      for key, issue in sorted(self.issues.items())
                      if key.startswith(project + "-") and user in issue["readers"]]
            return httpx.Response(200, json={"issues": issues, "isLast": True})
        if path.startswith("/rest/api/3/issue/"):
            key = path.rsplit("/", 1)[1]
            issue = self.issues.get(key)
            if issue is None or user not in issue["readers"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"key": key, "fields": {
                "summary": issue["summary"], "description": None,
                "updated": stamp(issue["updated"]), "project": {"key": key.split("-")[0]},
                "status": {"name": issue["status"]}}})
        # Slack
        if path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user_id": ACCOUNTS[user]["slack"],
                                             "team_id": WORKSPACE, "url": "https://demo.slack.com/"})
        if path == "/api/conversations.list":
            channels = [{"id": cid, "is_im": False, "is_mpim": False,
                         "is_private": channel["private"], "is_member": user in channel["members"]}
                        for cid, channel in sorted(self.channels.items())
                        if not channel["private"] or user in channel["members"]]
            return httpx.Response(200, json={"ok": True, "channels": channels,
                                             "response_metadata": {"next_cursor": ""}})
        if path.startswith("/api/conversations."):
            channel = self.channels.get(params["channel"])
            if channel is None or (channel["private"] and user not in channel["members"]):
                return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
            if path == "/api/conversations.info":
                return httpx.Response(200, json={"ok": True, "channel": {
                    "id": params["channel"], "is_im": False, "is_mpim": False,
                    "is_private": channel["private"], "is_member": user in channel["members"]}})
            if path == "/api/conversations.history":
                messages = []
                for message in channel["messages"]:
                    entry = {"type": "message", "ts": message["ts"], "text": message["text"]}
                    if message.get("replies"):
                        entry.update(thread_ts=message["ts"], reply_count=len(message["replies"]))
                    messages.append(entry)
                return httpx.Response(200, json={"ok": True, "has_more": False, "messages": messages})
            if path == "/api/conversations.replies":
                root = next(m for m in channel["messages"] if m["ts"] == params["ts"])
                messages = [{"type": "message", "ts": root["ts"], "thread_ts": root["ts"],
                             "text": root["text"]}] + [
                    {"type": "message", "ts": reply["ts"], "thread_ts": root["ts"], "text": reply["text"]}
                    for reply in root.get("replies", [])]
                return httpx.Response(200, json={"ok": True, "has_more": False, "messages": messages})
        # Drive
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"permissionId": ACCOUNTS[user]["drive"]}})
        if path == "/drive/v3/files":
            folder = params["q"].split("'")[1]
            files = [{"id": fid, "mimeType": "text/markdown"} for fid, item in sorted(self.files.items())
                     if item["folder"] == folder and user in item["readers"]]
            return httpx.Response(200, json={"files": files})
        if path.startswith("/drive/v3/files/"):
            item = self.files.get(path.split("/")[4])
            if item is None or user not in item["readers"]:
                return httpx.Response(404)
            if params.get("alt") == "media":
                return httpx.Response(200, text=item["body"])
            return httpx.Response(200, json={
                "id": path.split("/")[4], "name": item["name"], "mimeType": "text/markdown",
                "parents": [item["folder"]], "trashed": False, "version": str(item["version"]),
                "modifiedTime": stamp(item["modified"])})
        return httpx.Response(500)
