"""Polite, resilient HTTP client shared by every source.

Centralises the user-agent, per-host rate limiting, timeouts and retries so
individual scrapers stay small and every request is a good public-server
citizen.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        min_delay_seconds: float = 2.0,
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.min_delay = min_delay_seconds
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last_request_at = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._throttle()

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(
                (requests.ConnectionError, requests.Timeout)
            ),
            reraise=True,
        )
        def _do() -> requests.Response:
            kwargs.setdefault("timeout", self.timeout)
            log.debug("%s %s", method, url)
            resp = self.session.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

        return _do()

    def get_json(self, url: str, **kwargs) -> Optional[dict]:
        resp = self.get(url, **kwargs)
        try:
            return resp.json()
        except ValueError:
            log.warning("Non-JSON response from %s", url)
            return None
