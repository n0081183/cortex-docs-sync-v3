# cortex-docs-sync

Incremental local mirror of the Palo Alto **Cortex documentation portal**, driven by the official FluidTopics JSON API. Designed as a feeder for RAG pipelines, search indexes, and other downstream systems that need an up-to-date local copy of Cortex docs without manually downloading anything.

- **Source:** `https://docs-cortex.paloaltonetworks.com/`
- **Output:** one self-contained HTML file per publication, organized by product
- **Dependencies:** only `requests` — works on Python 3.10+
- **Politeness:** rate-limited (default 1 req/s), exponential backoff, descriptive User-Agent

## Why this tool exists

The portal is a single-page application. Visiting a documentation URL returns a ~3 KB JavaScript shell, not the actual content — naive HTML scraping produces nothing useful.

Behind the SPA, the portal runs FluidTopics 5.1.14, whose JSON API is publicly accessible and **explicitly allowed by the portal's own `robots.txt`**:

```
Allow: /r/*
Allow: /api/khub/documents/*/content
Allow: /sitemap.xml
```

This tool talks to that JSON API. No headless browser, no JS execution.

| Endpoint | Purpose |
|---|---|
| `GET /api/khub/maps?limit=10000` | Full publication catalog — ~529 entries, fetched in one request |
| `GET /api/khub/maps/{id}/topics` | Flat topic list per publication |
| `GET /api/khub/maps/{id}/topics/{tid}/content` | Clean HTML fragment per topic |

---

## What's new in v0.3.0 — dynamic catalog discovery

Previous versions maintained a hand-curated list of product names in the source code. That list was always one release behind, and products like AgentiX or Cortex Cloud were missing entirely.

**v0.3.0 removes the hard-coded product list entirely.** At startup, the tool fetches the live catalog (one HTTP call), extracts every distinct `Product` label it finds, and builds the product→directory mapping on the fly.

As of the last observed catalog state, the portal contains 12 product labels across 529 publications:

```
Cortex                         cortex_general/
Cortex AgentiX                 agentix/
Cortex CLOUD                   cortex_cloud/   ← same dir as "Cortex Cloud"
Cortex Cloud                   cortex_cloud/
Cortex Cloud Posture Management cortex_cloud/
Cortex Cloud Runtime Security  cortex_cloud/
Cortex IDE                     ide/
Cortex XDR                     xdr/
Cortex XDR Agent               xdr/            ← merged with XDR by default
Cortex XPANSE                  xpanse/
Cortex XSIAM                   xsiam/
Cortex XSOAR                   xsoar/
```

When Palo Alto adds a new product line to the portal, it appears in `--list-products` on the next run and can be synced immediately — no code change needed.

---

## Quick start

```bash
git clone https://github.com/n0081183/cortex-docs-sync.git
cd cortex-docs-sync
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# See what products the live catalog currently contains
cortex-docs-sync --list-products

# Dry-run: see what would be downloaded, without fetching any content
cortex-docs-sync --product xsiam --max 5 --dry-run

# Download a small sample (~1-2 minutes)
cortex-docs-sync --product xsiam --max 5 -v

# Re-run — unchanged publications are skipped automatically
cortex-docs-sync --product xsiam --max 5
```

> **Note:** `--list-products` always fetches the live catalog first (one lightweight request), so the shown product list is always current.

---

## Incremental sync — how it works

```
┌─────────────────────────────────────────────────────────────────┐
│  Startup (every run)                                            │
│                                                                 │
│  GET /api/khub/maps  (1 request)                               │
│    → extract all Product labels from 529 publications           │
│    → apply merge rules → build product→dir map                  │
│    → CLI choices = unique output directories                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ same response reused below
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  For each publication that passes filters:                      │
│                                                                 │
│  compare ft:lastTechChange vs local state.json                  │
│       ↓ unchanged + file exists → SKIP                         │
│       ↓ new or changed                                          │
│  GET /topics + GET /content per topic                           │
│  write HTML → update state.json (atomic)                        │
└─────────────────────────────────────────────────────────────────┘
```

The catalog response is **reused** — the initial fetch for product discovery doubles as the sync diff source, so there is no extra network round-trip.

After the first full sync, subsequent runs typically skip every publication and finish in seconds.

---

## CLI reference

```
cortex-docs-sync [options]
```

### Product selection

```
--product PRODUCT [...]
    Output directory name(s) to sync.
    Choices are discovered live from the catalog (e.g. xdr, xsiam, agentix).
    Default: all products found in the catalog.

--list-products
    Fetch the live catalog, print the product→directory table, and exit.
```

### Sync behaviour

```
--full
    Ignore the local state file — re-fetch every matching publication.

--dry-run
    List what would be fetched; pulls only the catalog, no content.

--max N
    Hard cap on publications (useful for testing).

--rate-limit RPS
    Max requests per second (default: 1.0). Be polite for scheduled jobs.

--include-release-notes
    Include "Content Update Release Notes", "OSS Listings", and
    "Analytics Content Releases" (excluded by default — noisy, low-value
    for RAG use cases).
```

### Paths

```
--output-dir PATH
    Root of the local mirror (default: ./cortex_docs).

--state-file PATH
    Incremental state file (default: <output-dir>/.cortex_docs_state.json).

--snapshot-cache PATH
    Cache the catalog snapshot to a JSON file. Reused in offline mode.
```

### Merge rules

```
--merge-rules PATH
    JSON file with custom merge rules that control which product labels
    are grouped into the same output directory.
    See docs/merge_rules_example.json.
```

