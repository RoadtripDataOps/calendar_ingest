from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
from urllib.parse import urlparse

from .dedupe import root_domain
from .utils import normalize_blank, normalize_key


URL_QUALITY_FIELDS = (
    "website_url",
    "best_calendar_url",
    "music_url",
    "events_url",
    "arts_url",
    "tourism_url",
    "about_url",
    "rss_url",
    "final_url",
    "source_url",
    "normalized_url",
)

EXPORTED_URL_QUALITY_FIELDS = (
    "website_url",
    "best_calendar_url",
    "music_url",
    "events_url",
    "arts_url",
)

URL_QUALITY_VALUES = {
    "standing_calendar_page",
    "standing_source_page",
    "useful_section_page",
    "homepage_only",
    "social_page",
    "ticketing_platform",
    "national_aggregator",
    "individual_event_page",
    "individual_ticket_page",
    "google_calendar_event_template",
    "google_calendar_embed",
    "affiliate_redirect",
    "login_or_signup",
    "regional_reference",
    "weak_article_or_blog_post",
    "unrelated",
    "invalid",
    "rejected",
}

SOURCE_QUALITY_TIERS = {
    "core_local_publication",
    "core_local_calendar",
    "tourism_cvb_calendar",
    "arts_culture_org",
    "music_org",
    "radio_media",
    "venue_calendar",
    "promoter_calendar",
    "university_calendar",
    "festival_hub",
    "regional_reference",
    "national_aggregator",
    "ticketing_platform",
    "social_platform",
    "weak_article_or_blog_post",
    "challenge_or_blocked_source",
    "real_estate_or_commercial_blog",
    "individual_event_page",
    "rejected",
}

CONTENT_QUALITY_STATUSES = {
    "usable_content",
    "challenge_page",
    "blocked_content",
    "sparse_content",
    "unknown",
}

BAD_EXPORT_URL_QUALITIES = {
    "ticketing_platform",
    "national_aggregator",
    "individual_event_page",
    "individual_ticket_page",
    "google_calendar_event_template",
    "google_calendar_embed",
    "affiliate_redirect",
    "login_or_signup",
    "social_page",
    "weak_article_or_blog_post",
    "unrelated",
    "invalid",
    "rejected",
}

BAD_BEST_CALENDAR_QUALITIES = BAD_EXPORT_URL_QUALITIES | {"homepage_only", "regional_reference"}
ACCEPTABLE_BEST_CALENDAR_QUALITIES = {"standing_calendar_page", "useful_section_page"}
ACCEPTABLE_WEBSITE_QUALITIES = {
    "homepage_only",
    "standing_calendar_page",
    "standing_source_page",
    "useful_section_page",
}

TOP_SOURCE_TIERS = {
    "core_local_publication",
    "core_local_calendar",
    "tourism_cvb_calendar",
    "arts_culture_org",
    "music_org",
    "radio_media",
    "venue_calendar",
    "promoter_calendar",
    "university_calendar",
    "festival_hub",
}

TOP_REJECT_TIERS = SOURCE_QUALITY_TIERS - TOP_SOURCE_TIERS
VERIFIED_REJECT_TIERS = {
    "national_aggregator",
    "ticketing_platform",
    "social_platform",
    "weak_article_or_blog_post",
    "real_estate_or_commercial_blog",
    "individual_event_page",
    "rejected",
}

CHALLENGE_PATTERNS = (
    "access denied",
    "attention required",
    "checking your browser",
    "cloudflare ray id",
    "ddos protection",
    "enable javascript",
    "just a moment",
    "please enable javascript",
    "verifying you are human",
)

BLOCKED_PATTERNS = (
    "403 forbidden",
    "blocked",
    "request unsuccessful",
    "temporarily unavailable",
)

GENERIC_SOURCE_NAMES = {
    "",
    "calendar",
    "events",
    "home",
    "homepage",
    "just a moment",
    "untitled",
}

