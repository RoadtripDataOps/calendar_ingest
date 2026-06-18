from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import yaml

from .utils import normalize_blank, normalize_key, to_int, utc_now


def load_priority_cities(path: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    rows = data.get("priority_cities", data) if isinstance(data, dict) else data
    priorities: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or []:
        city = normalize_blank(row.get("city"))
        state = normalize_blank(row.get("state"))
        if not city or not state:
            continue
        priorities[(normalize_key(city), normalize_key(state))] = {
            "city": city,
            "state": state,
            "reason": normalize_blank(row.get("reason")),
            "priority_level": to_int(row.get("priority_level")) or 1,
        }
    return priorities


def apply_priority_cities(conn: sqlite3.Connection, priority_cities: dict[tuple[str, str], dict[str, Any]]) -> int:
    applied = 0
    for (city_key, state_key), row in priority_cities.items():
        priority_level = to_int(row.get("priority_level")) or 1
        cur = conn.execute(
            """
            update cities
            set priority=?,
                priority_level=?,
                priority_reason=?,
                updated_at=?
            where lower(city)=? and lower(coalesce(state, ''))=?
            """,
            (priority_level, priority_level, row.get("reason"), utc_now(), city_key, state_key),
        )
        applied += cur.rowcount
    conn.commit()
    return applied

