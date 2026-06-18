from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse
import sqlite3
from typing import Any

from .classify import classify_source
from .crawl.fetcher import PageFetcher
from .crawl.link_extractor import analyze_html
from .crawl.robots import RobotsChecker
from .db import (
    create_city_run,
    create_search_query,
    finish_city_run,
    finish_search_query,
    record_provider_usage,
    save_candidate_url,
    save_rejected_source,
    save_source_page,
)
from .dedupe import LOW_PRIORITY_DEFAULTS, dedupe_search_results, normalize_url, root_domain
from .maintenance import clear_live_city_data
from .models import CandidatePageAnalysis, CityDiscoveryBudget, SourceCandidate
from .quality import sanitize_source_candidate_urls
from .query_builder import build_search_queries
from .queue import calculate_city_budget, mark_city_status
from .score import score_source, should_stop_discovery
from .search.base import SearchProvider
from .search.serpapi import SerpApiSearchProvider
from .validation import UrlValidationContext, UrlValidator, VALIDATION_ACCEPTED_STATUSES, is_verified_url_eligible, source_url_rejection_reason


@dataclass
class RunOptions:
    dry_run: bool = False
    force: bool = False
    max_serpapi_queries_per_city: int | None = None
    max_candidate_domains_per_city: int | None = None
    max_total_serpapi_queries: int | None = None
    stop_if_serpapi_remaining_below: int | None = None
    mode: str = "batch"
    quality_report: bool = False


@dataclass
class CityProcessResult:
    city_id: int
    run_id: int
    status: str
    queries_planned: int
    queries_completed: int
    candidates_found: int
    verified_sources: int
    rejected_sources: int
    error_message: str | None = None


def process_city(
    conn: sqlite3.Connection,
    city_row: sqlite3.Row,
    config: dict[str, Any],
    options: RunOptions,
    *,
    provider: SearchProvider | None = None,
    fetcher: PageFetcher | None = None,
) -> CityProcessResult:
    city = dict(city_row)
    if city.get("status") == "processing" and not options.force:
        raise RuntimeError(f"{city['city']} is already marked processing; use --force to rerun")

    run_mode = "dry_run" if options.dry_run else "live"
    previous_status = city.get("status") or "pending"
    if run_mode == "live" and options.force:
        clear_live_city_data(conn, city["id"])
    run_id = create_city_run(conn, city["id"], options.mode, run_mode=run_mode)
    if run_mode == "live":
        mark_city_status(conn, city["id"], "processing")
    queries_planned = 0
    queries_completed = 0
    candidates_found = 0
    verified_sources = 0
    rejected_sources = 0

    try:
        budget = calculate_city_budget(city, config)
        budget = _apply_overrides(budget, options)
        queries = build_search_queries(city, budget, country=city.get("country") or "US")
        planned_items = _planned_query_pages(queries, budget)
        queries_planned = len(planned_items)
        provider = provider or SerpApiSearchProvider(config.get("serpapi", {}), dry_run=options.dry_run)
        low_priority_domains = set(config.get("dedupe", {}).get("low_priority_domains", LOW_PRIORITY_DEFAULTS))

        all_results_count = 0
        batch_new_domains = 0
        low_yield_batches = 0
        seen_domains = _existing_domains(conn, city["id"])

        for index, (query, page) in enumerate(planned_items, start=1):
            if options.max_total_serpapi_queries is not None and queries_completed >= options.max_total_serpapi_queries:
                break
            query_id = create_search_query(conn, run_id, city["id"], query, page, run_mode=run_mode)
            try:
                response = provider.search(query, page=page, location=_location(city))
                record_provider_usage(conn, response.provider, run_id, city["id"], "search", query, used_cache=options.dry_run, run_mode=run_mode)
                candidates = dedupe_search_results(
                    response.results,
                    max_domains=budget.max_candidate_domains,
                    low_priority_domains=low_priority_domains,
                )
                for candidate in candidates:
                    candidate["city_id"] = city["id"]
                    candidate["run_id"] = run_id
                    candidate["query_id"] = query_id
                    candidate["provider"] = response.provider
                    candidate["run_mode"] = run_mode
                    save_candidate_url(conn, candidate)
                    if candidate["root_domain"] not in seen_domains:
                        batch_new_domains += 1
                        seen_domains.add(candidate["root_domain"])
                all_results_count += len(candidates)
                queries_completed += 1
                finish_search_query(conn, query_id, "completed", len(response.results), response.api_status)
            except Exception as exc:
                finish_search_query(conn, query_id, "failed", 0, error_message=str(exc))
                raise

            if index % 5 == 0:
                if batch_new_domains < 3:
                    low_yield_batches += 1
                else:
                    low_yield_batches = 0
                batch_new_domains = 0
            if should_stop_discovery(
                queries_completed=queries_completed,
                candidate_domains=len(seen_domains),
                verified_sources=verified_sources,
                max_serpapi_queries=budget.max_serpapi_queries,
                max_candidate_domains=budget.max_candidate_domains,
                max_verified_sources=budget.max_verified_sources,
                verified_sources_target=budget.verified_sources_target,
                low_yield_batches=low_yield_batches,
            ):
                break

        candidates_found = all_results_count
        verified_sources, rejected_sources = inspect_city_candidates(
            conn,
            city,
            run_id,
            budget,
            config,
            dry_run=options.dry_run,
            fetcher=fetcher,
        )
        finish_city_run(
            conn,
            run_id,
            "completed",
            queries_planned=queries_planned,
            queries_completed=queries_completed,
            candidates_found=candidates_found,
            verified_sources=verified_sources,
            rejected_sources=rejected_sources,
        )
        if run_mode == "live":
            mark_city_status(conn, city["id"], "completed")
        else:
            _restore_city_status(conn, city["id"], previous_status, city.get("error_message"))
        return CityProcessResult(
            city_id=city["id"],
            run_id=run_id,
            status="completed",
            queries_planned=queries_planned,
            queries_completed=queries_completed,
            candidates_found=candidates_found,
            verified_sources=verified_sources,
            rejected_sources=rejected_sources,
        )
    except Exception as exc:
        message = str(exc)
        finish_city_run(
            conn,
            run_id,
            "failed",
            queries_planned=queries_planned,
            queries_completed=queries_completed,
            candidates_found=candidates_found,
            verified_sources=verified_sources,
            rejected_sources=rejected_sources,
            error_message=message,
        )
        if run_mode == "live":
            mark_city_status(conn, city["id"], "failed", message)
        else:
            _restore_city_status(conn, city["id"], previous_status, city.get("error_message"))
        return CityProcessResult(
            city_id=city["id"],
            run_id=run_id,
            status="failed",
            queries_planned=queries_planned,
            queries_completed=queries_completed,
            candidates_found=candidates_found,
            verified_sources=verified_sources,
            rejected_sources=rejected_sources,
            error_message=message,
        )


