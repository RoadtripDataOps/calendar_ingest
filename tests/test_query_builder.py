from music_calendar_finder.models import CityDiscoveryBudget
from music_calendar_finder.query_builder import build_search_queries


def budget(limit=30):
    return CityDiscoveryBudget(
        top_sources_target=25,
        verified_sources_target=25,
        max_verified_sources=50,
        max_candidate_domains=100,
        max_serpapi_queries=limit,
        max_query_pages=1,
        should_expand_metro_queries=True,
    )


def test_queries_for_austin():
    queries = build_search_queries({"city": "Austin", "state": "TX"}, budget(5))
    assert queries[0] == "Austin TX live music calendar"
    assert len(queries) == 5


def test_queries_include_metro_templates():
    queries = build_search_queries({"city": "Los Angeles", "state": "CA", "metro_name": "Greater Los Angeles"}, budget(30))
    assert "Greater Los Angeles music calendar" in queries


def test_queries_unknown_state_do_not_double_space():
    queries = build_search_queries({"city": "Paris"}, budget(3))
    assert queries[0] == "Paris live music calendar"
    assert all("  " not in query for query in queries)

