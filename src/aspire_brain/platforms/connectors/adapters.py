"""Bounded requester-scoped platform reads; offline tests do not prove live compatibility.

Known IDs only: Confluence space key/page ID, Jira project key/issue key,
Slack workspace/channel ID (+ optional thread timestamp), Drive folder/file ID.
No discovery, refresh loop, credential acquisition, binary extraction, or writes.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from html.parser import HTMLParser
from itertools import groupby
from urllib.parse import urlsplit

from .core import (
    MAX_RESPONSE_BYTES,
    ConnectorDocument,
    ConnectorError,
    ConnectorSession,
    SourceRef,
    SourceUnavailable,
)

MAX_TEXT = 5000
MAX_PAGES = 10
MAX_MESSAGES = 100
logger = logging.getLogger(__name__)


def _safe_fetch(method):
    @wraps(method)
    def fetch(self, ref):
        if not isinstance(ref, SourceRef):
            raise ConnectorError("invalid_request")
        try:
            return method(self, ref)
        except ConnectorError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
            logger.warning("Malformed %s connector response: %s", self.session.platform, type(exc).__name__)
            raise ConnectorError("invalid_response") from None
    return fetch


def _text(value, *, empty=False, limit=MAX_TEXT):
    if not isinstance(value, str) or "\x00" in value:
        raise ConnectorError("invalid_response")
    if len(value) > limit:
        raise ConnectorError("content_too_large")
    if not empty and not value.strip():
        raise ConnectorError("invalid_response")
    return value


def _date(value):
    parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConnectorError("invalid_response")
    return parsed.astimezone(UTC)


def _id(value, pattern=r"[A-Za-z0-9_-]{1,128}"):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ConnectorError("invalid_request")
    return value


def _reference(session, ref, platform, source_pattern=None):
    if session.platform != platform or ref.platform != platform:
        raise ConnectorError("invalid_request")
    _id(ref.source_id, source_pattern or r"[A-Za-z0-9_-]{1,128}")
    _id(ref.parent_id)
    if ref.thread_id is not None:
        if platform != "slack":
            raise ConnectorError("invalid_request")
        _id(ref.thread_id, r"[0-9]{1,12}\.[0-9]{6}")


def _identity(actual, expected):
    if not isinstance(actual, str) or actual != expected:
        raise ConnectorError("identity_mismatch")


class _StorageLink:
    """Use only labels present in this page; never resolve a linked resource."""

    INLINE = frozenset({"b", "strong", "em", "i", "code", "tt", "sub", "sup", "br", "span"})
    BODIES = frozenset({"ac:link-body", "ac:plain-text-link-body"})

    def __init__(self):
        self.resource = None
        self.label = None
        self.body = None
        self.body_seen = False
        self.inline = []
        self.parts = []

    def start(self, tag, attrs):
        if self.body == "ac:link-body" and tag in self.INLINE:
            if tag == "br":
                self.parts.append("\n")
            else:
                self.inline.append(tag)
        elif tag in self.BODIES and not self.body_seen and self.resource is None:
            self.body = tag
            self.body_seen = True
        elif tag in {"ri:page", "ri:user"} and not self.body_seen and self.label is None:
            values = dict(attrs)
            if tag == "ri:page":
                label = values.get("ri:content-title")
            else:
                label = next((values[key] for key in ("ri:account-id", "ri:userkey", "ri:username")
                              if values.get(key)), None)
            if not isinstance(label, str) or not label.strip():
                raise ConnectorError("unsupported_content")
            self.label = _text(label) if tag == "ri:page" else "@" + _text(label)
            self.resource = tag
        else:
            raise ConnectorError("unsupported_content")

    def end(self, tag):
        if tag == "ac:link" and self.body is None and self.resource is None and not self.inline:
            label = "".join(self.parts) if self.body_seen else self.label
            if not isinstance(label, str) or not label.strip():
                raise ConnectorError("unsupported_content")
            return _text(label)
        if tag == self.resource:
            self.resource = None
        elif tag == self.body and not self.inline:
            self.body = None
        elif self.inline and tag == self.inline[-1]:
            self.inline.pop()
        elif tag != "br" or self.body != "ac:link-body":
            raise ConnectorError("unsupported_content")
        return None

    def data(self, data):
        if self.body is not None:
            self.parts.append(data)
        elif data.strip():
            raise ConnectorError("unsupported_content")

    def declaration(self, data):
        if self.body != "ac:plain-text-link-body" or not data.startswith("CDATA["):
            raise ConnectorError("unsupported_content")
        self.data(data[6:])


class _StorageText(HTMLParser):
    """Extract plain storage and a small set of visible macro bodies."""

    ALLOWED = frozenset("p br strong b em i u s code pre h1 h2 h3 h4 h5 h6 ul ol li table thead tbody tr th td a blockquote span div hr colgroup col".split())
    BLOCK = frozenset("p br pre h1 h2 h3 h4 h5 h6 li tr blockquote div hr".split())
    MACROS = frozenset({"info", "note", "tip", "warning", "code"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.macro = None
        self.macro_body = False
        self.macro_had_body = False
        self.plain_text_body = False
        self.preformatted = False
        self.title_parameter = False
        self.colgroup = False
        self.link = None
        self.skip_depth = 0

    def _append(self, data, *, preserve=None):
        if preserve is None:
            preserve = self.plain_text_body or self.preformatted
        self.parts.append((preserve, data))

    def render(self):
        blocks = []
        for preserve, parts in groupby(self.parts, key=lambda part: part[0]):
            value = "".join(data for _, data in parts)
            if not preserve:
                value = "\n".join(line.strip() for line in value.splitlines() if line.strip())
            if value:
                blocks.append(value)
        return "\n".join(blocks)

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            self.skip_depth += 1
            return
        if self.title_parameter:
            raise ConnectorError("unsupported_content")
        if self.colgroup and tag != "col":
            raise ConnectorError("unsupported_content")
        if self.link is not None:
            self.link.start(tag, attrs)
            return
        if self._start_macro(tag, attrs):
            return
        if self.plain_text_body or (self.macro is not None and not self.macro_body):
            raise ConnectorError("unsupported_content")
        if tag == "ac:link":
            self.link = _StorageLink()
            return
        if tag not in self.ALLOWED:
            raise ConnectorError("unsupported_content")
        if tag == "colgroup":
            self.colgroup = True
            return
        if tag == "col":
            if not self.colgroup:
                raise ConnectorError("unsupported_content")
            return
        if tag == "pre":
            if self.preformatted:
                raise ConnectorError("unsupported_content")
            self._append("\n", preserve=False)
            self.preformatted = True
            return
        if tag in self.BLOCK:
            self._append("\n")
        elif tag in {"td", "th"}:
            self._append(" | ")

    def _start_macro(self, tag, attrs):
        if tag == "ac:structured-macro":
            name = dict(attrs).get("ac:name")
            if self.macro is not None or name not in self.MACROS:
                raise ConnectorError("unsupported_content")
            self.macro = name
            self.macro_had_body = False
            self._append("\n")
            return True
        if tag == "ac:parameter" and self.macro is not None and not self.macro_had_body:
            if dict(attrs).get("ac:name") == "title":
                self.title_parameter = True
                self._append("\n")
            else:
                self.skip_depth = 1
            return True
        if tag in {"ac:rich-text-body", "ac:plain-text-body"} and self.macro is not None:
            if self.macro_body or (tag == "ac:plain-text-body") != (self.macro == "code"):
                raise ConnectorError("unsupported_content")
            self.macro_body = True
            self.macro_had_body = True
            self._append("\n", preserve=False)
            self.plain_text_body = tag == "ac:plain-text-body"
            return True
        return False

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if self.colgroup and tag not in {"col", "colgroup"}:
            raise ConnectorError("unsupported_content")
        if self.link is not None:
            label = self.link.end(tag)
            if label is not None:
                self._append(label)
                self.link = None
            return
        if self._end_macro(tag):
            return
        if tag not in self.ALLOWED or self.plain_text_body:
            raise ConnectorError("unsupported_content")
        if self.colgroup:
            if tag == "colgroup":
                self.colgroup = False
            elif tag != "col":
                raise ConnectorError("unsupported_content")
            return
        if tag in {"colgroup", "col"}:
            raise ConnectorError("unsupported_content")
        if tag == "pre":
            if not self.preformatted:
                raise ConnectorError("invalid_response")
            self.preformatted = False
            self._append("\n", preserve=False)
            return
        if tag in self.BLOCK:
            self._append("\n")

    def _end_macro(self, tag):
        if self.title_parameter:
            if tag != "ac:parameter":
                raise ConnectorError("unsupported_content")
            self.title_parameter = False
            self._append("\n")
            return True
        if tag == "ac:structured-macro" and self.macro is not None:
            if self.macro_body or not self.macro_had_body:
                raise ConnectorError("unsupported_content")
            self.macro = None
            self._append("\n")
            return True
        if tag in {"ac:rich-text-body", "ac:plain-text-body"} and self.macro_body:
            if self.preformatted:
                raise ConnectorError("invalid_response")
            if (tag == "ac:plain-text-body") != self.plain_text_body:
                raise ConnectorError("unsupported_content")
            self.macro_body = False
            self.plain_text_body = False
            self._append("\n", preserve=False)
            return True
        return False

    def handle_data(self, data):
        if not self.skip_depth:
            if self.link is not None:
                self.link.data(data)
                return
            if self.colgroup:
                if data.strip():
                    raise ConnectorError("unsupported_content")
                return
            if self.macro is not None and not self.macro_body and not self.title_parameter and data.strip():
                raise ConnectorError("unsupported_content")
            self._append(data)

    def unknown_decl(self, data):
        if self.skip_depth:
            return
        if self.link is not None:
            self.link.declaration(data)
        elif (self.plain_text_body or self.title_parameter) and data.startswith("CDATA["):
            self._append(data[6:])
        else:
            raise ConnectorError("unsupported_content")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.handle_starttag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)


def _storage(value):
    parser = _StorageText()
    parser.feed(_text(value, limit=MAX_RESPONSE_BYTES))
    parser.close()
    if (parser.macro is not None or parser.skip_depth or parser.preformatted or parser.title_parameter
            or parser.colgroup or parser.link is not None):
        raise ConnectorError("invalid_response")
    return parser.render()


def _adf(node, depth=0):
    if depth > 20 or not isinstance(node, dict):
        raise ConnectorError("invalid_response")
    kind = node.get("type")
    if kind == "text":
        return _text(node["text"], empty=True)
    if kind == "hardBreak":
        return "\n"
    if kind not in {"doc", "paragraph", "heading", "bulletList", "orderedList", "listItem",
                    "blockquote", "codeBlock", "table", "tableRow", "tableCell", "tableHeader"}:
        raise ConnectorError("unsupported_content")
    content = node.get("content", [])
    if not isinstance(content, list) or len(content) > 1000:
        raise ConnectorError("invalid_response")
    result = "".join(_adf(child, depth + 1) for child in content)
    return result + ("\n" if kind in {"paragraph", "heading", "listItem", "codeBlock", "tableRow"} else "")


class ConfluenceConnector:
    def __init__(self, session: ConnectorSession):
        self.session = session

    @_safe_fetch
    def fetch(self, ref: SourceRef) -> tuple[ConnectorDocument, ...]:
        session = self.session
        _reference(session, ref, "confluence", r"[0-9]{1,30}")
        _identity(session.get_json("/wiki/rest/api/user/current")["accountId"], session.binding.account_id)
        data = session.get_json(f"/wiki/rest/api/content/{ref.source_id}",
                                params={"expand": "body.storage,version,space"})
        if (data["id"] != ref.source_id or data["space"]["key"] != ref.parent_id
                or data["type"] != "page" or data["status"] != "current"):
            raise SourceUnavailable()
        version = data["version"]["number"]
        if type(version) is not int or version < 1:
            raise ConnectorError("invalid_response")
        body = _text(_text(data["title"]) + "\n" + _storage(data["body"]["storage"]["value"]))
        return (ConnectorDocument(
            platform="confluence", source_id=ref.source_id, source_kind="space_page", version_id=str(version),
            text=body, locator=f"{session.base_url}/wiki/spaces/{ref.parent_id}/pages/{ref.source_id}",
            parent_id=ref.parent_id, source_updated_at=_date(data["version"]["when"]), mode=session.mode),)


class JiraConnector:
    def __init__(self, session: ConnectorSession):
        self.session = session

    @_safe_fetch
    def fetch(self, ref: SourceRef) -> tuple[ConnectorDocument, ...]:
        session = self.session
        _reference(session, ref, "jira", r"[A-Z][A-Z0-9_]*-[0-9]+")
        _identity(session.get_json("/rest/api/3/myself")["accountId"], session.binding.account_id)
        data = session.get_json(f"/rest/api/3/issue/{ref.source_id}",
                                params={"fields": "summary,description,updated,project,status"})
        fields = data["fields"]
        if data["key"] != ref.source_id or fields["project"]["key"] != ref.parent_id:
            raise SourceUnavailable()
        description = fields.get("description")
        if description is not None and (description.get("type") != "doc" or description.get("version") != 1):
            raise ConnectorError("invalid_response")
        text = _text(_text(fields["summary"]) + "\nStatus: " + _text(fields["status"]["name"])
                     + "\n" + (_adf(description) if description is not None else ""))
        updated = _date(fields["updated"])
        return (ConnectorDocument(
            platform="jira", source_id=ref.source_id, source_kind="issue", version_id=updated.isoformat().replace("+00:00", "Z"),
            text=text, locator=f"{session.base_url}/browse/{ref.source_id}", parent_id=ref.parent_id,
            source_updated_at=updated, mode=session.mode),)


def _slack_ok(data):
    if data.get("ok") is not True:
        error = data.get("error")
        if error in {"channel_not_found", "not_in_channel", "thread_not_found", "access_denied"}:
            raise SourceUnavailable()
        categories = {
            "invalid_auth": "expired_access", "not_authed": "expired_access",
            "token_revoked": "expired_access", "token_expired": "expired_access",
            "account_inactive": "expired_access", "ratelimited": "rate_limited",
            "internal_error": "upstream_unavailable", "fatal_error": "upstream_unavailable",
        }
        raise ConnectorError(categories.get(error, "invalid_response"))
    return data


def _slack_date(value):
    _id(value, r"[0-9]{1,12}\.[0-9]{6}")
    return datetime.fromtimestamp(float(Decimal(value)), tz=UTC)


class SlackConnector:
    def __init__(self, session: ConnectorSession, *, page_size: int = 15):
        if type(page_size) is not int or not 1 <= page_size <= MAX_MESSAGES:
            raise ConnectorError("invalid_configuration")
        self.session = session
        self.page_size = page_size

    def _authorize(self, ref):
        session = self.session
        identity = _slack_ok(session.post_json("/api/auth.test"))
        _identity(identity.get("user_id"), session.binding.account_id)
        _identity(identity.get("team_id"), session.binding.workspace_id)
        if identity.get("bot_id") or ref.parent_id != session.binding.workspace_id:
            raise ConnectorError("identity_mismatch")
        workspace_url = urlsplit(identity["url"])
        if (workspace_url.scheme != "https" or not workspace_url.hostname
                or not re.fullmatch(r"(?:[a-z0-9-]+\.)+slack\.com", workspace_url.hostname)
                or workspace_url.port not in (None, 443) or workspace_url.username
                or workspace_url.password or workspace_url.path not in ("", "/")
                or workspace_url.query or workspace_url.fragment):
            raise ConnectorError("invalid_response")
        channel = _slack_ok(session.get_json("/api/conversations.info",
                                            params={"channel": ref.source_id}))["channel"]
        if (channel["id"] != ref.source_id or channel.get("is_im") is not False
                or channel.get("is_mpim") is not False):
            raise SourceUnavailable()
        if type(channel.get("is_private")) is not bool:
            raise ConnectorError("invalid_response")
        if channel["is_private"] and channel.get("is_member") is not True:
            raise SourceUnavailable()
        return f"https://{workspace_url.hostname}"

    @_safe_fetch
    def fetch(self, ref: SourceRef) -> tuple[ConnectorDocument, ...]:
        _reference(self.session, ref, "slack", r"[CG][A-Z0-9]{1,127}")
        workspace_url = self._authorize(ref)
        method = "conversations.replies" if ref.thread_id else "conversations.history"
        params = {"channel": ref.source_id, "limit": str(self.page_size)}
        if ref.thread_id:
            params = {**params, "ts": ref.thread_id}
        documents, seen_cursors, seen_messages, total_messages, skipped_events = [], set(), set(), 0, 0
        for _ in range(MAX_PAGES):
            data = _slack_ok(self.session.get_json(f"/api/{method}", params=params))
            messages = data["messages"]
            if not isinstance(messages, list) or total_messages + len(messages) > MAX_MESSAGES:
                raise ConnectorError("incomplete_response")
            total_messages += len(messages)
            for message in messages:
                if not isinstance(message, dict):
                    raise ConnectorError("invalid_response")
                if message.get("subtype") in {"channel_join", "channel_leave"}:
                    if ref.thread_id or message.get("type") != "message":
                        raise ConnectorError("invalid_response")
                    _slack_date(message["ts"])
                    if "channel" in message and message["channel"] != ref.source_id:
                        raise SourceUnavailable()
                    skipped_events += 1
                    continue
                document = self._message(ref, message, workspace_url)
                if document.source_id in seen_messages:
                    raise ConnectorError("incomplete_response")
                seen_messages.add(document.source_id)
                documents.append(document)
            more = data.get("has_more")
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if type(more) is not bool or not isinstance(cursor, str):
                raise ConnectorError("invalid_response")
            if not more and not cursor:
                if skipped_events:
                    logger.info("Skipped %d Slack membership events", skipped_events)
                return tuple(documents)
            if not cursor or cursor in seen_cursors or len(cursor) > 1024:
                raise ConnectorError("incomplete_response")
            seen_cursors.add(cursor)
            params = {**params, "cursor": cursor}
        raise ConnectorError("incomplete_response")

    def _message(self, ref, message, workspace_url):
        if message.get("type") != "message" or message.get("subtype") not in {None, "bot_message", "thread_broadcast"}:
            raise ConnectorError("unsupported_content")
        ts = message["ts"]
        event = _slack_date(ts)
        if "channel" in message and message["channel"] != ref.source_id:
            raise SourceUnavailable()
        thread = message.get("thread_ts")
        if thread is not None:
            _slack_date(thread)
        if ref.thread_id and ts != ref.thread_id and thread != ref.thread_id:
            raise ConnectorError("invalid_response")
        if message.get("files") or message.get("attachments"):
            raise ConnectorError("unsupported_content")
        if "text" not in message and message.get("blocks"):
            raise ConnectorError("unsupported_content")
        text = message["text"]
        if isinstance(text, str) and not text.strip() and message.get("blocks"):
            raise ConnectorError("unsupported_content")
        edited = message.get("edited", {}).get("ts", ts)
        updated = _slack_date(edited)
        if updated < event:
            raise ConnectorError("invalid_response")
        thread = thread or ref.thread_id
        thread_query = f"?thread_ts={thread}&cid={ref.source_id}" if thread and thread != ts else ""
        return ConnectorDocument(
            platform="slack", source_id=f"{ref.source_id}:{ts}", source_kind="thread_message" if thread or ref.thread_id else "channel_message",
            version_id=edited, text=_text(text),
            locator=f"{workspace_url}/archives/{ref.source_id}/p{ts.replace('.', '')}{thread_query}",
            parent_id=ref.source_id, source_updated_at=updated, event_at=event,
            thread_id=thread, mode=self.session.mode)


class DriveConnector:
    FIELDS = "id,name,mimeType,parents,trashed,version,modifiedTime"
    TEXT_MIMES = frozenset({"text/plain", "text/csv", "text/markdown"})
    DOC_MIME = "application/vnd.google-apps.document"

    def __init__(self, session: ConnectorSession):
        self.session = session

    def _metadata(self, ref):
        data = self.session.get_json(f"/drive/v3/files/{ref.source_id}",
                                    params={"fields": self.FIELDS, "supportsAllDrives": "true"})
        if (data["id"] != ref.source_id or data.get("trashed") is not False
                or not isinstance(data.get("parents"), list) or ref.parent_id not in data["parents"]):
            raise SourceUnavailable()
        _id(data["version"], r"[0-9]{1,30}")
        _date(data["modifiedTime"])
        _text(data["name"])
        return data

    @_safe_fetch
    def fetch(self, ref: SourceRef) -> tuple[ConnectorDocument, ...]:
        _reference(self.session, ref, "drive")
        identity = self.session.get_json("/drive/v3/about", params={"fields": "user(permissionId)"})
        _identity(identity["user"]["permissionId"], self.session.binding.account_id)
        before = self._metadata(ref)
        path = f"/drive/v3/files/{ref.source_id}"
        if before["mimeType"] == self.DOC_MIME:
            text = self.session.get_text(path + "/export", params={"mimeType": "text/plain"})
        elif before["mimeType"] in self.TEXT_MIMES:
            text = self.session.get_text(path, params={"alt": "media", "supportsAllDrives": "true"})
        else:
            raise ConnectorError("unsupported_content")
        after = self._metadata(ref)
        if any(before.get(key) != after.get(key) for key in self.FIELDS.split(",")):
            raise ConnectorError("source_changed")
        return (ConnectorDocument(
            platform="drive", source_id=ref.source_id, source_kind="folder_file", version_id=before["version"],
            text=_text(before["name"] + "\n" + _text(text).removeprefix("\ufeff")),
            locator=f"https://drive.google.com/file/d/{ref.source_id}/view", parent_id=ref.parent_id,
            source_updated_at=_date(before["modifiedTime"]), mode=self.session.mode),)
