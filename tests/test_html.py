"""Tests for the HTML assembly layer."""

from __future__ import annotations

from cortex_docs_sync.html_assembly import (
    build_publication_html,
    html_escape,
    safe_filename,
)


# ── safe_filename ───────────────────────────────────────────────────────────

def test_safe_filename_strips_unsafe_chars():
    fn = safe_filename("Cortex XDR Documentation: 8.x", "abc123")
    assert " " not in fn
    assert ":" not in fn
    assert fn.endswith("__abc123.html")


def test_safe_filename_handles_empty_title():
    fn = safe_filename("", "abc123")
    assert fn == "publication__abc123.html"


def test_safe_filename_truncates_long_title():
    fn = safe_filename("X" * 500, "abc123")
    assert "__abc123.html" in fn
    # base is capped at max_len=80
    base = fn.split("__")[0]
    assert len(base) <= 80


def test_safe_filename_appends_map_id_for_uniqueness():
    fn1 = safe_filename("Same Title", "id1")
    fn2 = safe_filename("Same Title", "id2")
    assert fn1 != fn2


# ── html_escape ─────────────────────────────────────────────────────────────

def test_html_escape_handles_all_xml_specials():
    assert html_escape("a & b") == "a &amp; b"
    assert html_escape("<x>") == "&lt;x&gt;"
    assert html_escape('"hi"') == "&quot;hi&quot;"
    assert html_escape("don't") == "don&#39;t"


# ── build_publication_html ──────────────────────────────────────────────────

def test_html_includes_source_deep_link(sample_publication):
    topics = [{"id": "t1", "title": "Intro", "breadcrumb": ["Intro"], "readerUrl": ""}]
    html = build_publication_html(sample_publication, topics, ["<p>X</p>"])
    assert sample_publication.absolute_reader_url in html
    assert "<h1>Cortex XSIAM Documentation</h1>" in html


def test_html_embeds_metadata_block(sample_publication):
    html = build_publication_html(sample_publication, [], [])
    assert "Product(s):</strong> Cortex XSIAM" in html
    assert "Category:</strong> Administrator Guide" in html
    assert "Version:</strong> 2.5" in html
    assert "Last edition:</strong> 2026-05-13" in html


def test_html_per_topic_section(sample_publication):
    topics = [{
        "id": "t1",
        "title": "What is XSIAM",
        "breadcrumb": ["Intro", "What is XSIAM"],
        "readerUrl": "/r/Cortex-XSIAM/Cortex-XSIAM-Documentation/What-is-XSIAM",
    }]
    contents = ["<p>XSIAM is a SIEM/SOAR platform.</p>"]
    html = build_publication_html(sample_publication, topics, contents)

    assert "<h2>What is XSIAM</h2>" in html
    assert "Intro &gt; What is XSIAM" in html
    assert "/r/Cortex-XSIAM/Cortex-XSIAM-Documentation/What-is-XSIAM" in html
    assert "<p>XSIAM is a SIEM/SOAR platform.</p>" in html


def test_html_escapes_dangerous_metadata():
    """Title with HTML chars must not break the document."""
    from cortex_docs_sync.models import Publication
    pub = Publication(
        map_id="x", title='Cortex <evil>"bad"</evil>',
        products=["Cortex XSIAM"], category=None,
        version=None, last_edition=None, last_tech_change=None,
        word_count=None, pretty_url="",
    )
    html = build_publication_html(pub, [], [])
    assert "&lt;evil&gt;" in html
    assert "&quot;bad&quot;" in html
    assert "<evil>" not in html


def test_html_handles_zero_topics(sample_publication):
    html = build_publication_html(sample_publication, [], [])
    assert "<h1>" in html
    assert "</body></html>" in html


def test_html_topics_and_contents_are_zip_iterated(sample_publication):
    topics = [
        {"id": "t1", "title": "A", "breadcrumb": ["A"]},
        {"id": "t2", "title": "B", "breadcrumb": ["B"]},
    ]
    contents = ["<p>first</p>", "<p>second</p>"]
    html = build_publication_html(sample_publication, topics, contents)
    assert html.find("<p>first</p>") < html.find("<p>second</p>")
    assert "<h2>A</h2>" in html
    assert "<h2>B</h2>" in html
