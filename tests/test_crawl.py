import httpx

from music_calendar_finder.crawl.fetcher import PageFetcher
from music_calendar_finder.crawl.link_extractor import analyze_html
from music_calendar_finder.crawl.robots import RobotsChecker


def test_robots_checker_fail_closed_and_allow():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    checker = RobotsChecker(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert checker.can_fetch("https://example.com/events") is True
    assert checker.can_fetch("https://example.com/private/page") is False


def test_link_extractor_finds_calendar_links():
    html = """
    <html><head><title>Austin Arts</title><meta name="description" content="Music and events">
    <link rel="alternate" type="application/rss+xml" href="/feed.xml"></head>
    <body><a href="/events">Events Calendar</a><a href="mailto:info@example.com">Email</a>
    <a href="https://instagram.com/example">Instagram</a></body></html>
    """
    analysis = analyze_html("https://example.com", html)
    assert analysis.title == "Austin Arts"
    assert analysis.rss_url == "https://example.com/feed.xml"
    assert analysis.contact_email == "info@example.com"
    assert analysis.likely_links[0].url == "https://example.com/events"


def test_link_extractor_handles_empty_body():
    analysis = analyze_html("https://example.com", "<html><head></head><body></body></html>")
    assert analysis.detected_keywords == []
    assert analysis.body_text is None


def test_link_extractor_skips_malformed_bracketed_shortcode_links():
    html = """
    <html><body>
    <a href="//[gravityform id=13 title=true]">Events</a>
    <a href="/events">Events Calendar</a>
    </body></html>
    """
    analysis = analyze_html("https://example.com", html)
    assert [link.url for link in analysis.likely_links] == ["https://example.com/events"]
