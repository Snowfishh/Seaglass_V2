"""Offline adapter contract tests; no account, credential or network use."""
import secrets
import socket
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from aspire_brain.platforms.connectors import connector_for
from aspire_brain.platforms.connectors.adapters import (
    ConfluenceConnector,
    DriveConnector,
    JiraConnector,
    SlackConnector,
)
from aspire_brain.platforms.connectors.core import (
    ConnectorError,
    ConnectorSession,
    IdentityBinding,
    SourceRef,
)

STAMP = "2026-10-12T01:30:00Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline adapter test attempted network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


class Session:
    mode = "offline_mock"
    base_url = "https://example.invalid"

    def __init__(self, platform, responses):
        self.platform = platform
        self.binding = SimpleNamespace(account_id="user-a", workspace_id="TDEMO")
        self.responses = responses
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        response = self.responses[path]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    post_json = get_json
    get_text = get_json


def confluence():
    return Session("confluence", {
        "/wiki/rest/api/user/current": {"accountId": "user-a"},
        "/wiki/rest/api/content/123": {
            "id": "123", "type": "page", "status": "current", "title": "Runbook",
            "space": {"key": "DEMO"}, "version": {"number": 2, "when": STAMP},
            "body": {"storage": {"value": "<p>Escalate after <strong>15 minutes</strong>.</p>"}},
        },
    })


def jira():
    return Session("jira", {
        "/rest/api/3/myself": {"accountId": "user-a"},
        "/rest/api/3/issue/DEMO-1": {"key": "DEMO-1", "fields": {
            "summary": "Investigate delayed status", "updated": STAMP,
            "project": {"key": "DEMO"}, "status": {"name": "In progress"},
            "description": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "No confirmed loss."}]}
            ]},
        }},
    })


def slack(pages=None):
    return Session("slack", {
        "/api/auth.test": {"ok": True, "user_id": "user-a", "team_id": "TDEMO",
                           "url": "https://fixture.slack.com/"},
        "/api/conversations.info": {"ok": True, "channel": {
            "id": "CDEMO", "is_private": True, "is_member": True, "is_im": False,
            "is_mpim": False}},
        "/api/conversations.history": pages or {"ok": True, "messages": [
            {"type": "message", "ts": "1791768600.000001", "text": "Partner status pending."}
        ], "has_more": False},
    })


def drive():
    meta = {"id": "file1", "name": "Reconciliation", "mimeType": "text/csv",
            "parents": ["folder1"], "trashed": False, "version": "4", "modifiedTime": STAMP}
    return Session("drive", {
        "/drive/v3/about": {"user": {"permissionId": "user-a"}},
        "/drive/v3/files/file1": [meta, "payment_id,status\nDEMO-01,pending", meta],
    })


