"""ACL predicates precede ranking/limit; FTS syntax never comes from raw input."""
import json
import re
from contextlib import closing
from datetime import date
from zoneinfo import ZoneInfo
from datetime import datetime

from aspire_brain.auth import ACL_PREDICATE, AuthService, principal_id

SCOPE_PREDICATE = '''NOT EXISTS (
 SELECT 1 FROM json_each(v.scope) dimension
 WHERE json_extract(?, '$.' || dimension.key) IS NULL
 OR json_extract(?, '$.' || dimension.key) != dimension.value
)'''

FIELDS = '''v.id AS version_id,v.document_id,c.id AS chunk_id,
 c.text,c.content_hash,c.source_locator'''


def _context(case_date, scope):
    # Import lazily to keep chunking usable while the DB importer loads.
    from aspire_brain.db.validation import canonical, checked_date, checked_scope
    day = case_date.isoformat() if isinstance(case_date, date) else case_date
    day = checked_date(day or datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat())
    return day, canonical(checked_scope(scope or {}))


def _tokens(question):
    if not isinstance(question, str) or len(question) > 4000:
        raise ValueError('Question must be at most 4000 characters')
    return list(dict.fromkeys(re.findall(r'[^\W_]+', question.lower(), re.UNICODE)))[:32]


class Retriever:
    def __init__(self, db):
        self.db = db
        self.mode = 'fts5_lexical' if db.fts_available else 'authorized_lexical_fallback'

    def _predicate(self):
        return f'''{ACL_PREDICATE} AND v.state='approved'
            AND v.valid_from<=? AND (v.valid_to IS NULL OR v.valid_to>?)
            AND {SCOPE_PREDICATE}'''

    def _params(self, principal, case_date, scope):
        AuthService(self.db).principal(principal_id(principal))
        day, encoded_scope = _context(case_date, scope)
        return (principal_id(principal), day, day, encoded_scope, encoded_scope)

    def search(self, principal, question, case_date=None, scope=None, top_k=5, max_chars=8000):
        if type(top_k) is not int or not 1 <= top_k <= 50 or type(max_chars) is not int or not 1 <= max_chars <= 50000:
            raise ValueError('Invalid retrieval bounds')
        tokens = _tokens(question)
        params = self._params(principal, case_date, scope)
        if not tokens:
            return []
        with closing(self.db.connect()) as connection:
            if self.db.fts_available:
                expression = ' OR '.join('"' + token + '"' for token in tokens)
                rows = connection.execute(f'''SELECT {FIELDS} FROM chunks_fts
                    JOIN chunks c ON c.id=chunks_fts.chunk_id JOIN versions v ON v.id=c.version_id
                    JOIN principals p ON p.tenant_id=v.tenant_id
                    WHERE {self._predicate()} AND chunks_fts MATCH ?
                    ORDER BY bm25(chunks_fts),c.id LIMIT ?''', (*params, expression, top_k)).fetchall()
            else:
                rows = self._fallback(connection, tokens, params, top_k)
        remaining, result = max_chars, []
        for row in rows:
            if remaining <= 0:
                break
            text = row['text'][:remaining]
            result.append({**dict(row), 'text': text})
            remaining -= len(text)
        return result

    def _fallback(self, connection, tokens, params, top_k):
        rows = connection.execute(f'''SELECT {FIELDS} FROM chunks c
            JOIN versions v ON v.id=c.version_id JOIN principals p ON p.tenant_id=v.tenant_id
            WHERE {self._predicate()}''', params).fetchall()
        scored = [(sum(row['text'].lower().count(token) for token in tokens), dict(row)) for row in rows]
        return [row for score, row in sorted(scored, key=lambda pair: (-pair[0], pair[1]['chunk_id']))
                if score > 0][:top_k]

    def all_rules(self, principal, case_date=None, scope=None):
        params = self._params(principal, case_date, scope)
        rule_scope = SCOPE_PREDICATE.replace('v.scope', 'r.scope')
        with closing(self.db.connect()) as connection:
            rows = connection.execute(f'''SELECT r.*, {FIELDS},v.scope AS version_scope,
                v.supersedes,v.valid_from,v.valid_to,v.state,v.tenant_id
                FROM rules r JOIN versions v ON v.id=r.version_id
                JOIN chunks c ON c.id=r.source_chunk_id
                JOIN principals p ON p.tenant_id=v.tenant_id
                WHERE {self._predicate()} AND {rule_scope} ORDER BY r.id''',
                                      (*params, params[-2], params[-1])).fetchall()
            visible_rules = {row[0] for row in connection.execute(f'''SELECT r.id FROM rules r
                JOIN versions v ON v.id=r.version_id JOIN principals p ON p.tenant_id=v.tenant_id
                WHERE {ACL_PREDICATE}''', (principal_id(principal),))}
            visible_versions = {row[0] for row in connection.execute(f'''SELECT v.id FROM versions v
                JOIN principals p ON p.tenant_id=v.tenant_id WHERE {ACL_PREDICATE}''',
                                                                    (principal_id(principal),))}
        return [{**dict(row), 'scope': json.loads(row['scope']), 'version_scope': json.loads(row['version_scope']),
                 'overrides': [target for target in json.loads(row['overrides']) if target in visible_rules],
                 'supersedes': row['supersedes'] if row['supersedes'] in visible_versions else None}
                for row in rows]
