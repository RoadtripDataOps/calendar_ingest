from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from .dedupe import normalize_url
from .utils import utc_now
from .validation import UrlValidationContext, UrlValidator, VALIDATION_ACCEPTED_STATUSES, is_verified_url_eligible


HARD_REJECT_STATUSES = {"synthetic_rejected", "dns_error", "http_error", "invalid_url", "unsupported_content_type", "connection_error"}


@dataclass
class CleanResult:
    city_runs: int = 0
    search_queries: int = 0
    candidate_urls: int = 0
    source_pages: int = 0
    rejected_sources: int = 0
    exports: int = 0
    provider_usage: int = 0


@dataclass
class ValidationRunResult:
    candidates_checked: int = 0
    sources_checked: int = 0
    rejected: int = 0
    verified_kept: int = 0
    unverified: int = 0


def clear_live_city_data(conn: sqlite3.Connection, city_id: int) -> dict[str, int]:
    removed: dict[str, int] = {}
    tables = [
        "candidate_urls",
        "source_pages",
        "rejected_sources",
        "search_queries",
        "provider_usage",
        "city_runs",
    ]
    for table in tables:
        cur = conn.execute(
            f"delete from {table} where city_id=? and coalesce(run_mode, 'live')='live'",
            (city_id,),
        )
        removed[table] = cur.rowcount
    conn.commit()
    return removed


def clean_dry_run_data(conn: sqlite3.Connection) -> CleanResult:
    result = CleanResult()
    dry_run_runs = [
        row["id"]
        for row in conn.execute(
            """
            select distinct cr.id
            from city_runs cr
            left join search_queries sq on sq.run_id=cr.id
            where coalesce(cr.run_mode, 'live')='dry_run'
               or coalesce(sq.run_mode, 'live')='dry_run'
               or sq.api_status='dry_run'
            """
        ).fetchall()
    ]
    run_placeholders = ", ".join("?" for _ in dry_run_runs) or "null"
    cur = conn.execute(
        f"""
        delete from candidate_urls
        where coalesce(run_mode, 'live')='dry_run'
           or url_origin='dry_run_fixture'
           or ({'run_id in (' + run_placeholders + ')' if dry_run_runs else '0'})
        """,
        tuple(dry_run_runs),
    )
    result.candidate_urls = cur.rowcount
    cur = conn.execute(
        f"""
        delete from source_pages
        where coalesce(run_mode, 'live')='dry_run'
           or url_origin='dry_run_fixture'
           or crawl_status='dry_run'
           or ({'run_id in (' + run_placeholders + ')' if dry_run_runs else '0'})
        """,
        tuple(dry_run_runs),
    )
    result.source_pages = cur.rowcount
    cur = conn.execute(
        f"""
        delete from rejected_sources
        where coalesce(run_mode, 'live')='dry_run'
           or url_origin='dry_run_fixture'
           or ({'run_id in (' + run_placeholders + ')' if dry_run_runs else '0'})
        """,
        tuple(dry_run_runs),
    )
    result.rejected_sources = cur.rowcount
    cur = conn.execute(
        f"""
        delete from search_queries
        where coalesce(run_mode, 'live')='dry_run'
           or api_status='dry_run'
           or ({'run_id in (' + run_placeholders + ')' if dry_run_runs else '0'})
        """,
        tuple(dry_run_runs),
    )
    result.search_queries = cur.rowcount
    cur = conn.execute("delete from provider_usage where coalesce(run_mode, 'live')='dry_run' or used_cache=1")
    result.provider_usage = cur.rowcount
    cur = conn.execute("delete from exports where coalesce(run_mode, 'live')='dry_run' or export_path like '%/dry_run/%'")
    result.exports = cur.rowcount
    if dry_run_runs:
        cur = conn.execute(f"delete from city_runs where id in ({run_placeholders})", tuple(dry_run_runs))
        result.city_runs = cur.rowcount
    else:
        cur = conn.execute("delete from city_runs where coalesce(run_mode, 'live')='dry_run'")
        result.city_runs = cur.rowcount
    conn.commit()
    return result


