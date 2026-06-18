from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import httpx

from .dedupe import normalize_url, root_domain
from .models import UrlValidationResult
from .quality import BAD_EXPORT_URL_QUALITIES, classify_url_quality
from .utils import slugify, utc_now


VALIDATION_ACCEPTED_STATUSES = {"valid", "redirect_valid", "forbidden_but_real"}
VERIFY_ALLOWED_ORIGINS = {
    "serpapi_organic",
    "serpapi_sitelink",
    "crawled_internal_link",
    "canonical_url",
    "redirect_final_url",
    "manual_seed",
}
DRY_RUN_ORIGIN = "dry_run_fixture"

COMPOUND_SYNTHETIC_TERMS = {
    "altarts",
    "altmusic",
    "chamberarts",
    "chambermusic",
    "concertsarts",
    "concertsmusic",
    "culturearts",
    "culturemusic",
    "newspaperarts",
    "newspapermusic",
    "nightlifearts",
    "nightlifemusic",
    "observerarts",
    "observermusic",
    "tourismarts",
    "tourismmusic",
    "visitarts",
    "visitmusic",
}

DISALLOWED_SOURCE_DOMAINS = {
    "allevents.in",
    "bandsintown.com",
    "eventbrite.ie",
    "eventbrite.com",
    "meetup.com",
    "musicfestivalwizard.com",
    "nytimes.com",
    "seatgeek.com",
    "songkick.com",
    "stubhub.com",
    "ticketmaster.com",
    "tripadvisor.com",
    "vividseats.com",
    "yelp.com",
}

DISALLOWED_PATH_TERMS = {
    "affiliate",
    "redirect",
    "referral",
    "checkout",
    "tickets",
    "ticket",
    "real-estate",
    "homes-for-sale",
    "apartments",
    "mortgage",
    "moving-to",
}


@dataclass(frozen=True)
class UrlValidationContext:
    city: str | None = None
    state: str | None = None


class UrlValidator:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        user_agent: str = "MusicCalendarSourceFinderBot/0.1",
        timeout: float = 15,
        max_bytes: int = 512_000,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.user_agent = user_agent
        self.max_bytes = max_bytes

    def validate(self, url: str, context: UrlValidationContext | None = None) -> UrlValidationResult:
        context = context or UrlValidationContext()
        if is_synthetic_url(url, city=context.city, state=context.state):
            return UrlValidationResult(
                url=url,
                url_validation_status="synthetic_rejected",
                validation_error="synthetic_url_pattern",
                validated_at=utc_now(),
            )
        try:
            parts = normalize_url(url)
            if not parts.domain:
                return UrlValidationResult(
                    url=url,
                    url_validation_status="invalid_url",
                    validation_error="missing_domain",
                    validated_at=utc_now(),
                )
        except Exception as exc:
            return UrlValidationResult(url=url, url_validation_status="invalid_url", validation_error=str(exc), validated_at=utc_now())

        try:
            response = self.client.get(url, headers={"User-Agent": self.user_agent})
        except httpx.InvalidURL as exc:
            return UrlValidationResult(url=url, url_validation_status="invalid_url", validation_error=str(exc), validated_at=utc_now())
        except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            return UrlValidationResult(url=url, url_validation_status="timeout", validation_error=str(exc), validated_at=utc_now())
        except httpx.ConnectError as exc:
            message = str(exc)
            status = "dns_error" if _looks_like_dns_error(message) else "connection_error"
            return UrlValidationResult(url=url, url_validation_status=status, validation_error=message, validated_at=utc_now())
        except httpx.HTTPError as exc:
            return UrlValidationResult(url=url, url_validation_status="connection_error", validation_error=str(exc), validated_at=utc_now())

        content_type = response.headers.get("content-type", "")
        final_url = str(response.url)
        parsed_final = urlparse(final_url)
        resolved = root_domain(parsed_final.hostname or "")
        page_title = _extract_page_title(response, content_type)

        if response.status_code in {401, 403}:
            status = "forbidden_but_real"
        elif 200 <= response.status_code <= 399:
            if not _is_supported_content_type(content_type):
                status = "unsupported_content_type"
            else:
                status = "redirect_valid" if final_url.rstrip("/") != url.rstrip("/") else "valid"
        elif response.status_code in {404, 410}:
            status = "http_error"
        else:
            status = "http_error"

        return UrlValidationResult(
            url=url,
            url_validation_status=status,
            http_status=response.status_code,
            final_url=final_url,
            resolved_domain=resolved,
            content_type=content_type,
            page_title=page_title,
            validation_error=None if status in VALIDATION_ACCEPTED_STATUSES else response.reason_phrase,
            validated_at=utc_now(),
        )


