"""The browser boundary resolves identity server-side and rejects forged requests."""

import secrets
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.config import Settings
from aspire_brain.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / 'brain.db', session_secret=secrets.token_hex(32),
                    audit_key=secrets.token_bytes(32), demo_mode=True)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url='http://localhost',
                    client=('127.0.0.1', 50000)) as result:
        root = Path(__file__).resolve().parents[2]
        result.app.state.db.seed(root / 'data/demo/manifest.json', root / 'data/demo/principals.json')
        yield result


def headers(client):
    session = client.get('/api/session').json()
    return {'X-CSRF-Token': session['csrf_token'], 'Origin': 'http://localhost'}


def test_liveness_and_four_views(client):
    assert client.get('/health').json() == {'status': 'ok'}
    for path in ('/ask', '/sources', '/policies', '/audit'):
        result = client.get(path)
        assert result.status_code == 200
        assert result.headers['cache-control'] == 'no-store'
        assert "default-src 'self'" in result.headers['content-security-policy']
        assert 'Local demo' in result.text


def test_home_opens_four_platform_cases_and_keeps_policy_demo_accessible(client):
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == '/cases'
    home = client.get('/')
    assert home.status_code == 200
    assert 'SIMULATED' in home.text
    assert 'data-case="case_1"' in home.text
    assert 'href="/ask"' in home.text
    policy = client.get('/ask')
    assert policy.status_code == 200
    assert 'id="ask-form"' in policy.text
    assert client.get('/', headers={'Host': 'attacker.invalid'}).status_code == 400


def test_pages_label_the_offline_default_mode(client):
    for path in ('/ask', '/cases'):
        assert 'Mode: <strong>offline_extractive</strong>' in client.get(path).text
    cases = client.get('/cases').text
    assert 'No live model is contacted from this page' in cases
    assert 'Live model: Case 7 only' not in cases


def test_session_only_exposes_server_identity_and_csrf(client):
    result = client.get('/api/session')
    assert result.json()['principal'] is None
    assert result.json()['csrf_token']
    assert 'httponly' in result.headers['set-cookie'].lower()
    assert 'samesite=strict' in result.headers['set-cookie'].lower()


def test_csrf_and_origin_are_both_required(client):
    assert client.post('/api/demo/session', json={'user_id': 'employee'}).status_code == 403
    valid = headers(client)
    valid['Origin'] = 'https://attacker.invalid'
    assert client.post('/api/demo/session', json={'user_id': 'employee'}, headers=valid).status_code == 403
    denials = client.app.state.audit.events('local-security', limit=20)
    assert [event['metadata']['reason'] for event in denials] == [
        'request_verification_failed', 'request_verification_failed']
    assert client.app.state.audit.verify('local-security')['chain_valid']


def test_no_identity_means_no_evidence_even_with_forged_headers(client):
    result = client.get('/api/sources/secret/version', headers={'X-Role': 'finance', 'X-Tenant': 'demo-a'})
    assert result.status_code == 401
    result = client.post('/api/queries', json={'question': 'cap?', 'context': {}}, headers=headers(client))
    assert result.status_code == 401


def test_extra_identity_claims_and_disabled_identity_rejected(client):
    valid = headers(client)
    response = client.post('/api/demo/session', json={'user_id': 'employee', 'roles': ['finance']}, headers=valid)
    assert response.status_code == 422
    assert 'finance' not in response.text
    assert client.post('/api/demo/session', json={'user_id': 'disabled'}, headers=valid).status_code == 403


def test_untrusted_host_rejected(client):
    assert client.get('/health', headers={'Host': 'attacker.invalid'}).status_code == 400
    denials = client.app.state.audit.events('local-security', limit=20)
    assert denials[-1]['metadata'] == {'reason': 'invalid_host'}


