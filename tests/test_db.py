from music_calendar_finder.db import connect_db, init_db, upsert_city


def test_init_db_and_city_upsert(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        city_id, inserted = upsert_city(conn, {"city": "Austin", "state": "TX", "population": 964000})
        same_id, inserted_again = upsert_city(conn, {"city": "Austin", "state": "TX", "population": 970000})
        row = conn.execute("select * from cities where id=?", (city_id,)).fetchone()
    assert inserted is True
    assert inserted_again is False
    assert same_id == city_id
    assert row["population"] == 970000