KNOWN_DOMAIN_TIERS = {
    "discoverlosangeles.com": "tourism_cvb_calendar",
    "do512.com": "core_local_calendar",
    "dola.com": "core_local_calendar",
    "dolosangeles.com": "core_local_calendar",
    "exploreasheville.com": "tourism_cvb_calendar",
    "laweekly.com": "core_local_publication",
    "musiccenter.org": "arts_culture_org",
    "ohmyrockness.com": "promoter_calendar",
    "timeout.com": "core_local_calendar",
}

KNOWN_DOMAIN_NAMES = {
    "discoverlosangeles.com": "Discover Los Angeles",
    "do512.com": "Do512",
    "dola.com": "DoLA",
    "dolosangeles.com": "DoLA",
    "exploreasheville.com": "Explore Asheville",
    "flyaustin.com": "Austin-Bergstrom International Airport",
    "flyavl.com": "Asheville Regional Airport",
    "laweekly.com": "LA Weekly",
    "livemusicasheville.com": "Live Music Asheville",
    "musiccenter.org": "The Music Center",
    "ohmyrockness.com": "Oh My Rockness Los Angeles",
    "timeout.com": "Time Out Los Angeles",
}

WEAK_ARTICLE_ROOTS = {
    "afar.com",
    "communityplaymaker.com",
    "drifttravel.com",
    "matadornetwork.com",
    "rollingstone.com",
}

AIRPORT_PORT_ROOT_TERMS = (
    "airport",
    "fly",
    "port",
)

AIRPORT_PORT_TEXT_TERMS = (
    "airport",
    "airline",
    "terminal",
)

HOSPITALITY_TEXT_TERMS = (
    "hotel",
    "restaurant",
    "resort",
)

TICKETING_ROOTS = {
    "axs.com",
    "eventbrite.com",
    "eventbrite.ie",
    "seatgeek.com",
    "stubhub.com",
    "ticketmaster.com",
    "vividseats.com",
}

NATIONAL_AGGREGATOR_ROOTS = {
    "allevents.in",
    "bandsintown.com",
    "concertfix.com",
    "meetup.com",
    "musicfestivalwizard.com",
    "nytimes.com",
    "songkick.com",
    "spotify.com",
    "yelp.com",
    "tripadvisor.com",
}

REGIONAL_REFERENCE_ROOTS = {
    "bachtrack.com",
    "traveltexas.com",
    "visitcalifornia.com",
    "visitnc.com",
}

SOCIAL_ROOTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

REAL_ESTATE_ROOT_TERMS = (
    "apartment",
    "apartments",
    "broker",
    "commercialrealestate",
    "homes",
    "properties",
    "property",
    "realestate",
    "realty",
    "realtor",
    "rentals",
)

REAL_ESTATE_TEXT_TERMS = (
    "apartments",
    "brokerage",
    "commercial real estate",
    "homes for sale",
    "mortgage",
    "property management",
    "real estate",
    "realtor",
    "relocation",
)

ARTICLE_PATH_TERMS = (
    "/article/",
    "/articles/",
    "/blog/",
    "/blogs/",
    "/guide/",
    "/guides/",
    "/news/",
    "/post/",
    "/posts/",
    "/story/",
    "/stories/",
)

CALENDAR_PATH_TERMS = (
    "calendar",
    "clubland",
    "event-calendar",
    "events",
    "live-music",
    "music-calendar",
    "things-to-do",
)

SECTION_PATH_TERMS = (
    "arts",
    "culture",
    "festival",
    "festivals",
    "music",
    "nightlife",
)

LOGIN_PATH_TERMS = (
    "login",
    "log-in",
    "register",
    "sign-in",
    "signin",
    "signup",
    "wp-login",
)

AFFILIATE_TERMS = (
    "aff=",
    "affiliate",
    "consumer.pxf.io",
    "pxf.io",
    "redirect=",
    "referrer=",
    "utm_",
)