def inspect_city_candidates(
    conn: sqlite3.Connection,
    city: dict[str, Any],
    run_id: int,
    budget: CityDiscoveryBudget,
    config: dict[str, Any],
    *,
    dry_run: bool = False,
    fetcher: PageFetcher | None = None,
    validator: UrlValidator | None = None,
) -> tuple[int, int]:
    rows = conn.execute(
        """
        select root_domain, min(source_url) as source_url,
               group_concat(coalesce(title, ''), ' ') as titles,
               group_concat(coalesce(snippet, ''), ' ') as snippets,
               min(status) as status,
               min(url_origin) as url_origin,
               min(run_mode) as run_mode
        from candidate_urls
        where city_id=? and run_id=?
        group by root_domain
        order by min(case when status='candidate' then 0 else 1 end), min(position)
        limit ?
        """,
        (city["id"], run_id, budget.max_candidate_domains),
    ).fetchall()

    verified = 0
    rejected = 0
    category_counts: Counter[str] = Counter(
        row["source_category"]
        for row in conn.execute("select source_category from source_pages where city_id=?", (city["id"],)).fetchall()
        if row["source_category"]
    )
    fetcher = fetcher or _build_fetcher(config)
    validator = validator or UrlValidator(
        user_agent=config.get("crawl", {}).get("user_agent", "MusicCalendarSourceFinderBot/0.1"),
        timeout=config.get("crawl", {}).get("timeout_seconds", 15),
    )

    for row in rows:
        if verified >= budget.max_verified_sources:
            break
        validation = None
        if not dry_run:
            low_quality_reason = source_url_rejection_reason(row["source_url"])
            if low_quality_reason:
                save_rejected_source(
                    conn,
                    city["id"],
                    run_id,
                    row["root_domain"],
                    row["source_url"],
                    low_quality_reason,
                    "URL is not a source/calendar landing page.",
                    run_mode=row["run_mode"] or "live",
                    url_origin=row["url_origin"],
                    url_validation_status="synthetic_rejected" if low_quality_reason == "individual_event_page" else None,
                )
                rejected += 1
                continue
            validation = validator.validate(row["source_url"], UrlValidationContext(city=city.get("city"), state=city.get("state")))
            _update_candidate_validation(conn, city["id"], run_id, row["source_url"], validation)
            if validation.url_validation_status not in VALIDATION_ACCEPTED_STATUSES:
                if validation.url_validation_status in {"synthetic_rejected", "dns_error", "http_error", "invalid_url", "unsupported_content_type", "connection_error"}:
                    save_rejected_source(
                        conn,
                        city["id"],
                        run_id,
                        row["root_domain"],
                        row["source_url"],
                        validation.url_validation_status,
                        validation.validation_error,
                        run_mode=row["run_mode"] or "live",
                        url_origin=row["url_origin"],
                        url_validation_status=validation.url_validation_status,
                        http_status=validation.http_status,
                        final_url=validation.final_url,
                        resolved_domain=validation.resolved_domain,
                        content_type=validation.content_type,
                        page_title=validation.page_title,
                        validation_error=validation.validation_error,
                        validated_at=validation.validated_at,
                    )
                    rejected += 1
                continue
        candidate = _candidate_from_row(city, run_id, row, dry_run=dry_run, fetcher=fetcher, config=config, validation=validation)
        sanitize_source_candidate_urls(candidate)
        if candidate.error_message:
            if candidate.crawl_status == "robots_disallowed":
                _update_candidate_validation(
                    conn,
                    city["id"],
                    run_id,
                    row["source_url"],
                    candidate,
                )
                save_rejected_source(
                    conn,
                    city["id"],
                    run_id,
                    row["root_domain"],
                    row["source_url"],
                    "robots_disallowed",
                    candidate.error_message,
                    run_mode=row["run_mode"] or "live",
                    url_origin=row["url_origin"],
                    url_validation_status="robots_disallowed",
                    validation_error=candidate.error_message,
                    validated_at=candidate.validated_at,
                )
                rejected += 1
            continue
        classification = classify_source(candidate)
        candidate.source_category = classification.source_category
        score = score_source(candidate, city, category_counts)
        category_counts[candidate.source_category or "other"] += 1
        has_score_signal = score.total_score >= 30 or candidate.source_category in {"tourism_cvb", "chamber_city_civic", "arts_council_nonprofit"}
        if has_score_signal and is_verified_url_eligible(candidate.run_mode, candidate.url_origin, candidate.url_validation_status):
            save_source_page(conn, candidate, score)
            verified += 1
        elif not has_score_signal:
            save_rejected_source(
                conn,
                city["id"],
                run_id,
                row["root_domain"],
                row["source_url"],
                "low_relevance",
                score.why_selected,
                run_mode=candidate.run_mode,
                url_origin=candidate.url_origin,
                url_validation_status=candidate.url_validation_status,
                http_status=candidate.http_status,
                final_url=candidate.final_url,
                resolved_domain=candidate.resolved_domain,
                content_type=candidate.content_type,
                page_title=candidate.page_title,
                validation_error=candidate.validation_error,
                validated_at=candidate.validated_at,
            )
            rejected += 1
        else:
            _update_candidate_validation(conn, city["id"], run_id, row["source_url"], candidate)
    return verified, rejected


