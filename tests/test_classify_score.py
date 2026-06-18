from collections import Counter

from music_calendar_finder.classify import classify_source
from music_calendar_finder.models import SourceCandidate
from music_calendar_finder.score import score_source, should_stop_discovery


def make_source(**kwargs):
    data = {
        "city_id": 1,
        "root_domain": "visitaustin.org",
        "website_url": "https://visitaustin.org/",
        "title": "Visit Austin Events Calendar",
        "meta_description": "Live music, concerts, arts, festivals, and things to do in Austin.",
        "best_calendar_url": "https://visitaustin.org/events",
        "detected_keywords": ["events", "music", "calendar"],
        "body_text": "Austin TX upcoming events live music calendar submit event 2026.",
    }
    data.update(kwargs)
    return SourceCandidate(**data)


def test_classify_tourism():
    result = classify_source(make_source())
    assert result.source_category == "tourism_cvb"


def test_score_source_high_signal():
    source = make_source(source_category="tourism_cvb")
    score = score_source(source, {"city": "Austin", "state": "TX"}, Counter())
    assert score.total_score >= 70
    assert score.confidence in {"medium", "high"}


def test_stopping_rules():
    assert should_stop_discovery(
        queries_completed=20,
        candidate_domains=10,
        verified_sources=10,
        max_serpapi_queries=20,
        max_candidate_domains=100,
        max_verified_sources=50,
        verified_sources_target=25,
        low_yield_batches=0,
    )