def classify_url_quality(
    url: Any,
    *,
    source_root_domain: str | None = None,
    field_name: str | None = None,
) -> str:
    value = normalize_blank(url)
    if not value:
        return ""
    try:
        parsed = urlparse(str(value))
        if not parsed.scheme or not parsed.netloc:
            return "invalid"
        host = (parsed.hostname or "").casefold()
    except ValueError:
        return "invalid"
    if not host:
        return "invalid"
    root = root_domain(host)
    path = (parsed.path or "").casefold()
    query = (parsed.query or "").casefold()
    full = str(value).casefold()
    source_root = normalize_key(source_root_domain)

    if root in SOCIAL_ROOTS:
        return "social_page"
    if _is_affiliate_url(full, query):
        return "affiliate_redirect"
    if _is_login_url(path, query):
        return "login_or_signup"
    if _is_google_calendar_url(host, path):
        return "google_calendar_event_template" if _is_google_calendar_event(path, query) else "google_calendar_embed"
    if _is_real_estate_url(root, path, full):
        return "weak_article_or_blog_post"
    if root in TICKETING_ROOTS:
        return "individual_ticket_page" if _is_ticket_or_event_path(root, path, query) else "ticketing_platform"
    if host == "open.spotify.com" and path.startswith("/concerts/location"):
        return "national_aggregator"
    if root in NATIONAL_AGGREGATOR_ROOTS:
        return "national_aggregator"
    if root in REGIONAL_REFERENCE_ROOTS:
        return "regional_reference"
    if _is_ticket_or_event_path(root, path, query):
        return "individual_ticket_page"
    if _is_individual_event_path(path):
        return "individual_event_page"
    if _is_weak_article_path(path):
        return "weak_article_or_blog_post"
    if field_name not in {None, "website_url", "rss_url"} and source_root and root and root != source_root:
        return "unrelated"
    if _is_homepage(path):
        return "homepage_only"
    if any(term in path for term in CALENDAR_PATH_TERMS):
        return "standing_calendar_page"
    if any(term in path for term in SECTION_PATH_TERMS):
        return "useful_section_page"
    return "standing_source_page"


def sanitize_url_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(record)
    source_root = _source_root(output)
    website_quality = classify_url_quality(output.get("website_url"), source_root_domain=source_root, field_name="website_url")

    for field in URL_QUALITY_FIELDS:
        if field not in output:
            continue
        if field == "website_url":
            continue
        quality = classify_url_quality(output.get(field), source_root_domain=source_root, field_name=field)
        if field == "best_calendar_url":
            if quality in BAD_BEST_CALENDAR_QUALITIES:
                output[field] = output.get("website_url") if website_quality == "standing_source_page" else None
            elif quality not in ACCEPTABLE_BEST_CALENDAR_QUALITIES and quality:
                output[field] = None
        elif quality in BAD_EXPORT_URL_QUALITIES:
            output[field] = None

    for field in URL_QUALITY_FIELDS:
        if field in output:
            output[f"{field}_quality"] = classify_url_quality(output.get(field), source_root_domain=source_root, field_name=field)
    output["content_quality_status"] = classify_content_quality(output)
    output["challenge_page_detected"] = 1 if output["content_quality_status"] == "challenge_page" else 0
    output = normalize_display_metadata(output)
    output["source_quality_tier"] = classify_source_quality_tier(output)
    return output


def classify_content_quality(record: Mapping[str, Any]) -> str:
    text = " ".join(
        str(record.get(field) or "")
        for field in (
            "source_name",
            "title",
            "page_title",
            "meta_description",
            "validation_error",
            "error_message",
        )
    ).casefold()
    if any(pattern in text for pattern in CHALLENGE_PATTERNS):
        return "challenge_page"
    if any(pattern in text for pattern in BLOCKED_PATTERNS):
        return "blocked_content"
    meaningful = " ".join(str(record.get(field) or "") for field in ("source_name", "title", "meta_description")).strip()
    if not meaningful:
        return "unknown"
    if len(meaningful) < 18 and not record.get("best_calendar_url"):
        return "sparse_content"
    return "usable_content"


