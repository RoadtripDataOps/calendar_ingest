from __future__ import annotations

from collections import Counter
import re
from typing import Any

from .models import ScoreResult, SourceCandidate
from .quality import classify_source_quality_tier, classify_url_quality


MUSIC_KEYWORDS = [
    "music",
    "live music",
    "concert",
    "concerts",
    "bands",
    "artists",
    "djs",
    "nightlife",
    "venue",
    "festival",
    "jazz",
    "electronic",
    "hip-hop",
    "rock",
    "indie",
    "classical",
    "opera",
    "symphony",
    "dance music",
    "open mic",
]

CALENDAR_KEYWORDS = [
    "events",
    "calendar",
    "event calendar",
    "things to do",
    "listings",
    "upcoming events",
    "submit event",
    "community calendar",
    "schedule",
]

AUTHORITY_CATEGORIES = {
    "tourism_cvb",
    "chamber_city_civic",
    "local_publication",
    "alt_weekly",
    "newspaper",
    "magazine",
    "arts_council_nonprofit",
    "university_college",
    "radio_media",
}

GENERIC_CATEGORIES = {"ticketing_platform", "social_platform"}
NATIONAL_OR_AGGREGATOR_DOMAINS = {
    "allevents.in",
    "bandsintown.com",
    "eventbrite.ie",
    "nytimes.com",
    "eventbrite.com",
    "meetup.com",
    "musicfestivalwizard.com",
    "ticketmaster.com",
    "seatgeek.com",
    "songkick.com",
    "yelp.com",
    "tripadvisor.com",
}


def score_source(
    source: SourceCandidate,
    city_record: dict[str, Any],
    existing_category_counts: Counter[str] | None = None,
) -> ScoreResult:
    existing_category_counts = existing_category_counts or Counter()
    text = _source_text(source)
    city = str(city_record.get("city") or "").casefold()
    state = str(city_record.get("state") or "").casefold()
    metro = str(city_record.get("metro_name") or "").casefold()

    city_hit = bool(city and city in text)
    state_hit = bool(state and re.search(rf"\b{re.escape(state)}\b", text))
    metro_hit = bool(metro and metro in text)
    local_score = 0
    if city_hit:
        local_score += 70
    if state_hit:
        local_score += 10
    if metro_hit:
        local_score += 10
    if source.source_category in {"tourism_cvb", "chamber_city_civic", "arts_council_nonprofit"}:
        local_score += 20
    if not city_hit:
        local_score = min(local_score, 25)
    local_score = min(100, local_score)

    music_score = _keyword_score(text, MUSIC_KEYWORDS)
    calendar_score = _keyword_score(text, CALENDAR_KEYWORDS)

    authority_score = 75 if source.source_category in AUTHORITY_CATEGORIES else 45
    if source.source_category in GENERIC_CATEGORIES:
        authority_score = 20
    if source.root_domain.endswith(".edu"):
        authority_score = max(authority_score, 75)

    freshness_score = 0
    if re.search(r"\b20(2[5-9]|3[0-9])\b", text):
        freshness_score += 40
    if any(phrase in text for phrase in ["upcoming", "this week", "submit event", "calendar"]):
        freshness_score += 40
    if source.rss_url:
        freshness_score += 20
    freshness_score = min(100, freshness_score)

    category_count = existing_category_counts.get(source.source_category or "", 0)
    diversity_score = max(20, 100 - category_count * 20)
    if source.source_category in GENERIC_CATEGORIES:
        diversity_score = min(diversity_score, 30)

    total = (
        local_score * 0.25
        + music_score * 0.30
        + calendar_score * 0.20
        + authority_score * 0.10
        + freshness_score * 0.05
        + diversity_score * 0.10
    )
    root = source.root_domain.casefold()
    path_text = " ".join(
        value or ""
        for value in (
            source.website_url,
            source.best_calendar_url,
            source.music_url,
            source.events_url,
            source.arts_url,
        )
    ).casefold()
    if root in NATIONAL_OR_AGGREGATOR_DOMAINS:
        total = min(total, 38 if not city_hit else 45)
    if source.source_category in GENERIC_CATEGORIES:
        total = min(total, 35)
    if not city_hit and source.source_category not in {"tourism_cvb", "chamber_city_civic"}:
        total = min(total, 42)
    if any(token in path_text for token in ("affiliate", "redirect", "checkout", "tickets", "real-estate", "homes-for-sale")):
        total = min(total, 30)
    quality_record = _quality_record(source, city_record)
    source_quality_tier = classify_source_quality_tier(quality_record)
    best_calendar_quality = classify_url_quality(
        source.best_calendar_url,
        source_root_domain=source.root_domain,
        field_name="best_calendar_url",
    )
    if source_quality_tier in {"real_estate_or_commercial_blog", "weak_article_or_blog_post", "individual_event_page", "rejected"}:
        total = min(total, 20)
    elif source_quality_tier in {"ticketing_platform", "social_platform"}:
        total = min(total, 25)
    elif source_quality_tier == "national_aggregator":
        total = min(total, 30)
    elif source_quality_tier == "regional_reference":
        total = min(total, 45)
    if best_calendar_quality in {
        "affiliate_redirect",
        "google_calendar_embed",
        "google_calendar_event_template",
        "individual_event_page",
        "individual_ticket_page",
        "login_or_signup",
        "national_aggregator",
        "ticketing_platform",
        "unrelated",
        "weak_article_or_blog_post",
    }:
        total = min(total, 35)
    confidence = "high" if total >= 75 else "medium" if total >= 50 else "low" if total >= 30 else "reject"
    return ScoreResult(
        local_relevance_score=round(local_score, 1),
        music_signal_score=round(music_score, 1),
        calendar_signal_score=round(calendar_score, 1),
        authority_score=round(authority_score, 1),
        freshness_score=round(freshness_score, 1),
        diversity_score=round(diversity_score, 1),
        total_score=round(total, 1),
        confidence=confidence,
        why_selected=why_selected(source, music_score, calendar_score, local_score),
    )


