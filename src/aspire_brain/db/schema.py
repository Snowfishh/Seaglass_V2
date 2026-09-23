SCHEMA_VERSION = '1'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tenants(
 id TEXT PRIMARY KEY, acl_revision INTEGER NOT NULL DEFAULT 0,
 content_revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS principals(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 active INTEGER NOT NULL CHECK(active IN (0,1)), roles TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 document_type TEXT NOT NULL, owner TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 tenant_id TEXT NOT NULL REFERENCES tenants(id), content TEXT NOT NULL,
 content_hash TEXT NOT NULL, published_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('approved','draft','withdrawn')),
 valid_from TEXT NOT NULL, valid_to TEXT, scope TEXT NOT NULL,
 supersedes TEXT REFERENCES versions(id) DEFERRABLE INITIALLY DEFERRED,
 acl TEXT NOT NULL, import_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 text TEXT NOT NULL, content_hash TEXT NOT NULL, source_locator TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 key TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL, currency TEXT,
 scope TEXT NOT NULL, source_chunk_id TEXT NOT NULL REFERENCES chunks(id),
 overrides TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS versions_tenant ON versions(tenant_id, state, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS chunks_version ON chunks(version_id);
CREATE INDEX IF NOT EXISTS rules_version ON rules(version_id);
'''

FTS_SCHEMA = '''
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text);
'''