def _candidate_from_row(
    city: dict[str, Any],
    run_id: int,
    row: sqlite3.Row,
    *,
    dry_run: bool,
    fetcher: PageFetcher,
    config: dict[str, Any],
    validation: Any = None,
) -> SourceCandidate:
    source_url = row["source_url"]
    parts = normalize_url(source_url)
    if dry_run:
        text = f"{row['titles'] or ''} {row['snippets'] or ''} {city['city']} {city.get('state') or ''} music events calendar"
        return SourceCandidate(
            city_id=city["id"],
            run_id=run_id,
            root_domain=row["root_domain"],
            source_name=_source_name(row["titles"], row["root_domain"]),
            website_url=_homepage(source_url),
            best_calendar_url=source_url,
            events_url=source_url,
            music_url=source_url if "music" in source_url.casefold() else None,
            title=row["titles"],
            meta_description=row["snippets"],
            detected_keywords=["music", "events", "calendar"],
            robots_allowed=True,
            crawl_status="dry_run",
            search_query=None,
            body_text=text,
            run_mode="dry_run",
            url_origin="dry_run_fixture",
            url_validation_status="valid",
            final_url=source_url,
            resolved_domain=row["root_domain"],
        )

    if validation and validation.url_validation_status == "forbidden_but_real":
        return SourceCandidate(
            city_id=city["id"],
            run_id=run_id,
            root_domain=row["root_domain"],
            source_name=validation.page_title or _source_name(row["titles"], row["root_domain"]),
            website_url=_homepage(source_url),
            best_calendar_url=source_url,
            title=validation.page_title or row["titles"],
            meta_description=row["snippets"],
            detected_keywords=["events", "calendar"],
            robots_allowed=None,
            crawl_status="forbidden_but_real",
            body_text=f"{row['titles'] or ''} {row['snippets'] or ''}",
            run_mode=row["run_mode"] or "live",
            url_origin=row["url_origin"] or "serpapi_organic",
            url_validation_status=validation.url_validation_status,
            http_status=validation.http_status,
            final_url=validation.final_url,
            resolved_domain=validation.resolved_domain,
            content_type=validation.content_type,
            page_title=validation.page_title,
            validation_error=validation.validation_error,
            validated_at=validation.validated_at,
        )

    fetched = fetcher.fetch(source_url)
    if fetched.error or not fetched.html:
        return SourceCandidate(
            city_id=city["id"],
            run_id=run_id,
            root_domain=row["root_domain"],
            source_name=row["root_domain"],
            website_url=_homepage(source_url),
            error_message=fetched.error or "empty_html",
            crawl_status=fetched.error or "empty_html",
            robots_allowed=fetched.error != "robots_disallowed",
            run_mode=row["run_mode"] or "live",
            url_origin=row["url_origin"] or "serpapi_organic",
            url_validation_status="robots_disallowed" if fetched.error == "robots_disallowed" else (validation.url_validation_status if validation else None),
            http_status=validation.http_status if validation else fetched.status_code,
            final_url=validation.final_url if validation else fetched.final_url,
            resolved_domain=validation.resolved_domain if validation else row["root_domain"],
            content_type=validation.content_type if validation else fetched.content_type,
            page_title=validation.page_title if validation else None,
            validation_error=fetched.error or (validation.validation_error if validation else None),
            validated_at=validation.validated_at if validation else None,
        )
    analysis = analyze_html(fetched.final_url or source_url, fetched.html)
    analyses = [analysis]
    for link in _additional_internal_links(analysis, row["root_domain"], config):
        child = fetcher.fetch(link.url)
        if child.html:
            analyses.append(analyze_html(child.final_url or link.url, child.html))

    source = _source_from_analyses(city["id"], run_id, row["root_domain"], source_url, analyses)
    source.run_mode = row["run_mode"] or "live"
    source.url_origin = row["url_origin"] or "serpapi_organic"
    if validation:
        source.url_validation_status = validation.url_validation_status
        source.http_status = validation.http_status
        source.final_url = validation.final_url
        source.resolved_domain = validation.resolved_domain
        source.content_type = validation.content_type
        source.page_title = validation.page_title
        source.validation_error = validation.validation_error
        source.validated_at = validation.validated_at
    return source


