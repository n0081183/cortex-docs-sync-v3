"""Live catalog discovery: fetch product labels and build product->dir mapping.

This module is the heart of the v3 dynamic approach. Instead of maintaining
a hand-curated list of product names, we ask the portal at startup what
products actually exist, then apply a small set of *merge rules* to collapse
related labels into a single output directory.

Merge rules (``MergeRule``) are the only thing that ever needs to be touched
when a product family reorganises on the Cortex side — and only when you want
to *collapse* multiple labels into one directory. New, completely separate
products require zero code changes: they are picked up automatically.
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MergeRule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MergeRule:
    """Map one or more FluidTopics Product labels to a single output directory.

    Matching is done on the *normalised stem* of the label, i.e. the part
    after stripping the leading ``"Cortex "`` prefix, lowercased, with
    non-alphanumeric runs replaced by ``_``.

    Examples of normalised stems:
        "Cortex XDR"                    -> "xdr"
        "Cortex XDR Agent"              -> "xdr_agent"
        "Cortex Cloud"                  -> "cloud"
        "Cortex CLOUD"                  -> "cloud"   (same stem)
        "Cortex Cloud Posture Management" -> "cloud_posture_management"

    A rule matches a label when its normalised stem:
      - equals ``stem_prefix`` exactly, OR
      - starts with ``stem_prefix`` followed by ``_``

    This means a rule with ``stem_prefix="cloud"`` matches all four Cloud
    variants above.

    Attributes:
        stem_prefix: Normalised stem (or stem prefix) to match.
        output_dir:  Directory to use for all matched labels.
    """
    stem_prefix: str
    output_dir: str


# Default rules — only needed where auto-naming would produce a wrong result
# or where multiple labels belong logically in the same directory.
#
# Rule evaluation order does not matter — every label is matched against all
# rules; the first match wins (rules are tried in list order).
DEFAULT_MERGE_RULES: List[MergeRule] = [
    # XDR Agent docs live alongside main XDR docs.
    MergeRule("xdr", "xdr"),

    # All Cloud variants (Cloud, CLOUD typo, Cloud Posture, Cloud Runtime)
    # go into one cortex_cloud directory.
    MergeRule("cloud", "cortex_cloud"),

    # Bare "Cortex" label (no product suffix) — legacy / catch-all publications.
    MergeRule("cortex_general", "cortex_general"),
]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_stem(label: str) -> str:
    """Strip 'Cortex ' prefix, lowercase, replace non-alnum runs with '_'."""
    stem = label.removeprefix("Cortex").strip()
    if not stem:
        return "cortex_general"   # bare "Cortex" label
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def label_to_dir(label: str, merge_rules: List[MergeRule] = DEFAULT_MERGE_RULES) -> str:
    """Return the output directory for a single FluidTopics Product label.

    Algorithm:
      1. Compute the normalised stem of the label.
      2. Walk ``merge_rules`` in order; the first rule whose ``stem_prefix``
         is an exact match or a prefix of the stem wins.
      3. If no rule matches, the normalised stem itself is the directory name.
    """
    stem = _normalise_stem(label)
    for rule in merge_rules:
        rp = rule.stem_prefix
        if stem == rp or stem.startswith(rp + "_") or stem.startswith(rp.lower() + "_"):
            return rule.output_dir
    return stem


# ---------------------------------------------------------------------------
# CatalogSnapshot
# ---------------------------------------------------------------------------

@dataclass
class CatalogSnapshot:
    """Everything we learned from one catalog fetch.

    This object is produced once at startup (``build_from_catalog``) and then
    consulted by the CLI (for argument choices) and by sync (for the
    product->dir map).

    Attributes:
        all_labels:      Every distinct Product label seen in the catalog.
        product_dir_map: Mapping ``label -> output_dir`` for every label,
                         after applying merge rules.
        dir_to_labels:   Inverse: ``output_dir -> frozenset of labels``.
        known_dirs:      Sorted list of unique output directories (= CLI choices).
    """
    all_labels: FrozenSet[str]
    product_dir_map: Dict[str, str]
    dir_to_labels: Dict[str, FrozenSet[str]]
    known_dirs: List[str]
    merge_rules: List[MergeRule] = field(default_factory=lambda: list(DEFAULT_MERGE_RULES))

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        labels: Set[str],
        merge_rules: List[MergeRule] = DEFAULT_MERGE_RULES,
    ) -> "CatalogSnapshot":
        """Build a snapshot from a raw set of Product labels."""
        product_dir_map: Dict[str, str] = {}
        for label in labels:
            product_dir_map[label] = label_to_dir(label, merge_rules)

        dir_to_labels: Dict[str, FrozenSet[str]] = {}
        for label, d in product_dir_map.items():
            existing = set(dir_to_labels.get(d, frozenset()))
            existing.add(label)
            dir_to_labels[d] = frozenset(existing)

        return cls(
            all_labels=frozenset(labels),
            product_dir_map=product_dir_map,
            dir_to_labels=dir_to_labels,
            known_dirs=sorted(dir_to_labels),
            merge_rules=list(merge_rules),
        )

    @classmethod
    def from_catalog(
        cls,
        publications: list,          # List[Publication] — avoid circular import
        merge_rules: List[MergeRule] = DEFAULT_MERGE_RULES,
    ) -> "CatalogSnapshot":
        """Extract all Product labels from a publication list and build the snapshot."""
        labels: Set[str] = set()
        for pub in publications:
            labels.update(pub.products)
        snap = cls.build(labels, merge_rules)
        logger.info(
            "Catalog snapshot: %d labels -> %d output dirs",
            len(snap.all_labels), len(snap.known_dirs),
        )
        return snap

    # ── Persistence (optional cache) ──────────────────────────────────────

    def save(self, path: Path) -> None:
        """Persist the snapshot as JSON (for --offline or test fixtures)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = {
            "version": 1,
            "all_labels": sorted(self.all_labels),
            "product_dir_map": self.product_dir_map,
            "merge_rules": [
                {"stem_prefix": r.stem_prefix, "output_dir": r.output_dir}
                for r in self.merge_rules
            ],
        }
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(
        cls,
        path: Path,
        merge_rules: Optional[List[MergeRule]] = None,
    ) -> "CatalogSnapshot":
        """Load a previously saved snapshot (used in offline / test mode)."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        if merge_rules is None:
            merge_rules = [
                MergeRule(**r) for r in raw.get("merge_rules", [])
            ]
        return cls.build(set(raw["all_labels"]), merge_rules)

    # ── Describe ──────────────────────────────────────────────────────────

    def describe(self) -> str:
        """Human-readable table of output dirs and which labels they contain."""
        lines = [
            f"{'OUTPUT DIR':<28} LABELS INCLUDED",
            "-" * 70,
        ]
        for d in self.known_dirs:
            labels_str = ", ".join(sorted(self.dir_to_labels[d]))
            lines.append(f"{d:<28} {labels_str}")
        return "\n".join(lines)
