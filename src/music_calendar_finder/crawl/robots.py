from __future__ import annotations

from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx


class RobotsChecker:
    def __init__(
        self,
        *,
        user_agent: str = "MusicCalendarSourceFinderBot/0.1",
        client: httpx.Client | None = None,
        timeout: float = 10,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client(timeout=timeout)
        self.cache: dict[str, RobotFileParser | None] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        domain_key = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if domain_key not in self.cache:
            self.cache[domain_key] = self._load_parser(parsed.scheme, parsed.netloc)
        parser = self.cache[domain_key]
        if parser is None:
            return False
        return parser.can_fetch(self.user_agent, url)

    def _load_parser(self, scheme: str, netloc: str) -> RobotFileParser | None:
        robots_url = urlunparse((scheme or "https", netloc, "/robots.txt", "", "", ""))
        try:
            response = self.client.get(robots_url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser


class AllowAllRobotsChecker:
    def can_fetch(self, url: str) -> bool:
        return True