CASES = [(ConfluenceConnector, confluence, SourceRef("confluence", "123", "DEMO")),
         (JiraConnector, jira, SourceRef("jira", "DEMO-1", "DEMO")),
         (SlackConnector, slack, SourceRef("slack", "CDEMO", "TDEMO")),
         (DriveConnector, drive, SourceRef("drive", "file1", "folder1"))]


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_real_session_registry_and_adapter_roundtrip_with_mock_http(cls, factory, ref):
    scripted = factory()
    def handler(request):
        assert request.method == ("POST" if request.url.path == "/api/auth.test" else "GET")
        data = scripted.get_json(request.url.path, dict(request.url.params))
        return httpx.Response(200, text=data) if isinstance(data, str) else httpx.Response(200, json=data)
    origin = {"slack": "https://slack.com", "drive": "https://www.googleapis.com"}.get(
        ref.platform, "https://fixture.atlassian.net")
    with ConnectorSession(platform=ref.platform, base_url=origin,
                          binding=IdentityBinding("fixture", "user-a", "user-a", "TDEMO"),
                          credential=secrets.token_urlsafe(24),
                          auth_user="demo@example.invalid" if ref.platform in {"jira", "confluence"} else None,
                          transport=httpx.MockTransport(handler)) as session:
        adapter = connector_for(session)
        assert isinstance(adapter, cls)
        document, = adapter.fetch(ref)
        assert document.mode == "offline_mock"
        assert document.platform == ref.platform
        assert document.text


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_fetch_returns_dated_offline_evidence(cls, factory, ref):
    docs = cls(factory()).fetch(ref)
    assert len(docs) == 1
    assert docs[0].text
    assert docs[0].platform == ref.platform
    assert docs[0].source_updated_at.utcoffset() is not None
    assert docs[0].mode == "offline_mock"
    assert len(docs[0].content_sha256) == 64


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_wrong_identity_stops_before_content(cls, factory, ref):
    session = factory()
    session.binding.account_id = "other-user"
    with pytest.raises(ConnectorError, match="identity_mismatch"):
        cls(session).fetch(ref)
    assert len(session.calls) == 1


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_wrong_parent_fails_closed(cls, factory, ref):
    with pytest.raises(ConnectorError):
        cls(factory()).fetch(SourceRef(ref.platform, ref.source_id, "OTHER"))


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_reference_injection_rejected_before_network(cls, factory, ref):
    session = factory()
    with pytest.raises((ConnectorError, ValueError)):
        cls(session).fetch(SourceRef(ref.platform, "../other?token=secret", ref.parent_id))
    assert session.calls == []


def test_confluence_normalizes_html_without_concatenating_words():
    doc, = ConfluenceConnector(confluence()).fetch(CASES[0][2])
    assert "Escalate after 15 minutes." in doc.text
    assert "<" not in doc.text


@pytest.mark.parametrize("change", [
    {"version": {"number": 2, "when": "2026-10-12T01:30:00"}},
    {"status": "trashed"}, {"type": "attachment"},
    {"body": {"storage": {"value": "<ac:structured-macro>Hidden</ac:structured-macro>"}}},
])
def test_confluence_rejects_unsupported_or_malformed_page(change):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"].update(change)
    with pytest.raises(ConnectorError):
        ConfluenceConnector(session).fetch(CASES[0][2])


def test_jira_preserves_summary_status_and_description():
    doc, = JiraConnector(jira()).fetch(CASES[1][2])
    assert "Investigate delayed status" in doc.text
    assert "In progress" in doc.text
    assert "No confirmed loss." in doc.text


def test_jira_rejects_unknown_adf_node_instead_of_partial_content():
    session = jira()
    session.responses["/rest/api/3/issue/DEMO-1"]["fields"]["description"]["content"] = [
        {"type": "media", "attrs": {"id": "secret"}}]
    with pytest.raises(ConnectorError, match="unsupported_content"):
        JiraConnector(session).fetch(CASES[1][2])


@pytest.mark.parametrize("change", [{"bot_id": "B123"}, {"team_id": "TOTHER"}, {"ok": False}])
def test_slack_rejects_bot_wrong_workspace_and_api_error(change):
    session = slack()
    session.responses["/api/auth.test"].update(change)
    with pytest.raises(ConnectorError):
        SlackConnector(session).fetch(CASES[2][2])
    assert len(session.calls) == 1


def test_slack_private_nonmember_cannot_read_history():
    session = slack()
    session.responses["/api/conversations.info"]["channel"]["is_member"] = False
    with pytest.raises(ConnectorError):
        SlackConnector(session).fetch(CASES[2][2])
    assert len(session.calls) == 2


def test_slack_pagination_collects_all_records_and_preserves_edit_time():
    pages = [{"ok": True, "messages": [{"type": "message", "ts": "1791768600.000001",
              "text": "One"}], "has_more": True, "response_metadata": {"next_cursor": "next"}},
             {"ok": True, "messages": [{"type": "message", "ts": "1791768601.000001",
              "text": "Two", "edited": {"ts": "1791768700.000001"}}], "has_more": False}]
    session = slack(pages)
    docs = SlackConnector(session).fetch(CASES[2][2])
    assert len(docs) == 2
    assert docs[1].source_updated_at > docs[1].event_at
    assert session.calls[-1][1]["cursor"] == "next"