def test_query_request_rejects_provider_fields_without_dispatch_or_packet(client):
    login(client)
    before = len(client.app.state.audit.events('demo-a', limit=1000))
    body = {'question': 'What is the Singapore travel cap?',
            'context': {'case_date': '2026-09-10'},
            'provider_mode': 'stage5e_service_live', 'response_format': {'type': 'json_schema'}}
    response = client.post('/api/queries', headers=headers(client), json=body)
    assert response.status_code == 422
    assert response.json() == {'detail': 'Invalid request fields'}
    assert len(client.app.state.audit.events('demo-a', limit=1000)) == before
    with closing(client.app.state.db.connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM packets').fetchone()[0] == 0
    denials = client.app.state.audit.events('local-security', limit=20)
    assert denials[-1]['metadata'] == {'reason': 'invalid_request'}
    assert 'stage5e_service_live' not in str(denials)
    assert client.app.state.audit.verify('local-security')['chain_valid']


def test_nonloopback_selector_rejected(settings):
    with TestClient(create_app(settings), base_url='http://localhost', client=('192.168.1.50', 1234)) as other:
        assert other.post('/api/demo/session', json={'user_id': 'employee'}, headers=headers(other)).status_code == 403


def test_demo_disabled_fails_closed(settings):
    from dataclasses import replace
    with TestClient(create_app(replace(settings, demo_mode=False)), base_url='http://localhost',
                    client=('127.0.0.1', 50000)) as other:
        assert other.post('/api/demo/session', json={'user_id': 'employee'}, headers=headers(other)).status_code == 403
        assert other.get('/api/audit/events').status_code == 401


def login(client, user='employee'):
    response = client.post('/api/demo/session', json={'user_id': user}, headers=headers(client))
    assert response.status_code == 200, response.text
    return response.json()


def query(client):
    return client.post('/api/queries', headers=headers(client), json={
        'question': 'What is the Singapore travel cap?',
        'context': {'case_date': '2026-09-10', 'jurisdiction': 'SG', 'worker_type': 'contractor'},
    })


def chunk(client, version):
    with closing(client.app.state.db.connect()) as db:
        return db.execute('SELECT id FROM chunks WHERE version_id=? LIMIT 1', (version,)).fetchone()[0]


def test_employee_useful_answer_source_history_and_export(client):
    login(client)
    response = query(client)
    assert response.status_code == 200, response.text
    packet = response.json()
    assert packet['query_status'] == 'answered'
    assert '250' in packet['answer']
    citation = packet['citations'][0]
    api_source = f"/api/sources/{citation['document_version_id']}/{citation['chunk_id']}"
    assert client.get(api_source).status_code == 200
    assert client.get(citation['source_url']).status_code == 200
    assert client.get('/api/policies/sg-travel/versions').status_code == 200
    saved = client.get(f"/api/packets/{packet['request_id']}")
    assert saved.json() == packet
    exported = client.get(f"/api/packets/{packet['request_id']}/export")
    assert exported.json() == packet
    assert 'attachment' in exported.headers['content-disposition']
    assert client.app.state.audit.verify('demo-a')['chain_valid']


def test_unknown_and_inaccessible_sources_have_same_response(client):
    login(client)
    restricted_chunk = chunk(client, 'p17-contract-v2')
    restricted = client.get(f'/api/sources/p17-contract-v2/{restricted_chunk}')
    unknown = client.get('/api/sources/unknown/not-present')
    assert restricted.status_code == unknown.status_code == 404
    assert restricted.json() == unknown.json()
    assert client.get('/api/policies/p17-contract/versions').status_code == 404
    assert client.get('/api/audit/events').status_code == 403


def test_role_switch_packets_and_cross_tenant_boundaries(client):
    login(client, 'finance_lead')
    packet = query(client).json()
    restricted_chunk = chunk(client, 'p17-contract-v2')
    assert client.get(f'/api/sources/p17-contract-v2/{restricted_chunk}').status_code == 200
    login(client, 'employee')
    assert client.get(f"/api/packets/{packet['request_id']}").status_code == 404
    assert client.get(f'/api/sources/p17-contract-v2/{restricted_chunk}').status_code == 404
    login(client, 'policy_admin')
    assert client.get('/api/policies/sg-travel/versions').status_code == 200
    assert client.get('/api/policies/p17-contract/versions').status_code == 404
    login(client, 'other_tenant')
    assert client.get('/api/policies/sg-travel/versions').status_code == 404
    assert client.get('/api/policies/tenant-b-travel/versions').status_code == 200


def test_re_read_identity_and_revoke_dependency(client):
    login(client)
    packet = query(client).json()
    citation = packet['citations'][0]
    client.app.state.db.revoke(citation['document_version_id'], client.app.state.audit)
    assert client.get(f"/api/packets/{packet['request_id']}").status_code == 404
    assert client.get(f"/api/sources/{citation['document_version_id']}/{citation['chunk_id']}").status_code == 404
    client.app.state.db.set_principal_roles('employee', [], client.app.state.audit)
    assert client.get('/api/session').json()['principal']['roles'] == []
    with closing(client.app.state.db.connect()) as db, db:
        db.execute("UPDATE principals SET active=0 WHERE id='employee'")
    assert client.get('/api/policies/sg-travel/versions').status_code == 401


def test_auditor_gets_safe_trace_not_source_identifiers_or_packets(client):
    login(client, 'finance_lead')
    packet = query(client).json()
    login(client, 'auditor')
    response = client.get('/api/audit/events')
    assert response.status_code == 200, response.text
    assert response.json()['integrity']['chain_valid']
    assert any(event['request_id'] == packet['request_id'] for event in response.json()['events'])
    for value in ['p17-contract', 'FINANCE_ONLY_SENTINEL', 'version_ids', 'rule_ids']:
        assert value not in response.text
    assert client.get(f"/api/packets/{packet['request_id']}").status_code == 404
    assert client.get('/api/policies/sg-travel/versions').status_code == 404
    assert client.get('/api/audit/events?limit=50000').status_code == 422


def test_audit_failure_prevents_source_disclosure_and_safe_errors(client, monkeypatch):
    from aspire_brain.audit import AuditError
    login(client)
    source_chunk = chunk(client, 'sg-travel-v2')
    def fail(*args, **kwargs):
        raise AuditError('PRIVATE DATABASE CONTENT')
    monkeypatch.setattr(client.app.state.audit, 'append', fail)
    response = client.get(f'/api/sources/sg-travel-v2/{source_chunk}')
    assert response.status_code == 503
    assert 'PRIVATE' not in response.text and '250' not in response.text
    assert client.post('/api/demo/session', json={'user_id': 'employee'}).status_code == 503


def test_source_response_aborts_when_revision_changes_during_read(client, monkeypatch):
    login(client)
    source_chunk = chunk(client, 'sg-travel-v2')
    original = client.app.state.auth.source
    def revoke_after_read(principal, version, cid):
        value = original(principal, version, cid)
        client.app.state.db.revoke(version, client.app.state.audit)
        return value
    monkeypatch.setattr(client.app.state.auth, 'source', revoke_after_read)
    response = client.get(f'/api/sources/sg-travel-v2/{source_chunk}')
    assert response.status_code == 409
    assert '250' not in response.text


def test_source_html_escapes_document_text(client, monkeypatch):
    login(client)
    source_chunk = chunk(client, 'sg-travel-v2')
    original = client.app.state.auth.source
    def untrusted(*args):
        return {**original(*args), 'text': '<script>alert("attack")</script>'}
    monkeypatch.setattr(client.app.state.auth, 'source', untrusted)
    response = client.get(f'/sources/sg-travel-v2/{source_chunk}')
    assert '&lt;script&gt;' in response.text
    assert '<script>' not in response.text


def test_configured_external_provider_cannot_silently_use_offline(settings):
    from dataclasses import replace

    from aspire_brain.providers import ExternalProviderUnavailable
    with pytest.raises(ExternalProviderUnavailable):
        with TestClient(create_app(replace(settings, provider_mode='external'))):
            pass


def test_forwarded_claims_do_not_create_session_or_bypass_loopback(settings):
    with TestClient(create_app(settings), base_url='http://localhost', client=('10.0.0.1', 1234)) as remote:
        valid = {**headers(remote), 'X-Forwarded-For': '127.0.0.1', 'X-Role': 'finance',
                 'X-User-ID': 'finance_lead'}
        assert remote.post('/api/demo/session', json={'user_id': 'finance_lead'}, headers=valid).status_code == 403
        assert remote.get('/api/audit/events', headers=valid).status_code == 401


def test_audit_role_revoked_between_route_and_read_is_denied(client, monkeypatch):
    login(client, 'auditor')
    original = client.app.state.auth.principal
    calls = 0
    def revoke_between_checks(identity):
        nonlocal calls
        calls += 1
        if calls == 2:
            client.app.state.db.set_principal_roles('auditor', [], client.app.state.audit)
        return original(identity)
    monkeypatch.setattr(client.app.state.auth, 'principal', revoke_between_checks)
    response = client.get('/api/audit/events')
    assert response.status_code in (403, 404)
    assert 'events' not in response.json()
