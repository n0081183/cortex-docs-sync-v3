"""Assemble per-publication HTML files from the FluidTopics topic content.

The output is a single self-contained HTML document per publication, with:

  - A header carrying the absolute deep-link to the publication on the
    portal, so a downstream RAG pipeline can cite it back to the user.
  - Per-topic sections, each with its own breadcrumb and deep-link URL
    embedded as visible text (so document-aware parsers like Docling
    preserve them in the chunked output).
  - The original HTML fragment from the FluidTopics API, untouched.

We deliberately keep the markup minimal — no styling, no scripts. The goal
is high-fidelity content for parsers like Docling, BeautifulSoup, or any
markdown converter; not a browser-presentable page.
"""

from __future__ import annotations

import re
from typing import List

from cortex_docs_sync.models import CORTEX_BASE_URL, Publication

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(title: str, map_id: str, max_len: int = 80) -> str:
    """Build a filesystem-safe filename from a publication title and map_id.

    The map_id is appended after a `__` separator to guarantee uniqueness
    even if two publications happen to share the same title.
    """
    base = _FILENAME_SAFE.sub("-", title.strip()).strip("-")[:max_len]
    if not base:
        base = "publication"
    return f"{base}__{map_id}.html"


def html_escape(text: str) -> str:
    """Escape the five XML-significant characters."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


def build_publication_html(
    pub: Publication,
    topics: List[dict],
    topic_contents: List[str],
) -> str:
    """Compose all topic fragments into one self-contained HTML document.

    `topics` and `topic_contents` are zip-iterated, so they must be parallel
    lists of equal length (caller's responsibility).
    """
    parts: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{html_escape(pub.title)}</title>",
        "</head><body>",
        f"<h1>{html_escape(pub.title)}</h1>",
        f'<p><strong>Source:</strong> '
        f'<a href="{pub.absolute_reader_url}">{pub.absolute_reader_url}</a></p>',
    ]
    if pub.products:
        parts.append(
            f"<p><strong>Product(s):</strong> {html_escape(', '.join(pub.products))}</p>"
        )
    if pub.category:
        parts.append(f"<p><strong>Category:</strong> {html_escape(pub.category)}</p>")
    if pub.version:
        parts.append(f"<p><strong>Version:</strong> {html_escape(pub.version)}</p>")
    if pub.last_edition:
        parts.append(f"<p><strong>Last edition:</strong> {pub.last_edition}</p>")
    parts.append("<hr>")

    for topic, content in zip(topics, topic_contents):
        topic_title = topic.get("title", "")
        breadcrumb = " > ".join(topic.get("breadcrumb", []))
        topic_reader = topic.get("readerUrl", "")
        topic_url = f"{CORTEX_BASE_URL}{topic_reader}" if topic_reader else ""

        parts.append("<section>")
        if topic_title:
            parts.append(f"<h2>{html_escape(topic_title)}</h2>")
        if breadcrumb:
            parts.append(f"<p><em>Breadcrumb:</em> {html_escape(breadcrumb)}</p>")
        if topic_url:
            parts.append(
                f'<p><em>Topic URL:</em> <a href="{topic_url}">{topic_url}</a></p>'
            )
        parts.append(content)
        parts.append("</section>")

    parts.append("</body></html>")
    return "\n".join(parts)