def _source_from_analyses(
    city_id: int,
    run_id: int,
    domain: str,
    source_url: str,
    analyses: list[CandidatePageAnalysis],
) -> SourceCandidate:
    title = next((item.title for item in analyses if item.title), domain)
    meta = next((item.meta_description for item in analyses if item.meta_description), None)
    all_links = [link for item in analyses for link in item.likely_links]
    urls_by_kind = _select_urls(all_links)
    detected = sorted({keyword for item in analyses for keyword in item.detected_keywords})
    socials = sorted({url for item in analyses for url in item.social_links})
    rss = next((item.rss_url for item in analyses if item.rss_url), None)
    email = next((item.contact_email for item in analyses if item.contact_email), None)
    body = " ".join(item.body_text or "" for item in analyses)[:5000]
    return SourceCandidate(
        city_id=city_id,
        run_id=run_id,
        root_domain=domain,
        source_name=title,
        website_url=_homepage(source_url),
        best_calendar_url=urls_by_kind.get("calendar") or urls_by_kind.get("events") or source_url,
        music_url=urls_by_kind.get("music"),
        events_url=urls_by_kind.get("events"),
        arts_url=urls_by_kind.get("arts"),
        tourism_url=urls_by_kind.get("tourism"),
        about_url=urls_by_kind.get("about"),
        rss_url=rss,
        contact_email=email,
        social_links=socials,
        title=title,
        meta_description=meta,
        detected_keywords=detected,
        robots_allowed=True,
        crawl_status="fetched",
        body_text=body,
    )