def normalize_display_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(record)
    fallback = _fallback_source_name(output)
    for field in ("source_name", "title"):
        value = str(output.get(field) or "").strip()
        if is_bad_source_name(value):
            output[field] = fallback
    return output


def is_bad_source_name(value: Any) -> bool:
    text = normalize_key(value)
    if text in GENERIC_SOURCE_NAMES:
        return True
    if any(pattern in text for pattern in CHALLENGE_PATTERNS):
        return True
    if text in {"checking your browser before accessing. just a moment", "please enable javascript"}:
        return True
    return False


def sanitize_source_candidate_urls(source: Any) -> Any:
    data = {
        field: getattr(source, field, None)
        for field in (
            "website_url",
            "best_calendar_url",
            "music_url",
            "events_url",
            "arts_url",
            "tourism_url",
            "about_url",
            "rss_url",
            "final_url",
        )
    }
    data["root_domain"] = getattr(source, "root_domain", None)
    sanitized = sanitize_url_fields(data)
    for field in (
        "best_calendar_url",
        "music_url",
        "events_url",
        "arts_url",
        "tourism_url",
        "about_url",
        "rss_url",
        "final_url",
    ):
        if hasattr(source, field):
            setattr(source, field, sanitized.get(field))
    return source


def classify_source_quality_tier(record: Mapping[str, Any]) -> str:
    source_root = _source_root(record)
    website_quality = record.get("website_url_quality") or classify_url_quality(
        record.get("website_url"),
        source_root_domain=source_root,
        field_name="website_url",
    )
    category = normalize_key(record.get("source_category"))
    text = _record_text(record)
    city = normalize_key(record.get("city"))
    city_hit = _city_hit(city, text)
    content_quality = str(record.get("content_quality_status") or classify_content_quality(record))

    if content_quality in {"challenge_page", "blocked_content"}:
        return "challenge_or_blocked_source"
    if website_quality in {"invalid", "rejected"}:
        return "rejected"
    if website_quality in {"individual_event_page", "google_calendar_event_template"}:
        return "individual_event_page"
    if website_quality in {"individual_ticket_page", "ticketing_platform"} or source_root in TICKETING_ROOTS:
        return "ticketing_platform"
    if website_quality == "social_page" or category == "social_platform":
        return "social_platform"
    if source_root in NATIONAL_AGGREGATOR_ROOTS or website_quality == "national_aggregator":
        return "national_aggregator"
    if _is_real_estate_source(source_root, text):
        return "real_estate_or_commercial_blog"
    if source_root in KNOWN_DOMAIN_TIERS:
        tier = KNOWN_DOMAIN_TIERS[source_root]
        if tier == "tourism_cvb_calendar" and not city_hit:
            return "regional_reference"
        return tier
    if _is_airport_or_port_source(source_root, text):
        return "venue_calendar"
    if _is_hospitality_source(text):
        return "venue_calendar" if "calendar" in text or "events" in text else "regional_reference"
    if website_quality == "weak_article_or_blog_post" or _looks_like_article_source(record):
        return "weak_article_or_blog_post"
    if source_root in REGIONAL_REFERENCE_ROOTS:
        return "regional_reference"
    if category == "tourism_cvb":
        return "tourism_cvb_calendar" if city_hit else "regional_reference"
    if category in {"alt_weekly", "local_publication", "magazine", "newspaper"}:
        return "core_local_publication" if city_hit else "regional_reference"
    if category in {"chamber_city_civic", "event_aggregator", "neighborhood_community"}:
        return "core_local_calendar" if city_hit else "regional_reference"
    if category == "arts_council_nonprofit":
        return "arts_culture_org"
    if category == "radio_media":
        return "radio_media"
    if category == "venue_calendar":
        return "venue_calendar"
    if category == "promoter_calendar":
        return "promoter_calendar"
    if category == "university_college":
        return "university_calendar"
    if category == "festival_hub":
        return "festival_hub"
    if any(term in text for term in ("music", "live music", "concert calendar")) and city_hit:
        return "music_org"
    if city_hit and any(term in text for term in ("calendar", "events", "arts", "culture")):
        return "core_local_calendar"
    return "regional_reference" if not city_hit else "core_local_calendar"


