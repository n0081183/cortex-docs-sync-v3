cat << 'EOF' > README.md
# Cortex Docs Sync & AI Vectorization Pipeline 🚀

An end-to-end, fully automated pipeline that creates an incremental local mirror of the Palo Alto Cortex documentation portal and instantly vectorizes it into an embedded Qdrant database using GPU acceleration. 

Designed for RAG (Retrieval-Augmented Generation) pipelines, search indexes, and autonomous agents that need an up-to-date, AI-ready copy of Cortex docs with **Zero-Touch Cloud Execution** (e.g., RunPod).

Source: https://docs-cortex.paloaltonetworks.com/
Output: `cortex_index.tar.gz` (Embedded Qdrant Vector DB) + Self-contained HTML files.

---

## 🌟 What's New: Cloud-Native & GPU AI Engine
The project has evolved from a simple scraper into a complete data pipeline. 

1. **Zero-SSH Execution:** A single entrypoint (`run_pipeline.sh`) installs dependencies, runs the scraper, triggers the AI worker, and packs the database. Ideal for ephemeral cloud instances.
2. **GPU-Accelerated Vectorization:** Built-in `worker.py` leverages `onnxruntime-gpu` and `fastembed` to process ~50,000 document segments on an RTX 4090 in seconds.
3. **Smart Chunking & HTML Cleaning:** Automatically strips noisy HTML tags, chunks text into 300-word segments (with 50-word overlaps), and maps them to product metadata.
4. **Embedded Qdrant:** Outputs a portable `/tmp/qdrant_sync` directory compressed into `cortex_index.tar.gz`, ready to be downloaded and queried locally without Docker.

---

## ⚡ Quick Start: Cloud Deployment (RunPod / Ubuntu)

To run the complete pipeline (Scraping + AI Vectorization) on a fresh GPU instance:

    # 1. Clone the repository
    git clone https://github.com/n0081183/cortex-docs-sync-v3.git
    cd cortex-docs-sync-v3

    # 2. Execute the Master Pipeline Script
    bash run_pipeline.sh

**Expected Output:**
Once finished, you will find `cortex_index.tar.gz` in the `/workspace` directory (or `/tmp` if workspace is unavailable). Download this file to your local machine — your AI agent is ready to read Cortex docs!

---

## 🧠 Pipeline Architecture

    ┌────────────────────────────────────────────────────────────────────────┐
    │  PHASE 1: SCRAPER (cortex_docs_sync)                                   │
    │  GET /api/khub/maps → Discover Products (XDR, XSOAR, XSIAM...)         │
    │  Incremental Diff → Fetch only new/changed topics                      │
    │  Save to: ./cortex_docs/ (HTML files)                                  │
    └───────────────────────────────────┬────────────────────────────────────┘
                                        │ triggers automatically
                                        ▼
    ┌────────────────────────────────────────────────────────────────────────┐
    │  PHASE 2: AI WORKER (worker.py)                                        │
    │  Read HTML → Clean Tags → Smart Chunking (300 words)                   │
    │  Load multilingual-e5-large to RTX 4090 GPU                            │
    │  Generate Vectors → Upsert to Embedded Qdrant                          │
    │  Save to: /workspace/cortex_index.tar.gz                               │
    └────────────────────────────────────────────────────────────────────────┘

---

## 🕵️ Why this tool exists
The portal is a single-page application. Visiting a documentation URL returns a ~3 KB JavaScript shell, not the actual content — naive HTML scraping produces nothing useful.
Behind the SPA, the portal runs FluidTopics 5.1.14, whose JSON API is publicly accessible and explicitly allowed by the portal's own robots.txt. This tool talks to that JSON API. No headless browser, no JS execution.

* `GET /api/khub/maps?limit=10000` - Full publication catalog
* `GET /api/khub/maps/{id}/topics` - Flat topic list per publication
* `GET /api/khub/maps/{id}/topics/{tid}/content` - Clean HTML fragment per topic

---

## 🛠️ Component 1: The Scraper CLI (`cortex_docs_sync`)

If you only want to download the HTML files without the AI vectorization, you can use the core Python module locally.

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .

