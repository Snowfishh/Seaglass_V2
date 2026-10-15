"""The opt-in hosted demo: exact public hosts, proxy-aware CSRF, offline fixture only."""

import json
import secrets
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aspire_brain.cli import main
from aspire_brain.config import ConfigurationError, Settings, initialize_config
from aspire_brain.main import create_app
from aspire_brain.providers.runtime import ProviderRuntimeConfig

ROOT = Path(__file__).resolve().parents[2]
HOST = 'aspire-demo.hf.space'
ORIGIN = f'https://{HOST}'
# Hugging Face terminates TLS; the app itself is reached over plain HTTP from a remote proxy.
PROXIED = {'X-Forwarded-Proto': 'https'}


@pytest.fixture
def local_settings(tmp_path):
    return Settings(db_path=tmp_path / 'brain.db', session_secret=secrets.token_hex(32),
                    audit_key=secrets.token_bytes(32), demo_mode=True)


@pytest.fixture
def hosted_settings(local_settings):
    return replace(local_settings, hosted_demo=True, allowed_hosts=(HOST,))


def proxied_client(app, host=HOST):
    return TestClient(app, base_url=f'http://{host}', client=('10.16.4.2', 41000))


def seed(client):
    client.app.state.db.seed(ROOT / 'data/demo/manifest.json', ROOT / 'data/demo/principals.json')


def cookie(client):
    # The session cookie is Secure, so the HTTP test transport would not resend it on its own;
    # the browser does, because it talks HTTPS to the proxy.
    value = client.cookies.get('aspire_demo')
    return {'Cookie': f'aspire_demo={value}'} if value else {}


def hosted_headers(client):
    session = client.get('/api/session', headers={**PROXIED, **cookie(client)})
    return {**PROXIED, **cookie(client), 'X-CSRF-Token': session.json()['csrf_token'],
            'Origin': ORIGIN}


def denials(client):
    return [event['metadata']['reason']
            for event in client.app.state.audit.events('local-security', limit=50)]


# (a) Hosted mode off keeps the loopback-only boundary.

def test_hosted_mode_is_off_by_default(local_settings, tmp_path, monkeypatch):
    assert local_settings.hosted_demo is False and local_settings.allowed_hosts == ()
    for name in ('ASPIRE_HOSTED_DEMO', 'ASPIRE_ALLOWED_HOSTS'):
        monkeypatch.delenv(name, raising=False)
    loaded = initialize_config(tmp_path)
    assert loaded.hosted_demo is False and loaded.allowed_hosts == ()


def test_allowed_hosts_are_ignored_while_hosted_mode_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv('ASPIRE_HOSTED_DEMO', raising=False)
    monkeypatch.setenv('ASPIRE_ALLOWED_HOSTS', HOST)
    settings = initialize_config(tmp_path)
    assert settings.allowed_hosts == ()
    with proxied_client(create_app(settings)) as remote:
        assert remote.get('/health').status_code == 400
        assert denials(remote) == ['invalid_host']
    with TestClient(create_app(settings), base_url='http://localhost',
                    client=('10.16.4.2', 41000)) as local:
        session = local.get('/api/session')
        assert 'secure' not in session.headers['set-cookie'].lower()
        assert 'strict-transport-security' not in session.headers
        valid = {'X-CSRF-Token': session.json()['csrf_token'], 'Origin': 'http://localhost'}
        # The proxy header buys nothing locally, and a remote client still cannot pick a persona.
        response = local.post('/api/demo/session', json={'user_id': 'employee'},
                              headers={**valid, **PROXIED})
        assert response.status_code == 403
        assert denials(local)[-1] == 'persona_unavailable'


# (b) Hosted mode on accepts the listed host only.

