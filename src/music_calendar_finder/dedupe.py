from __future__ import annotations

from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import SearchResult, UrlParts


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}

LOW_PRIORITY_DEFAULTS = {
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "eventbrite.com",
    "ticketmaster.com",
    "songkick.com",
    "bandsintown.com",
    "meetup.com",
    "allevents.in",
    "yelp.com",
    "tripadvisor.com",
}

SECOND_LEVEL_TLDS = {"co.uk", "org.uk", "ac.uk", "com.au", "com.br", "co.nz"}


def normalize_url(url: str, low_priority_domains: set[str] | None = None) -> UrlParts:
    low_priority_domains = low_priority_domains or LOW_PRIORITY_DEFAULTS
    raw_url = url.strip()
    try:
        parsed = urlparse(raw_url)
        if not parsed.scheme:
            parsed = urlparse(f"https://{raw_url}")
        domain = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return UrlParts(
            original_url=url,
            normalized_url=raw_url,
            grouping_url=raw_url,
            domain="",
            root_domain="",
            path="",
            is_low_priority=False,
        )
    scheme = parsed.scheme.lower()
    netloc = domain
    if port:
        netloc = f"{netloc}:{port}"
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS],
        doseq=True,
    )
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    grouping = urlunparse(("https", netloc, path, "", query, ""))
    root = root_domain(domain)
    return UrlParts(
        original_url=url,
        normalized_url=normalized,
        grouping_url=grouping,
        domain=domain,
        root_domain=root,
        path=path,
        is_low_priority=any(root == item or domain.endswith(f".{item}") for item in low_priority_domains),
    )


def root_domain(domain: str) -> str:
    domain = domain.lower().strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    suffix = ".".join(parts[-2:])
    if suffix in SECOND_LEVEL_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def dedupe_search_results(
    results: list[SearchResult],
    *,
    max_domains: int = 100,
    per_domain_limit: int = 3,
    low_priority_domains: set[str] | None = None,
) -> list[dict]:
    grouped_counts: dict[str, int] = defaultdict(int)
    output: list[dict] = []
    seen_urls: set[str] = set()
    for result in results:
        parts = normalize_url(result.link, low_priority_domains=low_priority_domains)
        if not parts.domain:
            continue
        if parts.normalized_url in seen_urls:
            continue
        if grouped_counts[parts.root_domain] >= per_domain_limit:
            continue
        if len(grouped_counts) >= max_domains and parts.root_domain not in grouped_counts:
            break
        seen_urls.add(parts.normalized_url)
        grouped_counts[parts.root_domain] += 1
        status = "low_priority" if parts.is_low_priority else "candidate"
        output.append(
            {
                "source_url": result.link,
                "normalized_url": parts.normalized_url,
                "domain": parts.domain,
                "root_domain": parts.root_domain,
                "title": result.title,
                "snippet": result.snippet,
                "position": result.position,
                "provider": result.source,
                "url_origin": result.url_origin,
                "status": status,
            }
        )
    return output