def is_verified_source_eligible(record: Mapping[str, Any]) -> bool:
    tier = str(record.get("source_quality_tier") or classify_source_quality_tier(record))
    if tier in VERIFIED_REJECT_TIERS:
        return False
    website_quality = str(record.get("website_url_quality") or "")
    if website_quality not in ACCEPTABLE_WEBSITE_QUALITIES:
        return False
    best_quality = str(record.get("best_calendar_url_quality") or "")
    if best_quality and best_quality in BAD_BEST_CALENDAR_QUALITIES:
        return False
    return True


def is_top_source_eligible(record: Mapping[str, Any]) -> bool:
    if not is_verified_source_eligible(record):
        return False
    tier = str(record.get("source_quality_tier") or "")
    if tier in TOP_REJECT_TIERS or tier not in TOP_SOURCE_TIERS:
        return False
    if is_bad_source_name(record.get("source_name")) or is_bad_source_name(record.get("title")):
        return False
    if record.get("content_quality_status") in {"challenge_page", "blocked_content"}:
        return False
    best_quality = str(record.get("best_calendar_url_quality") or "")
    if best_quality and best_quality not in ACCEPTABLE_BEST_CALENDAR_QUALITIES:
        return False
    local_score = _float_value(record.get("local_relevance_score"))
    music_score = _float_value(record.get("music_signal_score"))
    calendar_score = _float_value(record.get("calendar_signal_score"))
    total_score = _float_value(record.get("total_score"))
    return local_score >= 25 and total_score >= 50 and (music_score >= 18 or calendar_score >= 18)


def source_tier_sort_key(tier: str) -> int:
    order = {
        "core_local_calendar": 0,
        "core_local_publication": 1,
        "tourism_cvb_calendar": 2,
        "arts_culture_org": 3,
        "music_org": 4,
        "radio_media": 5,
        "venue_calendar": 6,
        "promoter_calendar": 7,
        "university_calendar": 8,
        "festival_hub": 9,
        "challenge_or_blocked_source": 19,
        "regional_reference": 20,
        "national_aggregator": 30,
        "ticketing_platform": 31,
        "social_platform": 32,
        "weak_article_or_blog_post": 40,
        "real_estate_or_commercial_blog": 41,
        "individual_event_page": 42,
        "rejected": 99,
    }
    return order.get(tier, 50)


def _source_root(record: Mapping[str, Any]) -> str:
    website_url = normalize_blank(record.get("website_url"))
    if website_url:
        try:
            parsed = urlparse(str(website_url))
            if parsed.hostname:
                return root_domain(parsed.hostname)
        except ValueError:
            pass
    return normalize_key(record.get("root_domain"))


def _is_google_calendar_url(host: str, path: str) -> bool:
    return host == "calendar.google.com" or (host.endswith(".google.com") and "/calendar" in path)


def _is_google_calendar_event(path: str, query: str) -> bool:
    return any(term in path for term in ("/event", "eventedit")) or "eid=" in query


def _is_affiliate_url(full: str, query: str) -> bool:
    return any(term in full for term in AFFILIATE_TERMS) or any(term in query for term in AFFILIATE_TERMS)


def _is_login_url(path: str, query: str) -> bool:
    combined = f"{path}?{query}"
    return any(term in combined for term in LOGIN_PATH_TERMS)


def _is_real_estate_url(root: str, path: str, full: str) -> bool:
    compact_root = root.replace("-", "")
    if any(term in compact_root for term in REAL_ESTATE_ROOT_TERMS):
        return True
    return any(term.replace(" ", "-") in full or term in full for term in REAL_ESTATE_TEXT_TERMS)


def _is_real_estate_source(source_root: str, text: str) -> bool:
    compact_root = source_root.replace("-", "")
    return any(term in compact_root for term in REAL_ESTATE_ROOT_TERMS) or any(term in text for term in REAL_ESTATE_TEXT_TERMS)