def _select_urls(links: list[Any]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for link in links:
        haystack = f"{link.url} {link.text or ''}".casefold()
        if "calendar" in haystack and "calendar" not in selected:
            selected["calendar"] = link.url
        if "event" in haystack and "events" not in selected:
            selected["events"] = link.url
        if ("music" in haystack or "concert" in haystack) and "music" not in selected:
            selected["music"] = link.url
        if ("arts" in haystack or "culture" in haystack) and "arts" not in selected:
            selected["arts"] = link.url
        if ("visit" in haystack or "tourism" in haystack or "things-to-do" in haystack) and "tourism" not in selected:
            selected["tourism"] = link.url
        if "about" in haystack and "about" not in selected:
            selected["about"] = link.url
    return selected


def _additional_internal_links(analysis: CandidatePageAnalysis, root: str, config: dict[str, Any]) -> list[Any]:
    limit = max(0, int(config.get("crawl", {}).get("max_pages_per_domain", 4)) - 1)
    output = []
    for link in analysis.likely_links:
        if root_domain(_safe_hostname(link.url) or "") == root:
            output.append(link)
        if len(output) >= limit:
            break
    return output


def _update_candidate_validation(conn: sqlite3.Connection, city_id: int, run_id: int, source_url: str, validation: Any) -> None:
    conn.execute(
        """
        update candidate_urls
        set url_validation_status=?,
            http_status=?,
            final_url=?,
            resolved_domain=?,
            content_type=?,
            page_title=?,
            validation_error=?,
            validated_at=?
        where city_id=? and run_id=? and source_url=?
        """,
        (
            getattr(validation, "url_validation_status", None),
            getattr(validation, "http_status", None),
            getattr(validation, "final_url", None),
            getattr(validation, "resolved_domain", None),
            getattr(validation, "content_type", None),
            getattr(validation, "page_title", None),
            getattr(validation, "validation_error", None),
            getattr(validation, "validated_at", None),
            city_id,
            run_id,
            source_url,
        ),
    )
    conn.commit()


def _restore_city_status(conn: sqlite3.Connection, city_id: int, status: str, error_message: str | None) -> None:
    conn.execute(
        "update cities set status=?, error_message=? where id=?",
        (status, error_message, city_id),
    )
    conn.commit()


def _apply_overrides(budget: CityDiscoveryBudget, options: RunOptions) -> CityDiscoveryBudget:
    values = budget.model_dump() if hasattr(budget, "model_dump") else budget.dict()
    if options.max_serpapi_queries_per_city is not None:
        values["max_serpapi_queries"] = min(values["max_serpapi_queries"], options.max_serpapi_queries_per_city)
    if options.max_candidate_domains_per_city is not None:
        values["max_candidate_domains"] = min(values["max_candidate_domains"], options.max_candidate_domains_per_city)
    return CityDiscoveryBudget(**values)


def _planned_query_pages(queries: list[str], budget: CityDiscoveryBudget) -> list[tuple[str, int]]:
    planned: list[tuple[str, int]] = []
    for query in queries:
        for page in range(1, budget.max_query_pages + 1):
            planned.append((query, page))
            if len(planned) >= budget.max_serpapi_queries:
                return planned
    return planned


def _existing_domains(conn: sqlite3.Connection, city_id: int) -> set[str]:
    return {
        row["root_domain"]
        for row in conn.execute(
            "select distinct root_domain from candidate_urls where city_id=? and root_domain is not null",
            (city_id,),
        )
    }


def _location(city: dict[str, Any]) -> str:
    pieces = [city.get("city"), city.get("state"), city.get("country") or "US"]
    return ", ".join(str(piece) for piece in pieces if piece)


def _build_fetcher(config: dict[str, Any]) -> PageFetcher:
    crawl = config.get("crawl", {})
    user_agent = crawl.get("user_agent", "MusicCalendarSourceFinderBot/0.1")
    robots = RobotsChecker(user_agent=user_agent, timeout=crawl.get("timeout_seconds", 15))
    return PageFetcher(
        robots=robots,
        user_agent=user_agent,
        timeout=crawl.get("timeout_seconds", 15),
        max_response_bytes=crawl.get("max_response_bytes", 2 * 1024 * 1024),
    )


def _homepage(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/"


def _safe_hostname(url: str) -> str | None:
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _source_name(title: str | None, domain: str) -> str:
    if title:
        return title.split(" - ")[0].split(" | ")[0].strip()[:120]
    return domain
