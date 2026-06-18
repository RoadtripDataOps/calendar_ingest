from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .models import SourceCandidate
from .utils import city_tier_for_population, ensure_dir, normalize_blank, normalize_key, utc_now


SCHEMA = """
pragma foreign_keys = on;

create table if not exists cities (
  id integer primary key,
  city text not null,
  state text,
  state_name text,
  country text default 'US',
  metro_name text,
  county text,
  population integer,
  lat real,
  lng real,
  original_row_id text,
  city_tier text,
  priority integer default 0,
  priority_level integer,
  priority_reason text,
  enabled integer default 1,
  source_row_number integer,
  import_batch_id text,
  created_at text,
  updated_at text,
  last_processed_at text,
  next_refresh_after text,
  status text default 'pending',
  error_message text
);

create index if not exists idx_cities_status on cities(status);
create index if not exists idx_cities_lookup on cities(city, state, country);
create index if not exists idx_cities_population on cities(population);

create table if not exists city_runs (
  id integer primary key,
  city_id integer not null,
  run_mode text default 'live',
  started_at text,
  finished_at text,
  status text,
  mode text,
  queries_planned integer default 0,
  queries_completed integer default 0,
  candidates_found integer default 0,
  verified_sources integer default 0,
  rejected_sources integer default 0,
  error_message text,
  foreign key(city_id) references cities(id)
);

create table if not exists search_queries (
  id integer primary key,
  run_id integer not null,
  city_id integer not null,
  run_mode text default 'live',
  query text not null,
  provider text default 'serpapi',
  page_number integer default 1,
  status text default 'pending',
  result_count integer default 0,
  api_status text,
  error_message text,
  created_at text,
  completed_at text,
  foreign key(run_id) references city_runs(id),
  foreign key(city_id) references cities(id)
);

create table if not exists candidate_urls (
  id integer primary key,
  city_id integer not null,
  run_id integer,
  query_id integer,
  source_url text not null,
  normalized_url text,
  domain text,
  root_domain text,
  title text,
  snippet text,
  position integer,
  provider text,
  run_mode text default 'live',
  url_origin text default 'serpapi_organic',
  url_validation_status text,
  http_status integer,
  final_url text,
  resolved_domain text,
  content_type text,
  page_title text,
  validation_error text,
  validated_at text,
  first_seen_at text,
  last_seen_at text,
  status text default 'candidate',
  foreign key(city_id) references cities(id)
);

create index if not exists idx_candidate_city_domain on candidate_urls(city_id, root_domain);
create unique index if not exists idx_candidate_unique on candidate_urls(city_id, normalized_url);

create table if not exists source_pages (
  id integer primary key,
  city_id integer not null,
  run_id integer,
  run_mode text default 'live',
  root_domain text not null,
  url_origin text default 'serpapi_organic',
  source_name text,
  source_category text,
  website_url text,
  best_calendar_url text,
  music_url text,
  events_url text,
  arts_url text,
  tourism_url text,
  about_url text,
  rss_url text,
  contact_email text,
  social_links_json text,
  title text,
  meta_description text,
  detected_keywords_json text,
  local_relevance_score real default 0,
  music_signal_score real default 0,
  calendar_signal_score real default 0,
  authority_score real default 0,
  freshness_score real default 0,
  diversity_score real default 0,
  total_score real default 0,
  confidence text,
  status text default 'verified',
  why_selected text,
  robots_allowed integer,
  crawl_status text,
  error_message text,
  url_validation_status text,
  http_status integer,
  final_url text,
  resolved_domain text,
  content_type text,
  page_title text,
  validation_error text,
  validated_at text,
  first_seen_at text,
  last_checked_at text,
  foreign key(city_id) references cities(id)
);

create unique index if not exists idx_source_city_domain on source_pages(city_id, root_domain);

create table if not exists rejected_sources (
  id integer primary key,
  city_id integer not null,
  run_id integer,
  run_mode text default 'live',
  root_domain text,
  url text,
  url_origin text,
  url_validation_status text,
  http_status integer,
  final_url text,
  resolved_domain text,
  content_type text,
  page_title text,
  validation_error text,
  validated_at text,
  reason text,
  details text,
  created_at text,
  foreign key(city_id) references cities(id)
);

create table if not exists exports (
  id integer primary key,
  export_path text,
  export_type text,
  run_mode text default 'live',
  city_id integer,
  created_at text,
  row_count integer
);

create table if not exists provider_usage (
  id integer primary key,
  provider text,
  run_id integer,
  city_id integer,
  run_mode text default 'live',
  endpoint text,
  query text,
  used_cache integer,
  created_at text
);
"""


