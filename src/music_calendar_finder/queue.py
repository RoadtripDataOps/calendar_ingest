from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any

from .models import CityDiscoveryBudget
from .utils import normalize_key, utc_now


TIERS = ["small", "mid", "large", "mega"]
PRIORITY_SQL = "(coalesce(priority_level, 0) > 0 or coalesce(priority, 0) > 0)"


def select_pending_cities(
    conn: sqlite3.Connection,
    limit: int | None,
    *,
    force: bool = False,
    min_population: int | None = None,
    max_population: int | None = None,
    state: str | None = None,
    priority_only: bool = False,
    include_priority_cities: bool = False,
) -> list[sqlite3.Row]:
    statuses = ("pending", "failed") if force else ("pending",)
    placeholders = ", ".join("?" for _ in statuses)
    filter_sql, filter_params = _city_filter_sql(
        min_population=min_population,
        max_population=max_population,
        state=state,
        priority_only=priority_only,
        include_priority_cities=include_priority_cities,
    )
    limit_sql, limit_params = _limit_sql(limit)
    return list(
        conn.execute(
            f"""
            select * from cities
            where enabled=1 and status in ({placeholders})
              {filter_sql}
            order by priority desc, population desc, city collate nocase
            {limit_sql}
            """,
            (*statuses, *filter_params, *limit_params),
        )
    )


def select_failed_cities(
    conn: sqlite3.Connection,
    limit: int | None,
    *,
    min_population: int | None = None,
    max_population: int | None = None,
    state: str | None = None,
    priority_only: bool = False,
    include_priority_cities: bool = False,
) -> list[sqlite3.Row]:
    filter_sql, filter_params = _city_filter_sql(
        min_population=min_population,
        max_population=max_population,
        state=state,
        priority_only=priority_only,
        include_priority_cities=include_priority_cities,
    )
    limit_sql, limit_params = _limit_sql(limit)
    return list(
        conn.execute(
            f"""
            select * from cities
            where enabled=1 and status='failed'
              {filter_sql}
            order by updated_at asc, city collate nocase
            {limit_sql}
            """,
            (*filter_params, *limit_params),
        )
    )


def select_stale_cities(
    conn: sqlite3.Connection,
    limit: int | None,
    older_than_days: int,
    *,
    min_population: int | None = None,
    max_population: int | None = None,
    state: str | None = None,
    priority_only: bool = False,
    include_priority_cities: bool = False,
) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).replace(microsecond=0).isoformat()
    filter_sql, filter_params = _city_filter_sql(
        min_population=min_population,
        max_population=max_population,
        state=state,
        priority_only=priority_only,
        include_priority_cities=include_priority_cities,
    )
    limit_sql, limit_params = _limit_sql(limit)
    return list(
        conn.execute(
            f"""
            select * from cities
            where enabled=1
              and status='completed'
              and (
                (next_refresh_after is not null and next_refresh_after <= ?)
                or (last_processed_at is not null and last_processed_at <= ?)
              )
              {filter_sql}
            order by coalesce(next_refresh_after, last_processed_at) asc
            {limit_sql}
            """,
            (utc_now(), cutoff, *filter_params, *limit_params),
        )
    )


def find_city(
    conn: sqlite3.Connection,
    city: str,
    state: str | None = None,
    country: str = "US",
) -> sqlite3.Row | None:
    return conn.execute(
        """
        select * from cities
        where lower(city)=?
          and coalesce(lower(state), '')=?
          and lower(coalesce(country, 'US'))=?
        order by enabled desc, priority desc
        limit 1
        """,
        (normalize_key(city), normalize_key(state), normalize_key(country)),
    ).fetchone()


def mark_city_status(conn: sqlite3.Connection, city_id: int, status: str, error_message: str | None = None) -> None:
    last_processed = utc_now() if status in {"completed", "failed"} else None
    conn.execute(
        """
        update cities
        set status=?, error_message=?, updated_at=?, last_processed_at=coalesce(?, last_processed_at)
        where id=?
        """,
        (status, error_message, utc_now(), last_processed, city_id),
    )
    conn.commit()