@pytest.mark.parametrize("pages", [
    [{"ok": True, "messages": [], "has_more": True}],
    [{"ok": True, "messages": [], "has_more": True,
      "response_metadata": {"next_cursor": "repeat"}}] * 3,
])
def test_slack_incomplete_or_looping_pagination_fails_closed(pages):
    with pytest.raises(ConnectorError, match="incomplete_response"):
        SlackConnector(slack(pages)).fetch(CASES[2][2])


def test_slack_specific_thread_rejects_unrelated_reply():
    session = slack()
    session.responses["/api/conversations.replies"] = {"ok": True, "has_more": False,
        "messages": [{"type": "message", "text": "Other", "ts": "1791768601.000001",
                      "thread_ts": "1791768602.000001"}]}
    with pytest.raises(ConnectorError):
        SlackConnector(session).fetch(SourceRef("slack", "CDEMO", "TDEMO", "1791768600.000001"))


def test_drive_google_doc_uses_text_export():
    session = drive()
    first, _, last = session.responses["/drive/v3/files/file1"]
    first["mimeType"] = last["mimeType"] = "application/vnd.google-apps.document"
    session.responses["/drive/v3/files/file1"] = [first, last]
    session.responses["/drive/v3/files/file1/export"] = "Fictional reconciliation result"
    doc, = DriveConnector(session).fetch(CASES[3][2])
    assert "Fictional reconciliation result" in doc.text
    assert session.calls[2] == ("/drive/v3/files/file1/export", {"mimeType": "text/plain"})


def test_drive_strips_utf8_bom_from_plain_text():
    session = drive()
    session.responses["/drive/v3/files/file1"][1] = "\ufeffpayment_id,status\nDEMO-01,pending"
    doc, = DriveConnector(session).fetch(CASES[3][2])
    assert "\ufeff" not in doc.text


@pytest.mark.parametrize("field,value", [("version", "5"), ("parents", ["other"]),
                                         ("trashed", True)])
def test_drive_detects_change_during_download(field, value):
    session = drive()
    session.responses["/drive/v3/files/file1"][-1] = {
        **session.responses["/drive/v3/files/file1"][-1], field: value}
    with pytest.raises(ConnectorError):
        DriveConnector(session).fetch(CASES[3][2])


def test_drive_binary_rejected_before_content_download():
    session = drive()
    session.responses["/drive/v3/files/file1"][0]["mimeType"] = "application/pdf"
    with pytest.raises(ConnectorError, match="unsupported_content"):
        DriveConnector(session).fetch(CASES[3][2])
    assert len(session.calls) == 2


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_second_fetch_rechecks_identity_instead_of_reusing_cached_authorization(cls, factory, ref):
    session = factory()
    cls(session).fetch(ref)
    session.binding.account_id = "revoked-user"
    with pytest.raises(ConnectorError, match="identity_mismatch"):
        cls(session).fetch(ref)


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_malformed_upstream_identity_is_sanitized(cls, factory, ref):
    session = factory()
    identity_path = next(iter(session.responses))
    session.responses[identity_path] = {"private_vendor_payload": "do-not-disclose"}
    with pytest.raises(ConnectorError) as error:
        cls(session).fetch(ref)
    assert "do-not-disclose" not in str(error.value)
    assert len(session.calls) == 1


def test_slack_specific_thread_preserves_parent_and_root():
    session = slack()
    ts = "1791768600.000001"
    session.responses["/api/conversations.replies"] = {"ok": True, "has_more": False,
        "messages": [{"type": "message", "text": "Root", "ts": ts},
                     {"type": "message", "text": "Reply", "ts": "1791768601.000001",
                      "thread_ts": ts}]}
    docs = SlackConnector(session).fetch(SourceRef("slack", "CDEMO", "TDEMO", ts))
    assert len(docs) == 2
    assert all(doc.source_kind == "thread_message" and doc.thread_id == ts for doc in docs)
    assert all(doc.parent_id == "CDEMO" for doc in docs)


