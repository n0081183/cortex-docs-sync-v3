"""Dataclasses for publications, filters, state entries, and run statistics.

v3: ProductRegistry and ProductEntry removed — replaced by CatalogSnapshot
in catalog.py.  This file now contains only data classes that do not depend
on knowing the product list at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

CORTEX_BASE_URL = "https://docs-cortex.paloaltonetworks.com"


@dataclass(frozen=True)
class Publication:
    """One publication entry from ``GET /api/khub/maps``."""

    map_id: str
    title: str
    products: List[str]
    category: Optional[str]
    version: Optional[str]
    last_edition: Optional[str]        # ISO date "YYYY-MM-DD"
    last_tech_change: Optional[str]    # ISO date "YYYY-MM-DD"
    word_count: Optional[int]
    pretty_url: str

    @property
    def reader_url(self) -> str:
        return f"/r/{self.pretty_url}" if self.pretty_url else ""

    @property
    def absolute_reader_url(self) -> str:
        return f"{CORTEX_BASE_URL}{self.reader_url}"

    @property
    def diff_key(self) -> str:
        """Value compared against local state to decide 'changed vs unchanged'."""
        return self.last_tech_change or self.last_edition or ""


@dataclass
class IngestStateEntry:
    """One publication's persisted state on disk (inside state.json)."""

    map_id: str
    title: str
    diff_key: str
    last_edition: str
    file_path: str
    fetched_at: str
    topic_count: int


@dataclass
class IngestStats:
    """Aggregated statistics returned by ``sync()``."""

    total_in_catalog: int = 0
    matched_filter: int = 0
    skipped_unchanged: int = 0
    fetched: int = 0
    failed: int = 0
    topics_total: int = 0
    bytes_written: int = 0
    elapsed_seconds: float = 0.0
    failed_publications: List[str] = field(default_factory=list)


@dataclass
class PublicationFilter:
    """Filters applied client-side after the catalog has been downloaded.

    All filters are AND-combined.  ``exclude_categories`` always wins over
    ``categories``.  Set ``min_word_count`` to None to keep stub publications.

    ``products`` is now a list of *FluidTopics Product labels* (not CLI
    short-names).  The CLI expands short-names (= output dirs) to labels
    using ``CatalogSnapshot.dir_to_labels`` before constructing this filter.
    """

    products: Optional[Sequence[str]] = None
    categories: Optional[Sequence[str]] = None
    exclude_categories: Sequence[str] = (
        "Content Update Release Notes",
        "OSS Listings",
        "Analytics Content Releases",
    )
    min_word_count: Optional[int] = 100

    def matches(self, pub: Publication) -> bool:
        if self.products and not any(p in self.products for p in pub.products):
            return False
        if self.categories and pub.category not in self.categories:
            return False
        if self.exclude_categories and pub.category in self.exclude_categories:
            return False
        if self.min_word_count and pub.word_count is not None:
            if pub.word_count < self.min_word_count:
                return False
        return True
