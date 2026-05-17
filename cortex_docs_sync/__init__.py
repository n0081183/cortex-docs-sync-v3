"""cortex-docs-sync v3 — dynamic, catalog-driven mirror of Cortex docs."""

from cortex_docs_sync.catalog import (
    CatalogSnapshot,
    MergeRule,
    DEFAULT_MERGE_RULES,
    label_to_dir,
)
from cortex_docs_sync.client import CortexDocsClient, RateLimiter
from cortex_docs_sync.html_assembly import build_publication_html
from cortex_docs_sync.models import (
    IngestStateEntry,
    IngestStats,
    Publication,
    PublicationFilter,
)
from cortex_docs_sync.state import IncrementalState
from cortex_docs_sync.sync import (
    fetch_publication,
    resolve_output_path,
    run_sync,
)

__version__ = "0.3.0"

__all__ = [
    # catalog
    "CatalogSnapshot",
    "MergeRule",
    "DEFAULT_MERGE_RULES",
    "label_to_dir",
    # client
    "CortexDocsClient",
    "RateLimiter",
    # models
    "Publication",
    "PublicationFilter",
    "IngestStateEntry",
    "IngestStats",
    # state
    "IncrementalState",
    # sync
    "build_publication_html",
    "fetch_publication",
    "resolve_output_path",
    "run_sync",
    # meta
    "__version__",
]
