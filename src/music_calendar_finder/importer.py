from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import pandas as pd

from .db import upsert_city
from .utils import city_tier_for_population, normalize_blank, normalize_key, to_float, to_int, truthy


COLUMN_ALIASES = {
    "city": "city",
    "City": "city",
    "STATE": "state",
    "State": "state",
    "ST": "state",
    "state": "state",
    "state_code": "state",
    "state_id": "state",
    "state_name": "state_name",
    "State Name": "state_name",
    "Country": "country",
    "country": "country",
    "metro": "metro_name",
    "Metro": "metro_name",
    "metro_name": "metro_name",
    "county": "county",
    "County": "county",
    "population": "population",
    "Population": "population",
    "pop": "population",
    "lat": "lat",
    "latitude": "lat",
    "lng": "lng",
    "lon": "lng",
    "longitude": "lng",
    "id": "original_row_id",
    "row_id": "original_row_id",
    "priority": "priority",
    "Priority": "priority",
    "priority_level": "priority_level",
    "priority_reason": "priority_reason",
    "enabled": "enabled",
    "Enabled": "enabled",
}


@dataclass(frozen=True)
class ImportColumnMapping:
    city_column: str = "city"
    state_column: str = "state_id"
    population_column: str = "population"
    lat_column: str = "lat"
    lng_column: str = "lng"


@dataclass
class ImportResult:
    rows_read: int
    cities_inserted: int
    cities_updated: int
    rows_skipped: int
    import_batch_id: str


def import_cities_from_xlsx(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    column_mapping: ImportColumnMapping | None = None,
    min_population: int | None = None,
    max_population: int | None = None,
    state: str | None = None,
    limit: int | None = None,
    priority_only: bool = False,
    include_priority_cities: bool = False,
    priority_cities: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> ImportResult:
    path = Path(path)
    frame = pd.read_excel(path)
    if limit is not None:
        frame = frame.head(limit)
    import_batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows_read = len(frame)
    inserted = 0
    updated = 0
    skipped = 0
    seen: set[tuple[str, str, str, str]] = set()

    frame = frame.rename(columns=_build_column_rename_map(frame.columns, column_mapping or ImportColumnMapping()))

    if "city" not in frame.columns:
        raise ValueError("Input XLSX must include a city column")

    priority_cities = priority_cities or {}
    for idx, row in frame.iterrows():
        record = _row_to_city(row.to_dict(), idx + 2, import_batch_id)
        if not record:
            skipped += 1
            continue
        priority_data = _priority_data_for(record, priority_cities)
        if priority_data:
            record.update(priority_data)
        if not _passes_filters(
            record,
            min_population=min_population,
            max_population=max_population,
            state=state,
            priority_only=priority_only,
            include_priority_cities=include_priority_cities,
        ):
            skipped += 1
            continue
        key = (
            normalize_key(record["city"]),
            normalize_key(record.get("state")),
            normalize_key(record.get("country") or "US"),
            normalize_key(record.get("metro_name")),
        )
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        _, was_inserted = upsert_city(conn, record)
        if was_inserted:
            inserted += 1
        else:
            updated += 1

    return ImportResult(
        rows_read=rows_read,
        cities_inserted=inserted,
        cities_updated=updated,
        rows_skipped=skipped,
        import_batch_id=import_batch_id,
    )


def _build_column_rename_map(columns: Iterable[Any], mapping: ImportColumnMapping) -> dict[Any, str]:
    explicit = {
        mapping.city_column: "city",
        mapping.state_column: "state",
        mapping.population_column: "population",
        mapping.lat_column: "lat",
        mapping.lng_column: "lng",
    }
    rename_map: dict[Any, str] = {}
    for column in columns:
        column_name = str(column)
        if column_name in explicit:
            rename_map[column] = explicit[column_name]
        else:
            rename_map[column] = COLUMN_ALIASES.get(column_name, COLUMN_ALIASES.get(column_name.strip().lower(), column_name.strip().lower()))
    return rename_map


def _row_to_city(row: dict[str, Any], source_row_number: int, import_batch_id: str) -> dict[str, Any] | None:
    city = normalize_blank(row.get("city"))
    if not city:
        return None
    population = to_int(row.get("population"))
    original_row_id = normalize_blank(row.get("original_row_id"))
    return {
        "city": city,
        "state": normalize_blank(row.get("state")),
        "state_name": normalize_blank(row.get("state_name")),
        "country": normalize_blank(row.get("country")) or "US",
        "metro_name": normalize_blank(row.get("metro_name")),
        "county": normalize_blank(row.get("county")),
        "population": population,
        "lat": to_float(row.get("lat")),
        "lng": to_float(row.get("lng")),
        "original_row_id": str(original_row_id) if original_row_id is not None else None,
        "city_tier": city_tier_for_population(population),
        "priority": to_int(row.get("priority")) or 0,
        "priority_level": to_int(row.get("priority_level")),
        "priority_reason": normalize_blank(row.get("priority_reason")),
        "enabled": truthy(row.get("enabled"), default=True),
        "source_row_number": source_row_number,
        "import_batch_id": import_batch_id,
    }


def _priority_data_for(record: dict[str, Any], priority_cities: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    priority = priority_cities.get((normalize_key(record.get("city")), normalize_key(record.get("state"))))
    if not priority:
        return {}
    priority_level = to_int(priority.get("priority_level")) or 1
    return {
        "priority": priority_level,
        "priority_level": priority_level,
        "priority_reason": normalize_blank(priority.get("reason")),
    }


def _passes_filters(
    record: dict[str, Any],
    *,
    min_population: int | None,
    max_population: int | None,
    state: str | None,
    priority_only: bool,
    include_priority_cities: bool,
) -> bool:
    is_priority = bool(record.get("priority_level") or record.get("priority"))
    if state and normalize_key(record.get("state")) != normalize_key(state):
        return False
    if priority_only:
        return is_priority
    population = record.get("population")
    population_matches = True
    if min_population is not None:
        population_matches = population_matches and population is not None and population >= min_population
    if max_population is not None:
        population_matches = population_matches and population is not None and population <= max_population
    return population_matches or (include_priority_cities and is_priority)
