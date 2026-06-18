from __future__ import annotations

from abc import ABC, abstractmethod

from music_calendar_finder.models import SearchResponse


class SearchProvider(ABC):
    provider_name = "base"

    @abstractmethod
    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResponse:
        raise NotImplementedError

