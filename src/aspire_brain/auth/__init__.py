"""Central authorization; callers' cached role/tenant claims are never trusted."""
import json
from contextlib import closing


class AccessDenied(Exception):
    """Unknown and inaccessible objects deliberately share this exception."""


ACL_PREDICATE = '''
v.tenant_id = p.tenant_id AND p.id = ? AND p.active = 1
AND EXISTS (
 SELECT 1 FROM json_each(v.acl) grant_role
 JOIN json_each(p.roles) user_role ON grant_role.value = user_role.value
)
'''


def principal_id(principal):
    value = principal.get('id') if isinstance(principal, dict) else None
    if not isinstance(value, str):
        raise AccessDenied('Access unavailable')
    return value


def decode_version(row):
    value = dict(row)
    for key in ('scope', 'acl'):
        if key in value:
            value[key] = json.loads(value[key])
    return value


class AuthService:
    def __init__(self, db):
        self.db = db

    def principal(self, identity):
        with closing(self.db.connect()) as connection:
            row = connection.execute('SELECT * FROM principals WHERE id=? AND active=1', (identity,)).fetchone()
        if row is None:
            raise AccessDenied('Access unavailable')
        return {'id': row['id'], 'tenant_id': row['tenant_id'], 'active': bool(row['active']),
                'roles': json.loads(row['roles'])}

    def readable(self, principal, version_id):
        with closing(self.db.connect()) as connection:
            row = connection.execute(f'''SELECT 1 FROM versions v JOIN principals p
                ON p.tenant_id=v.tenant_id WHERE {ACL_PREDICATE} AND v.id=?''',
                                     (principal_id(principal), version_id)).fetchone()
        return row is not None

    def revisions(self, principal):
        with closing(self.db.connect()) as connection:
            row = connection.execute('''SELECT t.acl_revision,t.content_revision FROM tenants t
                JOIN principals p ON p.tenant_id=t.id WHERE p.id=? AND p.active=1''',
                                     (principal_id(principal),)).fetchone()
        if row is None:
            raise AccessDenied('Access unavailable')
        return tuple(row)

    def authorized_versions(self, principal):
        self.principal(principal_id(principal))
        with closing(self.db.connect()) as connection:
            rows = connection.execute(f'''SELECT v.* FROM versions v JOIN principals p
                ON p.tenant_id=v.tenant_id WHERE {ACL_PREDICATE} ORDER BY v.id''',
                                      (principal_id(principal),)).fetchall()
        versions = [decode_version(row) for row in rows]
        readable_ids = {version['id'] for version in versions}
        return [{**version, 'supersedes': version['supersedes'] if version['supersedes'] in readable_ids else None}
                for version in versions]

    def source(self, principal, version_id, chunk_id):
        with closing(self.db.connect()) as connection:
            row = connection.execute(f'''SELECT v.id AS version_id,v.document_id,v.state,
                v.valid_from,v.valid_to,c.id AS chunk_id,c.text,c.content_hash,c.source_locator
                FROM chunks c JOIN versions v ON v.id=c.version_id
                JOIN principals p ON p.tenant_id=v.tenant_id
                WHERE {ACL_PREDICATE} AND v.id=? AND c.id=?''',
                                     (principal_id(principal), version_id, chunk_id)).fetchone()
        if row is None:
            raise AccessDenied('Access unavailable')
        return dict(row)

    def history(self, principal, document_id):
        permitted = self.authorized_versions(principal)
        selected = [version for version in permitted if version['document_id'] == document_id]
        if not selected:
            raise AccessDenied('Access unavailable')
        visible_ids = {version['id'] for version in permitted}
        with closing(self.db.connect()) as connection:
            rules = connection.execute(f'''SELECT r.* FROM rules r JOIN versions v ON v.id=r.version_id
                JOIN principals p ON p.tenant_id=v.tenant_id WHERE {ACL_PREDICATE}''',
                                       (principal_id(principal),)).fetchall()
        visible_rules = {row['id'] for row in rules}
        results = []
        for version in selected:
            clean = {key: value for key, value in version.items() if key not in {'content', 'acl', 'import_digest'}}
            clean['supersedes'] = version['supersedes'] if version['supersedes'] in visible_ids else None
            clean['rules'] = [{**dict(rule), 'scope': json.loads(rule['scope']),
                               'overrides': [i for i in json.loads(rule['overrides']) if i in visible_rules]}
                              for rule in rules if rule['version_id'] == version['id']]
            results.append(clean)
        return sorted(results, key=lambda version: (version['valid_from'], version['id']))
