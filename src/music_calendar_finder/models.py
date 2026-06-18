from __future__ import annotations

from pydantic import BaseModel, Field


class CityRecord(BaseModel):
    id: int | None = None
    city: str
    state: str | None = None
    state_name: str | None = None
    country: str = "US"
    metro_name: str | None = None
    county: str | None = None
    population: int | None = None
    lat: float | None = None
    lng: float | None = None
    original_row_id: str | None = None
    city_tier: str | None = None
    priority: int = 0
    priority_level: int | None = None
    priority_reason: str | None = None
    enabled: bool = True
    source_row_number: int | None = None
    import_batch_id: str | None = None
    status: str = "pending"


class CityDiscoveryBudget(BaseModel):
    top_sources_target: int
    verified_sources_target: int
    max_verified_sources: int
    max_candidate_domains: int
    max_serpapi_queries: int
    max_query_pages: int
    should_expand_metro_queries: bool = False


class SearchResult(BaseModel):
    title: str | None = None
    link: str
    displayed_link: str | None = None
    snippet: str | None = None
    position: int | None = None
    source: str | None = None
    url_origin: str = "serpapi_organic"


class SearchResponse(BaseModel):
    query: str
    page: int = 1
    provider: str
    results: list[SearchResult] = Field(default_factory=list)
    api_status: str | None = None
    raw: dict | None = None


class UrlParts(BaseModel):
    original_url: str
    normalized_url: str
    grouping_url: str
    domain: str
    root_domain: str
    path: str
    is_low_priority: bool = False


class FetchResult(BaseModel):
    url: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    html: str | None = None
    error: str | None = None


class UrlValidationResult(BaseModel):
    url: str
    url_validation_status: str
    http_status: int | None = None
    final_url: str | None = None
    resolved_domain: str | None = None
    content_type: str | None = None
    page_title: str | None = None
    validation_error: str | None = None
    validated_at: str | None = None


class ExtractedLink(BaseModel):
    url: str
    text: str | None = None
    kind: str = "link"


class CandidatePageAnalysis(BaseModel):
    url: str
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    links: list[ExtractedLink] = Field(default_factory=list)
    likely_links: list[ExtractedLink] = Field(default_factory=list)
    rss_url: str | None = None
    contact_email: str | None = None
    social_links: list[str] = Field(default_factory=list)
    detected_keywords: list[str] = Field(default_factory=list)
    body_text: str | None = None


class ClassificationResult(BaseModel):
    source_category: str
    secondary_tags: list[str] = Field(default_factory=list)
    confidence: str = "low"


class ScoreResult(BaseModel):
    local_relevance_score: float = 0
    music_signal_score: float = 0
    calendar_signal_score: float = 0
    authority_score: float = 0
    freshness_score: float = 0
    diversity_score: float = 0
    total_score: float = 0
    confidence: str = "low"
    why_selected: str = ""


class SourceCandidate(BaseModel):
    city_id: int
    run_id: int | None = None
    root_domain: str
    source_name: str | None = None
    source_category: str | None = None
    website_url: str
    best_calendar_url: str | None = None
    music_url: str | None = None
    events_url: str | None = None
    arts_url: str | None = None
    tourism_url: str | None = None
    about_url: str | None = None
    rss_url: str | None = None
    contact_email: str | None = None
    social_links: list[str] = Field(default_factory=list)
    title: str | None = None
    meta_description: str | None = None
    detected_keywords: list[str] = Field(default_factory=list)
    robots_allowed: bool | None = None
    crawl_status: str | None = None
    error_message: str | None = None
    search_query: str | None = None
    body_text: str | None = None
    run_mode: str = "live"
    url_origin: str = "serpapi_organic"
    url_validation_status: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    resolved_domain: str | None = None
    content_type: str | None = None
    page_title: str | None = None
    validation_error: str | None = None
    validated_at: str | None = None
