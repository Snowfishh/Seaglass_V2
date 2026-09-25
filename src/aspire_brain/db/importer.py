"""Append-only, transactional trusted imports."""
import json

from .validation import canonical, check_cycles


def _rows(connection, table):
    return {row['id']: dict(row) for row in connection.execute(f'SELECT * FROM {table}')}


def validate_links(connection, documents, people, versions):
    existing_docs = _rows(connection, 'documents')
    existing_versions = _rows(connection, 'versions')
    existing_rules = _rows(connection, 'rules')
    for rule in existing_rules.values():
        rule['scope'] = json.loads(rule['scope'])
        rule['overrides'] = json.loads(rule['overrides'])
    for version in existing_versions.values():
        version['scope'] = json.loads(version['scope'])
    all_docs = {**existing_docs, **documents}
    all_versions = {**existing_versions, **versions}
    new_rules = {r['id']: r for v in versions.values() for r in v['rules']}
    all_rules = {**existing_rules, **new_rules}
    for key, doc in documents.items():
        if key in existing_docs and doc != existing_docs[key]:
            raise ValueError('Conflicting immutable document identifier')
    for key, version in versions.items():
        if key in existing_versions and version['import_digest'] != existing_versions[key]['import_digest']:
            raise ValueError('Conflicting immutable version identifier')
        doc = all_docs.get(version['document_id'])
        if doc is None or doc['tenant_id'] != version['tenant_id']:
            raise ValueError('Missing or cross-tenant document link')
        target = all_versions.get(version['supersedes'])
        if version['supersedes'] and (target is None or target['document_id'] != version['document_id']
                                      or target['tenant_id'] != version['tenant_id']
                                      or target['scope'] != version['scope']):
            raise ValueError('Invalid supersession relation')
    for rule in new_rules.values():
        if rule['id'] in existing_rules and rule['version_id'] != existing_rules[rule['id']]['version_id']:
            raise ValueError('Conflicting immutable rule identifier')
        for target_id in rule['overrides']:
            _validate_override(rule, all_rules.get(target_id), all_versions)
    check_cycles({key: [v['supersedes']] if v['supersedes'] else [] for key, v in all_versions.items()})
    check_cycles({key: r['overrides'] for key, r in all_rules.items()})
    _check_combined_precedence(all_rules, all_versions)
    existing_people = _rows(connection, 'principals')
    for key, person in people.items():
        if key in existing_people and person['tenant_id'] != existing_people[key]['tenant_id']:
            raise ValueError('Principal cannot move tenants through import')
    return existing_docs, existing_people, existing_versions


def _check_combined_precedence(rules, versions):
    edges = {}
    for key, rule in rules.items():
        version = versions[rule['version_id']]
        implicit = [target['id'] for target in rules.values()
                    if target['version_id'] == version['supersedes']
                    and all(target[field] == rule[field] for field in ('key', 'unit', 'currency'))]
        edges[key] = [*rule['overrides'], *implicit]
    check_cycles(edges)


def _validate_override(rule, target, versions):
    source_version = versions[rule['version_id']]
    if target is None:
        raise ValueError('Missing override target')
    target_version = versions[target['version_id']]
    if source_version['tenant_id'] != target_version['tenant_id']:
        raise ValueError('Cross-tenant override')
    if source_version['state'] != 'approved' or target_version['state'] != 'approved':
        raise ValueError('Overrides require approved versions')
    if any(rule[k] != target[k] for k in ('key', 'unit', 'currency')):
        raise ValueError('Incompatible override rule')
    scope = {**source_version['scope'], **rule['scope']}
    target_scope = {**target_version['scope'], **target['scope']}
    if any(scope.get(key) != value for key, value in target_scope.items()):
        raise ValueError('Override must retain or narrow target scope')


def insert_fixtures(connection, docs, people, versions, fts_available):
    existing_docs, existing_people, existing_versions = validate_links(connection, docs, people, versions)
    tenants = {x['tenant_id'] for x in [*docs.values(), *people.values(), *versions.values()]}
    for tenant in tenants:
        connection.execute('INSERT OR IGNORE INTO tenants(id) VALUES (?)', (tenant,))
    changed_acl, changed_content = set(), set()
    for person in people.values():
        if person['id'] not in existing_people:
            connection.execute('INSERT INTO principals VALUES (?,?,?,?)',
                               (person['id'], person['tenant_id'], person['active'], canonical(person['roles'])))
            changed_acl.add(person['tenant_id'])
    for doc in docs.values():
        if doc['id'] not in existing_docs:
            connection.execute('INSERT INTO documents VALUES (?,?,?,?)',
                               tuple(doc[key] for key in ('id', 'tenant_id', 'document_type', 'owner')))
            changed_content.add(doc['tenant_id'])
    for version in versions.values():
        if version['id'] in existing_versions:
            continue
        _insert_version(connection, version, fts_available)
        changed_content.add(version['tenant_id'])
    for tenant in changed_content:
        connection.execute('UPDATE tenants SET content_revision=content_revision+1 WHERE id=?', (tenant,))
    for tenant in changed_acl:
        connection.execute('UPDATE tenants SET acl_revision=acl_revision+1 WHERE id=?', (tenant,))
    return {tenant: [v['id'] for v in versions.values()
                     if v['tenant_id'] == tenant and v['id'] not in existing_versions]
            for tenant in changed_acl | changed_content}


def _insert_version(connection, version, fts_available):
    fields = ('id', 'document_id', 'tenant_id', 'content', 'content_hash', 'published_at',
              'state', 'valid_from', 'valid_to', 'scope', 'supersedes', 'acl', 'import_digest')
    values = tuple(canonical(version[k]) if k in ('scope', 'acl') else version[k] for k in fields)
    connection.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
    for chunk in version['chunks']:
        connection.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',
                           tuple(chunk[k] for k in ('id', 'version_id', 'text', 'content_hash', 'source_locator')))
        if fts_available:
            connection.execute('INSERT INTO chunks_fts(chunk_id,text) VALUES (?,?)', (chunk['id'], chunk['text']))
    for rule in version['rules']:
        connection.execute('INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?)',
                           (rule['id'], rule['version_id'], rule['key'], rule['value'], rule['unit'],
                            rule['currency'], canonical(rule['scope']), rule['source_chunk_id'],
                            canonical(rule['overrides'])))
