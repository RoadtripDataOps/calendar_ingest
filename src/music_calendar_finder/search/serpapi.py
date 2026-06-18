from __future__ import annotations

import os
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from music_calendar_finder.models import SearchResponse, SearchResult
from .base import SearchProvider


class SerpApiSearchProvider(SearchProvider):
    provider_name = "serpapi"
    search_endpoint = "https://serpapi.com/search.json"
    account_endpoint = "https://serpapi.com/account.json"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        api_key: str | None = None,
        dry_run: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or {}
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY")
        self.dry_run = dry_run
        self.client = client or httpx.Client(timeout=self.config.get("timeout_seconds", 20))

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResponse:
        if self.dry_run:
            return self._dry_run_response(query, page)
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY is required unless --dry-run is used")
        payload = self._request(query, page, location)
        organic = payload.get("organic_results", []) or []
        results = [
            SearchResult(
                title=item.get("title"),
                link=item.get("link") or item.get("redirect_link") or "",
                displayed_link=item.get("displayed_link"),
                snippet=item.get("snippet"),
                position=item.get("position"),
                source=item.get("source"),
            )
            for item in organic
            if item.get("link") or item.get("redirect_link")
        ]
        return SearchResponse(
            query=query,
            page=page,
            provider=self.provider_name,
            results=results,
            api_status=payload.get("search_metadata", {}).get("status"),
            raw=payload,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _request(self, query: str, page: int, location: str | None) -> dict[str, Any]:
        params = {
            "engine": self.config.get("engine", "google"),
            "q": query,
            "api_key": self.api_key,
            "google_domain": self.config.get("google_domain", "google.com"),
            "hl": self.config.get("hl", "en"),
            "gl": self.config.get("gl", "us"),
            "num": self.config.get("num", 10),
            "safe": self.config.get("safe", "active"),
            "no_cache": str(bool(self.config.get("no_cache", False))).lower(),
            "start": max(page - 1, 0) * int(self.config.get("num", 10)),
        }
        if location:
            params["location"] = location
        response = self.client.get(self.search_endpoint, params=params)
        if response.status_code == 400 and location and "location" in response.text and "Unsupported" in response.text:
            params.pop("location", None)
            response = self.client.get(self.search_endpoint, params=params)
        response.raise_for_status()
        return response.json()

    def account(self) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY is required for account checks")
        response = self.client.get(self.account_endpoint, params={"api_key": self.api_key})
        response.raise_for_status()
        return response.json()

    def _dry_run_response(self, query: str, page: int) -> SearchResponse:
        cityish = query.split(" live ")[0].split(" music ")[0].split(" arts ")[0].strip()
        city_slug = re.sub(r"[^a-z0-9]+", "-", cityish.lower().replace("site:", " ")).strip("-") or "local"
        city_slug = "-".join(city_slug.split("-")[:3]) or "local"
        samples = [
            (
                f"{cityish} Music Calendar",
                f"https://{city_slug}music.org/events",
                "Local music, concerts, festivals, and nightlife calendar.",
            ),
            (
                f"Visit {cityish} Events",
                f"https://visit{city_slug}.com/events",
                "Official tourism events and things to do calendar with music listings.",
            ),
            (
                f"{cityish} Arts Council Calendar",
                f"https://{city_slug}arts.org/calendar",
                "Arts, culture, community calendar, concerts, and festivals.",
            ),
        ]
        return SearchResponse(
            query=query,
            page=page,
            provider=self.provider_name,
            api_status="dry_run",
            results=[
                SearchResult(
                    title=title,
                    link=link,
                    displayed_link=link.split("//", 1)[-1],
                    snippet=snippet,
                    position=i + 1,
                    url_origin="dry_run_fixture",
                )
                for i, (title, link, snippet) in enumerate(samples)
            ],
        )
