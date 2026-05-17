"""Tests for `Publication` and `PublicationFilter`."""

from __future__ import annotations

from cortex_docs_sync.client import CortexDocsClient
from cortex_docs_sync.models import CORTEX_BASE_URL, Publication, PublicationFilter


# ── Publication parsing ─────────────────────────────────────────────────────

def test_parse_publication_extracts_core_fields(raw_catalog_item):
    pub = CortexDocsClient._parse_publication(raw_catalog_item)
    assert pub.map_id == "abc123"
    assert pub.title == "Cortex XSIAM Documentation"
    assert pub.products == ["Cortex XSIAM"]
    assert pub.category == "Administrator Guide"
    assert pub.last_edition == "2026-05-13"
    assert pub.last_tech_change == "2026-05-12"
    assert pub.word_count == 12345
    assert pub.version == "2.5"


def test_diff_key_prefers_tech_change_over_last_edition(raw_catalog_item):
    pub = CortexDocsClient._parse_publication(raw_catalog_item)
    assert pub.diff_key == "2026-05-12"


def test_diff_key_falls_back_to_last_edition_when_no_tech_change():
    pub = Publication(
        map_id="x", title="t", products=[], category=None, version=None,
        last_edition="2026-01-01", last_tech_change=None,
        word_count=None, pretty_url="",
    )
    assert pub.diff_key == "2026-01-01"


def test_diff_key_empty_when_no_dates():
    pub = Publication(
        map_id="x", title="t", products=[], category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    assert pub.diff_key == ""


def test_reader_url_builders(sample_publication):
    assert sample_publication.reader_url == "/r/Cortex-XSIAM/Cortex-XSIAM-Documentation"
    assert sample_publication.absolute_reader_url == (
        f"{CORTEX_BASE_URL}/r/Cortex-XSIAM/Cortex-XSIAM-Documentation"
    )


def test_reader_url_empty_when_no_pretty_url():
    pub = Publication(
        map_id="x", title="t", products=[], category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    assert pub.reader_url == ""
    assert pub.absolute_reader_url == CORTEX_BASE_URL


def test_parse_handles_missing_optional_fields():
    item = {"id": "y", "title": "Bare", "metadata": []}
    pub = CortexDocsClient._parse_publication(item)
    assert pub.map_id == "y"
    assert pub.products == []
    assert pub.category is None
    assert pub.version is None
    assert pub.word_count is None
    assert pub.pretty_url == ""


def test_parse_word_count_handles_garbage():
    item = {
        "id": "y", "title": "t",
        "metadata": [{"key": "ft:wordCount", "values": ["not-a-number"]}],
    }
    pub = CortexDocsClient._parse_publication(item)
    assert pub.word_count is None


def test_parse_version_from_xinfo_when_no_subtitle():
    item = {
        "id": "y", "title": "t",
        "metadata": [
            {"key": "xinfo:version_major", "values": ["8"]},
            {"key": "xinfo:version_minor", "values": ["6"]},
        ],
    }
    pub = CortexDocsClient._parse_publication(item)
    assert pub.version == "8.6"


# ── PublicationFilter ───────────────────────────────────────────────────────

def test_filter_matches_when_product_listed(sample_publication):
    f = PublicationFilter(products=["Cortex XSIAM"])
    assert f.matches(sample_publication) is True


def test_filter_rejects_non_listed_product(sample_publication):
    f = PublicationFilter(products=["Cortex XDR"])
    assert f.matches(sample_publication) is False


def test_filter_excludes_release_notes_by_default():
    pub = Publication(
        map_id="x", title="t", products=["Cortex XSIAM"],
        category="Content Update Release Notes", version=None,
        last_edition=None, last_tech_change=None,
        word_count=500, pretty_url="x",
    )
    assert PublicationFilter().matches(pub) is False


def test_filter_drops_below_min_word_count():
    pub = Publication(
        map_id="x", title="t", products=["Cortex XSIAM"],
        category="Administrator Guide", version=None,
        last_edition=None, last_tech_change=None,
        word_count=50, pretty_url="x",
    )
    assert PublicationFilter(min_word_count=100).matches(pub) is False


def test_filter_keeps_when_word_count_unknown():
    pub = Publication(
        map_id="x", title="t", products=["Cortex XSIAM"],
        category="Administrator Guide", version=None,
        last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="x",
    )
    assert PublicationFilter(min_word_count=100).matches(pub) is True


def test_filter_categories_whitelist():
    pub_admin = Publication(
        map_id="x", title="t", products=["Cortex XSIAM"],
        category="Administrator Guide", version=None,
        last_edition=None, last_tech_change=None,
        word_count=500, pretty_url="x",
    )
    pub_release = Publication(
        map_id="y", title="t", products=["Cortex XSIAM"],
        category="Release Notes", version=None,
        last_edition=None, last_tech_change=None,
        word_count=500, pretty_url="y",
    )
    f = PublicationFilter(
        categories=["Administrator Guide"],
        exclude_categories=(),
    )
    assert f.matches(pub_admin) is True
    assert f.matches(pub_release) is False
