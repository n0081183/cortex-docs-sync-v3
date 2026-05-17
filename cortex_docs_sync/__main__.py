"""Allow `python -m cortex_docs_sync` invocation."""

from cortex_docs_sync.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