def test_slack_pagination_bound_fails_without_returning_partial_records():
    pages = [{"ok": True, "messages": [], "has_more": True,
              "response_metadata": {"next_cursor": f"cursor-{index}"}} for index in range(10)]
    session = slack(pages)
    with pytest.raises(ConnectorError, match="incomplete_response"):
        SlackConnector(session).fetch(CASES[2][2])
    assert len(session.calls) == 12


@pytest.mark.parametrize("message", [
    {"type": "message", "ts": "1791768600.000001", "text": "x" * 5001},
    {"type": "message", "ts": "1791768600.000001", "text": "Caption", "files": [{}]},
    {"type": "message", "ts": "1791768600.000001", "text": "New", "channel": "COTHER"},
    {"type": "message", "ts": "1791768600.000001", "text": "Old",
     "edited": {"ts": "1791768500.000001"}},
])
def test_slack_unsupported_or_inconsistent_messages_fail_closed(message):
    with pytest.raises(ConnectorError):
        SlackConnector(slack({"ok": True, "messages": [message], "has_more": False})).fetch(CASES[2][2])


@pytest.mark.parametrize("vendor_error,code", [
    ("token_revoked", "expired_access"), ("invalid_auth", "expired_access"),
    ("ratelimited", "rate_limited"), ("internal_error", "upstream_unavailable"),
    ("unexpected-private-error", "invalid_response"),
])
def test_slack_semantic_failures_cannot_be_treated_as_absent_sources(vendor_error, code):
    session = slack()
    session.responses["/api/conversations.history"] = {"ok": False, "error": vendor_error}
    with pytest.raises(ConnectorError) as error:
        SlackConnector(session).fetch(CASES[2][2])
    assert error.value.code == code
    assert vendor_error not in str(error.value)


@pytest.mark.parametrize("cls,factory,ref", CASES)
def test_wrong_ref_type_is_invalid_request(cls, factory, ref):
    session = factory()
    with pytest.raises(ConnectorError, match="invalid_request"):
        cls(session).fetch(object())
    assert session.calls == []


@pytest.mark.parametrize("cls,factory,ref,field", [
    (ConfluenceConnector, confluence, CASES[0][2], "body"),
    (JiraConnector, jira, CASES[1][2], "description"),
    (DriveConnector, drive, CASES[3][2], "content"),
])
def test_oversize_source_has_specific_error(cls, factory, ref, field):
    session = factory()
    if field == "body":
        session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = "<p>" + "x" * 5001 + "</p>"
    elif field == "description":
        session.responses["/rest/api/3/issue/DEMO-1"]["fields"]["description"]["content"] = [
            {"type": "paragraph", "content": [{"type": "text", "text": "x" * 5001}]}]
    else:
        session.responses["/drive/v3/files/file1"][1] = "x" * 5001
    with pytest.raises(ConnectorError, match="content_too_large"):
        cls(session).fetch(ref)


def test_slack_skips_join_event_and_keeps_broadcast_content():
    session = slack({"ok": True, "messages": [
        {"type": "message", "subtype": "channel_join", "ts": "1791768600.000001", "text": "User joined"},
        {"type": "message", "subtype": "thread_broadcast", "ts": "1791768601.000001",
         "thread_ts": "1791768600.000001", "text": "Actual update"},
    ], "has_more": False})
    docs = SlackConnector(session, page_size=100).fetch(CASES[2][2])
    assert len(docs) == 1
    assert docs[0].text == "Actual update"
    assert session.calls[-1][1]["limit"] == "100"
    assert docs[0].locator == ("https://fixture.slack.com/archives/CDEMO/p1791768601000001"
                               "?thread_ts=1791768600.000001&cid=CDEMO")


