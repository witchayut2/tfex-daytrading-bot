"""Read-only client for the TFEX public website's own data endpoints.

The tfex.co.th site is a Nuxt application whose pages are shells; the holiday table and the
contract calendar are fetched by the page's own JavaScript from JSON endpoints on the same
host. This module calls those same public, unauthenticated endpoints — the ones a browser
loading the page calls — and captures the bytes verbatim.

Why a session handshake is needed: the site sits behind a WAF that rejects a bare request to
an ``/api/`` path with HTTP 401/403. Loading the corresponding human page first sets the
cookies that make the subsequent API call look like what it is — the same page fetching its
own data. No credentials, no tokens, no access control is bypassed.

Usage is deliberately manual and low-volume. Section 2: *"Do not scrape them on every market
event. Build scheduled metadata refresh jobs and cache validated results."*
"""

from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = ["ENDPOINTS", "FetchError", "RawResponse", "TfexWebClient", "sha256_hex"]

BASE = "https://www.tfex.co.th"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

#: The endpoints this project reads, and the page whose session each one belongs to.
ENDPOINTS: dict[str, tuple[str, str]] = {
    "holidays": (
        "/api/cms/v1/holidays/year/{year}?lang={lang}",
        "/{lang}/about/holiday",
    ),
    "holiday_remark": (
        "/api/cms/v1/holidays/holiday-remark?lang={lang}",
        "/{lang}/about/holiday",
    ),
    "series_list": (
        "/api/set/tfex/series/list",
        "/en/products/equity/set50-index-futures/trading-calendar",
    ),
    "series_info": (
        "/api/set/tfex/series/{symbol}/info",
        "/en/products/equity/set50-index-futures/trading-calendar",
    ),
}

_TIMEOUT_SECONDS = 45


class FetchError(RuntimeError):
    """A source could not be retrieved. Never swallowed into an empty result."""


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class RawResponse:
    """Exactly what came back, before anything interprets it."""

    url: str
    status: int
    content: bytes
    content_type: str | None
    retrieved_at: datetime

    @property
    def sha256(self) -> str:
        return sha256_hex(self.content)

    def json(self) -> Any:
        try:
            return json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(f"{self.url} did not return valid JSON: {exc}") from exc

    def describe(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "http_status": self.status,
            "content_type": self.content_type,
            "content_length": len(self.content),
            "sha256": self.sha256,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


def _decode_body(raw: bytes, encoding: str | None) -> bytes:
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        return zlib.decompress(raw)
    return raw


class TfexWebClient:
    """Session-scoped reader for the public tfex.co.th JSON endpoints."""

    def __init__(self, *, base: str = BASE) -> None:
        self._base = base.rstrip("/")
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._warmed: set[str] = set()

    # --- low level --------------------------------------------------------------------

    def _get(self, path: str, *, referer: str | None, accept: str) -> RawResponse:
        url = f"{self._base}{path}"
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Accept", accept)
        request.add_header("Accept-Language", "en-US,en;q=0.9,th;q=0.8")
        request.add_header("Accept-Encoding", "gzip, deflate")
        if referer:
            request.add_header("Referer", f"{self._base}{referer}")

        try:
            with self._opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                body = _decode_body(response.read(), response.headers.get("Content-Encoding"))
                return RawResponse(
                    url=url,
                    status=response.status,
                    content=body,
                    content_type=response.headers.get("Content-Type"),
                    retrieved_at=datetime.now(UTC),
                )
        except urllib.error.HTTPError as exc:
            raise FetchError(f"GET {url} failed with HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError(f"GET {url} failed: {exc}") from exc

    def _warm(self, page_path: str) -> None:
        """Load the human page so the WAF issues this session its cookies."""
        if page_path in self._warmed:
            return
        self._get(page_path, referer=None, accept="text/html,application/xhtml+xml")
        self._warmed.add(page_path)

    def fetch(self, endpoint: str, **params: str | int) -> RawResponse:
        """Fetch a named endpoint from :data:`ENDPOINTS`, warming its page session first."""
        try:
            path_template, page_template = ENDPOINTS[endpoint]
        except KeyError:
            raise FetchError(f"unknown endpoint {endpoint!r}; known: {sorted(ENDPOINTS)}") from None
        page = page_template.format(**params) if "{" in page_template else page_template
        self._warm(page)
        path = path_template.format(**params)
        response = self._get(path, referer=page, accept="application/json, text/plain, */*")
        if response.status != 200:
            raise FetchError(f"{response.url} returned HTTP {response.status}")
        return response

    # --- named reads ------------------------------------------------------------------

    def holidays(self, year: int, lang: str = "en") -> RawResponse:
        return self.fetch("holidays", year=year, lang=lang)

    def holiday_remark(self, lang: str = "en") -> RawResponse:
        return self.fetch("holiday_remark", lang=lang)

    def series_list(self) -> RawResponse:
        return self.fetch("series_list")

    def series_info(self, symbol: str) -> RawResponse:
        return self.fetch("series_info", symbol=symbol)
