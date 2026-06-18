from __future__ import annotations

from typing import Iterable

from .models import ClassificationResult, SourceCandidate


CATEGORIES = {
    "tourism_cvb": ["visit", "tourism", "convention", "visitors bureau", "things to do"],
    "chamber_city_civic": ["chamber", "city of", "downtown", "main street", "civic"],
    "arts_council_nonprofit": ["arts council", "arts foundation", "nonprofit", "cultural council"],
    "alt_weekly": ["weekly", "observer", "new times", "reader", "chronicle", "scene"],
    "newspaper": ["newspaper", "daily", "times", "tribune", "gazette", "journal"],
    "magazine": ["magazine", "mag", "culture magazine"],
    "radio_media": ["radio", "fm", "am ", "listener supported", "station"],
    "university_college": [".edu", "university", "college", "campus"],
    "venue_calendar": ["venue", "theatre", "theater", "club", "hall", "amphitheater", "calendar"],
    "promoter_calendar": ["presents", "productions", "promoter", "booking"],
    "festival_hub": ["festival", "festivals"],
    "neighborhood_community": ["neighborhood", "community", "district"],
    "event_aggregator": ["event aggregator", "events calendar", "things to do"],
    "social_platform": ["facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com"],
    "ticketing_platform": ["ticketmaster.com", "eventbrite.com", "songkick.com", "bandsintown.com"],
}


def classify_source(source: SourceCandidate) -> ClassificationResult:
    text = _text_parts(
        source.root_domain,
        source.website_url,
        source.best_calendar_url,
        source.title,
        source.meta_description,
        source.search_query,
        source.body_text,
        " ".join(source.detected_keywords),
    )
    scores: dict[str, int] = {}
    for category, needles in CATEGORIES.items():
        scores[category] = sum(1 for needle in needles if needle.casefold() in text)

    if source.root_domain.endswith(".edu"):
        scores["university_college"] = scores.get("university_college", 0) + 3
    if source.root_domain in {"facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com"}:
        scores["social_platform"] = scores.get("social_platform", 0) + 5
    if source.root_domain in {"ticketmaster.com", "eventbrite.com", "songkick.com", "bandsintown.com"}:
        scores["ticketing_platform"] = scores.get("ticketing_platform", 0) + 5

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]
    if best_score == 0:
        best_category = "local_publication" if any(word in text for word in ["music", "arts", "events"]) else "other"
    confidence = "high" if best_score >= 3 else "medium" if best_score >= 1 else "low"
    secondary = [category for category, score in scores.items() if category != best_category and score > 0][:5]
    return ClassificationResult(source_category=best_category, secondary_tags=secondary, confidence=confidence)


def _text_parts(*parts: str | None) -> str:
    return " ".join(part for part in parts if part).casefold()

