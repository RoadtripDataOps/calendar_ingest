import pandas as pd

from music_calendar_finder.db import connect_db, init_db
from music_calendar_finder.importer import import_cities_from_xlsx


def test_importer_supports_aliases_and_dedupe(tmp_path):
    xlsx = tmp_path / "cities.xlsx"
    pd.DataFrame(
        [
            {"City": " Austin ", "ST": "TX", "pop": "964,000", "enabled": "yes"},
            {"City": "Austin", "ST": "TX", "pop": "964000"},
            {"City": None, "ST": "CA"},
            {"City": "Los Angeles", "State": "CA", "metro": "Greater Los Angeles"},
        ]
    ).to_excel(xlsx, index=False)
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        result = import_cities_from_xlsx(conn, xlsx)
        rows = conn.execute("select city, state, metro_name from cities order by city").fetchall()
    assert result.rows_read == 4
    assert result.cities_inserted == 2
    assert result.rows_skipped == 2
    assert [row["city"] for row in rows] == ["Austin", "Los Angeles"]
    assert rows[1]["metro_name"] == "Greater Los Angeles"


def test_importer_default_us_cities_mapping_stores_geo_id_and_tier(tmp_path):
    xlsx = tmp_path / "uscities.xlsx"
    pd.DataFrame(
        [
            {"city": "New York", "state_id": "NY", "state_name": "New York", "lat": 40.6943, "lng": -73.9249, "population": 18832416, "id": 1840034016},
            {"city": "Tiny Town", "state_id": "TX", "population": 1000, "lat": 30.1, "lng": -97.1, "id": 123},
        ]
    ).to_excel(xlsx, index=False)
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        result = import_cities_from_xlsx(conn, xlsx)
        ny = conn.execute("select * from cities where city='New York'").fetchone()
        tiny = conn.execute("select * from cities where city='Tiny Town'").fetchone()
    assert result.cities_inserted == 2
    assert ny["state"] == "NY"
    assert ny["lat"] == 40.6943
    assert ny["lng"] == -73.9249
    assert ny["original_row_id"] == "1840034016"
    assert ny["city_tier"] == "mega"
    assert tiny["city_tier"] == "tiny"


def test_importer_filters_population_state_and_priority(tmp_path):
    xlsx = tmp_path / "uscities.xlsx"
    pd.DataFrame(
        [
            {"city": "Big CA", "state_id": "CA", "population": 100000},
            {"city": "Small CA", "state_id": "CA", "population": 10000},
            {"city": "Big TX", "state_id": "TX", "population": 100000},
        ]
    ).to_excel(xlsx, index=False)
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        result = import_cities_from_xlsx(
            conn,
            xlsx,
            min_population=50000,
            state="CA",
            include_priority_cities=True,
            priority_cities={("small ca", "ca"): {"city": "Small CA", "state": "CA", "reason": "test", "priority_level": 5}},
        )
        rows = conn.execute("select city, priority_level from cities order by city").fetchall()
    assert result.cities_inserted == 2
    assert [(row["city"], row["priority_level"]) for row in rows] == [("Big CA", None), ("Small CA", 5)]
