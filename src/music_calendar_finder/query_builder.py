from __future__ import annotations

from typing import Any

from .models import CityDiscoveryBudget


CORE_TEMPLATES = [
    "{place} live music calendar",
    "{place} music events calendar",
    "{place} concerts calendar local",
    "{place} arts culture events",
    "{place} arts calendar",
    "{place} culture magazine music",
    "{place} alt weekly music",
    "{place} newspaper arts music",
    "{place} observer music events",
    "{place} new times music events",
    "{place} tourism events calendar",
    "{place} visit events music",
    "{place} chamber events calendar",
    "{place} downtown events calendar",
    "{place} nightlife calendar",
    "{place} local music blog",
    "{place} radio station events calendar",
    "{place} university music events calendar",
    "{place} community calendar music",
    "{place} festival calendar music",
    "site:.org {place} arts events calendar",
    "site:.edu {place} music events calendar",
]

METRO_TEMPLATES = [
    "{metro_name} music calendar",
    "{metro_name} arts culture events",
    "{metro_name} concert calendar",
    "{metro_name} nightlife events",
]


def build_search_queries(city_record: dict[str, Any], budget: CityDiscoveryBudget, country: str = "US") -> list[str]:
    city = str(city_record.get("city") or "").strip()
    state = str(city_record.get("state") or "").strip()
    place = f"{city} {state}".strip()
    queries: list[str] = []
    for template in CORE_TEMPLATES:
        queries.append(template.format(place=place, city=city, state=state, country=country))

    metro_name = city_record.get("metro_name")
    if metro_name and budget.should_expand_metro_queries:
        for template in METRO_TEMPLATES:
            queries.append(template.format(metro_name=metro_name))

    return _dedupe(queries)[: budget.max_serpapi_queries]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output

