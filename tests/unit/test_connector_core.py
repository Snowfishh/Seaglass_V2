"""Read-only connector transport contracts, exercised without network or credentials."""

import secrets
import socket
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import httpx
import pytest

from aspire_brain.platforms.connectors.core import (
    ConnectorDocument,
    ConnectorError,
    ConnectorSession,
    IdentityBinding,
    SourceRef,
    SourceUnavailable,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline connector test attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def session(handler, **overrides):
    options = dict(platform="slack", base_url="https://slack.com",
                   binding=IdentityBinding("demo", "user-a", "U123", "T123"),
                   credential=secrets.token_urlsafe(24), transport=httpx.MockTransport(handler))
    return ConnectorSession(**(options | overrides))


def test_default_refuses_live_transport_before_client_creation():
    with pytest.raises(ConnectorError, match="network_disabled"):
        ConnectorSession(platform="slack", base_url="https://slack.com",
                         binding=IdentityBinding("demo", "user-a", "U123", "T123"),
                         credential=secrets.token_urlsafe(24))


def test_mock_request_is_get_bound_to_origin_and_has_no_proxy_or_redirect():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    with session(handler) as client:
        assert client.mode == "offline_mock"
        assert client.get_json("/api/auth.test") == {"ok": True}
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.host == "slack.com"
    assert seen[0].headers["authorization"].startswith("Bearer ")


@pytest.mark.parametrize("url", ["http://slack.com", "https://evil.example", "https://slack.com.evil.example",
                                      "https://x@slack.com", "https://slack.com:8443", "https://slack.com/path"])
def test_invalid_destination_is_rejected(url):
    with pytest.raises(ConnectorError, match="invalid_configuration"):
        session(lambda request: httpx.Response(200), base_url=url)


@pytest.mark.parametrize("path", ["https://evil.example/api/x", "//evil.example/api/x", "/other",
                                       "/api/../secret", "/api/%2e%2e/secret", "/api/auth.test?token=x"])
def test_paths_cannot_escape_the_api_boundary(path):
    with session(lambda request: pytest.fail("No request expected")) as client:
        with pytest.raises(ConnectorError, match="invalid_request"):
            client.get_json(path)


@pytest.mark.parametrize("status,code", [(301, "invalid_response"), (401, "expired_access"),
                                         (403, "unavailable"), (404, "unavailable"),
                                         (429, "rate_limited"), (500, "upstream_unavailable")])
def test_http_failure_is_sanitized_and_never_retried(status, code):
    calls = []
    marker = secrets.token_urlsafe(24)
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=marker, headers={"Location": "https://evil.example"})
    with session(handler) as client:
        with pytest.raises(ConnectorError) as error:
            client.get_json("/api/auth.test")
    assert error.value.code == code
    assert marker not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"[]", b"null", b"not JSON", b'"text"'])
def test_invalid_json_envelope_fails_closed(body):
    with session(lambda request: httpx.Response(200, content=body)) as client:
        with pytest.raises(ConnectorError, match="invalid_response"):
            client.get_json("/api/auth.test")


def test_response_size_is_bounded_before_parsing():
    with session(lambda request: httpx.Response(200, content=b"x" * 1_048_577)) as client:
        with pytest.raises(ConnectorError, match="response_too_large"):
            client.get_text("/api/auth.test")


def test_timeout_does_not_expose_exception_or_retry():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private exception text")
    with session(handler) as client:
        with pytest.raises(ConnectorError, match="timeout") as error:
            client.get_json("/api/auth.test")
    assert "private" not in str(error.value)
    assert len(calls) == 1


def test_network_errors_are_sanitized():
    def handler(request):
        raise httpx.ConnectError("private exception text")
    with session(handler) as client:
        with pytest.raises(ConnectorError, match="upstream_unavailable"):
            client.get_json("/api/auth.test")


def test_atlassian_basic_auth_is_explicit():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"accountId": "A123"})
    with session(handler, platform="jira", base_url="https://demo.atlassian.net",
                 auth_user="demo@example.invalid") as client:
        client.get_json("/rest/api/3/myself")
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_document_and_binding_are_immutable_and_hash_original_text():
    import hashlib
    document = ConnectorDocument("jira", "OPS-1", "issue", "v1", "Payment is held.",
                                 "https://demo.atlassian.net/browse/OPS-1", "OPS",
                                 datetime(2026, 10, 12, tzinfo=UTC))
    assert document.content_sha256 == hashlib.sha256(b"Payment is held.").hexdigest()
    with pytest.raises(FrozenInstanceError):
        document.text = "Payment released."
    with pytest.raises(ConnectorError):
        IdentityBinding("", "user-a", "U123")
    with pytest.raises(ConnectorError):
        SourceRef("jira", "../private", "OPS")
    assert str(SourceUnavailable()) == "Connector request failed: unavailable"


def test_naive_dates_and_unsupported_platforms_are_rejected():
    with pytest.raises(ConnectorError):
        ConnectorDocument("jira", "OPS-1", "issue", "v1", "Payment is held.",
                          "https://demo.atlassian.net/browse/OPS-1", "OPS", datetime(2026, 10, 12))
    with pytest.raises(ConnectorError):
        SourceRef("other", "one", "two")


@pytest.mark.parametrize("path", ["/api/chat.postMessage", "/api/chat.delete", "/api/conversations.archive"])
def test_read_transport_rejects_slack_mutations_even_via_get(path):
    with session(lambda request: pytest.fail("No request expected")) as client:
        with pytest.raises(ConnectorError, match="invalid_request"):
            client.get_json(path)