def test_hosted_mode_accepts_the_listed_host_and_a_remote_persona_change(hosted_settings):
    with proxied_client(create_app(hosted_settings)) as client:
        seed(client)
        assert client.get('/health', headers=PROXIED).json() == {'status': 'ok'}
        session = client.get('/api/session', headers=PROXIED)
        set_cookie = session.headers['set-cookie'].lower()
        assert 'secure' in set_cookie and 'httponly' in set_cookie and 'samesite=strict' in set_cookie
        assert session.headers['strict-transport-security'] == 'max-age=31536000'
        response = client.post('/api/demo/session', json={'user_id': 'employee'},
                               headers=hosted_headers(client))
        assert response.status_code == 200, response.text
        assert response.json()['principal']['id'] == 'employee'
        answer = client.post('/api/queries', headers=hosted_headers(client), json={
            'question': 'What is the Singapore travel cap?',
            'context': {'case_date': '2026-09-10', 'jurisdiction': 'SG', 'worker_type': 'contractor'},
        })
        assert answer.status_code == 200, answer.text
        assert denials(client) == []


@pytest.mark.parametrize('host', ['attacker.invalid', 'localhost', '127.0.0.1',
                                  'other-demo.hf.space', f'{HOST}.attacker.invalid'])
def test_hosted_mode_rejects_every_other_host(hosted_settings, host):
    with proxied_client(create_app(hosted_settings), host=host) as client:
        assert client.get('/health', headers=PROXIED).status_code == 400
        assert client.post('/api/demo/session', json={'user_id': 'employee'},
                           headers={**PROXIED, 'Origin': f'https://{host}'}).status_code == 400
        assert denials(client) == ['host_not_allowed', 'host_not_allowed']
        assert client.app.state.audit.verify('local-security')['chain_valid']


def test_hosted_mode_still_refuses_disabled_and_unknown_personas(hosted_settings):
    with proxied_client(create_app(hosted_settings)) as client:
        seed(client)
        for user in ('disabled', 'root'):
            response = client.post('/api/demo/session', json={'user_id': user},
                                   headers=hosted_headers(client))
            assert response.status_code == 403
        assert denials(client) == ['persona_unavailable', 'persona_unavailable']


# (c) CSRF and Origin remain enforced behind the proxy.

def test_hosted_mode_requires_csrf_token_and_exact_https_origin(hosted_settings):
    with proxied_client(create_app(hosted_settings)) as client:
        seed(client)
        valid = hosted_headers(client)
        body = {'user_id': 'employee'}
        assert client.post('/api/demo/session', json=body,
                           headers={**valid, 'X-CSRF-Token': ''}).status_code == 403
        assert client.post('/api/demo/session', json=body,
                           headers={**valid, 'X-CSRF-Token': 'forged'}).status_code == 403
        for origin in (f'http://{HOST}', 'https://attacker.invalid', f'{ORIGIN}:8443',
                       f'{ORIGIN}/path', ''):
            assert client.post('/api/demo/session', json=body,
                               headers={**valid, 'Origin': origin}).status_code == 403
        no_session = {key: value for key, value in valid.items() if key != 'Cookie'}
        client.cookies.clear()
        assert client.post('/api/demo/session', json=body, headers=no_session).status_code == 403
        assert denials(client) == ['request_verification_failed'] * 8


@pytest.mark.parametrize('proto', [None, 'http', 'ftp', 'http, https'])
def test_hosted_mode_refuses_state_changes_not_forwarded_as_https(hosted_settings, proto):
    with proxied_client(create_app(hosted_settings)) as client:
        valid = hosted_headers(client)
        del valid['X-Forwarded-Proto']
        if proto is not None:
            valid['X-Forwarded-Proto'] = proto
        response = client.post('/api/demo/session', json={'user_id': 'employee'}, headers=valid)
        assert response.status_code == 403
        assert denials(client) == ['insecure_transport']


def test_forwarded_scheme_is_not_trusted_while_hosted_mode_is_off(local_settings):
    with TestClient(create_app(local_settings), base_url='http://localhost',
                    client=('127.0.0.1', 50000)) as client:
        session = client.get('/api/session')
        spoofed = {'X-CSRF-Token': session.json()['csrf_token'], 'Origin': 'https://localhost',
                   **PROXIED}
        assert client.post('/api/demo/session', json={'user_id': 'employee'},
                           headers=spoofed).status_code == 403
        assert denials(client) == ['request_verification_failed']