CITY_COLUMN_MIGRATIONS = {
    "lat": "alter table cities add column lat real",
    "lng": "alter table cities add column lng real",
    "original_row_id": "alter table cities add column original_row_id text",
    "city_tier": "alter table cities add column city_tier text",
    "priority_level": "alter table cities add column priority_level integer",
    "priority_reason": "alter table cities add column priority_reason text",
}

TABLE_COLUMN_MIGRATIONS = {
    "city_runs": {
        "run_mode": "alter table city_runs add column run_mode text default 'live'",
    },
    "search_queries": {
        "run_mode": "alter table search_queries add column run_mode text default 'live'",
    },
    "candidate_urls": {
        "run_mode": "alter table candidate_urls add column run_mode text default 'live'",
        "url_origin": "alter table candidate_urls add column url_origin text default 'serpapi_organic'",
        "url_validation_status": "alter table candidate_urls add column url_validation_status text",
        "http_status": "alter table candidate_urls add column http_status integer",
        "final_url": "alter table candidate_urls add column final_url text",
        "resolved_domain": "alter table candidate_urls add column resolved_domain text",
        "content_type": "alter table candidate_urls add column content_type text",
        "page_title": "alter table candidate_urls add column page_title text",
        "validation_error": "alter table candidate_urls add column validation_error text",
        "validated_at": "alter table candidate_urls add column validated_at text",
    },
    "source_pages": {
        "run_mode": "alter table source_pages add column run_mode text default 'live'",
        "url_origin": "alter table source_pages add column url_origin text default 'serpapi_organic'",
        "url_validation_status": "alter table source_pages add column url_validation_status text",
        "http_status": "alter table source_pages add column http_status integer",
        "final_url": "alter table source_pages add column final_url text",
        "resolved_domain": "alter table source_pages add column resolved_domain text",
        "content_type": "alter table source_pages add column content_type text",
        "page_title": "alter table source_pages add column page_title text",
        "validation_error": "alter table source_pages add column validation_error text",
        "validated_at": "alter table source_pages add column validated_at text",
    },
    "rejected_sources": {
        "run_mode": "alter table rejected_sources add column run_mode text default 'live'",
        "url_origin": "alter table rejected_sources add column url_origin text",
        "url_validation_status": "alter table rejected_sources add column url_validation_status text",
        "http_status": "alter table rejected_sources add column http_status integer",
        "final_url": "alter table rejected_sources add column final_url text",
        "resolved_domain": "alter table rejected_sources add column resolved_domain text",
        "content_type": "alter table rejected_sources add column content_type text",
        "page_title": "alter table rejected_sources add column page_title text",
        "validation_error": "alter table rejected_sources add column validation_error text",
        "validated_at": "alter table rejected_sources add column validated_at text",
    },
    "exports": {
        "run_mode": "alter table exports add column run_mode text default 'live'",
    },
    "provider_usage": {
        "run_mode": "alter table provider_usage add column run_mode text default 'live'",
    },
}


def connect_db(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    ensure_dir(path.parent)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(path: str | Path) -> None:
    with connect_db(path) as conn:
        conn.executescript(SCHEMA)
        migrate_db(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    existing_columns = {row["name"] for row in conn.execute("pragma table_info(cities)").fetchall()}
    for column, sql in CITY_COLUMN_MIGRATIONS.items():
        if column not in existing_columns:
            conn.execute(sql)
    for table, migrations in TABLE_COLUMN_MIGRATIONS.items():
        _migrate_table(conn, table, migrations)
    conn.execute("create index if not exists idx_cities_tier on cities(city_tier)")
    conn.execute("create index if not exists idx_cities_priority on cities(priority_level, priority)")
    conn.execute(
        """
        update cities
        set city_tier = case
          when coalesce(population, 0) >= 1000000 then 'mega'
          when coalesce(population, 0) >= 250000 then 'large'
          when coalesce(population, 0) >= 100000 then 'mid'
          when coalesce(population, 0) >= 50000 then 'small_major'
          when coalesce(population, 0) >= 25000 then 'small'
          else 'tiny'
        end
        where city_tier is null
        """
    )
    conn.commit()


def _migrate_table(conn: sqlite3.Connection, table: str, migrations: dict[str, str]) -> None:
    existing_columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    for column, sql in migrations.items():
        if column not in existing_columns:
            conn.execute(sql)


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    cur = conn.execute(sql, tuple(params))
    conn.commit()
    return cur


def fetch_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(params)).fetchone()


def fetch_all(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)).fetchall())


