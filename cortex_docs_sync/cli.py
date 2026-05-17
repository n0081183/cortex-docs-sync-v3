"""Command-line interface for cortex-docs-sync (v3).

Flow
----
1. Parse *pre-args* (flags needed before we know the product list):
   --base-url, --user-agent, --merge-rules, --verbose, --list-products,
   --no-catalog (offline mode).

2. Fetch the live catalog (one HTTP call) to discover all Product labels.
   Apply merge rules -> CatalogSnapshot.

3. Build the full argparse parser with --product choices derived from the
   live snapshot, then parse the remaining args.

4. Run sync, re-using the already-fetched catalog (zero extra requests).

Run via:
    cortex-docs-sync                          # all products, incremental
    cortex-docs-sync --product xdr xsiam      # specific products
    cortex-docs-sync --list-products           # show snapshot table + exit
    cortex-docs-sync --dry-run --product agentix
    cortex-docs-sync --merge-rules rules.json  # custom merge rules
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from cortex_docs_sync import __version__
from cortex_docs_sync.catalog import (
    DEFAULT_MERGE_RULES,
    CatalogSnapshot,
    MergeRule,
)
from cortex_docs_sync.client import DEFAULT_USER_AGENT, CortexDocsClient
from cortex_docs_sync.models import PublicationFilter
from cortex_docs_sync.sync import run_sync

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Merge-rules loader
# ---------------------------------------------------------------------------

def _load_merge_rules(path: Optional[Path]) -> List[MergeRule]:
    """Load merge rules from a JSON file, or return the defaults."""
    if path is None:
        return list(DEFAULT_MERGE_RULES)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [MergeRule(**r) for r in raw.get("merge_rules", raw)]


# ---------------------------------------------------------------------------
# Parser builders
# ---------------------------------------------------------------------------

def _build_pre_parser() -> argparse.ArgumentParser:
    """Minimal parser for flags needed before the catalog is fetched."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--base-url", default=None)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--merge-rules", type=Path, default=None,
                   dest="merge_rules_file")
    p.add_argument("--list-products", action="store_true")
    p.add_argument("--no-catalog", action="store_true",
                   help="Skip live catalog fetch; use --snapshot-cache if available.")
    p.add_argument("--snapshot-cache", type=Path, default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _build_main_parser(snapshot: CatalogSnapshot) -> argparse.ArgumentParser:
    """Full parser; --product choices come from the live snapshot."""
    p = argparse.ArgumentParser(
        prog="cortex-docs-sync",
        description=(
            "Incremental local mirror of Cortex documentation. "
            "Product list is discovered live from the portal catalog."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cortex-docs-sync                             # all products\n"
            "  cortex-docs-sync --product xdr xsiam         # specific subset\n"
            "  cortex-docs-sync --list-products             # show catalog map\n"
            "  cortex-docs-sync --dry-run --product agentix\n"
            "  cortex-docs-sync --merge-rules rules.json    # custom grouping\n"
        ),
    )
    p.add_argument(
        "--product", nargs="+",
        choices=snapshot.known_dirs,
        default=snapshot.known_dirs,
        metavar="PRODUCT",
        help=(
            "Output directory name(s) to sync. "
            f"Available: {', '.join(snapshot.known_dirs)}. "
            "Default: all."
        ),
    )
    p.add_argument("--output-dir", type=Path, default=Path("./cortex_docs"))
    p.add_argument("--state-file", type=Path, default=None)
    p.add_argument("--full", action="store_true",
                   help="Ignore state — re-fetch every matching publication.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max", type=int, default=None, dest="max_publications",
                   help="Cap on publications to fetch (for testing).")
    p.add_argument("--rate-limit", type=float, default=1.0)
    p.add_argument(
        "--include-release-notes", action="store_true",
        help="Include release-note categories (excluded by default).",
    )
    p.add_argument("--merge-rules", type=Path, default=None, dest="merge_rules_file",
                   help="JSON file with custom merge rules.")
    p.add_argument("--snapshot-cache", type=Path, default=None,
                   help="Where to cache/load the catalog snapshot JSON.")
    p.add_argument("--no-catalog", action="store_true",
                   help="Use cached snapshot only (offline mode).")
    p.add_argument("--list-products", action="store_true",
                   help="Print the product->directory map and exit.")
    p.add_argument("--base-url", default=None)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


# ---------------------------------------------------------------------------
# Catalog fetch / cache helpers
# ---------------------------------------------------------------------------

def _fetch_snapshot(
    base_url: Optional[str],
    user_agent: str,
    merge_rules: List[MergeRule],
    cache_path: Optional[Path],
    offline: bool,
) -> tuple[CatalogSnapshot, list]:
    """Return (snapshot, publications).

    If ``offline`` is True, load from ``cache_path`` (must exist).
    Otherwise fetch live, then optionally persist to ``cache_path``.

    Returns publications=[] in offline mode (we don't cache individual pubs).
    """
    if offline:
        if not cache_path or not cache_path.exists():
            raise SystemExit(
                "ERROR: --no-catalog requires --snapshot-cache pointing to an "
                "existing snapshot file."
            )
        logger.info("Offline mode: loading snapshot from %s", cache_path)
        return CatalogSnapshot.load(cache_path, merge_rules), []

    client_kwargs: dict = {"user_agent": user_agent, "rate_limit_rps": 10.0}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = CortexDocsClient(**client_kwargs)

    logger.info("Fetching catalog to discover products...")
    publications = client.list_publications()
    snapshot = CatalogSnapshot.from_catalog(publications, merge_rules)

    if cache_path:
        snapshot.save(cache_path)
        logger.debug("Snapshot cached to %s", cache_path)

    return snapshot, publications


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    # ── Phase 1: pre-parse (no choices needed yet) ──────────────────────────
    pre_args, remaining = _build_pre_parser().parse_known_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if pre_args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    merge_rules = _load_merge_rules(pre_args.merge_rules_file)

    # ── Phase 2: discover products from live catalog (or cache) ─────────────
    snapshot, preloaded_catalog = _fetch_snapshot(
        base_url=pre_args.base_url,
        user_agent=pre_args.user_agent,
        merge_rules=merge_rules,
        cache_path=pre_args.snapshot_cache,
        offline=pre_args.no_catalog,
    )

    # Early exit: --list-products before full parse (works even w/o remaining args)
    if pre_args.list_products:
        print(snapshot.describe())
        return 0

    # ── Phase 3: full parse with live choices ────────────────────────────────
    args = _build_main_parser(snapshot).parse_args(argv)

    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if args.list_products:
        print(snapshot.describe())
        return 0

    # Expand selected output-dirs -> FluidTopics labels
    selected_dirs = set(args.product)
    selected_labels: List[str] = []
    for d in selected_dirs:
        selected_labels.extend(sorted(snapshot.dir_to_labels.get(d, set())))

    # Build a product_dir_map restricted to selected dirs only
    product_dir_map = {
        label: d
        for label, d in snapshot.product_dir_map.items()
        if d in selected_dirs
    }

    default_excludes = list(PublicationFilter().exclude_categories)
    if args.include_release_notes:
        default_excludes = [c for c in default_excludes if "Release Notes" not in c]

    pub_filter = PublicationFilter(
        products=selected_labels,
        exclude_categories=tuple(default_excludes),
    )

    state_file = args.state_file or (args.output_dir / ".cortex_docs_state.json")

    print("== Session configuration ==")
    print(f"  Products selected:   {sorted(selected_dirs)}")
    print(f"  Labels matched:      {selected_labels}")
    print(f"  Mode:                {'FULL re-fetch' if args.full else 'incremental'}")
    print(f"  Dry-run:             {args.dry_run}")
    print(f"  Rate limit:          {args.rate_limit} req/s")
    print(f"  Output dir:          {args.output_dir}")
    print(f"  State file:          {state_file}")
    print(f"  Excluded categories: {default_excludes}")
    if args.max_publications:
        print(f"  Max publications:    {args.max_publications}")
    print()

    stats = run_sync(
        output_dir=args.output_dir,
        state_file=state_file,
        pub_filter=pub_filter,
        product_dir_map=product_dir_map,
        rate_limit_rps=args.rate_limit,
        user_agent=args.user_agent,
        full_refetch=args.full,
        dry_run=args.dry_run,
        max_publications=args.max_publications,
        base_url=args.base_url,
        preloaded_catalog=preloaded_catalog if preloaded_catalog else None,
    )

    print()
    print("== Summary ==")
    print(f"  In catalog:          {stats.total_in_catalog}")
    print(f"  After filters:       {stats.matched_filter}")
    print(f"  Skipped (unchanged): {stats.skipped_unchanged}")
    print(f"  Fetched:             {stats.fetched}")
    print(f"  Topics total:        {stats.topics_total}")
    print(f"  Bytes written:       {stats.bytes_written:,} "
          f"({stats.bytes_written/1024/1024:.1f} MB)")
    print(f"  Failed:              {stats.failed}")
    if stats.failed_publications:
        for title in stats.failed_publications:
            print(f"    - {title}")
    print(f"  Elapsed:             {stats.elapsed_seconds:.1f}s")

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
