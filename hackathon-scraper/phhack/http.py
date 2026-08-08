"""Shared HTTP client: retries, polite pacing, optional disk cache, raw dumps."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "ph-hackathon-scraper/1.0 (+https://github.com/StarRayX/StarRayX) "
    "python-requests"
)

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a request fails after exhausting retries."""


class HttpClient:
    """Thin wrapper over `requests.Session` with the behaviour every adapter wants.

    Caching is opt-in and keyed on the full request, which makes iterating on a
    parser cheap: the first run pays for the network, later runs replay it.
    """

    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.5,
        delay: float = 0.6,
        cache_dir: Optional[str] = None,
        cache_ttl: int = 3600,
        dump_dir: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.delay = delay
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.dump_dir = dump_dir
        self._last_request_at = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        for directory in (cache_dir, dump_dir):
            if directory:
                os.makedirs(directory, exist_ok=True)

    # -- public ---------------------------------------------------------

    def get_json(
        self,
        url: str,
        params: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        label: str = "",
    ) -> Any:
        return self._request_json("GET", url, params=params, headers=headers, label=label)

    def post_json(
        self,
        url: str,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        label: str = "",
    ) -> Any:
        return self._request_json("POST", url, json_body=payload, headers=headers, label=label)

    def get_text(
        self,
        url: str,
        params: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        label: str = "",
    ) -> str:
        body = self._request_raw("GET", url, params=params, headers=headers, label=label)
        return body

    # -- internals ------------------------------------------------------

    def _request_json(
        self,
        method: str,
        url: str,
        params: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        label: str = "",
    ) -> Any:
        body = self._request_raw(
            method, url, params=params, json_body=json_body, headers=headers, label=label
        )
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            # Nearly always an HTML interstitial (Cloudflare, login wall) rather
            # than malformed JSON, so say what actually arrived.
            preview = body[:180].replace("\n", " ")
            raise FetchError(f"{url} returned non-JSON ({exc}): {preview!r}") from exc

    def _request_raw(
        self,
        method: str,
        url: str,
        params: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        label: str = "",
    ) -> str:
        cache_key = self._cache_key(method, url, params, json_body)
        cached = self._cache_read(cache_key)
        if cached is not None:
            log.debug("cache hit %s %s", method, url)
            return cached

        last_error: Optional[str] = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in RETRY_STATUS:
                    last_error = f"HTTP {response.status_code}"
                elif not response.ok:
                    # 4xx other than 429 will not fix themselves; fail fast.
                    raise FetchError(f"{method} {url} -> HTTP {response.status_code}")
                else:
                    body = response.text
                    self._cache_write(cache_key, body)
                    self._dump(label or cache_key, body)
                    return body

            if attempt < self.retries:
                sleep_for = self.backoff ** (attempt + 1)
                log.warning(
                    "%s %s failed (%s); retry %d/%d in %.1fs",
                    method, url, last_error, attempt + 1, self.retries, sleep_for,
                )
                time.sleep(sleep_for)

        raise FetchError(f"{method} {url} failed after {self.retries + 1} attempts: {last_error}")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at = time.time()

    def _cache_key(self, method: str, url: str, params: Any, json_body: Any) -> str:
        raw = json.dumps(
            [method, url, params, json_body], sort_keys=True, default=str
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def _cache_path(self, key: str) -> Optional[str]:
        return os.path.join(self.cache_dir, key + ".txt") if self.cache_dir else None

    def _cache_read(self, key: str) -> Optional[str]:
        path = self._cache_path(key)
        if not path or not os.path.exists(path):
            return None
        if self.cache_ttl >= 0 and time.time() - os.path.getmtime(path) > self.cache_ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return None

    def _cache_write(self, key: str, body: str) -> None:
        path = self._cache_path(key)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
        except OSError as exc:
            log.debug("cache write failed: %s", exc)

    def _dump(self, label: str, body: str) -> None:
        """Persist raw payloads so a broken parser can be diagnosed offline."""
        if not self.dump_dir:
            return
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in label)[:80]
        path = os.path.join(self.dump_dir, f"{safe}.txt")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
        except OSError as exc:
            log.debug("dump write failed: %s", exc)