def upsert_city(conn: sqlite3.Connection, city_data: dict[str, Any]) -> tuple[int, bool]:
    now = utc_now()
    city = normalize_blank(city_data.get("city"))
    if not city:
        raise ValueError("city is required")
    country = normalize_blank(city_data.get("country")) or "US"
    state = normalize_blank(city_data.get("state"))
    metro_name = normalize_blank(city_data.get("metro_name"))
    existing = fetch_one(
        conn,
        """
        select * from cities
        where lower(city)=?
          and coalesce(lower(state), '')=?
          and lower(coalesce(country, 'US'))=?
          and coalesce(lower(metro_name), '')=?
        """,
        (normalize_key(city), normalize_key(state), normalize_key(country), normalize_key(metro_name)),
    )
    payload = {
        "city": city,
        "state": state,
        "state_name": normalize_blank(city_data.get("state_name")),
        "country": country,
        "metro_name": metro_name,
        "county": normalize_blank(city_data.get("county")),
        "population": city_data.get("population"),
        "lat": city_data.get("lat"),
        "lng": city_data.get("lng"),
        "original_row_id": normalize_blank(city_data.get("original_row_id")),
        "city_tier": normalize_blank(city_data.get("city_tier")) or city_tier_for_population(city_data.get("population")),
        "priority": city_data.get("priority") or 0,
        "priority_level": city_data.get("priority_level"),
        "priority_reason": normalize_blank(city_data.get("priority_reason")),
        "enabled": 1 if city_data.get("enabled", True) else 0,
        "source_row_number": city_data.get("source_row_number"),
        "import_batch_id": city_data.get("import_batch_id"),
        "updated_at": now,
    }
    if existing:
        assignments = ", ".join(f"{key}=?" for key in payload)
        conn.execute(
            f"update cities set {assignments} where id=?",
            (*payload.values(), existing["id"]),
        )
        conn.commit()
        return int(existing["id"]), False

    payload["created_at"] = now
    payload["status"] = city_data.get("status") or "pending"
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    cur = conn.execute(
        f"insert into cities ({columns}) values ({placeholders})",
        tuple(payload.values()),
    )
    conn.commit()
    return int(cur.lastrowid), True


