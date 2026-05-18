"""Main orchestration: catalog -> diff -> fetch -> write HTML.

v3: product_dir_map is now built from a live CatalogSnapshot, not from
a hard-coded dict. The only public API change is that run_sync() no longer
ships a DEFAULT_PRODUCT_DIR_MAP constant — callers must pass the map built
by CatalogSnapshot.product_dir_map (done automatically by cli.py).

For backwards-compat, a module-level DEFAULT_PRODUCT_DIR_MAP is still
exported but it is built lazily from the merge rules, NOT from a live
catalog fetch.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from cortex_docs_sync.catalog import DEFAULT_MERGE_RULES, MergeRule, label_to_dir
from cortex_docs_sync.client import (
    DEFAULT_RATE_LIMIT_RPS,
    DEFAULT_USER_AGENT,
    CortexDocsClient,
)
from cortex_docs_sync.html_assembly import (
    build_publication_html,
    html_escape,
    safe_filename,
)
from cortex_docs_sync.models import IngestStats, Publication, PublicationFilter
from cortex_docs_sync.state import IncrementalState

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, Publication], None]


def resolve_output_path(
    pub: Publication,
    base_output_dir: Path,
    product_dir_map: Dict[str, str],
) -> Optional[Path]:
    """Return the HTML output path for ``pub``, or None to skip it."""
    for product in pub.products:
        if product in product_dir_map:
            subdir = product_dir_map[product]
            return base_output_dir / subdir / safe_filename(pub.title, pub.map_id)
    return None


def fetch_publication(
    client: CortexDocsClient,
    pub: Publication,
    output_path: Path,
) -> Tuple[int, int]:
    """Pull every topic of one publication and write the assembled HTML.

    Returns (topic_count, bytes_written).
    """
    topics = client.get_topics(pub.map_id)
    if not topics:
        logger.warning("Publication %s (%s) has no topics — skipping", pub.title, pub.map_id)
        return (0, 0)

    # Definiujemy funkcję roboczą dla pojedynczego wątku
    def download_topic(topic: dict) -> str:
        try:
            return client.get_topic_content(pub.map_id, topic["id"])
        except Exception as exc:
            logger.warning(
                "Topic fetch failed (%s/%s): %s — inserting placeholder",
                pub.map_id, topic.get("id"), exc,
            )
            return f"<p><em>[FETCH ERROR: {html_escape(str(exc))}]</em></p>"

    # 🚀 Uruchamiamy 32 wątki naraz. executor.map gwarantuje, że kolejność 
    # elementów w liście 'contents' będzie dokładnie taka sama jak w 'topics'.
    with ThreadPoolExecutor(max_workers=32) as executor:
        contents = list(executor.map(download_topic, topics))

    html = build_publication_html(pub, topics, contents)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return (len(topics), len(html.encode("utf-8")))


def run_sync(
    output_dir: Path,
    state_file: Path,
    pub_filter: PublicationFilter,
    product_dir_map: Dict[str, str],
    *,
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS,
    user_agent: str = DEFAULT_USER_AGENT,
    full_refetch: bool = False,
    dry_run: bool = False,
    max_publications: Optional[int] = None,
    progress_callback: Optional[ProgressCallback] = None,
    base_url: Optional[str] = None,
    # catalog is injected by the caller — avoids a second network round-trip
    preloaded_catalog: Optional[List[Publication]] = None,
) -> IngestStats:
    """End-to-end sync of the Cortex docs portal into a local mirror.

    ``product_dir_map`` must be provided by the caller (typically built by
    ``CatalogSnapshot.product_dir_map`` after the catalog fetch).

    ``preloaded_catalog`` allows the caller to pass in the publication list
    that was already fetched during the snapshot phase, so that sync does not
    issue a second ``GET /api/khub/maps`` request.
    """
    started = time.monotonic()
    stats = IngestStats()

    client_kwargs: Dict = {
        "user_agent": user_agent,
        "rate_limit_rps": rate_limit_rps,
    }
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    client = CortexDocsClient(**client_kwargs)

    state = IncrementalState(state_file)
    state.load()

    if preloaded_catalog is not None:
        catalog = preloaded_catalog
        logger.info("Using pre-loaded catalog (%d publications)", len(catalog))
    else:
        logger.info("Fetching catalog...")
        catalog = client.list_publications()

    stats.total_in_catalog = len(catalog)
    logger.info("Catalog: %d publications", stats.total_in_catalog)

    matched = [p for p in catalog if pub_filter.matches(p)]
    stats.matched_filter = len(matched)
    logger.info("After filters: %d publications", stats.matched_filter)

    if max_publications:
        matched = matched[:max_publications]
        logger.info("Capped to --max %d publications", len(matched))

    to_fetch: List[Tuple[Publication, Path]] = []
    for pub in matched:
        out_path = resolve_output_path(pub, output_dir, product_dir_map)
        if out_path is None:
            logger.debug(
                "Skipping %s — none of %s is in product_dir_map",
                pub.title, pub.products,
            )
            continue
        if not full_refetch and state.is_unchanged(pub):
            stats.skipped_unchanged += 1
            continue
        to_fetch.append((pub, out_path))

    logger.info(
        "To fetch: %d (skipped unchanged: %d)",
        len(to_fetch), stats.skipped_unchanged,
    )

    if dry_run:
        logger.info("=== DRY RUN — no content requests will be made ===")
        for i, (pub, out_path) in enumerate(to_fetch, 1):
            logger.info(
                "[%d/%d] would fetch: %s (edition %s, %s words) -> %s",
                i, len(to_fetch), pub.title,
                pub.last_edition or "?", pub.word_count or "?", out_path,
            )
        stats.elapsed_seconds = time.monotonic() - started
        return stats

    for i, (pub, out_path) in enumerate(to_fetch, 1):
        logger.info(
            "[%d/%d] %s (edition %s, %s words)",
            i, len(to_fetch), pub.title,
            pub.last_edition or "?", pub.word_count or "?",
        )
        if progress_callback:
            try:
                progress_callback(i, len(to_fetch), pub)
            except Exception:
                logger.debug("progress_callback raised", exc_info=True)
        try:
            topic_count, bytes_written = fetch_publication(client, pub, out_path)
            stats.fetched += 1
            stats.topics_total += topic_count
            stats.bytes_written += bytes_written
            state.update(pub, out_path, topic_count)
            state.save()
        except Exception as exc:
            logger.exception("Failed to fetch %s: %s", pub.title, exc)
            stats.failed += 1
            stats.failed_publications.append(pub.title)

    stats.elapsed_seconds = time.monotonic() - started
    logger.info(
        "Done: %d fetched, %d skipped, %d failed in %.1fs",
        stats.fetched, stats.skipped_unchanged, stats.failed, stats.elapsed_seconds,
    )
    return stats