def why_selected(source: SourceCandidate, music_score: float, calendar_score: float, local_score: float) -> str:
    category = (source.source_category or "source").replace("_", " ")
    strengths: list[str] = []
    if local_score >= 60:
        strengths.append("local relevance")
    if music_score >= 50:
        strengths.append("music coverage")
    if calendar_score >= 50:
        strengths.append("calendar signals")
    if not strengths:
        strengths.append("source-page evidence")
    return f"{category.title()} with " + ", ".join(strengths) + "."


def should_stop_discovery(
    *,
    queries_completed: int,
    candidate_domains: int,
    verified_sources: int,
    max_serpapi_queries: int,
    max_candidate_domains: int,
    max_verified_sources: int,
    verified_sources_target: int,
    low_yield_batches: int,
) -> bool:
    if queries_completed >= max_serpapi_queries:
        return True
    if candidate_domains >= max_candidate_domains:
        return True
    if verified_sources >= max_verified_sources:
        return True
    return verified_sources >= verified_sources_target and low_yield_batches >= 3


def _keyword_score(text: str, keywords: list[str]) -> float:
    hits = sum(1 for keyword in keywords if keyword in text)
    return min(100, hits * 18)


def _source_text(source: SourceCandidate) -> str:
    pieces = [
        source.root_domain,
        source.website_url,
        source.best_calendar_url,
        source.music_url,
        source.events_url,
        source.arts_url,
        source.title,
        source.meta_description,
        " ".join(source.detected_keywords),
        source.body_text,
    ]
    return " ".join(piece for piece in pieces if piece).casefold()


def _quality_record(source: SourceCandidate, city_record: dict[str, Any]) -> dict[str, Any]:
    data = source.model_dump() if hasattr(source, "model_dump") else source.dict()
    data["city"] = city_record.get("city")
    data["state"] = city_record.get("state")
    return data