def test_slack_default_limit_respects_restricted_app_tier():
    session = slack()
    SlackConnector(session).fetch(CASES[2][2])
    assert session.calls[-1][1]["limit"] == "15"


def test_slack_rejects_malformed_workspace_url():
    session = slack()
    session.responses["/api/auth.test"]["url"] = "https://attacker.example/"
    with pytest.raises(ConnectorError, match="invalid_response"):
        SlackConnector(session).fetch(CASES[2][2])
    assert len(session.calls) == 1


@pytest.mark.parametrize("macro", ["info", "warning"])
@pytest.mark.parametrize("title", ["IMPORTANT TITLE", "<![CDATA[IMPORTANT TITLE]]>"])
def test_confluence_extracts_macro_title_and_body_without_configuration_parameters(macro, title):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        f'<ac:structured-macro ac:name="{macro}"><ac:parameter ac:name="title">{title}</ac:parameter>'
        '<ac:parameter ac:name="collapse"><![CDATA[true]]></ac:parameter>'
        '<ac:rich-text-body><p>Escalate after 15 minutes.</p></ac:rich-text-body>'
        '</ac:structured-macro>')
    doc, = ConfluenceConnector(session).fetch(CASES[0][2])
    assert "Escalate after 15 minutes." in doc.text
    assert "IMPORTANT TITLE\nEscalate after 15 minutes." in doc.text
    assert "true" not in doc.text


def test_confluence_code_macro_preserves_cdata():
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        '<![CDATA[if x < 2:\n  print(x)]]></ac:plain-text-body></ac:structured-macro>')
    doc, = ConfluenceConnector(session).fetch(CASES[0][2])
    assert "if x < 2:\n  print(x)" in doc.text


def test_confluence_rejects_mismatched_macro_body_tags():
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        'text</ac:rich-text-body></ac:structured-macro>')
    with pytest.raises(ConnectorError, match="unsupported_content"):
        ConfluenceConnector(session).fetch(CASES[0][2])


@pytest.mark.parametrize("markup", [
    '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[{code}]]>'
    '</ac:plain-text-body></ac:structured-macro>',
    '<pre>{code}</pre>',
])
def test_confluence_preserves_code_indentation_blank_lines_and_trailing_spaces(markup):
    code = "def f():\n    return 1  \n\n\t# tab indentation\n    # end"
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        '<p>  Before  </p>' + markup.format(code=code) + '<p>  After  </p>')
    doc, = ConfluenceConnector(session).fetch(CASES[0][2])
    assert doc.text == "Runbook\nBefore\n" + code + "\nAfter"


def test_confluence_accepts_table_column_layout_without_losing_cell_text():
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        '<table><colgroup><col style="width: 100px"/><col/></colgroup>'
        '<tbody><tr><th>Queue</th><th>Count</th></tr><tr><td>Pending</td><td>3</td>'
        '</tr></tbody></table>')
    doc, = ConfluenceConnector(session).fetch(CASES[0][2])
    assert "Queue | Count" in doc.text
    assert "Pending | 3" in doc.text


@pytest.mark.parametrize("markup", [
    '<colgroup>Hidden text<col/></colgroup>',
    '<colgroup><p>Hidden text</p></colgroup>',
    '<colgroup><ac:structured-macro ac:name="code"><ac:plain-text-body>'
    '<![CDATA[Hidden text]]></ac:plain-text-body></ac:structured-macro></colgroup>',
    '<ac:adf-extension><p>Unsupported panel text</p></ac:adf-extension>',
])
def test_confluence_rejects_unrepresented_structured_content(markup):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = markup
    with pytest.raises(ConnectorError, match="unsupported_content"):
        ConfluenceConnector(session).fetch(CASES[0][2])


