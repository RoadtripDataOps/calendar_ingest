import httpx

from music_calendar_finder.search.serpapi import SerpApiSearchProvider


def test_serpapi_parses_organic_results():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "organic_results": [
                    {"title": "Austin Music", "link": "https://example.com/events", "snippet": "Music calendar", "position": 1}
                ],
            },
        )

    provider = SerpApiSearchProvider(api_key="key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = provider.search("Austin TX music")
    assert response.api_status == "Success"
    assert response.results[0].link == "https://example.com/events"


def test_serpapi_retries_without_unsupported_location():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "Unsupported `Austin, TX, US` location - location parameter."})
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "organic_results": [{"title": "Austin Music", "link": "https://example.com/events"}],
            },
        )

    provider = SerpApiSearchProvider(api_key="key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = provider.search("Austin TX music", location="Austin, TX, US")
    assert response.api_status == "Success"
    assert len(calls) == 2
    assert "location=" in calls[0]
    assert "location=" not in calls[1]


def test_serpapi_dry_run_has_results():
    provider = SerpApiSearchProvider(dry_run=True)
    response = provider.search("Austin TX music calendar")
    assert response.api_status == "dry_run"
    assert len(response.results) >= 3


def test_serpapi_dry_run_sanitizes_site_queries():
    provider = SerpApiSearchProvider(dry_run=True)
    response = provider.search("site:.org Los Angeles CA arts events calendar")
    assert response.results[0].link.startswith("https://org-los-angelesmusic.org")
