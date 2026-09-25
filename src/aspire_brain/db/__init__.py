"""SQLite storage. Existing incompatible databases are never automatically reset."""
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .importer import insert_fixtures
from .schema import FTS_SCHEMA, SCHEMA, SCHEMA_VERSION
from .validation import canonical, checked_roles, load_fixtures


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.fts_available = False

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=15000')
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection, connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'app_meta' not in tables:
                raise ValueError('Unrecognized database schema; manual migration required')
            if 'app_meta' in tables:
                version = connection.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
                if version is None or version[0] != SCHEMA_VERSION:
                    raise ValueError('Incompatible database schema; manual migration required')
            connection.executescript(SCHEMA)
            connection.execute('INSERT OR IGNORE INTO app_meta VALUES (?,?)', ('schema_version', SCHEMA_VERSION))
            try:
                connection.execute(FTS_SCHEMA)
                self.fts_available = True
            except sqlite3.OperationalError as exc:
                if 'no such module: fts5' not in str(exc).lower():
                    raise
                self.fts_available = False

    def seed(self, manifest_path, principals_path, audit=None):
        try:
            fixtures = load_fixtures(manifest_path, principals_path)
        except (KeyError, TypeError, OSError, RecursionError) as exc:
            raise ValueError('Invalid trusted fixture metadata') from exc
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            populated = connection.execute('SELECT 1 FROM principals LIMIT 1').fetchone() is not None
            changes = insert_fixtures(connection, *fixtures, self.fts_available)
            if changes and populated and audit is None:
                raise ValueError('Subsequent imports require an audit writer')
            if audit is not None:
                for tenant_id, version_ids in sorted(changes.items()):
                    audit.append_in_transaction(connection, tenant_id, 'local_admin', uuid4().hex,
                                                'metadata_change', {'operation': 'trusted_import',
                                                                    'version_ids': version_ids})

    def set_acl(self, version_id, roles, audit, principal_id='local_admin'):
        roles = checked_roles(roles, allow_empty=True)
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT tenant_id FROM versions WHERE id=?', (version_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown version')
            audit.append_in_transaction(connection, row['tenant_id'], principal_id, uuid4().hex,
                                        'metadata_change', {'operation': 'set_acl', 'version_ids': [version_id]})
            connection.execute('UPDATE versions SET acl=? WHERE id=?', (canonical(roles), version_id))
            connection.execute('UPDATE tenants SET acl_revision=acl_revision+1 WHERE id=?', (row['tenant_id'],))

    def revoke(self, version_id, audit, principal_id='local_admin'):
        self.set_acl(version_id, [], audit, principal_id)

    def set_principal_roles(self, principal_id, roles, audit):
        roles = checked_roles(roles, allow_empty=True)
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT tenant_id FROM principals WHERE id=?', (principal_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown principal')
            audit.append_in_transaction(connection, row['tenant_id'], 'local_admin', uuid4().hex,
                                        'metadata_change', {'operation': 'set_principal_roles'})
            connection.execute('UPDATE principals SET roles=? WHERE id=?', (canonical(roles), principal_id))
            connection.execute('UPDATE tenants SET acl_revision=acl_revision+1 WHERE id=?', (row['tenant_id'],))

    def set_publication_state(self, version_id, state, audit, principal_id='local_admin'):
        if state not in {'approved', 'draft', 'withdrawn'}:
            raise ValueError('Invalid publication state')
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT tenant_id,state FROM versions WHERE id=?', (version_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown version')
            if row['state'] == state:
                return
            audit.append_in_transaction(connection, row['tenant_id'], principal_id, uuid4().hex,
                                        'metadata_change', {'operation': 'set_publication_state',
                                                            'version_ids': [version_id], 'status': state})
            connection.execute('UPDATE versions SET state=? WHERE id=?', (state, version_id))
            connection.execute('UPDATE tenants SET content_revision=content_revision+1 WHERE id=?',
                               (row['tenant_id'],))

    def set_active(self, target_id, active, audit, principal_id='local_admin'):
        if type(active) is not bool:
            raise ValueError('Active state must be boolean')
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT tenant_id,active FROM principals WHERE id=?', (target_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown principal')
            if bool(row['active']) == active:
                return
            audit.append_in_transaction(connection, row['tenant_id'], principal_id, uuid4().hex,
                                        'metadata_change', {'operation': 'set_active',
                                                            'status': 'active' if active else 'disabled'})
            connection.execute('UPDATE principals SET active=? WHERE id=?', (active, target_id))
            connection.execute('UPDATE tenants SET acl_revision=acl_revision+1 WHERE id=?', (row['tenant_id'],))