def reset_city(
    conn: sqlite3.Connection,
    city_id: int,
    *,
    delete_city_data: bool = False,
) -> None:
    if delete_city_data:
        for table in ("candidate_urls", "source_pages", "rejected_sources"):
            conn.execute(f"delete from {table} where city_id=?", (city_id,))
    conn.execute(
        """
        update cities
        set status='pending', error_message=null, next_refresh_after=null, updated_at=?
        where id=?
        """,
        (utc_now(), city_id),
    )
    conn.commit()


def reset_failed(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    count = conn.execute("select count(*) from cities where status='failed'").fetchone()[0]
    if not dry_run:
        conn.execute("update cities set status='pending', error_message=null, updated_at=? where status='failed'", (utc_now(),))
        conn.commit()
    return int(count)


def mark_stale(conn: sqlite3.Connection, older_than_days: int) -> int:
    refresh_after = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).replace(microsecond=0).isoformat()
    cur = conn.execute(
        """
        update cities
        set next_refresh_after=?, updated_at=?
        where enabled=1 and status='completed'
        """,
        (refresh_after, utc_now()),
    )
    conn.commit()
    return int(cur.rowcount)


def _city_filter_sql(
    *,
    min_population: int | None,
    max_population: int | None,
    state: str | None,
    priority_only: bool,
    include_priority_cities: bool,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if state:
        clauses.append("upper(coalesce(state, '')) = upper(?)")
        params.append(state)
    if priority_only:
        clauses.append(PRIORITY_SQL)
    else:
        population_clauses: list[str] = []
        population_params: list[Any] = []
        if min_population is not None:
            population_clauses.append("population >= ?")
            population_params.append(min_population)
        if max_population is not None:
            population_clauses.append("population <= ?")
            population_params.append(max_population)
        if population_clauses:
            population_sql = "(" + " and ".join(population_clauses) + ")"
            if include_priority_cities:
                clauses.append(f"({population_sql} or {PRIORITY_SQL})")
            else:
                clauses.append(population_sql)
            params.extend(population_params)
    if not clauses:
        return "", []
    return " and " + " and ".join(clauses), params


def _limit_sql(limit: int | None) -> tuple[str, tuple[int, ...]]:
    if limit is None:
        return "", ()
    return "limit ?", (limit,)


def calculate_city_budget(city_record: dict[str, Any] | sqlite3.Row, config: dict[str, Any]) -> CityDiscoveryBudget:
    city = dict(city_record)
    population = city.get("population") or 0
    tier = "small"
    if population >= 2_000_000:
        tier = "mega"
    elif population >= 500_000:
        tier = "large"
    elif population >= 100_000:
        tier = "mid"

    budgets = config.get("budgets", {})
    if _matches_override(city, budgets.get("music_market_overrides", [])):
        tier = _upgrade_tier(tier)

    values = dict(budgets.get(tier, budgets.get("small", {})))
    if _matches_override(city, budgets.get("tourism_market_overrides", [])):
        values["max_serpapi_queries"] = int(values.get("max_serpapi_queries", 0)) + 10
        values["max_candidate_domains"] = int(values.get("max_candidate_domains", 0)) + 50

    return CityDiscoveryBudget(
        top_sources_target=int(values.get("top_sources_target", 25)),
        verified_sources_target=int(values.get("verified_sources_target", 25)),
        max_verified_sources=int(values.get("max_verified_sources", 50)),
        max_candidate_domains=int(values.get("max_candidate_domains", 100)),
        max_serpapi_queries=int(values.get("max_serpapi_queries", 20)),
        max_query_pages=int(values.get("max_query_pages", 1)),
        should_expand_metro_queries=bool(city.get("metro_name")),
    )


def _upgrade_tier(tier: str) -> str:
    idx = TIERS.index(tier)
    return TIERS[min(idx + 1, len(TIERS) - 1)]


def _matches_override(city: dict[str, Any], overrides: list[dict[str, str]]) -> bool:
    city_name = normalize_key(city.get("city"))
    state = normalize_key(city.get("state"))
    return any(normalize_key(item.get("city")) == city_name and normalize_key(item.get("state")) == state for item in overrides)
