from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3


def overall_status(conn: sqlite3.Connection, *, stale_days: int = 90) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).replace(microsecond=0).isoformat()
    status_counts = {row["status"]: row["count"] for row in conn.execute("select status, count(*) as count from cities group by status")}
    disabled = conn.execute("select count(*) from cities where enabled=0").fetchone()[0]
    stale = conn.execute(
        "select count(*) from cities where enabled=1 and status='completed' and last_processed_at <= ?",
        (cutoff,),
    ).fetchone()[0]
    last_export = conn.execute("select export_path from exports order by created_at desc limit 1").fetchone()
    return {
        "total_cities": conn.execute("select count(*) from cities").fetchone()[0],
        "pending": status_counts.get("pending", 0),
        "processing": status_counts.get("processing", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "disabled": disabled,
        "stale": stale,
        "total_verified_sources": conn.execute("select count(*) from source_pages where status='verified'").fetchone()[0],
        "total_candidate_urls": conn.execute("select count(*) from candidate_urls").fetchone()[0],
        "total_rejected_sources": conn.execute("select count(*) from rejected_sources").fetchone()[0],
        "last_export_path": last_export["export_path"] if last_export else None,
    }


def city_status(conn: sqlite3.Connection, city: str, state: str | None = None) -> dict | None:
    row = conn.execute(
        """
        select * from cities
        where lower(city)=lower(?) and coalesce(lower(state), '')=coalesce(lower(?), '')
        limit 1
        """,
        (city, state),
    ).fetchone()
    if not row:
        return None
    city_id = row["id"]
    last_run = conn.execute("select * from city_runs where city_id=? order by started_at desc limit 1", (city_id,)).fetchone()
    top_sources = [
        dict(item)
        for item in conn.execute(
            """
            select source_name, source_category, total_score, best_calendar_url
            from source_pages
            where city_id=?
            order by total_score desc
            limit 10
            """,
            (city_id,),
        )
    ]
    return {
        "city": dict(row),
        "last_run": dict(last_run) if last_run else None,
        "candidate_count": conn.execute("select count(*) from candidate_urls where city_id=?", (city_id,)).fetchone()[0],
        "verified_source_count": conn.execute("select count(*) from source_pages where city_id=?", (city_id,)).fetchone()[0],
        "rejected_count": conn.execute("select count(*) from rejected_sources where city_id=?", (city_id,)).fetchone()[0],
        "top_sources": top_sources,
        "failure_reason": row["error_message"] if row["status"] == "failed" else None,
    }


def report(conn: sqlite3.Connection, *, top: int = 50) -> dict:
    return {
        "top_cities": [
            dict(row)
            for row in conn.execute(
                """
                select c.city, c.state, count(sp.id) as verified_sources
                from cities c left join source_pages sp on sp.city_id=c.id
                group by c.id
                order by verified_sources desc, c.city
                limit ?
                """,
                (top,),
            )
        ],
        "cities_with_no_sources": [
            dict(row)
            for row in conn.execute(
                """
                select c.city, c.state, c.status
                from cities c left join source_pages sp on sp.city_id=c.id
                group by c.id
                having count(sp.id)=0
                order by c.state, c.city
                """
            )
        ],
        "failed_cities": [dict(row) for row in conn.execute("select city, state, error_message from cities where status='failed' order by state, city")],
        "under_covered_cities": [
            dict(row)
            for row in conn.execute(
                """
                select c.city, c.state, count(sp.id) as verified_sources
                from cities c left join source_pages sp on sp.city_id=c.id
                where c.enabled=1
                group by c.id
                having count(sp.id) between 1 and 9
                order by verified_sources asc, c.state, c.city
                """
            )
        ],
        "category_distribution": [
            dict(row)
            for row in conn.execute(
                """
                select coalesce(source_category, 'unknown') as source_category, count(*) as count
                from source_pages
                group by source_category
                order by count desc
                """
            )
        ],
        "average_music_signal_by_city": [
            dict(row)
            for row in conn.execute(
                """
                select c.city, c.state, round(avg(sp.music_signal_score), 1) as avg_music_signal_score
                from cities c join source_pages sp on sp.city_id=c.id
                group by c.id
                order by avg_music_signal_score desc
                limit ?
                """,
                (top,),
            )
        ],
    }