def create_city_run(conn: sqlite3.Connection, city_id: int, mode: str, run_mode: str = "live") -> int:
    cur = conn.execute(
        """
        insert into city_runs (city_id, run_mode, started_at, status, mode)
        values (?, ?, ?, 'running', ?)
        """,
        (city_id, run_mode, utc_now(), mode),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_city_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    *,
    queries_planned: int = 0,
    queries_completed: int = 0,
    candidates_found: int = 0,
    verified_sources: int = 0,
    rejected_sources: int = 0,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        update city_runs
        set finished_at=?, status=?, queries_planned=?, queries_completed=?,
            candidates_found=?, verified_sources=?, rejected_sources=?, error_message=?
        where id=?
        """,
        (
            utc_now(),
            status,
            queries_planned,
            queries_completed,
            candidates_found,
            verified_sources,
            rejected_sources,
            error_message,
            run_id,
        ),
    )
    conn.commit()


def update_city_status(conn: sqlite3.Connection, city_id: int, status: str, error_message: str | None = None) -> None:
    now = utc_now()
    last_processed = now if status in {"completed", "failed"} else None
    conn.execute(
        """
        update cities
        set status=?,
            error_message=?,
            updated_at=?,
            last_processed_at=coalesce(?, last_processed_at)
        where id=?
        """,
        (status, error_message, now, last_processed, city_id),
    )
    conn.commit()


def create_search_query(
    conn: sqlite3.Connection,
    run_id: int,
    city_id: int,
    query: str,
    page_number: int = 1,
    run_mode: str = "live",
) -> int:
    cur = conn.execute(
        """
        insert into search_queries (run_id, city_id, run_mode, query, page_number, created_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (run_id, city_id, run_mode, query, page_number, utc_now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_search_query(
    conn: sqlite3.Connection,
    query_id: int,
    status: str,
    result_count: int,
    api_status: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        update search_queries
        set status=?, result_count=?, api_status=?, error_message=?, completed_at=?
        where id=?
        """,
        (status, result_count, api_status, error_message, utc_now(), query_id),
    )
    conn.commit()


def save_candidate_url(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    now = utc_now()
    existing = fetch_one(
        conn,
        "select id, first_seen_at from candidate_urls where city_id=? and normalized_url=?",
        (data["city_id"], data.get("normalized_url")),
    )
    payload = {
        "city_id": data["city_id"],
        "run_id": data.get("run_id"),
        "query_id": data.get("query_id"),
        "source_url": data["source_url"],
        "normalized_url": data.get("normalized_url"),
        "domain": data.get("domain"),
        "root_domain": data.get("root_domain"),
        "title": data.get("title"),
        "snippet": data.get("snippet"),
        "position": data.get("position"),
        "provider": data.get("provider"),
        "run_mode": data.get("run_mode", "live"),
        "url_origin": data.get("url_origin", "serpapi_organic"),
        "url_validation_status": data.get("url_validation_status"),
        "http_status": data.get("http_status"),
        "final_url": data.get("final_url"),
        "resolved_domain": data.get("resolved_domain"),
        "content_type": data.get("content_type"),
        "page_title": data.get("page_title"),
        "validation_error": data.get("validation_error"),
        "validated_at": data.get("validated_at"),
        "last_seen_at": now,
        "status": data.get("status", "candidate"),
    }
    if existing:
        assignments = ", ".join(f"{key}=?" for key in payload)
        conn.execute(f"update candidate_urls set {assignments} where id=?", (*payload.values(), existing["id"]))
        conn.commit()
        return int(existing["id"])
    payload["first_seen_at"] = now
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    cur = conn.execute(f"insert into candidate_urls ({columns}) values ({placeholders})", tuple(payload.values()))
    conn.commit()
    return int(cur.lastrowid)


def save_source_page(conn: sqlite3.Connection, source: SourceCandidate, score: Any) -> int:
    now = utc_now()
    existing = fetch_one(
        conn,
        "select id, first_seen_at from source_pages where city_id=? and root_domain=?",
        (source.city_id, source.root_domain),
    )
    payload = {
        "city_id": source.city_id,
        "run_id": source.run_id,
        "run_mode": source.run_mode,
        "root_domain": source.root_domain,
        "url_origin": source.url_origin,
        "source_name": source.source_name,
        "source_category": source.source_category,
        "website_url": source.website_url,
        "best_calendar_url": source.best_calendar_url,
        "music_url": source.music_url,
        "events_url": source.events_url,
        "arts_url": source.arts_url,
        "tourism_url": source.tourism_url,
        "about_url": source.about_url,
        "rss_url": source.rss_url,
        "contact_email": source.contact_email,
        "social_links_json": json.dumps(source.social_links),
        "title": source.title,
        "meta_description": source.meta_description,
        "detected_keywords_json": json.dumps(source.detected_keywords),
        "local_relevance_score": score.local_relevance_score,
        "music_signal_score": score.music_signal_score,
        "calendar_signal_score": score.calendar_signal_score,
        "authority_score": score.authority_score,
        "freshness_score": score.freshness_score,
        "diversity_score": score.diversity_score,
        "total_score": score.total_score,
        "confidence": score.confidence,
        "status": "verified",
        "why_selected": score.why_selected,
        "robots_allowed": None if source.robots_allowed is None else int(source.robots_allowed),
        "crawl_status": source.crawl_status,
        "error_message": source.error_message,
        "url_validation_status": source.url_validation_status,
        "http_status": source.http_status,
        "final_url": source.final_url,
        "resolved_domain": source.resolved_domain,
        "content_type": source.content_type,
        "page_title": source.page_title,
        "validation_error": source.validation_error,
        "validated_at": source.validated_at,
        "last_checked_at": now,
    }
    if existing:
        assignments = ", ".join(f"{key}=?" for key in payload)
        conn.execute(f"update source_pages set {assignments} where id=?", (*payload.values(), existing["id"]))
        conn.commit()
        return int(existing["id"])
    payload["first_seen_at"] = now
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    cur = conn.execute(f"insert into source_pages ({columns}) values ({placeholders})", tuple(payload.values()))
    conn.commit()
    return int(cur.lastrowid)


def save_rejected_source(
    conn: sqlite3.Connection,
    city_id: int,
    run_id: int | None,
    root_domain: str | None,
    url: str,
    reason: str,
    details: str | None = None,
    *,
    run_mode: str = "live",
    url_origin: str | None = None,
    url_validation_status: str | None = None,
    http_status: int | None = None,
    final_url: str | None = None,
    resolved_domain: str | None = None,
    content_type: str | None = None,
    page_title: str | None = None,
    validation_error: str | None = None,
    validated_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        insert into rejected_sources (
          city_id, run_id, run_mode, root_domain, url, reason, details,
          url_origin, url_validation_status, http_status, final_url,
          resolved_domain, content_type, page_title, validation_error, validated_at, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            city_id,
            run_id,
            run_mode,
            root_domain,
            url,
            reason,
            details,
            url_origin,
            url_validation_status,
            http_status,
            final_url,
            resolved_domain,
            content_type,
            page_title,
            validation_error,
            validated_at,
            utc_now(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def record_provider_usage(
    conn: sqlite3.Connection,
    provider: str,
    run_id: int | None,
    city_id: int | None,
    endpoint: str,
    query: str | None,
    used_cache: bool = False,
    run_mode: str = "live",
) -> None:
    conn.execute(
        """
        insert into provider_usage (provider, run_id, city_id, run_mode, endpoint, query, used_cache, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (provider, run_id, city_id, run_mode, endpoint, query, int(used_cache), utc_now()),
    )
    conn.commit()
