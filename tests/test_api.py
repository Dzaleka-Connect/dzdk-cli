"""API client behaviour: headers, errors, rate limits, caching."""
import pytest
import requests
import responses

from dzdk import api as api_module
from dzdk.api import ApiError, DzdkClient, extract_items
from tests.conftest import API, SERVICES, collection_payload


@pytest.fixture
def client(tmp_path):
    return DzdkClient(API, cache_dir=tmp_path / "cache", cache_ttl=300)


@responses.activate
def test_sends_user_agent_and_api_version(client):
    responses.add(responses.GET, f"{API}/services", json=collection_payload("services", SERVICES))
    client.list_collection("services")
    headers = responses.calls[0].request.headers
    assert headers["User-Agent"].startswith("dzdk/")
    assert headers["API-Version"] == "1.0.0"


@responses.activate
def test_problem_json_becomes_api_error(client):
    responses.add(responses.GET, f"{API}/nope", status=404, json={
        "title": "Collection not found", "code": "collection_not_found",
        "detail": "No API endpoint at /api/nope.", "resolution": "Use the api-catalog."})
    with pytest.raises(ApiError) as info:
        client.get("/nope")
    assert info.value.status == 404
    assert info.value.code == "collection_not_found"
    assert info.value.resolution == "Use the api-catalog."


@responses.activate
def test_html_response_is_reported(client):
    responses.add(responses.GET, f"{API}/page", body="<html></html>", content_type="text/html")
    with pytest.raises(ApiError, match="web page"):
        client.get("/page")


@responses.activate
def test_rate_limit_headers_are_tracked(client):
    responses.add(responses.GET, f"{API}/status", json={"status": "ok"},
                  headers={"RateLimit-Limit": "60", "RateLimit-Remaining": "12", "RateLimit-Reset": "30"})
    client.status()
    assert (client.rate_limit.limit, client.rate_limit.remaining, client.rate_limit.reset) == (60, 12, 30)
    assert str(client.rate_limit) == "12/60 left, resets in 30s"


@responses.activate
def test_429_is_retried_after_waiting(client, monkeypatch):
    waits = []
    monkeypatch.setattr(api_module.time, "sleep", waits.append)
    responses.add(responses.GET, f"{API}/status", status=429, headers={"Retry-After": "3"}, json={})
    responses.add(responses.GET, f"{API}/status", json={"status": "ok"})
    assert client.status() == {"status": "ok"}
    assert waits == [3.0]


@responses.activate
def test_retry_wait_is_capped(client, monkeypatch):
    waits = []
    monkeypatch.setattr(api_module.time, "sleep", waits.append)
    for _ in range(3):
        responses.add(responses.GET, f"{API}/status", status=429, headers={"Retry-After": "600"},
                      json={"title": "Too many requests"})
    with pytest.raises(ApiError):
        client.status()
    assert waits == [api_module.MAX_RETRY_WAIT] * 2


@responses.activate
def test_responses_are_cached(client):
    responses.add(responses.GET, f"{API}/services", json=collection_payload("services", SERVICES))
    client.list_collection("services")
    client.list_collection("services")
    assert len(responses.calls) == 1
    client.list_collection("services", cache=False)
    assert len(responses.calls) == 2


@responses.activate
def test_network_error_without_cache(client):
    responses.add(responses.GET, f"{API}/services", body=requests.ConnectionError("down"))
    with pytest.raises(ApiError, match="Network error"):
        client.list_collection("services")


def test_get_item_not_found(client, monkeypatch):
    monkeypatch.setattr(client, "list_collection", lambda name: SERVICES)
    assert client.get_item("services", "inua-advocacy")["title"] == "Inua Advocacy"
    with pytest.raises(ApiError) as info:
        client.get_item("services", "missing")
    assert info.value.code == "not_found"


@pytest.mark.parametrize("payload, expected", [
    ({"data": {"services": [1]}}, [1]),
    ({"data": {"communityVoices": [2]}}, [2]),
    ({"data": {"other": [3]}}, [3]),
    ([4], [4]),
    ({"data": {"a": [1], "b": [2]}}, []),
    ("nonsense", []),
])
def test_extract_items(payload, expected):
    name = "community-voices" if expected == [2] else "services"
    assert extract_items(payload, name) == expected


def test_site_url(client):
    assert client.site_url == "https://services.dzaleka.com"