def is_synthetic_url(url: str, *, city: str | None = None, state: str | None = None) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return True
    if host.startswith("www."):
        host = host[4:]
    stem = host.rsplit(".", 1)[0]
    compact_stem = stem.replace("-", "")
    if any(term in compact_stem for term in COMPOUND_SYNTHETIC_TERMS):
        return True
    if city and state:
        city_slug = slugify(city).replace("_", "-")
        state_slug = slugify(state).replace("_", "-")
        if re.match(rf"^{re.escape(city_slug)}-{re.escape(state_slug)}-[a-z0-9-]+$", stem):
            return True
        if re.match(rf"^visit{re.escape(city_slug)}-{re.escape(state_slug)}-[a-z0-9-]+$", stem):
            return True
    return False


def source_url_rejection_reason(url: str) -> str | None:
    quality = classify_url_quality(url, field_name="source_url")
    if quality == "invalid":
        return "invalid_url"
    if quality in BAD_EXPORT_URL_QUALITIES:
        return {
            "affiliate_redirect": "affiliate_or_redirect_url",
            "google_calendar_embed": "google_calendar_embed",
            "google_calendar_event_template": "google_calendar_event_template",
            "individual_event_page": "individual_event_page",
            "individual_ticket_page": "individual_ticket_page",
            "login_or_signup": "login_or_signup",
            "national_aggregator": "ticketing_or_national_aggregator",
            "social_page": "social_platform",
            "ticketing_platform": "ticketing_or_national_aggregator",
            "weak_article_or_blog_post": "weak_article_or_blog_post",
        }.get(quality, quality)
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return "invalid_url"
    root = root_domain(host)
    path = (parsed.path or "").casefold()
    query = (parsed.query or "").casefold()
    if root in DISALLOWED_SOURCE_DOMAINS:
        return "ticketing_or_national_aggregator"
    if "calendar.google.com" in host and "/event" in path:
        return "individual_event_page"
    if "/event/" in path or re.search(r"/events/[^/]+/.+", path):
        return "individual_event_page"
    if any(term in path for term in DISALLOWED_PATH_TERMS):
        return "non_source_or_affiliate_url"
    if any(token in query for token in ("aff=", "affiliate=", "ref=", "redirect=", "url=", "utm_")):
        return "affiliate_or_redirect_url"
    return None


def is_verified_url_eligible(run_mode: str | None, url_origin: str | None, validation_status: str | None) -> bool:
    return (
        (run_mode or "live") == "live"
        and (url_origin or "") in VERIFY_ALLOWED_ORIGINS
        and (validation_status or "") in VALIDATION_ACCEPTED_STATUSES
    )


def _is_supported_content_type(content_type: str) -> bool:
    lowered = (content_type or "").casefold()
    if not lowered:
        return True
    return any(
        token in lowered
        for token in (
            "text/html",
            "application/xhtml",
            "xml",
            "rss",
            "atom",
            "calendar",
            "text/calendar",
            "application/json",
        )
    )


def _extract_page_title(response: httpx.Response, content_type: str) -> str | None:
    if "html" not in (content_type or "").casefold():
        return None
    text = response.text[:200_000]
    soup = BeautifulSoup(text, "html.parser")
    if soup.title:
        title = re.sub(r"\s+", " ", soup.title.get_text(" ")).strip()
        return title or None
    return None


def _looks_like_dns_error(message: str) -> bool:
    lowered = message.casefold()
    return any(token in lowered for token in ("name or service", "nodename", "name resolution", "dns", "temporary failure"))
