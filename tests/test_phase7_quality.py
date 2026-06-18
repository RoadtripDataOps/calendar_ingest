from __future__ import annotations

from openpyxl import Workbook

from music_calendar_finder.db import connect_db, init_db, upsert_city
from music_calendar_finder.exporter import build_export_frames
from music_calendar_finder.quality import sanitize_url_fields
from music_calendar_finder.workbook_qa import qa_workbook


def test_phase7_challenge_and_article_rows_do_not_rank_as_top_sources(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        city_id, _ = upsert_city(conn, {"city": "Asheville", "state": "NC", "population": 295040, "city_tier": "large"})
        run_id = _insert_completed_run(conn, city_id)
        _insert_source(
            conn,
            city_id,
            run_id,
            "exploreasheville.com",
            "Just a moment...",
            "tourism_cvb",
            "https://www.exploreasheville.com/",
            None,
            title="Just a moment...",
            score=99,
        )
        _insert_source(
            conn,
            city_id,
            run_id,
            "livemusicasheville.com",
            "Checking your browser before accessing. Just a moment...",
            "venue_calendar",
            "https://livemusicasheville.com/",
            None,
            title="Checking your browser before accessing. Just a moment...",
            score=98,
        )
        _insert_source(
            conn,
            city_id,
            run_id,
            "afar.com",
            "3 Days in Asheville: a Local Musician's Travel Guide - AFAR",
            "local_publication",
            "https://www.afar.com/",
            "https://www.afar.com/travel-inspiration/art-and-culture/festivals-and-events",
            score=97,
        )
        _insert_source(
            conn,
            city_id,
            run_id,
            "rollingstone.com",
            "Why Asheville, North Carolina Is the New Must-Visit Music City",
            "local_publication",
            "https://www.rollingstone.com/",
            None,
            score=96,
        )
        _insert_source(
            conn,
            city_id,
            run_id,
            "visitasheville.example",
            "Visit Asheville Events",
            "tourism_cvb",
            "https://visitasheville.example/",
            "https://visitasheville.example/events/",
            score=95,
        )

        frames = build_export_frames(conn)

    top = frames["Top Sources"]
    top_text = _frame_text(top)
    assert "Just a moment" not in top_text
    assert "Checking your browser" not in top_text
    assert "3 Days in Asheville" not in top_text
    assert "Must-Visit Music City" not in top_text
    assert set(top["source_quality_tier"]) == {"tourism_cvb_calendar"}


def test_phase7_named_sources_get_better_tiers():
    cases = [
        ("LA Weekly", "venue_calendar", "https://www.laweekly.com/", "Los Angeles News and Events - LA Weekly", "core_local_publication"),
        ("Time Out Los Angeles", "venue_calendar", "https://www.timeout.com/los-angeles", "Time Out Los Angeles | L.A. Events", "core_local_calendar"),
        ("Oh My Rockness Los Angeles", "venue_calendar", "https://losangeles.ohmyrockness.com/", "Oh My Rockness Los Angeles", "promoter_calendar"),
        ("Discover Los Angeles", "tourism_cvb", "https://www.discoverlosangeles.com/", "Visit Los Angeles", "tourism_cvb_calendar"),
        ("The Music Center", "local_publication", "https://www.musiccenter.org/", "The Music Center Los Angeles Events", "arts_culture_org"),
        ("Asheville Regional Airport", "local_publication", "https://flyavl.com/", "Art + Music in the Airport | Asheville Regional Airport", "venue_calendar"),
    ]
    for source_name, category, website_url, title, expected in cases:
        row = sanitize_url_fields(
            {
                "city": "Los Angeles" if "Los Angeles" in title or "LA " in source_name or source_name == "The Music Center" else "Asheville",
                "state": "CA",
                "source_name": source_name,
                "source_category": category,
                "website_url": website_url,
                "best_calendar_url": website_url.rstrip("/") + "/events",
                "title": title,
                "meta_description": f"{title} music arts events calendar",
            }
        )
        assert row["source_quality_tier"] == expected

    challenge = sanitize_url_fields(
        {
            "city": "Asheville",
            "state": "NC",
            "source_name": "Just a moment...",
            "source_category": "tourism_cvb",
            "website_url": "https://www.exploreasheville.com/",
            "title": "Just a moment...",
        }
    )
    assert challenge["source_name"] == "Explore Asheville"
    assert challenge["content_quality_status"] == "challenge_page"
    assert challenge["challenge_page_detected"] == 1
    assert challenge["source_quality_tier"] == "challenge_or_blocked_source"


def test_phase7_venue_cap_is_enforced_after_classification(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect_db(db_path) as conn:
        city_id, _ = upsert_city(conn, {"city": "Austin", "state": "TX", "population": 974447, "city_tier": "large"})
        run_id = _insert_completed_run(conn, city_id)
        for index in range(15):
            _insert_source(
                conn,
                city_id,
                run_id,
                f"austinvenue{index}.example",
                f"Austin Venue {index}",
                "venue_calendar",
                f"https://austinvenue{index}.example/",
                f"https://austinvenue{index}.example/events",
                score=100 - index,
            )
        for index in range(20):
            _insert_source(
                conn,
                city_id,
                run_id,
                f"austincalendar{index}.example",
                f"Austin Calendar {index}",
                "event_aggregator",
                f"https://austincalendar{index}.example/",
                f"https://austincalendar{index}.example/events",
                score=90 - index,
            )
        frames = build_export_frames(conn)

    top = frames["Top Sources"]
    venue_count = int((top["source_quality_tier"] == "venue_calendar").sum())
    assert len(top) == 25
    assert venue_count <= 10


def test_phase7_workbook_qa_fails_on_weak_top_source_and_cap(tmp_path):
    path = tmp_path / "bad.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_sheet(
        workbook,
        "Top Sources",
        ["city", "state", "source_name", "title", "source_quality_tier", "website_url_quality", "best_calendar_url_quality"],
        [
            ["Austin", "TX", "3 Days in Austin", "3 Days in Austin", "weak_article_or_blog_post", "standing_source_page", ""],
            *[["Austin", "TX", f"Venue {i}", f"Venue {i}", "venue_calendar", "homepage_only", "standing_calendar_page"] for i in range(11)],
        ],
    )
    for sheet in ["Verified Sources", "Candidates Unverified", "Rejected", "Search API Usage"]:
        _write_sheet(workbook, sheet, ["city", "state"], [])
    _write_sheet(
        workbook,
        "City Summary",
        ["city", "state", "top_sources_count", "verified_sources_count", "candidates_unverified_count", "rejected_count", "search_api_queries_count"],
        [["Austin", "TX", 12, 0, 0, 0, 0]],
    )
    workbook.save(path)

    issues = qa_workbook(path)
    messages = "\n".join(issue.message for issue in issues)
    assert "Weak article/blog post" in messages
    assert "venue_calendar count 11 exceeds cap 10" in messages


def _insert_completed_run(conn, city_id: int) -> int:
    conn.execute(
        "insert into city_runs (city_id, run_mode, status, mode, queries_planned, queries_completed) values (?, 'live', 'completed', 'test', 1, 1)",
        (city_id,),
    )
    conn.commit()
    return int(conn.execute("select last_insert_rowid()").fetchone()[0])


def _insert_source(
    conn,
    city_id: int,
    run_id: int,
    root_domain: str,
    source_name: str,
    source_category: str,
    website_url: str,
    best_calendar_url: str | None,
    *,
    title: str | None = None,
    score: float = 80,
) -> None:
    conn.execute(
        """
        insert into source_pages (
          city_id, run_id, run_mode, root_domain, url_origin, source_name,
          source_category, website_url, best_calendar_url, title, meta_description,
          local_relevance_score, music_signal_score, calendar_signal_score,
          authority_score, freshness_score, diversity_score, total_score,
          confidence, status, url_validation_status
        )
        values (?, ?, 'live', ?, 'serpapi_organic', ?, ?, ?, ?, ?, ?, 80, 80, 80, 70, 60, 80, ?, 'high', 'verified', 'valid')
        """,
        (
            city_id,
            run_id,
            root_domain,
            source_name,
            source_category,
            website_url,
            best_calendar_url,
            title or source_name,
            f"{source_name} music arts culture events calendar.",
            score,
        ),
    )
    conn.commit()


def _write_sheet(workbook, name: str, headers: list[str], rows: list[list[object]]) -> None:
    sheet = workbook.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)


def _frame_text(frame) -> str:
    return "\n".join(str(value) for value in frame.astype(str).to_numpy().flatten())