Merge rules let you control directory grouping without touching the source code. The default rules collapse all `Cortex Cloud*` variants into `cortex_cloud/` and `Cortex XDR Agent` into `xdr/`. Everything else gets its own directory named from the label automatically.

Example — keep Cloud sub-products in separate directories:

```json
{
  "merge_rules": [
    {"stem_prefix": "xdr", "output_dir": "xdr"}
  ]
}
```

```bash
cortex-docs-sync --merge-rules my_rules.json --list-products
```

### Offline / cached mode

```
--snapshot-cache PATH   Save (or load) the catalog snapshot as JSON.
--no-catalog            Skip the live catalog fetch; use --snapshot-cache instead.
```

Useful when you want to run without network access, or to freeze the product list for reproducibility:

```bash
# Save snapshot
cortex-docs-sync --snapshot-cache .snapshot.json --dry-run

# Later, run offline
cortex-docs-sync --no-catalog --snapshot-cache .snapshot.json --product xdr
```

### Other

```
--user-agent UA     HTTP User-Agent (override per team / deployment).
--base-url URL      Override portal base URL (testing only).
-v, --verbose       DEBUG-level logging.
--version           Print version and exit.
```

---

## Output structure

```
cortex_docs/
├── .cortex_docs_state.json           ← incremental state (do not commit)
├── xdr/
│   ├── Cortex-XDR-Documentation__GD6sG6FlxDWxAn13_eZuUQ.html
│   ├── Cortex-XDR-Agent-Administrator-Guide__<id>.html
│   └── ...
├── xsiam/
│   └── Cortex-XSIAM-Documentation__<id>.html
├── xsoar/
│   └── ...
├── xpanse/
│   └── ...
├── agentix/
│   └── ...
└── cortex_cloud/
    └── ...
```

Each HTML file is self-contained: a metadata header with a source deep-link, then one `<section>` per topic with its breadcrumb and topic URL embedded. Downstream parsers preserve those URLs through chunking, so RAG answers can cite `https://docs-cortex.paloaltonetworks.com/r/…` as the source.

---

## Integration

### Generic RAG pipeline

1. Run `cortex-docs-sync --output-dir <your-data-dir>` periodically.
2. Point your parser (Docling, Unstructured, LangChain `DirectoryLoader`, …) at `<your-data-dir>/**/*.html`.
3. Use `.cortex_docs_state.json` to detect which files changed since the last run and trigger a targeted reindex.

### Programmatic use (no CLI)

```python
from pathlib import Path
from cortex_docs_sync import (
    CatalogSnapshot,
    CortexDocsClient,
    PublicationFilter,
    run_sync,
)

client = CortexDocsClient()
publications = client.list_publications()

snapshot = CatalogSnapshot.from_catalog(publications)
print(snapshot.describe())   # show product→dir table

stats = run_sync(
    output_dir=Path("./cortex_docs"),
    state_file=Path("./cortex_docs/.cortex_docs_state.json"),
    pub_filter=PublicationFilter(products=["Cortex XSIAM", "Cortex AgentiX"]),
    product_dir_map=snapshot.product_dir_map,
    preloaded_catalog=publications,   # reuse, no second request
    rate_limit_rps=1.5,
)
print(f"Fetched: {stats.fetched}, skipped: {stats.skipped_unchanged}")
```

### Scheduled sync — cron

```cron
# Every weekday at 06:30
30 6 * * 1-5  cd /opt/your-rag && .venv/bin/cortex-docs-sync >> logs/cortex_sync.log 2>&1
```

### Scheduled sync — GitHub Actions

```yaml
name: Cortex docs sync
on:
  schedule:
    - cron: "30 6 * * 1-5"
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .
      - run: cortex-docs-sync --output-dir ./cortex_docs
      # then: push to S3, trigger downstream indexer, etc.
```

---

## Performance

- ~529 publications in the catalog; after default filters (no Release Notes / OSS Listings) roughly 380–400 are synced depending on selected products.
- Largest publication: ~1244 topics, ~738k words.
- At 1 req/s, a **first full sync** of all products takes several hours (rate-limit bound, not server bound). Use `--max` to sample first.
- **Incremental runs** after the first full sync typically finish in seconds.
- Bumping `--rate-limit` to 2–3 req/s is reasonable for a one-off backfill. Keep it at 1.0 for scheduled jobs.

---

## Development

```bash
# Create and activate venv (recommended)
python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
pytest                         # all tests, no network access required
pytest --cov=cortex_docs_sync  # with coverage
```

All HTTP traffic is mocked in tests — the suite runs fully offline and is CI-safe.

### Project layout

```
cortex-docs-sync/
├── pyproject.toml
├── README.md
├── LICENSE                           MIT
├── docs/
│   ├── merge_rules_example.json      default merge rules
│   └── merge_rules_split_cloud.json  example: separate Cloud subdirectories
├── cortex_docs_sync/
│   ├── __init__.py                   public API exports
│   ├── __main__.py                   python -m cortex_docs_sync
│   ├── catalog.py                    live discovery: labels → CatalogSnapshot
│   ├── cli.py                        two-phase argparse entry point
│   ├── client.py                     HTTP client + RateLimiter
│   ├── html_assembly.py              per-publication HTML builder
│   ├── models.py                     Publication, PublicationFilter, IngestStats
│   ├── state.py                      IncrementalState (diff / skip logic)
│   └── sync.py                       orchestration: catalog → diff → fetch → write
└── tests/
    ├── conftest.py
    ├── test_catalog.py               label normalisation, merge rules, CatalogSnapshot
    ├── test_html.py
    ├── test_models.py
    ├── test_state.py
    └── test_sync.py
```

---

## License

MIT — see `LICENSE`.