### CLI reference
`cortex-docs-sync [options]`

#### Product selection
* `--product PRODUCT [...]` Output directory name(s) to sync. Choices are discovered live from the catalog. Default: all products.
* `--list-products` Fetch the live catalog, print the product→directory table, and exit.

#### Sync behaviour
* `--full` Ignore the local state file — re-fetch every matching publication.
* `--dry-run` List what would be fetched; pulls only the catalog, no content.
* `--max N` Hard cap on publications (useful for testing).
* `--rate-limit RPS` Max requests per second (default: 1.0). Be polite for scheduled jobs.
* `--include-release-notes` Include "Content Update Release Notes", "OSS Listings", etc. (excluded by default).

#### Paths
* `--output-dir PATH` Root of the local mirror (default: `./cortex_docs`).
* `--state-file PATH` Incremental state file.
* `--snapshot-cache PATH` Cache the catalog snapshot to a JSON file.

#### Merge rules
* `--merge-rules PATH` JSON file with custom merge rules that control which product labels are grouped into the same output directory.
The default rules collapse all Cortex Cloud* variants into `cortex_cloud/` and Cortex XDR Agent into `xdr/`. Example — keep Cloud sub-products in separate directories:

    {
      "merge_rules": [
        {"stem_prefix": "xdr", "output_dir": "xdr"}
      ]
    }

    cortex-docs-sync --merge-rules my_rules.json --list-products

#### Offline / cached mode
* `--no-catalog` Skip the live catalog fetch; use `--snapshot-cache` instead.

    # Save snapshot
    cortex-docs-sync --snapshot-cache .snapshot.json --dry-run
    # Later, run offline
    cortex-docs-sync --no-catalog --snapshot-cache .snapshot.json --product xdr

#### Other
* `--user-agent UA` HTTP User-Agent (override per team / deployment).
* `--base-url URL` Override portal base URL (testing only).
* `-v, --verbose` DEBUG-level logging.

---

## 📦 Component 2: The Vectorizer (`worker.py`)

The `worker.py` script runs automatically via `run_pipeline.sh`, but can be executed standalone:

    pip install -r requirements-runpod.txt --break-system-packages
    python3 worker.py

Each vector payload contains `{"title": "doc_name", "product": "xsiam", "text": "chunk_content"}` for targeted RAG filtering.

---

## 🧩 Programmatic Use & Integration

### Python API
    from pathlib import Path
    from cortex_docs_sync import CatalogSnapshot, CortexDocsClient, PublicationFilter, run_sync

    client = CortexDocsClient()
    publications = client.list_publications()
    snapshot = CatalogSnapshot.from_catalog(publications)
    
    stats = run_sync(
        output_dir=Path("./cortex_docs"),
        state_file=Path("./cortex_docs/.cortex_docs_state.json"),
        pub_filter=PublicationFilter(products=["Cortex XSIAM"]),
        product_dir_map=snapshot.product_dir_map,
        preloaded_catalog=publications,
        rate_limit_rps=1.5,
    )

### Scheduled sync — GitHub Actions
    name: Cortex docs sync
    on:
      schedule:
        - cron: "30 6 * * 1-5"
    jobs:
      sync:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with: { python-version: "3.12" }
          - run: pip install -e .
          - run: cortex-docs-sync --output-dir ./cortex_docs

---

## 🚀 Performance
~529 publications in the catalog; after default filters roughly 380–400 are synced. Largest publication: ~1244 topics, ~738k words. At 1 req/s, a first full sync takes several hours. Incremental runs finish in seconds.

## 💻 Development
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    pytest                         # all tests, no network access required

## 📂 Project Layout

    cortex-docs-sync-v3/
    ├── run_pipeline.sh                   ← 🚀 MASTER CLOUD ENTRYPOINT
    ├── worker.py                         ← AI GPU Vectorization Engine
    ├── requirements-runpod.txt           ← GPU & Qdrant dependencies
    ├── pyproject.toml
    ├── README.md
    ├── cortex_docs_sync/                 ← Core Scraper Package
    └── tests/                            ← Offline CI-safe test suite

## 📝 License
MIT — see LICENSE.
EOF