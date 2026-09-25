import json
from contextlib import closing

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
    with closing(db.connect()) as connection, connection:
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
    with closing(db.connect()) as connection, connection:
        connection.execute("UPDATE app_meta SET value='999' WHERE key='schema_version'")
    with pytest.raises(ValueError):
        db.initialize()


def test_controlled_changes_fail_closed_and_increment_revisions(tmp_path):
    from aspire_brain.audit import AuditWriter
    db = setup_database(tmp_path)
    audit = AuditWriter(db.path, b'x' * 32)
    audit.initialize()
    auth = AuthService(db)
    person = auth.principal('employee')
    before = auth.revisions(person)
    db.set_publication_state('v1', 'withdrawn', audit)
    assert auth.revisions(person) == (before[0], before[1] + 1)
    assert Retriever(db).search(person, 'claim', '2026-09-10') == []
    db.set_publication_state('v1', 'approved', audit)
    db.set_active('employee', False, audit)
    with pytest.raises(AccessDenied):
        auth.principal('employee')
    db.set_active('employee', True, audit)
    db.revoke('v1', audit)
    assert not auth.readable(person, 'v1')
    # Reseeding cannot restore controlled publication/ACL/persona state.
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    assert not auth.readable(person, 'v1')


def test_audit_failure_rolls_back_acl_and_import(tmp_path):
    db = setup_database(tmp_path)
    auth = AuthService(db)
    principal = auth.principal('employee')
    before = auth.revisions(principal)

    class BrokenAudit:
        def append_in_transaction(self, *args, **kwargs):
            raise RuntimeError('Audit unavailable')

    with pytest.raises(RuntimeError):
        db.revoke('v1', BrokenAudit())
    assert auth.readable(principal, 'v1')
    assert auth.revisions(principal) == before
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['versions'].append({**manifest['versions'][0], 'id': 'v2'})
    write_manifest(tmp_path, manifest)
    with pytest.raises(RuntimeError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json', audit=BrokenAudit())
    assert not auth.readable(principal, 'v2')
    assert auth.revisions(principal) == before
    with pytest.raises(ValueError, match='audit'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


@pytest.mark.parametrize('value', [True, -1, 'NaN', 'Infinity', 2.5, {}, 'no'])
def test_invalid_rule_values_are_rejected(tmp_path, value):
    manifest = seed_data(tmp_path)
    manifest['versions'][0]['rules'] = [{'id': 'r1', 'key': 'travel_cap', 'value': value,
                                       'unit': 'claim', 'currency': 'SGD', 'scope': {},
                                       'source_paragraph': 2, 'overrides': []}]
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_cycles_and_cross_tenant_rule_links_rejected(tmp_path):
    manifest = seed_data(tmp_path)
    base = manifest['versions'][0]
    base['supersedes'] = 'v2'
    manifest['versions'].append({**base, 'id': 'v2', 'supersedes': 'v1'})
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError, match='Cyclic'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')
    base['supersedes'] = None
    manifest['versions'] = [base]
    base['rules'] = [{'id': 'r1', 'key': 'travel_cap', 'value': '250', 'unit': 'claim',
                      'currency': 'SGD', 'scope': {}, 'source_paragraph': 2, 'overrides': ['r2']}]
    manifest['documents'].append({'id': 'other-policy', 'tenant_id': 'b',
                                  'document_type': 'policy', 'owner': 'other'})
    manifest['versions'].append({**base, 'id': 'v2', 'document_id': 'other-policy',
                                  'tenant_id': 'b', 'rules': [{**base['rules'][0], 'id': 'r2', 'overrides': []}]})
    write_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match='Cross-tenant'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_fallback_date_scope_and_context_bounds(tmp_path):
    db = setup_database(tmp_path)
    db.fts_available = False
    retriever = Retriever(db)
    person = AuthService(db).principal('employee')
    assert retriever.mode == 'authorized_lexical_fallback'
    assert retriever.search(person, 'claim', '2025-12-31') == []
    hits = retriever.search(person, 'claim', '2026-01-01', max_chars=7)
    assert len(hits[0]['text']) == 7
    assert retriever.search(AuthService(db).principal('other'), 'claim', '2026-01-01') == []
    with pytest.raises(ValueError):
        retriever.search(person, 'claim', '2026-01-01', scope={'malicious': 'x'})


def test_tampered_chunk_is_rejected_before_disclosure(tmp_path):
    db = setup_database(tmp_path)
    person = AuthService(db).principal('employee')
    with closing(db.connect()) as connection, connection:
        connection.execute("UPDATE chunks SET text='Forged claim cap' WHERE id='v1:p2'")
    with pytest.raises(ValueError, match='integrity'):
        AuthService(db).source(person, 'v1', 'v1:p2')
    with pytest.raises(ValueError, match='integrity'):
        Retriever(db).search(person, 'claim', '2026-09-10')


def test_audited_import_is_idempotent_and_changes_content_revision(tmp_path):
    from aspire_brain.audit import AuditWriter
    db = setup_database(tmp_path)
    auth = AuthService(db)
    principal = auth.principal('employee')
    before = auth.revisions(principal)
    audit = AuditWriter(db.path, b'z' * 32)
    audit.initialize()
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['versions'].append({**manifest['versions'][0], 'id': 'v2'})
    write_manifest(tmp_path, manifest)
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json', audit=audit)
    assert auth.readable(principal, 'v2')
    assert auth.revisions(principal) == (before[0], before[1] + 1)
    with closing(db.connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0] == 1
    db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json', audit=audit)
    with closing(db.connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0] == 1


@pytest.mark.parametrize('scenario', ['cyclic', 'missing_source', 'incompatible_units', 'broader_scope'])
def test_invalid_rule_relations_rejected_before_import(tmp_path, scenario):
    manifest = seed_data(tmp_path)
    base = {'id': 'r1', 'key': 'travel_cap', 'value': '250', 'unit': 'claim',
            'currency': 'SGD', 'scope': {}, 'source_paragraph': 2, 'overrides': ['r2']}
    target = {**base, 'id': 'r2', 'overrides': []}
    if scenario == 'cyclic':
        target = {**target, 'overrides': ['r1']}
    elif scenario == 'missing_source':
        base = {**base, 'source_paragraph': 999}
    elif scenario == 'incompatible_units':
        target = {**target, 'unit': 'day'}
    else:
        target = {**target, 'scope': {'project': 'P17'}}
    manifest['versions'][0]['rules'] = [base, target]
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_duplicate_json_fields_rejected(tmp_path):
    seed_data(tmp_path)
    (tmp_path / 'manifest.json').write_text('{"documents":[],"versions":[],"versions":[]}')
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError, match='Duplicate JSON'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_missing_date_does_not_silently_choose_today(tmp_path):
    db = setup_database(tmp_path)
    principal = AuthService(db).principal('employee')
    assert Retriever(db).search(principal, 'claim') == []
    assert Retriever(db).all_rules(principal) == []


@pytest.mark.parametrize('invalid_end', ['', False, 0])
def test_end_date_rejects_invalid_falsy_coercions(tmp_path, invalid_end):
    manifest = seed_data(tmp_path)
    manifest['versions'][0]['valid_to'] = invalid_end
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_scope_keys_match_case_policy_contract(tmp_path):
    manifest = seed_data(tmp_path)
    manifest['versions'][0]['scope'] = {'workflow_id': 'general'}
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError, match='scope'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


def test_mixed_supersession_override_cycle_rejected(tmp_path):
    manifest = seed_data(tmp_path)
    rule = {'id': 'r1', 'key': 'travel_cap', 'value': '250', 'unit': 'claim',
            'currency': 'SGD', 'scope': {}, 'source_paragraph': 2, 'overrides': []}
    first = {**manifest['versions'][0], 'supersedes': 'v2', 'rules': [rule]}
    second = {**manifest['versions'][0], 'id': 'v2',
              'rules': [{**rule, 'id': 'r2', 'overrides': ['r1']}]}
    manifest['versions'] = [first, second]
    write_manifest(tmp_path, manifest)
    db = Database(tmp_path / 'test.db')
    db.initialize()
    with pytest.raises(ValueError, match='Cyclic'):
        db.seed(tmp_path / 'manifest.json', tmp_path / 'principals.json')


@pytest.mark.parametrize('fallback', [False, True])
def test_unrelated_question_cannot_match_stopwords(tmp_path, fallback):
    db = setup_database(tmp_path)
    if fallback:
        db.fts_available = False
    person = AuthService(db).principal('employee')
    retriever = Retriever(db)
    assert retriever.search(person, 'What is the parental leave entitlement?', '2026-09-10') == []
    assert retriever.search(person, 'What is the claim cap?', '2026-09-10')