@pytest.mark.parametrize("change", [
    {"attachments": [{"text": "Additional evidence"}]},
    {"text": "", "blocks": [{"type": "section", "text": {"type": "plain_text", "text": "Evidence"}}]},
])
def test_slack_unsupported_body_fails_entire_fetch_instead_of_partial_evidence(change):
    session = slack({"ok": True, "has_more": False, "messages": [
        {"type": "message", "ts": "1791768600.000001", "text": "Readable first message"},
        {"type": "message", "ts": "1791768601.000001", "text": "Fallback", **change},
    ]})
    with pytest.raises(ConnectorError, match="unsupported_content"):
        SlackConnector(session).fetch(CASES[2][2])


@pytest.mark.parametrize("page_size", [101, 200])
def test_slack_page_size_cannot_exceed_total_message_bound(page_size):
    session = slack()
    with pytest.raises(ConnectorError, match="invalid_configuration"):
        SlackConnector(session, page_size=page_size)
    assert session.calls == []


@pytest.mark.parametrize("markup,label", [
    ('<ac:link><ri:page ri:content-title="Target page"/>'
     '<ac:plain-text-link-body><![CDATA[Readable <label>]]></ac:plain-text-link-body></ac:link>',
     'Readable <label>'),
    ('<ac:link><ri:page ri:content-title="Target page"/>'
     '<ac:link-body>Readable <strong>label</strong></ac:link-body></ac:link>', 'Readable label'),
    ('<ac:link><ri:page ri:content-title="Target page"/></ac:link>', 'Target page'),
    ('<ac:link><ri:user ri:account-id="user-123"/></ac:link>', '@user-123'),
])
def test_confluence_preserves_local_link_labels_without_fetching_targets(markup, label):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = (
        '<p>See ' + markup + ' now.</p>')
    doc, = ConfluenceConnector(session).fetch(CASES[0][2])
    assert doc.text == "Runbook\nSee " + label + " now."
    assert len(session.calls) == 2


@pytest.mark.parametrize("markup", [
    '<ac:link/>',
    '<ac:link><ri:page/></ac:link>',
    '<ac:link><ac:link-body><ac:image/></ac:link-body></ac:link>',
    '<ac:link><ac:plain-text-link-body><strong>Label</strong>'
    '</ac:plain-text-link-body></ac:link>',
])
def test_confluence_rejects_links_without_representable_labels(markup):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = markup
    with pytest.raises(ConnectorError, match="unsupported_content"):
        ConfluenceConnector(session).fetch(CASES[0][2])


@pytest.mark.parametrize("markup", [
    '<pre>    code',
    '<ac:structured-macro ac:name="info"><ac:parameter ac:name="title">Unclosed title',
    '<ac:structured-macro ac:name="info"><ac:rich-text-body><pre>    code'
    '</ac:rich-text-body></ac:structured-macro></pre>',
])
def test_confluence_rejects_unclosed_whitespace_or_title_context(markup):
    session = confluence()
    session.responses["/wiki/rest/api/content/123"]["body"]["storage"]["value"] = markup
    with pytest.raises(ConnectorError, match="invalid_response"):
        ConfluenceConnector(session).fetch(CASES[0][2])


def test_slack_blocks_without_text_have_explicit_unsupported_content_category():
    session = slack({"ok": True, "has_more": False, "messages": [
        {"type": "message", "ts": "1791768600.000001", "blocks": [{"type": "section"}]},
    ]})
    with pytest.raises(ConnectorError, match="unsupported_content"):
        SlackConnector(session).fetch(CASES[2][2])


@pytest.mark.parametrize("text", [None, 123])
def test_slack_malformed_text_remains_invalid_response(text):
    session = slack({"ok": True, "has_more": False, "messages": [
        {"type": "message", "ts": "1791768600.000001", "text": text, "blocks": [{"type": "section"}]},
    ]})
    with pytest.raises(ConnectorError, match="invalid_response"):
        SlackConnector(session).fetch(CASES[2][2])
