"""Bounded, explicitly activated HTTP reads with no implicit credential discovery.

An injected MockTransport is the offline path. A network transport requires explicit
allow_live=True, caller-supplied credentials, and a server-owned identity binding.
Neither mode supplies a live provider or changes the default application configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlsplit

import httpx

PLATFORMS = frozenset({"confluence", "jira", "slack", "drive"})
MAX_RESPONSE_BYTES = 1_048_576
MAX_DOCUMENT_CHARS = 5000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,199}\Z")
_PREFIXES = {"confluence": ("/wiki/api/v2/", "/wiki/rest/api/"),
             "jira": ("/rest/api/3/",), "slack": ("/api/",), "drive": ("/drive/v3/",)}
#: Every path a connector may read. The list endpoints (Confluence content in a space, Jira
#: search, Slack conversations.list, Drive files in a folder) let a sync discover what each
#: user can see instead of relying on known item IDs.
_READ_PATHS = {
    "confluence": r"/wiki/rest/api/(?:user/current|content|content/[0-9]{1,30})",
    "jira": r"/rest/api/3/(?:myself|search/jql|project/[A-Z][A-Z0-9_]{0,63}|issue/[A-Z][A-Z0-9_]*-[0-9]+)",
    "slack": r"/api/(?:auth\.test|conversations\.(?:info|history|replies|list))",
    "drive": r"/drive/v3/(?:about|files|files/[A-Za-z0-9_-]{1,128}(?:/export)?)",
}


#: ``time.monotonic()`` value after which no connector request may start or keep reading.
_DEADLINE: ContextVar[float | None] = ContextVar("connector_deadline", default=None)


@contextmanager
def request_deadline(seconds: float):
    """Bound every connector request made in this context to ``seconds`` from now in total.

    Each request's timeout is cut to the time left, and a response still arriving at the
    deadline is abandoned as ``timeout``.
    """
    token = _DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def _time_left(deadline):
    if deadline is None:
        return None
    left = deadline - time.monotonic()
    if left <= 0:
        raise ConnectorError("timeout")
    return left


class ConnectorError(Exception):
    """Only a fixed category may cross the connector boundary; never vendor text."""

    CODES = frozenset({"network_disabled", "invalid_configuration", "invalid_request",
                       "invalid_response", "response_too_large", "content_too_large", "expired_access",
                       "unavailable", "rate_limited", "upstream_unavailable", "timeout",
                       "identity_mismatch", "pagination_limit", "unsupported_content",
                       "source_changed", "incomplete_response"})

    def __init__(self, code):
        self.code = code if code in self.CODES else "invalid_response"
        super().__init__(f"Connector request failed: {self.code}")


class SourceUnavailable(ConnectorError):
    """A missing and a forbidden resource have the same outward error."""

    def __init__(self):
        super().__init__("unavailable")


def _identifier(value):
    return isinstance(value, str) and _ID.fullmatch(value) and ".." not in value


@dataclass(frozen=True, slots=True)
class IdentityBinding:
    tenant_id: str
    principal_id: str
    account_id: str
    workspace_id: str = ""

    def __post_init__(self):
        if not all(_identifier(value) for value in
                   (self.tenant_id, self.principal_id, self.account_id)):
            raise ConnectorError("invalid_configuration")
        if self.workspace_id and not _identifier(self.workspace_id):
            raise ConnectorError("invalid_configuration")


@dataclass(frozen=True, slots=True)
class SourceRef:
    platform: str
    source_id: str
    parent_id: str
    thread_id: str | None = None

    def __post_init__(self):
        if self.platform not in PLATFORMS or not all(
            _identifier(value) for value in (self.source_id, self.parent_id)
        ) or (self.thread_id is not None and not _identifier(self.thread_id)):
            raise ConnectorError("invalid_request")


@dataclass(frozen=True, slots=True)
class ConnectorDocument:
    platform: str
    source_id: str
    source_kind: str
    version_id: str
    text: str
    locator: str
    parent_id: str
    source_updated_at: datetime
    event_at: datetime | None = None
    thread_id: str | None = None
    mode: str = "offline_mock"

    def __post_init__(self):
        SourceRef(self.platform, self.source_id, self.parent_id, self.thread_id)
        kinds = {"confluence": {"space_page", "space_page_restricted"}, "jira": {"issue"},
                 "slack": {"channel_message", "thread_message"},
                 "drive": {"folder_file", "folder_file_restricted"}}
        if (self.source_kind not in kinds[self.platform] or self.mode not in {"offline_mock", "live"}
                or not isinstance(self.version_id, str) or not self.version_id
                or len(self.version_id) > 300 or not isinstance(self.text, str)
                or not self.text.strip() or "\x00" in self.text):
            raise ConnectorError("invalid_response")
        if len(self.text) > MAX_DOCUMENT_CHARS:
            raise ConnectorError("content_too_large")
        timestamps = (self.source_updated_at,) + (() if self.event_at is None else (self.event_at,))
        for timestamp in timestamps:
            if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
                raise ConnectorError("invalid_response")
        parts = urlsplit(self.locator)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ConnectorError("invalid_response")
        if (self.source_kind == "thread_message") != (self.thread_id is not None):
            raise ConnectorError("invalid_response")

    @property
    def content_sha256(self):
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _origin(platform, base_url):
    try:
        parts = urlsplit(base_url)
        valid = (parts.scheme == "https" and parts.port in (None, 443)
                 and not parts.username and not parts.password
                 and parts.path in ("", "/") and not parts.query and not parts.fragment)
        host = parts.hostname or ""
        if platform in {"jira", "confluence"}:
            valid = valid and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.atlassian\.net", host))
        else:
            valid = valid and host == {"slack": "slack.com", "drive": "www.googleapis.com"}[platform]
        if not valid:
            raise ValueError
        return f"https://{host}"
    except (ValueError, TypeError, KeyError):
        raise ConnectorError("invalid_configuration") from None


class ConnectorSession:
    """One caller identity and origin, one attempt per request, no redirect/proxy discovery.

    Slack auth.test is an identity-only POST with no body. All resource operations are GET.
    Server-side setup must bind the credential to the app principal; request JSON must not
    choose this binding. Identity is checked by the adapters again on every fetch.
    """

    def __init__(self, *, platform, base_url, binding, credential, auth_user=None,
                 transport=None, allow_live=False, timeout_seconds=10.0):
        if platform not in PLATFORMS or not isinstance(binding, IdentityBinding):
            raise ConnectorError("invalid_configuration")
        origin = _origin(platform, base_url)
        if (not isinstance(credential, str) or not credential or len(credential) > 8192
                or any(char.isspace() for char in credential)
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise ConnectorError("invalid_configuration")
        if type(allow_live) is not bool:
            raise ConnectorError("invalid_configuration")
        if transport is None and not allow_live:
            raise ConnectorError("network_disabled")
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ConnectorError("invalid_configuration")
        headers = {"Accept": "application/json"}
        auth = None
        if platform in {"jira", "confluence"}:
            if (not isinstance(auth_user, str) or not auth_user or ":" in auth_user
                    or any(char.isspace() for char in auth_user)):
                raise ConnectorError("invalid_configuration")
            auth = httpx.BasicAuth(auth_user, credential)
        else:
            if auth_user is not None:
                raise ConnectorError("invalid_configuration")
            headers["Authorization"] = f"Bearer {credential}"
        self._platform, self._binding, self._base_url = platform, binding, origin
        self._mode = "offline_mock" if transport is not None else "live"
        self._client = httpx.Client(base_url=origin, auth=auth, headers=headers,
                                    timeout=timeout_seconds, follow_redirects=False,
                                    trust_env=False, transport=transport or
                                    httpx.HTTPTransport(retries=0, trust_env=False))

    @property
    def platform(self):
        return self._platform

    @property
    def binding(self):
        return self._binding

    @property
    def base_url(self):
        return self._base_url

    @property
    def mode(self):
        return self._mode

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _body(self, path, params=None, *, method="GET"):
        if not isinstance(path, str) or not path.startswith(_PREFIXES[self.platform]):
            raise ConnectorError("invalid_request")
        decoded = unquote(path)
        if (any(char in decoded for char in ("?", "#", "\\", "\r", "\n"))
                or any(part in {".", ".."} for part in decoded.split("/"))
                or "%" in decoded):
            raise ConnectorError("invalid_request")
        if method == "POST" and (self.platform != "slack" or path != "/api/auth.test" or params):
            raise ConnectorError("invalid_request")
        if method not in {"GET", "POST"} or not re.fullmatch(_READ_PATHS[self.platform], path):
            raise ConnectorError("invalid_request")
        deadline = _DEADLINE.get()
        left = _time_left(deadline)
        options = {} if left is None else {"timeout": min(left, self._client.timeout.read or left)}
        try:
            with self._client.stream(method, path, params=params, **options) as response:
                status = response.status_code
                if status in (403, 404):
                    raise SourceUnavailable()
                if status != 200:
                    code = {401: "expired_access", 429: "rate_limited"}.get(
                        status, "upstream_unavailable" if status >= 500 else "invalid_response")
                    raise ConnectorError(code)
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    _time_left(deadline)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ConnectorError("response_too_large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException:
            raise ConnectorError("timeout") from None
        except httpx.HTTPError:
            raise ConnectorError("upstream_unavailable") from None

    def _json(self, path, params=None, *, method="GET"):
        raw = self._body(path, params, method=method)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ConnectorError("invalid_response") from None
        if not isinstance(data, dict):
            raise ConnectorError("invalid_response")
        return data

    def get_json(self, path, params=None):
        return self._json(path, params)

    def post_json(self, path):
        return self._json(path, method="POST")

    def get_text(self, path, params=None):
        try:
            return self._body(path, params).decode("utf-8")
        except UnicodeError:
            raise ConnectorError("invalid_response") from None
