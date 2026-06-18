from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from music_calendar_finder.models import CandidatePageAnalysis, ExtractedLink


KEYWORDS = [
    "events",
    "event-calendar",
    "calendar",
    "music",
    "live-music",
    "concerts",
    "nightlife",
    "arts",
    "culture",
    "things-to-do",
    "entertainment",
    "community-calendar",
    "festivals",
    "listings",
]

SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com")


def analyze_html(url: str, html: str) -> CandidatePageAnalysis:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _clean(soup.title.get_text(" ")) if soup.title else None
    meta_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_description = _clean(meta_tag.get("content")) if meta_tag and meta_tag.get("content") else None
    canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    canonical_url = _safe_urljoin(url, canonical_tag.get("href")) if canonical_tag and canonical_tag.get("href") else None

    links: list[ExtractedLink] = []
    likely_links: list[ExtractedLink] = []
    social_links: list[str] = []
    contact_email: str | None = None
    rss_url: str | None = None

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        text = _clean(tag.get_text(" "))
        if href.startswith("mailto:") and not contact_email:
            contact_email = href.replace("mailto:", "").split("?", 1)[0]
            continue
        absolute = _safe_urljoin(url, href)
        if not absolute:
            continue
        link = ExtractedLink(url=absolute, text=text)
        links.append(link)
        haystack = f"{absolute} {text}".casefold()
        if any(domain in haystack for domain in SOCIAL_DOMAINS):
            social_links.append(absolute)
        if any(keyword in haystack for keyword in KEYWORDS):
            likely_links.append(link)

    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).casefold()
        kind = (tag.get("type") or "").casefold()
        if "alternate" in rel and ("rss" in kind or "atom" in kind or "xml" in kind):
            rss_url = _safe_urljoin(url, tag["href"])

    body_text = _clean(soup.get_text(" "))
    body_text_folded = (body_text or "").casefold()
    detected = sorted({keyword for keyword in KEYWORDS if keyword.replace("-", " ") in body_text_folded or keyword in body_text_folded})
    return CandidatePageAnalysis(
        url=url,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        links=links,
        likely_links=likely_links,
        rss_url=rss_url,
        contact_email=contact_email,
        social_links=sorted(set(social_links)),
        detected_keywords=detected,
        body_text=body_text[:5000] if body_text else None,
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def _safe_urljoin(base: str, href: str | None) -> str | None:
    if not href:
        return None
    try:
        return urljoin(base, href)
    except ValueError:
        return None