# (d) Only the offline provider over the fictional fixture may run hosted.

@pytest.mark.parametrize('changes', [
    {'provider_mode': 'live_grounded'},
    {'provider_mode': 'fake_grounded'},
    {'provider_runtime': ProviderRuntimeConfig(service='groq', model='m',
                                               endpoint='https://api.groq.com')},
    {'provider_key_path': Path('/private/provider.key')},
    {'allowed_hosts': ()},
    {'platform_source': 'connectors'},
    {'connectors_config_path': Path('/private/connectors.json')},
])
def test_hosted_settings_refuse_live_providers_and_missing_hosts(hosted_settings, changes):
    with pytest.raises(ConfigurationError):
        replace(hosted_settings, **changes)


@pytest.mark.parametrize('env', [
    {'ASPIRE_PROVIDER_MODE': 'live_grounded'},
    {'ASPIRE_PROVIDER_SERVICE': 'groq'},
    {'ASPIRE_PLATFORM_SOURCE': 'connectors'},
    {'ASPIRE_CONNECTORS_CONFIG': 'var/connectors.json'},
    {'ASPIRE_ALLOWED_HOSTS': ''},
    {'ASPIRE_ALLOWED_HOSTS': '*.hf.space'},
    {'ASPIRE_ALLOWED_HOSTS': f'{HOST}:443'},
    {'ASPIRE_HOSTED_DEMO': 'yes'},
])
def test_hosted_startup_refuses_live_or_connected_configuration(tmp_path, monkeypatch, capsys, env):
    monkeypatch.setenv('ASPIRE_HOSTED_DEMO', 'true')
    monkeypatch.setenv('ASPIRE_ALLOWED_HOSTS', HOST)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert main(['--root', str(tmp_path), 'init-demo', '--fixtures', str(ROOT / 'data/demo')]) == 1
    assert 'error' in json.loads(capsys.readouterr().out)


def test_hosted_container_start_initializes_offline_fixture(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ASPIRE_HOSTED_DEMO', 'true')
    monkeypatch.setenv('ASPIRE_ALLOWED_HOSTS', f' {HOST.upper()} , {HOST} ')
    monkeypatch.setenv('ASPIRE_PLATFORM_SOURCE', 'fixture')
    assert main(['--root', str(tmp_path), 'init-demo', '--fixtures', str(ROOT / 'data/demo')]) == 0
    assert json.loads(capsys.readouterr().out)['provider_mode'] == 'offline_extractive'
    settings = Settings.load(tmp_path)
    assert settings.hosted_demo and settings.allowed_hosts == (HOST,)


def test_hosted_app_refuses_an_injected_non_offline_provider(hosted_settings):
    class Grounded:
        mode = 'fake_grounded'

    with pytest.raises(ConfigurationError):
        with TestClient(create_app(hosted_settings, provider=Grounded())):
            pass


def test_dockerfile_fixes_hosted_mode_without_a_default_host():
    dockerfile = (ROOT / 'Dockerfile').read_text()
    assert 'ASPIRE_HOSTED_DEMO=true' in dockerfile
    assert 'ASPIRE_PROVIDER_MODE=offline_extractive' in dockerfile
    assert 'ASPIRE_ALLOWED_HOSTS=' not in dockerfile
    assert 'useradd --create-home --uid 1000 user' in dockerfile and 'USER user' in dockerfile
    assert 'aspire_brain.cli init-demo' in dockerfile and '--port 7860' in dockerfile
    ignored = (ROOT / '.dockerignore').read_text().splitlines()
    assert ignored[ignored.index('*') + 1:][0].startswith('!')
    assert not any(line.startswith('!') and ('var' in line or '.env' in line or 'key' in line)
                   for line in ignored)
