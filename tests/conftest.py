"""Shared fixtures: an isolated config dir and a mocked Dzaleka API."""
import pytest
import responses

SITE = "https://services.dzaleka.com"
API = f"{SITE}/api"
RATE = {"RateLimit-Limit": "60", "RateLimit-Remaining": "59", "RateLimit-Reset": "60"}

SERVICES = [
    {
        "id": "inua-advocacy", "title": "Inua Advocacy", "category": "Advocacy", "status": "active",
        "description": "Legal aid and advocacy for refugees.", "featured": True, "verified": True,
        "contact": {"email": "info@inua.org", "phone": "+265 882 717995", "hours": "Mon-Fri"},
        "socialMedia": {"website": "https://www.inuaadvocacy.org", "facebook": "https://fb.com/inua"},
        "location": {"address": "Dzaleka Refugee Camp", "city": "Dowa",
                     "coordinates": {"lat": -13.66, "lng": 33.87}},
        "lastUpdated": "2025-08-18T00:00:00.000Z",
    },
    {
        "id": "dzaleka-health-centre", "title": "Dzaleka Health Centre", "category": "Health",
        "status": "inactive", "description": "Primary health care.",
        "contact": {"email": "", "phone": ""}, "socialMedia": {}, "location": {},
    },
]
EVENTS = [{"id": "faith-talk", "title": "Faith and Refugees", "date": "2025-09-25T16:00:00.000Z",
           "endDate": "2025-09-25T17:00:00.000Z", "location": "Online", "category": "Advocacy",
           "status": "past", "organizer": "Inua", "tags": ["faith"],
           "registration": {"required": True, "url": "https://example.org/register"},
           "contact": {"email": "events@inua.org"}}]
JOBS = [
    {"id": "project-associate", "title": "Project Associate", "organization": "UNHCR Malawi",
     "type": "full-time", "category": "community", "deadline": "2026-04-27T00:00:00.000Z",
     "posted": "2026-04-22T00:00:00.000Z", "status": "open", "skills": ["Protection"],
     "contact": {"email": "jobs@unhcr.org"}, "description": "Oversee protection programmes."},
    {"id": "old-job", "title": "Old Job", "organization": "NGO", "status": "closed",
     "deadline": "2024-01-01T00:00:00.000Z"},
]
NEWS = [{"id": "encyclopedia-launch", "title": "Introducing the Dzaleka Encyclopedia",
         "date": "2026-07-13T00:00:00.000Z", "category": "Announcements", "author": "Team",
         "description": "A sourced reference work."}]
RESOURCES = [{"id": "annual-report", "title": "Annual Report", "category": "Reports",
              "author": "Test Author", "date": "2024-03-20T00:00:00Z", "fileType": "pdf",
              "fileSize": "1 MB", "downloadUrl": "https://files.example.org/report.pdf",
              "lastUpdated": "2024-03-21T00:00:00Z", "languages": ["English"]}]
PHOTOS = [{"id": "cardboard", "title": "Cardboard Collection", "date": "2023-10-15T00:00:00.000Z",
           "image": "https://img.example.org/cardboard.jpg", "location": "Dzaleka",
           "photographer": {"name": "Carlos Martinez"}, "tags": ["UNHCR"]}]
ENTRY = {
    "id": "water-and-sanitation", "title": "Water and sanitation", "category": "Infrastructure",
    "entryType": "topic", "status": "reviewed", "summary": "How water reaches the camp.",
    "url": f"{SITE}/encyclopedia/water-and-sanitation", "aliases": ["WASH"],
    "facts": [{"label": "Boreholes", "value": "12"}], "body": "## Supply\n\nBoreholes and taps.",
    "relatedEntries": ["dzaleka-refugee-camp"], "lastReviewed": "2026-07-13T00:00:00.000Z",
    "sources": [{"title": "UNHCR report", "publisher": "UNHCR", "url": "https://unhcr.org/x"}],
}
POPULATION = {"total": 55425, "newArrivals": 304,
              "demographics": {"women": 45, "children": 48, "men": 7},
              "nationalities": {"DRC": 64.9, "Burundi": 21.9},
              "trends": {"labels": ["2019", "2024"], "values": [40000, 55425]}}
