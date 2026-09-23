"""Deterministic paragraph chunks; document instructions are never executable."""
import hashlib
import re


def chunk_text(version_id: str, content: str) -> list[dict]:
    heading = 'Document'
    result = []
    for index, paragraph in enumerate(re.split(r'\n\s*\n', content.strip()), 1):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        first = paragraph.splitlines()[0]
        if first.startswith('#'):
            heading = first.lstrip('#').strip()
        result.append({'id': f'{version_id}:p{index}', 'version_id': version_id,
                       'text': paragraph, 'content_hash': hashlib.sha256(paragraph.encode()).hexdigest(),
                       'source_locator': f'{heading} · paragraph {index}'})
    return result
