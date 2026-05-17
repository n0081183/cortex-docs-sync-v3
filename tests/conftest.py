"""Shared pytest fixtures.

The catalog fixture mirrors the real shape of one item from
`GET /api/khub/maps?limit=10000` against the live portal — including the
oddities like `subtitle` carrying the version, or `Product` being a list.
"""

from __future__ import annotations

import pytest

from cortex_docs_sync.models import Publication


@pytest.fixture
def raw_catalog_item() -> dict:
    """One realistic catalog item dict (shape verified against live API)."""
    return {
        "id": "abc123",
        "title": "Cortex XSIAM Documentation",
        "mapApiEndpoint": "/api/khub/maps/abc123",
        "metadata": [
            {"key": "Product", "values": ["Cortex XSIAM"]},
            {"key": "Category", "values": ["Administrator Guide"]},
            {"key": "ft:lastEdition", "values": ["2026-05-13"]},
            {"key": "ft:lastTechChange", "values": ["2026-05-12"]},
            {"key": "ft:wordCount", "values": ["12345"]},
            {"key": "ft:prettyUrl", "values": ["Cortex-XSIAM/Cortex-XSIAM-Documentation"]},
            {"key": "subtitle", "values": ["Version: 2.5"]},
        ],
    }


@pytest.fixture
def sample_publication() -> Publication:
    return Publication(
        map_id="abc123",
        title="Cortex XSIAM Documentation",
        products=["Cortex XSIAM"],
        category="Administrator Guide",
        version="2.5",
        last_edition="2026-05-13",
        last_tech_change="2026-05-12",
        word_count=12345,
        pretty_url="Cortex-XSIAM/Cortex-XSIAM-Documentation",
    )
