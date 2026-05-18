"""HTTP client for the Cortex Documentation Hub FluidTopics JSON API."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cortex_docs_sync.models import CORTEX_BASE_URL, Publication

DEFAULT_USER_AGENT = "cortex-docs-sync/0.1.0 (+https://github.com/mzalewski87/cortex-docs-sync)"
DEFAULT_RATE_LIMIT_RPS = 100.0  # Wartość domyślna bez znaczenia po zdjęciu limitów

logger = logging.getLogger(__name__)


class RateLimiter:
    """Zneutralizowany limiter prędkości."""

    def __init__(self, requests_per_second: float) -> None:
        pass

    def wait(self) -> None:
        # Pełna przepustowość - brak sztucznego czekania
        pass


class CortexDocsClient:
    """Agresywny klient GET dla API FluidTopics z pulą połączeń TCP."""

    def __init__(
        self,
        base_url: str = CORTEX_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS,
        timeout_seconds: int = 30,
        max_retries: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.8, */*;q=0.5",
        })
        
        # --- KLUCZOWA ZMIANA: Autostrada sieciowa ---
        # Utrzymujemy 100 otwartych połączeń TCP. Zero narzutu na Handshake TLS.
        retries = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
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
        resp = self._get("/api/khub/maps", params={"limit": limit})
        raw = resp.json()
        return [self._parse_publication(item) for item in raw]

    def get_topics(self, map_id: str) -> List[dict]:
        resp = self._get(f"/api/khub/maps/{quote(map_id)}/topics")
        return resp.json()

    def get_topic_content(self, map_id: str, topic_id: str) -> str:
        resp = self._get(
            f"/api/khub/maps/{quote(map_id)}/topics/{quote(topic_id)}/content"
        )
        return resp.text

    # ── Parsing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_publication(item: dict) -> Publication:
        meta_lookup: Dict[str, List[str]] = {}
        for meta in item.get("metadata", []):
            key = meta.get("key")
            values = meta.get("values") or []
            if key:
                meta_lookup[key] = values

        def first(key: str) -> Optional[str]:
            values = meta_lookup.get(key)
            return values[0] if values else None

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