def _is_ticket_or_event_path(root: str, path: str, query: str) -> bool:
    if root == "axs.com" and path.startswith("/events/"):
        return True
    if root in {"ticketmaster.com", "eventbrite.com", "eventbrite.ie", "vividseats.com"} and re.search(r"/e(vent)?s?/", path):
        return True
    if any(term in path for term in ("/tickets/", "/ticket/", "/checkout", "/buy/", "/purchase")):
        return True
    return "tickets" in query or "ticket" in query


def _is_individual_event_path(path: str) -> bool:
    if re.search(r"/20[0-9]{2}/[0-9]{2}/[0-9]{2}/", path):
        return True
    if re.search(r"/events?/[^/]+-[0-9]{5,}", path):
        return True
    return bool(re.search(r"/events?/[^/]+/.+", path))


def _is_weak_article_path(path: str) -> bool:
    if any(term in path for term in ARTICLE_PATH_TERMS):
        return True
    return bool(re.search(r"/20[0-9]{2}/[0-9]{2}/[^/]+", path))


def _looks_like_article_source(record: Mapping[str, Any]) -> bool:
    title = normalize_key(record.get("source_name") or record.get("title"))
    url_text = " ".join(str(record.get(field) or "") for field in ("website_url", "best_calendar_url", "music_url", "events_url", "arts_url")).casefold()
    source_root = _source_root(record)
    if source_root in WEAK_ARTICLE_ROOTS:
        return True
    if any(term in url_text for term in ARTICLE_PATH_TERMS):
        return True
    article_title_terms = (
        "3 days in",
        "8 places",
        "balancing boom",
        "best places",
        "guide to",
        "local musician's travel guide",
        "must-visit music city",
        "things to do",
        "things to know",
        "travel guide",
        "vibrant city of music",
        "where to ",
        "why ",
    )
    if any(term in title for term in article_title_terms) and "calendar" not in title:
        return True
    return bool(re.match(r"^[0-9]+\\s+(days|places|things|reasons)\\b", title))


def _is_airport_or_port_source(source_root: str, text: str) -> bool:
    root_stem = source_root.split(".", 1)[0]
    if any(term in root_stem for term in AIRPORT_PORT_ROOT_TERMS) and any(term in text for term in AIRPORT_PORT_TEXT_TERMS):
        return True
    return any(term in text for term in AIRPORT_PORT_TEXT_TERMS) and "airport" in text


def _is_hospitality_source(text: str) -> bool:
    return any(term in text for term in HOSPITALITY_TEXT_TERMS)


def _fallback_source_name(record: Mapping[str, Any]) -> str:
    source_root = _source_root(record)
    if source_root in KNOWN_DOMAIN_NAMES:
        return KNOWN_DOMAIN_NAMES[source_root]
    root_label = source_root.rsplit(".", 1)[0] if source_root else "Unknown Source"
    words = re.split(r"[-_.]+", root_label)
    small_words = {"and", "of", "the"}
    formatted = " ".join(word.upper() if len(word) <= 3 and word not in small_words else word.title() for word in words if word)
    return formatted or "Unknown Source"


def _is_homepage(path: str) -> bool:
    cleaned = path.strip("/")
    return cleaned == ""


def _record_text(record: Mapping[str, Any]) -> str:
    pieces = [
        record.get("root_domain"),
        record.get("source_name"),
        record.get("source_category"),
        record.get("website_url"),
        record.get("best_calendar_url"),
        record.get("music_url"),
        record.get("events_url"),
        record.get("arts_url"),
        record.get("title"),
        record.get("meta_description"),
        record.get("detected_keywords"),
        record.get("why_selected"),
    ]
    return " ".join(str(piece) for piece in pieces if piece).casefold()


def _city_hit(city: str, text: str) -> bool:
    if not city:
        return False
    city_slug = city.replace(" ", "-")
    city_compact = city.replace(" ", "")
    text_compact = text.replace("-", "").replace("_", "").replace(" ", "")
    return city in text or city_slug in text or city_compact in text_compact


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
