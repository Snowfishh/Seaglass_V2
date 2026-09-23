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

    def seed(self, manifest_path, principals_path):
        try:
            fixtures = load_fixtures(manifest_path, principals_path)
        except (KeyError, TypeError, OSError, RecursionError) as exc:
            raise ValueError('Invalid trusted fixture metadata') from exc
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            insert_fixtures(connection, *fixtures, self.fts_available)

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
