from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def normalize_blank(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_key(value: Any) -> str:
    value = normalize_blank(value)
    return str(value or "").strip().casefold()


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    return re.sub(r"_+", "_", value).strip("_").lower() or "unknown"


def truthy(value: Any, default: bool = True) -> bool:
    value = normalize_blank(value)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "enabled", "active"}


def to_int(value: Any) -> int | None:
    value = normalize_blank(value)
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    value = normalize_blank(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def city_tier_for_population(population: Any) -> str:
    population_value = to_int(population) or 0
    if population_value >= 1_000_000:
        return "mega"
    if population_value >= 250_000:
        return "large"
    if population_value >= 100_000:
        return "mid"
    if population_value >= 50_000:
        return "small_major"
    if population_value >= 25_000:
        return "small"
    return "tiny"
