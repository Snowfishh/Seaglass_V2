"""Validate trusted fixture metadata completely before starting an import."""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aspire_brain.knowledge.chunking import chunk_text

SCOPE_KEYS = frozenset({'workflow_id', 'jurisdiction', 'worker_type', 'project', 'cost_centre'})
ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def stable_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError('Invalid stable identifier')
    return value


def checked_scope(value):
    if not isinstance(value, dict) or set(value) - SCOPE_KEYS:
        raise ValueError('Invalid scope keys')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in value.values()):
        raise ValueError('Invalid scope values')
    return dict(value)


def checked_roles(value, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError('Explicit role ACL required')
    if len(value) > 32 or len(value) != len(set(value)):
        raise ValueError('Invalid role list')
    return [stable_id(role) for role in value]


def checked_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('Expected ISO business date')
    return date.fromisoformat(value).isoformat()


def bounded_string(value, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Invalid text metadata')
    return value


def unique(items, name):
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f'Invalid {name}')
        item_id = stable_id(item.get('id'))
        if item_id in result:
            raise ValueError(f'Duplicate {name} identifier')
        result[item_id] = item
    return result


def check_cycles(edges):
    visited, pending = set(), set()

    def visit(node):
        if node in pending:
            raise ValueError('Cyclic precedence relation')
        if node in visited:
            return
        pending.add(node)
        for target in edges.get(node, []):
            visit(target)
        pending.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)


def validate_rule(rule, version, chunks):
    allowed = {'id', 'key', 'value', 'unit', 'currency', 'scope', 'source_paragraph', 'overrides'}
    if set(rule) - allowed:
        raise ValueError('Unknown rule metadata')
    stable_id(rule['id'])
    stable_id(rule['key'])
    bounded_string(rule['unit'], 50)
    checked_scope(rule['scope'])
    if any(k in version['scope'] and version['scope'][k] != v for k, v in rule['scope'].items()):
        raise ValueError('Rule scope contradicts version')
    raw = rule['value']
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValueError('Rule value must be a finite decimal')
    try:
        amount = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError('Rule value must be a finite decimal') from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError('Rule value must be finite and nonnegative')
    if rule.get('currency') is not None and not re.fullmatch(r'[A-Z]{3}', rule['currency']):
        raise ValueError('Invalid currency')
    paragraph = rule['source_paragraph']
    if isinstance(paragraph, bool) or not isinstance(paragraph, int):
        raise ValueError('Source paragraph must be an integer')
    chunk_id = f"{version['id']}:p{paragraph}"
    if chunk_id not in {chunk['id'] for chunk in chunks}:
        raise ValueError('Rule source paragraph does not exist')
    overrides = rule.get('overrides', [])
    if not isinstance(overrides, list) or len(overrides) != len(set(overrides)):
        raise ValueError('Invalid override relations')
    for target in overrides:
        stable_id(target)
    return {**rule, 'value': str(amount), 'currency': rule.get('currency'),
            'overrides': overrides, 'source_chunk_id': chunk_id, 'version_id': version['id']}


def validate_version(raw, directory):
    allowed = {'id', 'document_id', 'tenant_id', 'file', 'published_at', 'state',
               'valid_from', 'valid_to', 'scope', 'supersedes', 'acl', 'rules'}
    if set(raw) - allowed:
        raise ValueError('Unknown version metadata')
    for field in ('id', 'document_id', 'tenant_id'):
        stable_id(raw[field])
    checked_roles(raw.get('acl'))
    checked_scope(raw['scope'])
    start = checked_date(raw['valid_from'])
    end = checked_date(raw['valid_to']) if raw.get('valid_to') else None
    if end and start >= end:
        raise ValueError('Empty or reversed effective interval')
    published = datetime.fromisoformat(raw['published_at'].replace('Z', '+00:00'))
    if published.tzinfo is None:
        raise ValueError('Publication timestamp requires timezone')
    if raw['state'] not in {'approved', 'draft', 'withdrawn'}:
        raise ValueError('Invalid publication state')
    if raw.get('supersedes') is not None:
        stable_id(raw['supersedes'])
    relative = Path(bounded_string(raw['file']))
    path = (directory / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(directory):
        raise ValueError('Fixture path must remain inside manifest directory')
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError('Missing or oversized fixture file')
    content = path.read_text(encoding='utf-8')
    if not content.strip():
        raise ValueError('Empty document')
    version = {**raw, 'valid_from': start, 'valid_to': end, 'content': content,
               'content_hash': hashlib.sha256(content.encode()).hexdigest(),
               'supersedes': raw.get('supersedes')}
    chunks = chunk_text(raw['id'], content)
    rules = [validate_rule(rule, version, chunks) for rule in raw.get('rules', [])]
    digest_data = {**version, 'rules': rules}
    digest_data.pop('file')
    return {**version, 'rules': rules, 'chunks': chunks,
            'import_digest': hashlib.sha256(canonical(digest_data).encode()).hexdigest()}


def load_fixtures(manifest_path, principals_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    principals = json.loads(Path(principals_path).read_text())
    if not isinstance(manifest, dict) or set(manifest) != {'documents', 'versions'}:
        raise ValueError('Manifest requires documents and versions')
    docs = unique(manifest['documents'], 'document')
    people = unique(principals, 'principal')
    raw_versions = unique(manifest['versions'], 'version')
    for person in people.values():
        if set(person) != {'id', 'tenant_id', 'active', 'roles'} or type(person['active']) is not bool:
            raise ValueError('Invalid principal metadata')
        stable_id(person['tenant_id'])
        checked_roles(person['roles'], allow_empty=True)
    for doc in docs.values():
        if set(doc) != {'id', 'tenant_id', 'document_type', 'owner'}:
            raise ValueError('Invalid document metadata')
        stable_id(doc['tenant_id'])
        bounded_string(doc['document_type'])
        bounded_string(doc['owner'])
    versions = {key: validate_version(v, manifest_path.parent) for key, v in raw_versions.items()}
    unique([rule for version in versions.values() for rule in version['rules']], 'rule')
    return docs, people, versions
