from music_calendar_finder.dedupe import dedupe_search_results, normalize_url
from music_calendar_finder.models import SearchResult


def test_normalize_url_removes_tracking_and_fragment():
    parts = normalize_url("HTTP://Example.com/events/?utm_source=x&ok=1#top")
    assert parts.normalized_url == "http://example.com/events?ok=1"
    assert parts.grouping_url == "https://example.com/events?ok=1"
    assert parts.root_domain == "example.com"


def test_dedupe_limits_domain_and_marks_low_priority():
    results = [
        SearchResult(title="A", link="https://example.com/events"),
        SearchResult(title="B", link="https://example.com/music"),
        SearchResult(title="C", link="https://example.com/arts"),
        SearchResult(title="FB", link="https://facebook.com/local/events"),
    ]
    deduped = dedupe_search_results(results, per_domain_limit=2)
    assert len([row for row in deduped if row["root_domain"] == "example.com"]) == 2
    assert deduped[-1]["status"] == "low_priority"


def test_dedupe_skips_malformed_bracketed_hosts():
    results = [
        SearchResult(title="Bad", link="https://[gravityform id=13 title=true]"),
        SearchResult(title="Good", link="https://example.com/events"),
    ]
    deduped = dedupe_search_results(results)
    assert [row["source_url"] for row in deduped] == ["https://example.com/events"]
