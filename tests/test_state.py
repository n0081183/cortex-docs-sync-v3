"""Tests for `IncrementalState` — the local-vs-online diff."""

from __future__ import annotations

from pathlib import Path

from cortex_docs_sync.models import Publication
from cortex_docs_sync.state import IncrementalState


def test_empty_state_treats_everything_as_changed(tmp_path, sample_publication):
    s = IncrementalState(tmp_path / "state.json")
    s.load()
    assert s.is_unchanged(sample_publication) is False


def test_round_trip_preserves_diff_key(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    s1 = IncrementalState(sp)
    s1.load()

    fp = tmp_path / "out.html"
    fp.write_text("<html></html>")
    s1.update(sample_publication, fp, topic_count=42)
    s1.save()

    s2 = IncrementalState(sp)
    s2.load()
    assert s2.is_unchanged(sample_publication) is True


def test_diff_key_change_triggers_refetch(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    s = IncrementalState(sp)
    s.load()
    fp = tmp_path / "out.html"
    fp.write_text("<html></html>")
    s.update(sample_publication, fp, topic_count=1)
    s.save()

    # Same map_id but the publication has been updated upstream
    refreshed = Publication(
        **{**sample_publication.__dict__, "last_tech_change": "2026-06-01"}
    )
    assert s.is_unchanged(refreshed) is False


def test_missing_local_file_triggers_refetch(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    s = IncrementalState(sp)
    s.load()
    fp = tmp_path / "missing.html"
    fp.write_text("<html></html>")
    s.update(sample_publication, fp, topic_count=1)

    fp.unlink()  # operator deleted the local mirror file
    assert s.is_unchanged(sample_publication) is False


def test_corrupted_state_file_starts_from_empty(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    sp.write_text("{not valid json")
    s = IncrementalState(sp)
    s.load()
    assert s.is_unchanged(sample_publication) is False
    assert s.known_ids == []


def test_save_is_atomic_via_tmp_rename(tmp_path, sample_publication):
    """The .tmp file should never linger after a successful save."""
    sp = tmp_path / "state.json"
    s = IncrementalState(sp)
    s.load()
    fp = tmp_path / "out.html"
    fp.write_text("<html></html>")
    s.update(sample_publication, fp, topic_count=1)
    s.save()

    assert sp.exists()
    leftovers = list(tmp_path.glob("state.json.tmp"))
    assert leftovers == []


def test_state_records_topic_count(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    s = IncrementalState(sp)
    s.load()
    fp = tmp_path / "out.html"
    fp.write_text("<html></html>")
    s.update(sample_publication, fp, topic_count=1244)
    s.save()

    s2 = IncrementalState(sp)
    s2.load()
    entry = s2.entry(sample_publication.map_id)
    assert entry is not None
    assert entry.topic_count == 1244


def test_remove_drops_entry(tmp_path, sample_publication):
    sp = tmp_path / "state.json"
    s = IncrementalState(sp)
    s.load()
    fp = tmp_path / "out.html"
    fp.write_text("x")
    s.update(sample_publication, fp, topic_count=1)
    assert sample_publication.map_id in s.known_ids
    s.remove(sample_publication.map_id)
    assert sample_publication.map_id not in s.known_ids
