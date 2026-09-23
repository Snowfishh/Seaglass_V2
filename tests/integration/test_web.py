"""The browser boundary resolves identity server-side and rejects forged requests."""

import secrets

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
        yield result


def headers(client):
    session = client.get('/api/session').json()
    return {'X-CSRF-Token': session['csrf_token'], 'Origin': 'http://localhost'}


def test_liveness_and_four_views(client):
    assert client.get('/health').json() == {'status': 'ok'}
    for path in ('/', '/sources', '/policies', '/audit'):
        result = client.get(path)
        assert result.status_code == 200
        assert result.headers['cache-control'] == 'no-store'
        assert "default-src 'self'" in result.headers['content-security-policy']
        assert 'Local demo' in result.text


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


def test_nonloopback_selector_rejected(settings):
    with TestClient(create_app(settings), base_url='http://localhost', client=('192.168.1.50', 1234)) as other:
        assert other.post('/api/demo/session', json={'user_id': 'employee'}, headers=headers(other)).status_code == 403


def test_demo_disabled_fails_closed(settings):
    from dataclasses import replace
    with TestClient(create_app(replace(settings, demo_mode=False)), base_url='http://localhost',
                    client=('127.0.0.1', 50000)) as other:
        assert other.post('/api/demo/session', json={'user_id': 'employee'}, headers=headers(other)).status_code == 403
        assert other.get('/api/audit/events').status_code == 401