CHARTS_PAYLOAD = {"population": {
    "historical": {"labels": ["1994", "2010", "2024"], "values": [12000, 35000, 60000]},
    "challenges": {"labels": ["Overcrowding", "Healthcare Access"], "values": [95, 70]},
    "services": {"labels": ["Education", "Water"], "capacity": [45, 60]},
    "incidents": {"labels": ["Nov 2022"], "events": ["Aid distribution unrest"]},
}}
SEARCH = {"status": "success", "query": "legal", "totalResults": 2, "results": {
    "services": [{"slug": "inua-advocacy", "title": "Inua Advocacy", "description": "Legal aid",
                  "collection": "services", "url": f"{SITE}/services/inua-advocacy"}],
    "encyclopedia": [{"slug": "water-and-sanitation", "title": "Water and sanitation",
                      "description": "Water", "collection": "encyclopedia",
                      "url": f"{SITE}/encyclopedia/water-and-sanitation"}],
}}


def collection_payload(name, items):
    return {"status": "success", "count": len(items), "data": {name: items}}


@pytest.fixture(autouse=True)
def config_home(monkeypatch, tmp_path):
    """Every test gets its own config and cache directory."""
    monkeypatch.setenv("DZDK_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path / "config"


@pytest.fixture
def api():
    """Mock every endpoint the CLI and TUI use."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        def add(path, body, method=responses.GET, **kwargs):
            mock.add(method, f"{API}{path}", json=body, headers=RATE, **kwargs)

        for name, items in [("services", SERVICES), ("events", EVENTS), ("jobs", JOBS),
                            ("news", NEWS), ("resources", RESOURCES), ("photos", PHOTOS),
                            ("courses", [{"id": "python-101", "title": "Python 101",
                                          "category": "Tech"}])]:
            add(f"/{name}", collection_payload(name, items))
        add("/encyclopedia", {"status": "success", "data": {"entries": [ENTRY]},
                              "meta": {"total": 1, "page": 1, "perPage": 100, "totalPages": 1}})
        add("/encyclopedia/water-and-sanitation", {"status": "success", "data": {"entry": ENTRY}})
        add("/encyclopedia/suggest", {"status": "success", "data": {"suggestions": [
            {"id": "water-and-sanitation", "title": "Water and sanitation", "category": "Infrastructure"}]}})
        add("/encyclopedia/facets", {"status": "success", "data": {
            "categories": {"Infrastructure": 1}, "entryTypes": {"topic": 1}, "statuses": {"reviewed": 1}}})
        mock.add(responses.GET, f"{API}/encyclopedia/missing", status=404, headers=RATE, json={
            "title": "Entry not found", "status": 404, "code": "entry_not_found",
            "detail": "No encyclopedia entry 'missing'.", "resolution": "Use /api/encyclopedia/suggest."})
        add("/search", SEARCH)
        add("/population", POPULATION)
        add("/charts", CHARTS_PAYLOAD)
        add("/alerts", [{"id": 1, "type": "critical", "title": "Cholera outbreak",
                         "message": "Boil water.", "date": "2025-12-30T00:00:00Z"}])
        add("/weather-alerts", [{"title": "Strong winds", "description": "Mwera winds.",
                                 "type": "warning", "publishedAt": "2026-08-19T09:20:00.000Z"}])
        add("/weather", {"location": "Dowa District", "date": "30/09/2026", "sourceLabel": "MET Malawi",
                         "forecast": {"current": {"temperature": "20.6", "condition": "Partly Cloudy",
                                                  "rainfall": "6.1", "windSpeed": "10", "time": "17:00"},
                                      "hourly": [{"time": "18:00", "condition": "Clear", "maxTemp": "19"}]}})
        add("/finance", {"budget": 26300000, "funded": 4679887, "gap": 21620113,
                         "lastUpdated": "2025-07-31T00:00:00Z", "source": "https://reporting.unhcr.org"})
        add("/status", {"status": "ok", "version": "1.0.0", "apiBase": API,
                        "mcp": f"{SITE}/.well-known/mcp", "documentation": f"{SITE}/api-docs"})
        add("/export", {"status": "success", "data": {"services": SERVICES, "jobs": JOBS}},
            method=responses.POST)
        mock.add(responses.GET, f"{SITE}/mcp", headers=RATE, json={
            "serverInfo": {"title": "Dzaleka MCP"}, "documentationUrl": f"{SITE}/docs",
            "transports": [{"type": "streamable-http", "endpoint": f"{SITE}/.well-known/mcp"}],
            "tools": [{"name": "search_dzaleka", "description": "Full-text search."}]})
        mock.add(responses.GET, "https://files.example.org/report.pdf", body=b"%PDF-1.4 test",
                 headers={"content-length": "13"})
        mock.add(responses.GET, "https://img.example.org/cardboard.jpg", body=b"JPEGDATA")
        yield mock
