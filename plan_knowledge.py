"""Bounded learning references; retrieval never changes personal evidence or scores."""
import hashlib
import logging
import time
from urllib.parse import urlsplit
from career_models import LearningReference

logger = logging.getLogger(__name__)


def safe_reference_url(value):
    try:
        parts = urlsplit(value)
        return (parts.scheme in ('http', 'https') and bool(parts.hostname)
                and not parts.username and not parts.password
                and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


def collect_references(requirements, deadline):
    from rag_chroma import retrieve
    references, states = {}, {}
    for row in requirements:
        references[row.id] = []
        if time.monotonic() >= deadline:
            states[row.id] = 'unavailable'
            continue
        try:
            hits = retrieve(f'{row.title}\n{row.jd_quote}'[:1200], top_k=2)
            seen = set()
            for hit in hits:
                meta = hit.get('metadata') or {}
                url = str(meta.get('source_url', ''))
                text = str(hit.get('content', '')).strip()[:600]
                title = str(meta.get('title', '')).strip()
                source = str(meta.get('source', ''))
                if not text or not title or len(url) > 500 or not safe_reference_url(url):
                    continue
                identity = hashlib.sha256((source + '\0' + text).encode()).hexdigest()[:16]
                if identity in seen:
                    continue
                seen.add(identity)
                references[row.id].append(LearningReference(
                    id=identity, title=title[:120], source_url=url, excerpt=text,
                    source=source[:240], updated_at=str(meta.get('updated_at', ''))[:10]))
                if len(references[row.id]) >= 2:
                    break
            states[row.id] = 'available' if references[row.id] else 'empty'
        except Exception as exc:
            logger.warning('plan_retrieval_failed type=%s', type(exc).__name__)
            states[row.id] = 'unavailable'
    return references, states
