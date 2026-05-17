"""Local mirror state — what we have already pulled from the portal.

This is the heart of incremental sync. Without it, every run would re-fetch
everything; with it, the run cost scales with the number of publications
that actually changed online (often zero).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from cortex_docs_sync.models import IngestStateEntry, Publication

logger = logging.getLogger(__name__)


class IncrementalState:
    """Persisted JSON file mapping `map_id → IngestStateEntry`.

    File format::

        {
          "version": 1,
          "last_run": "2026-05-15T11:30:00+00:00",
          "publications": {
            "<map_id>": {
              "map_id": "...",
              "title": "...",
              "diff_key": "2026-05-13",
              "last_edition": "2026-05-13",
              "file_path": "<output>/xdr/Cortex-XDR-Documentation__abc.html",
              "fetched_at": "2026-05-15T11:30:00+00:00",
              "topic_count": 1244
            }, ...
          }
        }

    The state file is written atomically via a `.tmp` rename so that a
    Ctrl+C in the middle of a save cannot corrupt it.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._entries: Dict[str, IngestStateEntry] = {}
        self._loaded = False

    # ── Persistence ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Read state from disk. Missing file is treated as "fresh start"."""
        if not self.path.exists():
            self._loaded = True
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for map_id, data in raw.get("publications", {}).items():
                self._entries[map_id] = IngestStateEntry(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning(
                "State file %s is unreadable (%s) — starting from empty state",
                self.path, exc,
            )
            self._entries = {}
        self._loaded = True

    def save(self) -> None:
        """Atomically persist state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.SCHEMA_VERSION,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "publications": {mid: asdict(e) for mid, e in self._entries.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    # ── Diff API ────────────────────────────────────────────────────────────

    def is_unchanged(self, pub: Publication) -> bool:
        """True iff the local mirror already has the latest version of `pub`.

        Three things must all hold:
          1. We have a previous entry for this map_id.
          2. Its `diff_key` matches the current `pub.diff_key` (i.e. the
             publication has not been updated upstream since we last fetched).
          3. The local HTML file still exists on disk (someone may have
             deleted it; we want to re-create it in that case).
        """
        if not self._loaded:
            self.load()

        entry = self._entries.get(pub.map_id)
        if not entry:
            return False
        if not pub.diff_key or entry.diff_key != pub.diff_key:
            return False
        return Path(entry.file_path).exists()

    def update(self, pub: Publication, file_path: Path, topic_count: int) -> None:
        """Record a successful fetch."""
        self._entries[pub.map_id] = IngestStateEntry(
            map_id=pub.map_id,
            title=pub.title,
            diff_key=pub.diff_key,
            last_edition=pub.last_edition or "",
            file_path=str(file_path),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            topic_count=topic_count,
        )

    def remove(self, map_id: str) -> None:
        """Forget a publication — used by `--prune` if implemented downstream."""
        self._entries.pop(map_id, None)

    # ── Read API ────────────────────────────────────────────────────────────

    @property
    def known_ids(self) -> List[str]:
        """All map_ids we currently have local files for."""
        if not self._loaded:
            self.load()
        return list(self._entries.keys())

    def entry(self, map_id: str) -> IngestStateEntry | None:
        if not self._loaded:
            self.load()
        return self._entries.get(map_id)
