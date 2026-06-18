import httpx

from music_calendar_finder.validation import UrlValidationContext, UrlValidator, is_synthetic_url, is_verified_url_eligible


def test_synthetic_url_detection_for_bad_austin_patterns():
    assert is_synthetic_url("https://austin-tx-altarts.org/calendar", city="Austin", state="TX")
    assert is_synthetic_url("https://austin-tx-altmusic.org/events", city="Austin", state="TX")
    assert is_synthetic_url("https://visitaustin-tx-newspaper.com/events", city="Austin", state="TX")
    assert not is_synthetic_url("https://www.austinchronicle.com/events/", city="Austin", state="TX")


def test_malformed_bracketed_host_is_invalid_not_exception():
    validator = UrlValidator(client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))))
    result = validator.validate("https://[gravityform id=13 title=true]")
    assert result.url_validation_status == "invalid_url"


def test_url_validation_status_mapping_and_redirect():
    def handler(request):
        path = request.url.path
        if path == "/ok":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><title>OK</title></html>")
        if path == "/redirect":
            return httpx.Response(302, headers={"location": "https://example.com/ok"})
        if path == "/forbidden":
            return httpx.Response(403, headers={"content-type": "text/html"}, text="Forbidden")
        if path == "/missing":
            return httpx.Response(404, headers={"content-type": "text/html"}, text="Missing")
        if path == "/pdf":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        return httpx.Response(500)

    validator = UrlValidator(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    ok = validator.validate("https://example.com/ok")
    redirect = validator.validate("https://example.com/redirect")
    forbidden = validator.validate("https://example.com/forbidden")
    missing = validator.validate("https://example.com/missing")
    pdf = validator.validate("https://example.com/pdf")
    synthetic = validator.validate("https://austin-tx-altarts.org/calendar", UrlValidationContext(city="Austin", state="TX"))
    assert ok.url_validation_status == "valid"
    assert ok.page_title == "OK"
    assert redirect.url_validation_status == "redirect_valid"
    assert redirect.final_url == "https://example.com/ok"
    assert forbidden.url_validation_status == "forbidden_but_real"
    assert missing.url_validation_status == "http_error"
    assert pdf.url_validation_status == "unsupported_content_type"
    assert synthetic.url_validation_status == "synthetic_rejected"


def test_dns_and_timeout_mapping():
    def dns_handler(request):
        raise httpx.ConnectError("[Errno 8] nodename nor servname provided")

    def timeout_handler(request):
        raise httpx.ReadTimeout("timed out")

    dns = UrlValidator(client=httpx.Client(transport=httpx.MockTransport(dns_handler)))
    timeout = UrlValidator(client=httpx.Client(transport=httpx.MockTransport(timeout_handler)))
    assert dns.validate("https://missing.example").url_validation_status == "dns_error"
    assert timeout.validate("https://slow.example").url_validation_status == "timeout"


def test_verified_requirements():
    assert is_verified_url_eligible("live", "serpapi_organic", "valid")
    assert not is_verified_url_eligible("dry_run", "dry_run_fixture", "valid")
    assert not is_verified_url_eligible("live", "dry_run_fixture", "valid")
    assert not is_verified_url_eligible("live", "serpapi_organic", "timeout")
