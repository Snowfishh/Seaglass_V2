import json
from pathlib import Path

import pytest

from aspire_brain.auth import AccessDenied, AuthService
from aspire_brain.db import Database
from aspire_brain.knowledge import Retriever


def seed_data(tmp_path):
    (tmp_path / 'text.md').write_text('# Policy\n\nVisible claim cap is 250.\n', encoding='utf-8')
    principals = [{'id': 'employee', 'tenant_id': 'a', 'active': True, 'roles': ['employee']},
                  {'id': 'finance', 'tenant_id': 'a', 'active': True, 'roles': ['finance']},
                  {'id': 'other', 'tenant_id': 'b', 'active': True, 'roles': ['employee']},
                  {'id': 'disabled', 'tenant_id': 'a', 'active': False, 'roles': ['employee']}]
    manifest = {'documents': [{'id': 'policy', 'tenant_id': 'a', 'document_type': 'policy', 'owner': 'ops'}],
                'versions': [{'id': 'v1', 'document_id': 'policy', 'tenant_id': 'a', 'file': 'text.md',
                              'published_at': '2026-01-01T00:00:00Z', 'state': 'approved',
                              'valid_from': '2026-01-01', 'valid_to': None, 'scope': {},
                              'supersedes': None, 'acl': ['employee', 'finance'], 'rules': []}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'principals.json').write_text(json.dumps(principals))
    return manifest


def write_manifest(tmp_path, manifest):
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))


def setup_database(tmp_path):
    seed_data(tmp_path)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    return db


def test_retrieval_auth_and_idempotence(tmp_path):
    db = setup_database(tmp_path)
    auth = AuthService(db)
    employee = auth.principal('employee')
    before = auth.revisions(employee)
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    assert before == auth.revisions(employee)
    hits = Retriever(db).search(employee, 'claim', '2026-09-10')
    assert hits and '250' in hits[0]['text']
    assert not Retriever(db).search(auth.principal('other'), 'claim', '2026-09-10')
    assert not auth.readable(auth.principal('other'), 'v1')
    assert auth.source(employee, 'v1', 'v1:p2')['text'] == 'Visible claim cap is 250.'
    with pytest.raises(AccessDenied):
        auth.principal('disabled')
    with pytest.raises(AccessDenied):
        auth.source(employee, 'v1', '../../text.md')


@pytest.mark.parametrize('field,value', [('acl', []), ('valid_from', 'nonsense'),
                                        ('valid_to', '2025-01-01'), ('file', '../secret.md'),
                                        ('tenant_id', 'b')])
def test_invalid_seed_atomic(tmp_path, field, value):
    manifest = seed_data(tmp_path)
    manifest['versions'][0][field] = value
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    with db.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM principals').fetchone()[0] == 0


def test_immutable_conflicting_import(tmp_path):
    db = setup_database(tmp_path)
    (tmp_path / 'text.md').write_text('Changed content')
    with pytest.raises(ValueError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    assert '250' in AuthService(db).source(AuthService(db).principal('employee'), 'v1', 'v1:p2')['text']


def test_unauthorized_hits_cannot_consume_top_k(tmp_path):
    manifest = seed_data(tmp_path)
    (tmp_path / 'secret.md').write_text('claim claim claim SECRET_SENTINEL')
    hidden = {**manifest['versions'][0], 'id': 'secret', 'file': 'secret.md', 'acl': ['finance']}
    manifest['versions'].append(hidden)
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    principal = AuthService(db).principal('employee')
    assert Retriever(db).search(principal, 'claim', '2026-09-10', top_k=1)[0]['version_id'] == 'v1'
    assert 'SECRET_SENTINEL' not in json.dumps(Retriever(db).search(principal, '" OR *', '2026-09-10'))


def test_forged_principal_roles_are_not_trusted(tmp_path):
    db = setup_database(tmp_path)
    assert not AuthService(db).readable({'id': 'other', 'tenant_id': 'a', 'roles': ['finance']}, 'v1')


def test_schema_mismatch_is_not_dropped(tmp_path):
    db = setup_database(tmp_path)
    with db.connect() as connection:
        connection.execute("UPDATE app_meta SET value='999' WHERE key='schema_version'")
    with pytest.raises(ValueError):
        db.initialize()
