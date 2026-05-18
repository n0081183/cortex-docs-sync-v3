"""HTTP client for the Cortex Documentation Hub FluidTopics JSON API.

The portal at docs-cortex.paloaltonetworks.com is backed by FluidTopics 5.1.14.
Its `robots.txt` explicitly allows the API and reader paths used by this client:

    Allow: /r/*
    Allow: /reader/*/*
    Allow: /api/khub/documents/*/content
    Allow: /sitemap.xml
    Allow: /sitemap/structured/*.xml
    Allow: /sitemap/unstructured/*.xml

Endpoints used (no authentication required):

    GET /api/khub/maps                                  → publication catalog
    GET /api/khub/maps/{map_id}                         → publication metadata
    GET /api/khub/maps/{map_id}/topics                  → flat topic list
    GET /api/khub/maps/{map_id}/topics/{tid}/content    → topic HTML fragment
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

from cortex_docs_sync.models import CORTEX_BASE_URL, Publication

DEFAULT_USER_AGENT = "cortex-docs-sync/0.1.0 (+https://github.com/mzalewski87/cortex-docs-sync)"
DEFAULT_RATE_LIMIT_RPS = 1.0

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforce a minimum time interval between successive calls.

    Single-process, single-threaded. Not safe across processes — if you run
    multiple sync jobs in parallel against the portal, give each its own
    rate budget and lower `requests_per_second` accordingly.
    """

    def __init__(self, requests_per_second: float) -> None:
        self.min_interval = 1.0 / max(requests_per_second, 0.1)
        self._last_call = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class CortexDocsClient:
    """Polite GET-only client for the FluidTopics JSON API.

    Retries on 5xx and transport errors with exponential backoff
    (1, 2, 4 seconds by default). 4xx responses are raised immediately —
    no point retrying a 404.
    """

    def __init__(
        self,
        base_url: str = CORTEX_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS,
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.8, */*;q=0.5",
        })
        self.rate_limiter = RateLimiter(rate_limit_rps)
        self.timeout = timeout_seconds
        self.max_retries = max_retries

    # ── Internal HTTP helper ────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        url = f"{self.base_url}{path}"
        last_exc: Optional[BaseException] = None

        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code >= 500:
                    raise requests.HTTPError(
                        f"HTTP {resp.status_code} from {url}", response=resp
                    )
                resp.raise_for_status()
                return resp
            except (requests.RequestException, requests.HTTPError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "GET %s failed (attempt %d/%d): %s — retrying in %ds",
                        path, attempt, self.max_retries, exc, backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "GET %s failed after %d attempts: %s",
                        path, attempt, exc,
                    )

        raise RuntimeError(
            f"GET {path} failed after {self.max_retries} attempts"
        ) from last_exc

    # ── Public API ──────────────────────────────────────────────────────────

    def list_publications(self, limit: int = 10000) -> List[Publication]:
        """Fetch the entire publication catalog in a single request.

        This is the only endpoint that exposes `ft:lastTechChange` for every
        publication in one call — the foundation of incremental sync.
        """
        resp = self._get("/api/khub/maps", params={"limit": limit})
        raw = resp.json()
        return [self._parse_publication(item) for item in raw]

    def get_topics(self, map_id: str) -> List[dict]:
        """Return the publication's flat topic list.

        Topic objects contain at least: `id`, `title`, `breadcrumb`,
        `contentApiEndpoint`, `readerUrl`. Hierarchy is encoded in
        `breadcrumb`, not via nested `children`.
        """
        resp = self._get(f"/api/khub/maps/{quote(map_id)}/topics")
        return resp.json()

    def get_topic_content(self, map_id: str, topic_id: str) -> str:
        """Return the topic's HTML fragment (no SPA shell)."""
        resp = self._get(
            f"/api/khub/maps/{quote(map_id)}/topics/{quote(topic_id)}/content"
        )
        return resp.text

    # ── Parsing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_publication(item: dict) -> Publication:
        """Convert one raw catalog item dict into a `Publication`.

        FluidTopics flattens metadata into `[{"key": ..., "values": [...]}]`,
        which is awkward to consume — we collapse it to a single lookup dict
        and pull out the fields we care about.
        """
        meta_lookup: Dict[str, List[str]] = {}
        for meta in item.get("metadata", []):
            key = meta.get("key")
            values = meta.get("values") or []
            if key:
                meta_lookup[key] = values

        def first(key: str) -> Optional[str]:
            values = meta_lookup.get(key)
            return values[0] if values else None

        # Version: prefer "subtitle: Version: X.Y", fall back to xinfo:version_*
        version: Optional[str] = None
        sub = first("subtitle")
        if sub and "version" in sub.lower():
            version = sub.split(":", 1)[-1].strip()
        elif first("xinfo:version_major"):
            major = first("xinfo:version_major")
            minor = first("xinfo:version_minor")
            version = f"{major}.{minor}" if minor else major

        word_count: Optional[int] = None
        wc_raw = first("ft:wordCount")
        if wc_raw:
            try:
                word_count = int(wc_raw)
            except ValueError:
                pass

        return Publication(
            map_id=item["id"],
            title=item.get("title", ""),
            products=meta_lookup.get("Product", []),
            category=first("Category"),
            version=version,
            last_edition=first("ft:lastEdition"),
            last_tech_change=first("ft:lastTechChange"),
            word_count=word_count,
            pretty_url=first("ft:prettyUrl") or "",
        )
