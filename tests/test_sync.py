"""Tests for the sync orchestration with a mocked HTTP client."""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from cortex_docs_sync import sync as sync_module
from cortex_docs_sync.catalog import CatalogSnapshot
from cortex_docs_sync.models import Publication, PublicationFilter
from cortex_docs_sync.sync import (
    fetch_publication,
    resolve_output_path,
    run_sync,
)

# Minimal product_dir_map for tests — derived from a snapshot so it stays
# consistent with the catalog module.
_TEST_SNAP = CatalogSnapshot.build({"Cortex XSIAM", "Cortex XDR", "Cortex XDR Agent"})
TEST_DIR_MAP = _TEST_SNAP.product_dir_map


# ── resolve_output_path ─────────────────────────────────────────────────────

def test_resolve_path_picks_first_known_product():
    pub = Publication(
        map_id="x", title="My Doc", products=["Unknown", "Cortex XDR"],
        category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    out = resolve_output_path(pub, Path("/tmp/data"), TEST_DIR_MAP)
    assert out is not None
    assert "xdr" in str(out)
    assert str(out).endswith("My-Doc__x.html")


def test_resolve_path_returns_none_when_no_product_known():
    pub = Publication(
        map_id="x", title="t", products=["Some Other Product"],
        category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    assert resolve_output_path(pub, Path("/tmp/data"), TEST_DIR_MAP) is None


def test_resolve_path_supports_custom_product_map():
    custom_snap = CatalogSnapshot.build({"Cortex AgentiX"})
    pub = Publication(
        map_id="x", title="t", products=["Cortex AgentiX"],
        category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    out = resolve_output_path(pub, Path("/tmp/data"), custom_snap.product_dir_map)
    assert out is not None
    assert "agentix" in str(out)


# ── fetch_publication ───────────────────────────────────────────────────────

def test_fetch_publication_writes_html(tmp_path, sample_publication):
    client = MagicMock()
    client.get_topics.return_value = [
        {"id": "t1", "title": "Intro", "breadcrumb": ["Intro"], "readerUrl": ""},
    ]
    client.get_topic_content.return_value = "<p>Hello world</p>"

    out = tmp_path / "doc.html"
    topic_count, written = fetch_publication(client, sample_publication, out)

    assert topic_count == 1
    assert written > 0
    assert out.exists()
    body = out.read_text()
    assert "Hello world" in body
    assert "<h2>Intro</h2>" in body


def test_fetch_publication_handles_topic_errors_gracefully(tmp_path, sample_publication):
    client = MagicMock()
    client.get_topics.return_value = [
        {"id": "ok", "title": "OK topic", "breadcrumb": ["OK topic"]},
        {"id": "boom", "title": "Bad topic", "breadcrumb": ["Bad topic"]},
    ]

    def get_content(map_id, topic_id):
        if topic_id == "boom":
            raise RuntimeError("simulated network blip")
        return "<p>good</p>"

    client.get_topic_content.side_effect = get_content
    out = tmp_path / "doc.html"
    topic_count, _ = fetch_publication(client, sample_publication, out)

    assert topic_count == 2
    body = out.read_text()
    assert "<p>good</p>" in body
    assert "FETCH ERROR" in body


def test_fetch_publication_skips_when_no_topics(tmp_path, sample_publication):
    client = MagicMock()
    client.get_topics.return_value = []
    out = tmp_path / "doc.html"
    topic_count, written = fetch_publication(client, sample_publication, out)
    assert (topic_count, written) == (0, 0)
    assert not out.exists()


# ── sync() — end-to-end with mocked client ──────────────────────────────────

class _FakeClient:
    def __init__(self, catalog, topics, content):
        self._catalog = catalog
        self._topics = topics
        self._content = content
        self.list_calls = 0
        self.topic_calls = 0
        self.content_calls = 0

    def list_publications(self):
        self.list_calls += 1
        return self._catalog

    def get_topics(self, map_id):
        self.topic_calls += 1
        return self._topics.get(map_id, [])

    def get_topic_content(self, map_id, topic_id):
        self.content_calls += 1
        return self._content


@pytest.fixture
def patched_client(monkeypatch):
    holder = {}

    def install(catalog, topics_map, content):
        fake = _FakeClient(catalog, topics_map, content)
        monkeypatch.setattr(sync_module, "CortexDocsClient", lambda **kw: fake)
        holder["client"] = fake
        return fake

    return install


def _xsiam_dir_map():
    return CatalogSnapshot.build({"Cortex XSIAM"}).product_dir_map


def test_sync_full_first_run_fetches_everything(tmp_path, patched_client, sample_publication):
    fake = patched_client(
        catalog=[sample_publication],
        topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
        content="<p>content</p>",
    )
    stats = run_sync(
        output_dir=tmp_path,
        state_file=tmp_path / "state.json",
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(),
        rate_limit_rps=100.0,
    )
    assert stats.fetched == 1
    assert stats.skipped_unchanged == 0
    assert fake.list_calls == 1
    assert fake.topic_calls == 1
    assert fake.content_calls == 1


def test_sync_uses_preloaded_catalog(tmp_path, patched_client, sample_publication):
    """When preloaded_catalog is passed, list_publications must NOT be called."""
    fake = patched_client(
        catalog=[],   # would return nothing if called
        topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
        content="<p>content</p>",
    )
    stats = run_sync(
        output_dir=tmp_path,
        state_file=tmp_path / "state.json",
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(),
        rate_limit_rps=100.0,
        preloaded_catalog=[sample_publication],  # injected — no extra fetch
    )
    assert stats.fetched == 1
    assert fake.list_calls == 0    # catalog NOT re-fetched


def test_sync_second_run_skips_unchanged(tmp_path, patched_client, sample_publication):
    state_file = tmp_path / "state.json"

    fake1 = patched_client(
        catalog=[sample_publication],
        topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
        content="<p>content</p>",
    )
    run_sync(
        output_dir=tmp_path, state_file=state_file,
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(), rate_limit_rps=100.0,
    )
    assert fake1.content_calls == 1

    fake2 = patched_client(
        catalog=[sample_publication],
        topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
        content="<p>content</p>",
    )
    stats = run_sync(
        output_dir=tmp_path, state_file=state_file,
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(), rate_limit_rps=100.0,
    )
    assert stats.skipped_unchanged == 1
    assert stats.fetched == 0
    assert fake2.list_calls == 1
    assert fake2.content_calls == 0


def test_sync_dry_run_does_not_pull_content(tmp_path, patched_client, sample_publication):
    fake = patched_client(
        catalog=[sample_publication],
        topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
        content="<p>content</p>",
    )
    stats = run_sync(
        output_dir=tmp_path, state_file=tmp_path / "state.json",
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(), rate_limit_rps=100.0, dry_run=True,
    )
    assert stats.fetched == 0
    assert fake.list_calls == 1
    assert fake.topic_calls == 0
    assert fake.content_calls == 0


def test_sync_full_refetch_ignores_state(tmp_path, patched_client, sample_publication):
    state_file = tmp_path / "state.json"
    for _ in range(2):
        fake = patched_client(
            catalog=[sample_publication],
            topics_map={"abc123": [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"]}]},
            content="<p>content</p>",
        )
        stats = run_sync(
            output_dir=tmp_path, state_file=state_file,
            pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
            product_dir_map=_xsiam_dir_map(), rate_limit_rps=100.0,
            full_refetch=True,
        )
        assert stats.fetched == 1
    assert fake.content_calls == 1


def test_sync_max_publications_limits_count(tmp_path, patched_client):
    publications = [
        Publication(
            map_id=f"id-{i}", title=f"Doc {i}", products=["Cortex XSIAM"],
            category="Administrator Guide", version=None,
            last_edition="2026-05-01", last_tech_change=None,
            word_count=200, pretty_url=f"x/doc-{i}",
        )
        for i in range(5)
    ]
    fake = patched_client(
        catalog=publications,
        topics_map={p.map_id: [{"id": "t", "title": "x", "breadcrumb": []}]
                    for p in publications},
        content="<p>x</p>",
    )
    stats = run_sync(
        output_dir=tmp_path, state_file=tmp_path / "state.json",
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=_xsiam_dir_map(), rate_limit_rps=100.0,
        max_publications=2,
    )
    assert stats.fetched == 2
    assert fake.content_calls == 2
