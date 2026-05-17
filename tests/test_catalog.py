"""Tests for catalog.py — label normalisation, merge rules, CatalogSnapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_docs_sync.catalog import (
    DEFAULT_MERGE_RULES,
    CatalogSnapshot,
    MergeRule,
    _normalise_stem,
    label_to_dir,
)
from cortex_docs_sync.models import Publication


# ── _normalise_stem ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("Cortex XDR",                     "xdr"),
    ("Cortex XDR Agent",               "xdr_agent"),
    ("Cortex XSIAM",                   "xsiam"),
    ("Cortex XSOAR",                   "xsoar"),
    ("Cortex XPANSE",                  "xpanse"),
    ("Cortex AgentiX",                 "agentix"),
    ("Cortex Cloud",                   "cloud"),
    ("Cortex CLOUD",                   "cloud"),           # case-insensitive
    ("Cortex Cloud Posture Management","cloud_posture_management"),
    ("Cortex Cloud Runtime Security",  "cloud_runtime_security"),
    ("Cortex IDE",                     "ide"),
    ("Cortex",                         "cortex_general"),  # bare label
])
def test_normalise_stem(label, expected):
    assert _normalise_stem(label) == expected


# ── label_to_dir — default merge rules ─────────────────────────────────────

@pytest.mark.parametrize("label,expected_dir", [
    ("Cortex XDR",                     "xdr"),
    ("Cortex XDR Agent",               "xdr"),          # merged into xdr
    ("Cortex XSIAM",                   "xsiam"),
    ("Cortex XSOAR",                   "xsoar"),
    ("Cortex XPANSE",                  "xpanse"),
    ("Cortex AgentiX",                 "agentix"),
    ("Cortex Cloud",                   "cortex_cloud"),
    ("Cortex CLOUD",                   "cortex_cloud"),
    ("Cortex Cloud Posture Management","cortex_cloud"),
    ("Cortex Cloud Runtime Security",  "cortex_cloud"),
    ("Cortex IDE",                     "ide"),
    ("Cortex",                         "cortex_general"),
])
def test_label_to_dir_defaults(label, expected_dir):
    assert label_to_dir(label) == expected_dir


def test_label_to_dir_custom_rule_overrides_auto():
    custom = [MergeRule("agentix", "ai_agents")]
    assert label_to_dir("Cortex AgentiX", custom) == "ai_agents"


def test_label_to_dir_no_match_falls_back_to_stem():
    # No merge rules -> pure auto
    assert label_to_dir("Cortex IDE", []) == "ide"
    assert label_to_dir("Cortex XSIAM", []) == "xsiam"


# ── CatalogSnapshot.build ───────────────────────────────────────────────────

LIVE_LABELS = {
    "Cortex",
    "Cortex AgentiX",
    "Cortex CLOUD",
    "Cortex Cloud",
    "Cortex Cloud Posture Management",
    "Cortex Cloud Runtime Security",
    "Cortex IDE",
    "Cortex XDR",
    "Cortex XDR Agent",
    "Cortex XPANSE",
    "Cortex XSIAM",
    "Cortex XSOAR",
}


@pytest.fixture
def live_snapshot():
    return CatalogSnapshot.build(LIVE_LABELS)


def test_snapshot_all_labels_present(live_snapshot):
    assert live_snapshot.all_labels == LIVE_LABELS


def test_snapshot_cloud_variants_merged(live_snapshot):
    for label in [
        "Cortex CLOUD",
        "Cortex Cloud",
        "Cortex Cloud Posture Management",
        "Cortex Cloud Runtime Security",
    ]:
        assert live_snapshot.product_dir_map[label] == "cortex_cloud", label


def test_snapshot_xdr_agent_merged(live_snapshot):
    assert live_snapshot.product_dir_map["Cortex XDR"] == "xdr"
    assert live_snapshot.product_dir_map["Cortex XDR Agent"] == "xdr"


def test_snapshot_known_dirs_sorted(live_snapshot):
    assert live_snapshot.known_dirs == sorted(live_snapshot.known_dirs)


def test_snapshot_dir_to_labels_inverse(live_snapshot):
    # cortex_cloud bucket must contain all 4 cloud variants
    cloud_set = live_snapshot.dir_to_labels["cortex_cloud"]
    assert "Cortex Cloud" in cloud_set
    assert "Cortex CLOUD" in cloud_set
    assert "Cortex Cloud Posture Management" in cloud_set
    assert "Cortex Cloud Runtime Security" in cloud_set


def test_snapshot_all_dirs_covered(live_snapshot):
    # Every label must appear in exactly one dir bucket
    covered: set = set()
    for labels in live_snapshot.dir_to_labels.values():
        covered.update(labels)
    assert covered == LIVE_LABELS


# ── CatalogSnapshot.from_catalog ────────────────────────────────────────────

def _make_pub(products):
    return Publication(
        map_id="x", title="t", products=products,
        category=None, version=None,
        last_edition=None, last_tech_change=None,
        word_count=500, pretty_url="",
    )


def test_from_catalog_extracts_all_labels():
    pubs = [
        _make_pub(["Cortex XDR"]),
        _make_pub(["Cortex XSIAM", "Cortex XDR Agent"]),
    ]
    snap = CatalogSnapshot.from_catalog(pubs)
    assert "Cortex XDR" in snap.all_labels
    assert "Cortex XSIAM" in snap.all_labels
    assert "Cortex XDR Agent" in snap.all_labels


def test_from_catalog_empty_products_handled():
    pubs = [_make_pub([])]
    snap = CatalogSnapshot.from_catalog(pubs)
    assert snap.all_labels == frozenset()
    assert snap.known_dirs == []


# ── Persistence round-trip ──────────────────────────────────────────────────

def test_save_and_load_roundtrip(tmp_path, live_snapshot):
    cache = tmp_path / "snap.json"
    live_snapshot.save(cache)
    loaded = CatalogSnapshot.load(cache)

    assert loaded.all_labels == live_snapshot.all_labels
    assert loaded.product_dir_map == live_snapshot.product_dir_map
    assert loaded.known_dirs == live_snapshot.known_dirs


def test_save_creates_valid_json(tmp_path, live_snapshot):
    cache = tmp_path / "snap.json"
    live_snapshot.save(cache)
    data = json.loads(cache.read_text())
    assert "all_labels" in data
    assert "product_dir_map" in data
    assert "merge_rules" in data


# ── describe ────────────────────────────────────────────────────────────────

def test_describe_contains_all_dirs(live_snapshot):
    table = live_snapshot.describe()
    for d in live_snapshot.known_dirs:
        assert d in table


def test_describe_contains_all_labels(live_snapshot):
    table = live_snapshot.describe()
    for label in live_snapshot.all_labels:
        assert label in table


# ── Custom merge rules ──────────────────────────────────────────────────────

def test_custom_rules_can_split_xdr():
    """Verify a user can choose to keep XDR and XDR Agent separate."""
    no_xdr_merge = [r for r in DEFAULT_MERGE_RULES if r.stem_prefix != "xdr"]
    snap = CatalogSnapshot.build({"Cortex XDR", "Cortex XDR Agent"}, no_xdr_merge)
    assert snap.product_dir_map["Cortex XDR"] == "xdr"
    assert snap.product_dir_map["Cortex XDR Agent"] == "xdr_agent"
    assert "xdr" in snap.known_dirs
    assert "xdr_agent" in snap.known_dirs


def test_custom_rules_can_split_cloud():
    """Verify a user can opt for separate cloud subdirectories."""
    no_cloud_merge = [r for r in DEFAULT_MERGE_RULES if r.stem_prefix != "cloud"]
    snap = CatalogSnapshot.build(
        {"Cortex Cloud", "Cortex Cloud Runtime Security"}, no_cloud_merge
    )
    assert snap.product_dir_map["Cortex Cloud"] == "cloud"
    assert snap.product_dir_map["Cortex Cloud Runtime Security"] == "cloud_runtime_security"
