"""HTTP client for the Dzaleka Online Services public API.

Handles the API's conventions in one place:
- descriptive User-Agent and optional API-Version pinning
- RFC 9457 problem+json errors -> ApiError(code, detail, resolution)
- RateLimit-* headers tracking, and a bounded retry on 429 honouring Retry-After
- an on-disk response cache, with stale fallback when the network is down
"""
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests

from dzdk import __version__

USER_AGENT = f"dzdk/{__version__} (+https://github.com/Dzaleka-Connect/dzdk-cli)"
API_VERSION = "1.0.0"
MAX_RETRY_WAIT = 10  # seconds; never block the user longer than this on a 429


class ApiError(Exception):
    """An API or network failure with the server's problem details when available."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        detail: Optional[str] = None,
        resolution: Optional[str] = None,
        url: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail
        self.resolution = resolution
        self.url = url

    @classmethod
    def from_response(cls, response: requests.Response) -> "ApiError":
        problem: Dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict):
                problem = body
        except ValueError:
            pass
        title = problem.get("title") or response.reason or "Request failed"
        return cls(
            f"HTTP {response.status_code}: {title}",
            status=response.status_code,
            code=problem.get("code"),
            detail=problem.get("detail"),
            resolution=problem.get("resolution"),
            url=response.url,
        )


class RateLimit:
    """Latest RateLimit-* values reported by the server."""

    def __init__(self) -> None:
        self.limit: Optional[int] = None
        self.remaining: Optional[int] = None
        self.reset: Optional[int] = None

    def update(self, headers: Any) -> None:
        for attr, header in (("limit", "RateLimit-Limit"), ("remaining", "RateLimit-Remaining"),
                             ("reset", "RateLimit-Reset")):
            value = headers.get(header)
            if value is not None:
                try:
                    setattr(self, attr, int(value))
                except ValueError:
                    pass

    def __str__(self) -> str:
        if self.remaining is None:
            return "unknown"
        return f"{self.remaining}/{self.limit} left, resets in {self.reset}s"


class ResponseCache:
    """Tiny JSON file cache keyed by request."""

    def __init__(self, directory: Optional[Path], ttl: int):
        self.directory = directory
        self.ttl = ttl
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.directory is not None and self.ttl > 0

    def _path(self, key: str) -> Path:
        assert self.directory is not None
        return self.directory / (hashlib.sha1(key.encode()).hexdigest() + ".json")

    def get(self, key: str, *, allow_stale: bool = False) -> Tuple[bool, Any]:
        if not self.enabled:
            return False, None
        path = self._path(key)
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
            return False, None
        if allow_stale or time.time() - entry.get("t", 0) < self.ttl:
            return True, entry.get("data")
        return False, None

    def set(self, key: str, data: Any) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"t": time.time(), "data": data}))
                tmp.replace(path)
            except OSError:
                pass  # the cache is best-effort

    def clear(self) -> int:
        if not self.directory or not self.directory.exists():
            return 0
        count = 0
        for path in self.directory.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        return count


def extract_items(payload: Any, collection: str) -> List[Dict[str, Any]]:
    """Pull the item list out of a collection response ({status, data: {<name>: [...]}})."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in (collection, collection.replace("-", "_"), _camel(collection), "items"):
            if isinstance(data.get(key), list):
                return data[key]
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return []


def _camel(name: str) -> str:
    head, *rest = name.split("-")
    return head + "".join(part.title() for part in rest)


def item_id(item: Dict[str, Any]) -> str:
    return str(item.get("id") or item.get("slug") or "")


class DzdkClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30,
        cache_dir: Optional[Path] = None,
        cache_ttl: int = 300,
        offline_fallback: bool = True,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.offline_fallback = offline_fallback
        self.cache = ResponseCache(cache_dir, cache_ttl)
        self.rate_limit = RateLimit()
        self.last_was_stale = False
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/problem+json",
            "API-Version": API_VERSION,
        })

    @classmethod
    def from_config(cls, config: Dict[str, Any], *, use_cache: bool = True) -> "DzdkClient":
        from dzdk.config import cache_dir

        return cls(
            config["api_url"],
            timeout=config.get("timeout", 30),
            cache_dir=cache_dir() if use_cache else None,
            cache_ttl=int(config.get("cache_ttl", 300)),
            offline_fallback=bool(config.get("offline_fallback", True)),
        )

    # ------------------------------------------------------------------ core

    @property
    def site_url(self) -> str:
        return self.base_url[: -len("/api")] if self.base_url.endswith("/api") else self.base_url

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        cache: bool = True,
        retries: int = 2,
    ) -> Any:
        url = self.url(path)
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        key = json.dumps([method, url, params, json_body], sort_keys=True, default=str)
        self.last_was_stale = False

        if cache:
            hit, data = self.cache.get(key)
            if hit:
                return data

        try:
            response = self._send(method, url, params, json_body, retries)
        except requests.RequestException as exc:
            if cache and self.offline_fallback:
                hit, data = self.cache.get(key, allow_stale=True)
                if hit:
                    self.last_was_stale = True
                    return data
            raise ApiError(f"Network error: {exc}", url=url) from exc

        if not response.ok:
            raise ApiError.from_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError(
                "The endpoint returned a web page, not JSON",
                status=response.status_code,
                code="not_json",
                resolution=f"Open it in a browser instead: {response.url}",
                url=response.url,
            ) from exc
        if cache:
            self.cache.set(key, data)
        return data

    def _send(self, method: str, url: str, params: Dict[str, Any], json_body: Any,
              retries: int) -> requests.Response:
        for attempt in range(retries + 1):
            response = self.session.request(method, url, params=params or None, json=json_body,
                                            timeout=self.timeout)
            self.rate_limit.update(response.headers)
            if response.status_code != 429 or attempt == retries:
                return response
            time.sleep(self._retry_after(response))
        return response  # pragma: no cover - loop always returns

    @staticmethod
    def _retry_after(response: requests.Response) -> float:
        try:
            wait = float(response.headers.get("Retry-After", 1))
        except ValueError:
            wait = 1.0
        return max(0.0, min(wait, MAX_RETRY_WAIT))

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    # ----------------------------------------------------------- collections

    def list_collection(self, name: str, *, cache: bool = True) -> List[Dict[str, Any]]:
        return extract_items(self.get(f"/{name}", cache=cache), name)

    def get_item(self, collection: str, identifier: str) -> Dict[str, Any]:
        """Find one item by id or slug (the API has no per-item routes)."""
        for item in self.list_collection(collection):
            if identifier in (item.get("id"), item.get("slug")):
                return item
        raise ApiError(
            f"No {collection} item with id '{identifier}'",
            status=404,
            code="not_found",
            resolution=f"Run `dzdk {collection} list` to see valid ids.",
        )

    def export(self, collections: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch several collections in a single request."""
        names = list(collections)
        payload = self.request("POST", "/export", json_body={"collections": names})
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        return {name: data.get(name, []) for name in names}

    def export_info(self) -> Dict[str, Any]:
        return self.get("/export")

    # ---------------------------------------------------------------- search

    def search(self, query: str, *, collections: Optional[Iterable[str]] = None,
               limit: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if collections:
            params["collections"] = ",".join(collections)
        return self.get("/search", params=params)

    # ---------------------------------------------------------- encyclopedia

    def encyclopedia(
        self,
        *,
        q: Optional[str] = None,
        category: Optional[str] = None,
        entry_type: Optional[str] = None,
        status: Optional[str] = None,
        featured: Optional[bool] = None,
        page: int = 1,
        per_page: int = 20,
        sort: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        payload = self.get("/encyclopedia", params={
            "q": q, "category": category, "type": entry_type, "status": status,
            "featured": None if featured is None else str(featured).lower(),
            "page": page, "perPage": per_page, "sort": sort, "order": order,
        })
        return payload.get("data", {}).get("entries", []), payload.get("meta", {})

    def encyclopedia_entry(self, slug: str) -> Dict[str, Any]:
        return self.get(f"/encyclopedia/{slug}").get("data", {}).get("entry", {})

    def encyclopedia_suggest(self, q: str, limit: int = 8) -> List[Dict[str, Any]]:
        payload = self.get("/encyclopedia/suggest", params={"q": q, "limit": limit})
        return payload.get("data", {}).get("suggestions", [])

    def encyclopedia_facets(self) -> Dict[str, Any]:
        return self.get("/encyclopedia/facets").get("data", {})

    # ------------------------------------------------------------ dashboards

    def status(self) -> Dict[str, Any]:
        return self.get("/status", cache=False)

    def population(self) -> Dict[str, Any]:
        return self.get("/population")

    def alerts(self) -> List[Dict[str, Any]]:
        data = self.get("/alerts")
        return data if isinstance(data, list) else extract_items(data, "alerts")

    def weather(self) -> Dict[str, Any]:
        return self.get("/weather")

    def weather_alerts(self) -> List[Dict[str, Any]]:
        data = self.get("/weather-alerts")
        return data if isinstance(data, list) else []

    def finance(self) -> Dict[str, Any]:
        return self.get("/finance")

    def charts(self) -> Dict[str, Any]:
        return self.get("/charts")

    def mcp_card(self) -> Dict[str, Any]:
        response = self.session.get(f"{self.site_url}/mcp", timeout=self.timeout)
        if not response.ok:
            raise ApiError.from_response(response)
        return response.json()

    # ------------------------------------------------------------- downloads

    def download(self, url: str, dest: Path,
                 on_progress: Optional[Callable[[int, Optional[int]], None]] = None) -> int:
        """Stream a file to disk. Calls on_progress(bytes_so_far, total_or_None)."""
        try:
            with self.session.get(url, stream=True, timeout=self.timeout) as response:
                if not response.ok:
                    raise ApiError.from_response(response)
                total = response.headers.get("content-length")
                total_bytes = int(total) if total and total.isdigit() else None
                written = 0
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                            if on_progress:
                                on_progress(written, total_bytes)
                return written
        except requests.RequestException as exc:
            raise ApiError(f"Download failed: {exc}", url=url) from exc
