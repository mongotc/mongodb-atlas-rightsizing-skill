"""
Atlas Admin API wrapper: authentication, retry/backoff, pagination.

Public surface:
  - AtlasAPIError            raised for any Atlas API failure not swallowed
                             by retries
  - AtlasClient              requests-based wrapper with:
      * OAuth service account (ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET) with
        token refresh
      * Legacy digest auth (ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY)
      * Retry with exponential backoff on 429 / 5xx
      * Pagination helper `get_all` for endpoints returning `{results: [...]}`
  - utc_now                  ISO-8601 UTC timestamp helper used by callers
                             that record when they ran

Auth is picked at construction time from either an env dict passed in or
`os.environ`. If neither credential pair is present, construction raises
AtlasAPIError with a clear message — no silent fallback to unauthenticated.

Kept API-compatible with the equivalent code in scripts/rightsizing.py and
src/extraction/common.py so this can become the shared source of truth
without breaking either.
"""

import os
import time
from datetime import datetime, timezone

import requests
from requests.auth import HTTPDigestAuth


ATLAS_BASE = "https://cloud.mongodb.com/api/atlas/v2"
TOKEN_URL = "https://cloud.mongodb.com/api/oauth/token"
# Pinned so a newer default API version can't change response shapes underneath us.
API_VERSION_HEADER = {"Accept": "application/vnd.atlas.2025-03-12+json"}


def utc_now():
    """ISO-8601 UTC timestamp string, e.g. '2026-09-29T21:15:00Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AtlasAPIError(Exception):
    pass


class AtlasClient:
    """requests wrapper: auth (with OAuth token refresh), retry with backoff on
    429/5xx, pagination, and failures raised as AtlasAPIError instead of
    being swallowed."""

    RETRY_STATUSES = (429, 500, 502, 503, 504)

    def __init__(self, session=None, max_retries=5, timeout=30, sleep=time.sleep, env=None):
        env = os.environ if env is None else env
        self.session = session or requests.Session()
        self.session.headers.update(API_VERSION_HEADER)
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep
        self._client_id = env.get("ATLAS_CLIENT_ID")
        self._client_secret = env.get("ATLAS_CLIENT_SECRET")
        self._token_expires_at = 0.0
        public_key, private_key = env.get("ATLAS_PUBLIC_KEY"), env.get("ATLAS_PRIVATE_KEY")
        if self._uses_oauth():
            self._refresh_token()
        elif public_key and private_key:
            self.session.auth = HTTPDigestAuth(public_key, private_key)
        else:
            raise AtlasAPIError(
                "No credentials found. Set ATLAS_CLIENT_ID/ATLAS_CLIENT_SECRET "
                "(service account) or ATLAS_PUBLIC_KEY/ATLAS_PRIVATE_KEY "
                "(API key) in the environment."
            )

    def _uses_oauth(self):
        return bool(self._client_id and self._client_secret)

    def _refresh_token(self):
        resp = self.session.post(
            TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        if not resp.ok:
            raise AtlasAPIError(
                f"OAuth token request failed ({resp.status_code}): {resp.text[:300]}"
            )
        body = resp.json()
        self.session.headers["Authorization"] = f"Bearer {body['access_token']}"
        # Service-account tokens last an hour; refresh a minute early so long
        # audits don't 401 mid-run.
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600)) - 60

    def _backoff(self, attempt, retry_after):
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(2 ** attempt, 30)

    def get(self, path, params=None):
        url = path if path.startswith("http") else f"{ATLAS_BASE}{path}"
        refreshed_after_401 = False
        for attempt in range(self.max_retries + 1):
            if self._uses_oauth() and time.time() >= self._token_expires_at:
                self._refresh_token()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise AtlasAPIError(f"Network error on {path}: {e}")
                self._sleep(self._backoff(attempt, None))
                continue
            if resp.status_code == 401 and self._uses_oauth() and not refreshed_after_401:
                self._refresh_token()
                refreshed_after_401 = True
                continue
            if resp.status_code in self.RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, resp.headers.get("Retry-After")))
                continue
            if not resp.ok:
                raise AtlasAPIError(
                    f"Atlas API error {resp.status_code} on {path}: {resp.text[:500]}"
                )
            return resp.json()
        raise AtlasAPIError(f"Gave up on {path} after {self.max_retries} retries")

    def get_all(self, path, params=None, items_per_page=500):
        """Follow Atlas pagination and return every item in `results`."""
        params = dict(params or {})
        params.update({"itemsPerPage": items_per_page, "includeCount": "true"})
        items, page = [], 1
        while True:
            params["pageNum"] = page
            data = self.get(path, dict(params))
            batch = data.get("results", [])
            items.extend(batch)
            total = data.get("totalCount")
            if not batch or len(batch) < items_per_page or (total is not None and len(items) >= total):
                return items
            page += 1
