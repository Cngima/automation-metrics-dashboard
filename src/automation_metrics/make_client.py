"""Read-only client for the Make API (data store records).

Only GET requests are made. The client never creates, edits or deletes anything in Make.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

log = logging.getLogger(__name__)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class MakeAPIError(RuntimeError):
    pass


class MakeClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        session: requests.Session | None = None,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        page_size: int = 100,
    ):
        if not token:
            raise MakeAPIError("No Make API token. Set MAKE_API_TOKEN in .env (read-only scopes are enough).")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.page_size = page_size

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise MakeAPIError(f"Network error calling Make: {e}") from e
                self._wait(attempt, None)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                self._wait(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code == 401:
                raise MakeAPIError("Make rejected the token (401). Check MAKE_API_TOKEN and its scopes.")
            if resp.status_code >= 400:
                raise MakeAPIError(f"Make API error {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise MakeAPIError("Make API retries exhausted")

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff_seconds * 2**attempt
        log.warning("Make API busy, retrying in %.1fs", delay)
        self.sleep(delay)

    def data_store_records(self, data_store_id: int) -> list[dict]:
        """All records of a data store, following pagination. Each record is {'key': ..., 'data': {...}}."""
        records: list[dict] = []
        offset = 0
        while True:
            page = self._get(
                f"/data-stores/{data_store_id}/data",
                {"pg[limit]": self.page_size, "pg[offset]": offset},
            )
            batch = page.get("records", [])
            records.extend(batch)
            if len(batch) < self.page_size:
                return records
            offset += self.page_size
