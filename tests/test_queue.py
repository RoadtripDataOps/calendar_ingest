from datetime import datetime, timedelta, timezone

from music_calendar_finder.db import connect_db, init_db, upsert_city
from music_calendar_finder.queue import (
    calculate_city_budget,
    find_city,
    mark_city_status,
    select_pending_cities,
    select_stale_cities,
)
from music_calendar_finder.utils import city_tier_for_population


CONFIG = {
    "budgets": {
        "small": {
            "top_sources_target": 25,
            "verified_sources_target": 25,
            "max_verified_sources": 50,
            "max_candidate_domains": 100,
            "max_serpapi_queries": 20,
            "max_query_pages": 1,
        },
        "mid": {
            "top_sources_target": 25,
            "verified_sources_target": 50,
            "max_verified_sources": 75,
            "max_candidate_domains": 150,
            "max_serpapi_queries": 30,
            "max_query_pages": 2,
        },
        "large": {
            "top_sources_target": 25,
            "verified_sources_target": 75,
            "max_verified_sources": 100,
            "max_candidate_domains": 225,
            "max_serpapi_queries": 45,
            "max_query_pages": 2,
        },
        "mega": {
            "top_sources_target": 50,
            "verified_sources_target": 100,
            "max_verified_sources": 150,
            "max_candidate_domains": 350,
            "max_serpapi_queries": 70,
            "max_query_pages": 3,
        },
        "music_market_overrides": [{"city": "Austin", "state": "TX"}],
        "tourism_market_overrides": [{"city": "Las Vegas", "state": "NV"}],
    }
}


def test_queue_selection_and_status(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        austin_id, _ = upsert_city(conn, {"city": "Austin", "state": "TX", "priority": 10})
        upsert_city(conn, {"city": "Disabled", "state": "TX", "enabled": False})
        pending = select_pending_cities(conn, 10)
        mark_city_status(conn, austin_id, "completed")
        stale_time = (datetime.now(timezone.utc) - timedelta(days=100)).replace(microsecond=0).isoformat()
        conn.execute("update cities set last_processed_at=? where id=?", (stale_time, austin_id))
        conn.commit()
        stale = select_stale_cities(conn, 10, 90)
        found = find_city(conn, "Austin", "TX")
    assert len(pending) == 1
    assert pending[0]["city"] == "Austin"
    assert len(stale) == 1
    assert found["id"] == austin_id


def test_budget_calculation_overrides():
    budget = calculate_city_budget({"city": "Austin", "state": "TX", "population": 100000}, CONFIG)
    tourism = calculate_city_budget({"city": "Las Vegas", "state": "NV", "population": 650000}, CONFIG)
    assert budget.max_serpapi_queries == 45
    assert tourism.max_serpapi_queries == 55
    assert tourism.max_candidate_domains == 275


def test_city_tier_assignment():
    assert city_tier_for_population(1_000_000) == "mega"
    assert city_tier_for_population(250_000) == "large"
    assert city_tier_for_population(100_000) == "mid"
    assert city_tier_for_population(50_000) == "small_major"
    assert city_tier_for_population(25_000) == "small"
    assert city_tier_for_population(24_999) == "tiny"


def test_population_state_and_priority_filters(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        upsert_city(conn, {"city": "Big CA", "state": "CA", "population": 100_000})
        upsert_city(conn, {"city": "Small CA", "state": "CA", "population": 10_000, "priority": 50, "priority_level": 50})
        upsert_city(conn, {"city": "Big TX", "state": "TX", "population": 100_000})
        upsert_city(conn, {"city": "Mid CA", "state": "CA", "population": 30_000})
        ca_big = select_pending_cities(conn, None, min_population=50_000, state="CA")
        band = select_pending_cities(conn, None, min_population=25_000, max_population=49_999)
        with_priority = select_pending_cities(conn, None, min_population=50_000, include_priority_cities=True)
        priority_only = select_pending_cities(conn, None, priority_only=True)
    assert [row["city"] for row in ca_big] == ["Big CA"]
    assert [row["city"] for row in band] == ["Mid CA"]
    assert {row["city"] for row in with_priority} == {"Big CA", "Big TX", "Small CA"}
    assert [row["city"] for row in priority_only] == ["Small CA"]