def validate_city_urls(
    conn: sqlite3.Connection,
    city_row: sqlite3.Row,
    *,
    validator: UrlValidator | None = None,
) -> ValidationRunResult:
    validator = validator or UrlValidator()
    context = UrlValidationContext(city=city_row["city"], state=city_row["state"])
    result = ValidationRunResult()

    candidates = conn.execute(
        """
        select * from candidate_urls
        where city_id=? and coalesce(run_mode, 'live')='live'
          and coalesce(url_origin, '') != 'dry_run_fixture'
        """,
        (city_row["id"],),
    ).fetchall()
    for row in candidates:
        validation = validator.validate(row["source_url"], context)
        _update_candidate(conn, row["id"], validation)
        result.candidates_checked += 1
        if validation.url_validation_status in HARD_REJECT_STATUSES:
            _insert_rejection_from_validation(conn, row, validation)
            result.rejected += 1
        elif validation.url_validation_status in VALIDATION_ACCEPTED_STATUSES:
            result.verified_kept += 1
        else:
            result.unverified += 1

    sources = conn.execute(
        """
        select * from source_pages
        where city_id=? and coalesce(run_mode, 'live')='live'
        """,
        (city_row["id"],),
    ).fetchall()
    for row in sources:
        source_url = row["best_calendar_url"] or row["website_url"]
        validation = validator.validate(source_url, context)
        status = "verified" if is_verified_url_eligible(row["run_mode"], row["url_origin"], validation.url_validation_status) else "candidate_unverified"
        if validation.url_validation_status in HARD_REJECT_STATUSES:
            status = "rejected"
        _update_source(conn, row["id"], validation, status)
        result.sources_checked += 1
        if status == "rejected":
            _insert_rejection_from_source(conn, row, source_url, validation)
            result.rejected += 1
        elif status == "verified":
            result.verified_kept += 1
        else:
            result.unverified += 1

    conn.commit()
    return result


def _update_candidate(conn: sqlite3.Connection, row_id: int, validation) -> None:
    conn.execute(
        """
        update candidate_urls
        set url_validation_status=?, http_status=?, final_url=?, resolved_domain=?,
            content_type=?, page_title=?, validation_error=?, validated_at=?
        where id=?
        """,
        (
            validation.url_validation_status,
            validation.http_status,
            validation.final_url,
            validation.resolved_domain,
            validation.content_type,
            validation.page_title,
            validation.validation_error,
            validation.validated_at,
            row_id,
        ),
    )


def _update_source(conn: sqlite3.Connection, row_id: int, validation, status: str) -> None:
    conn.execute(
        """
        update source_pages
        set status=?, url_validation_status=?, http_status=?, final_url=?,
            resolved_domain=?, content_type=?, page_title=?, validation_error=?,
            validated_at=?, last_checked_at=?
        where id=?
        """,
        (
            status,
            validation.url_validation_status,
            validation.http_status,
            validation.final_url,
            validation.resolved_domain,
            validation.content_type,
            validation.page_title,
            validation.validation_error,
            validation.validated_at,
            utc_now(),
            row_id,
        ),
    )


def _insert_rejection_from_validation(conn: sqlite3.Connection, row: sqlite3.Row, validation) -> None:
    conn.execute(
        """
        insert into rejected_sources (
          city_id, run_id, run_mode, root_domain, url, reason, details,
          url_origin, url_validation_status, http_status, final_url,
          resolved_domain, content_type, page_title, validation_error, validated_at, created_at
        )
        values (?, ?, 'live', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["city_id"],
            row["run_id"],
            row["root_domain"],
            row["source_url"],
            validation.url_validation_status,
            validation.validation_error,
            row["url_origin"],
            validation.url_validation_status,
            validation.http_status,
            validation.final_url,
            validation.resolved_domain,
            validation.content_type,
            validation.page_title,
            validation.validation_error,
            validation.validated_at,
            utc_now(),
        ),
    )


def _insert_rejection_from_source(conn: sqlite3.Connection, row: sqlite3.Row, source_url: str, validation) -> None:
    try:
        domain = normalize_url(source_url).root_domain
    except Exception:
        domain = row["root_domain"]
    conn.execute(
        """
        insert into rejected_sources (
          city_id, run_id, run_mode, root_domain, url, reason, details,
          url_origin, url_validation_status, http_status, final_url,
          resolved_domain, content_type, page_title, validation_error, validated_at, created_at
        )
        values (?, ?, 'live', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["city_id"],
            row["run_id"],
            domain,
            source_url,
            validation.url_validation_status,
            validation.validation_error,
            row["url_origin"],
            validation.url_validation_status,
            validation.http_status,
            validation.final_url,
            validation.resolved_domain,
            validation.content_type,
            validation.page_title,
            validation.validation_error,
            validation.validated_at,
            utc_now(),
        ),
    )
