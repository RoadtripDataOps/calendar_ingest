from __future__ import annotations

from typing import Any

import httpx

from music_calendar_finder.models import FetchResult
from .robots import RobotsChecker


class PageFetcher:
    def __init__(
        self,
        *,
        robots: RobotsChecker | None = None,
        user_agent: str = "MusicCalendarSourceFinderBot/0.1",
        timeout: float = 15,
        max_response_bytes: int = 2 * 1024 * 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self.robots = robots
        self.user_agent = user_agent
        self.max_response_bytes = max_response_bytes
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, url: str) -> FetchResult:
        if self.robots and not self.robots.can_fetch(url):
            return FetchResult(url=url, error="robots_disallowed")
        try:
            with self.client.stream("GET", url, headers={"User-Agent": self.user_agent}) as response:
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return FetchResult(
                        url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        error="non_html_content",
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        return FetchResult(
                            url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=content_type,
                            error="response_too_large",
                        )
                    chunks.append(chunk)
                response.raise_for_status()
                encoding = response.encoding or "utf-8"
                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                    html=b"".join(chunks).decode(encoding, errors="replace"),
                )
        except httpx.HTTPError as exc:
            return FetchResult(url=url, error=str(exc))


class StaticFetcher:
    def __init__(self, pages: dict[str, str | dict[str, Any]]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> FetchResult:
        page = self.pages.get(url)
        if page is None:
            return FetchResult(url=url, status_code=404, error="not_found")
        if isinstance(page, dict):
            return FetchResult(url=url, final_url=page.get("final_url", url), status_code=page.get("status_code", 200), html=page.get("html"))
        return FetchResult(url=url, final_url=url, status_code=200, content_type="text/html", html=page)

