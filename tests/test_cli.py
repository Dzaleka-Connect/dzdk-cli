"""CLI commands against a mocked API."""
import csv
import json
import re

import pytest
import requests
import responses
import yaml
from click.testing import CliRunner

from dzdk import cli
from tests.conftest import API


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(*args, **kwargs):
        return runner.invoke(cli, list(args), catch_exceptions=False, **kwargs)

    return invoke


def test_welcome_and_help(run):
    result = run()
    assert result.exit_code == 0
    assert "open the full-screen app" in result.output
    assert "get-help-now" in result.output
    assert "Usage:" in result.output


def test_version(run):
    assert "0.2.0" in run("--version").output


# ------------------------------------------------------------ collections


def test_services_list(run, api):
    result = run("services", "list")
    assert result.exit_code == 0
    assert "Inua Advocacy" in result.output
    assert "Dzaleka Health Centre" in result.output
    assert "2 services" in result.output


def test_services_list_filters(run, api):
    result = run("services", "list", "--search", "legal")
    assert "Inua Advocacy" in result.output
    assert "Health Centre" not in result.output
    result = run("services", "list", "--status", "inactive")
    assert "Health Centre" in result.output and "Inua" not in result.output
    result = run("services", "list", "--category", "health")
    assert "Health Centre" in result.output and "Inua" not in result.output


def test_services_list_json_and_categories(run, api):
    data = json.loads(run("services", "list", "--json").output)
    assert [s["id"] for s in data] == ["dzaleka-health-centre", "inua-advocacy"]
    assert run("services", "list", "--categories").output.split() == ["Advocacy", "Health"]


def test_services_list_no_matches(run, api):
    result = run("services", "list", "--search", "zzz")
    assert "No services match" in result.output


def test_services_get(run, api):
    for args in (("--id", "inua-advocacy"), ("inua-advocacy",)):
        result = run("services", "get", *args)
        assert result.exit_code == 0
        assert "Inua Advocacy" in result.output
        assert "info@inua.org" in result.output
        assert "Verified" in result.output


def test_services_get_not_found(run, api):
    result = run("services", "get", "--id", "nope")
    assert result.exit_code == 1
    assert "No services item with id 'nope'" in result.output
    assert "dzdk services list" in result.output


@pytest.mark.parametrize("name, expected", [
    ("events", "Faith and Refugees"),
    ("jobs", "Project Associate"),
    ("news", "Introducing the"),
    ("resources", "Annual Report"),
    ("photos", "Cardboard Collection"),
])
def test_other_collections(run, api, name, expected):
    result = run(name, "list")
    assert result.exit_code == 0
    assert expected in result.output


def test_job_detail(run, api):
    result = run("jobs", "get", "project-associate")
    assert "UNHCR Malawi" in result.output
    assert "Protection" in result.output
    assert "jobs@unhcr.org" in result.output


def test_browse(run, api):
    assert "courses" in run("browse").output
    result = run("browse", "courses")
    assert "Python 101" in result.output
    assert run("browse", "not-a-collection").exit_code == 2


# ----------------------------------------------------------------- search


def test_search_uses_search_endpoint(run, api):
    result = run("search", "legal", "--type", "services")
    assert result.exit_code == 0
    assert "Inua Advocacy" in result.output
    call = [c for c in api.calls if "/search" in c.request.url][0]
    assert "q=legal" in call.request.url and "collections=services" in call.request.url


def test_search_legacy_query_option(run, api):
    result = run("search", "--query", "legal")
    assert "2 results" in result.output


def test_search_requires_query(run, api):
    assert run("search").exit_code == 2


# ----------------------------------------------------------- encyclopedia


def test_wiki_get(run, api):
    result = run("wiki", "get", "water-and-sanitation")
    assert result.exit_code == 0
    assert "Water and sanitation" in result.output
    assert "Boreholes" in result.output
    assert "UNHCR report" in result.output


def test_wiki_alias_and_list(run, api):
    result = run("encyclopedia", "list")
    assert "Water and sanitation" in result.output
    assert "1 entries" in result.output


def test_wiki_missing_suggests(run, api):
    result = run("wiki", "get", "missing")
    assert result.exit_code == 1
    assert "Did you mean" in result.output
    assert "water-and-sanitation" in result.output


def test_wiki_categories(run, api):
    assert "Infrastructure" in run("wiki", "categories").output


# ------------------------------------------------------------- dashboards


def test_population_stats(run, api):
    result = run("population", "stats")
    assert "55,425" in result.output
    assert "Burundi" in result.output
    assert "2024" in result.output


def test_alerts(run, api):
    result = run("alerts")
    assert "Cholera outbreak" in result.output
    assert "Strong winds" in result.output
    assert "get-help-now" in result.output


def test_weather(run, api):
    assert "Partly Cloudy" in run("weather").output


def test_stats(run, api):
    assert "Category Distribution" in run("stats", "services").output
    result = run("stats", "overview")
    assert "UNHCR Malawi funding" in result.output


def test_status_and_mcp(run, api):
    assert "1.0.0" in run("status").output
    result = run("mcp")
    assert "search_dzaleka" in result.output
    assert "claude mcp add --transport http dzaleka" in result.output


# ----------------------------------------------------------------- health


def test_health_ok(run, api):
    result = run("health")
    assert result.exit_code == 0
    assert "API Health Check" in result.output
    assert "All endpoints are healthy" in result.output


def test_health_failure(run):
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, re.compile(f"{API}/.*"),
                 body=requests.ConnectionError("Network error"))
        result = run("health")
    assert result.exit_code == 1
    assert "Some endpoints are not responding" in result.output


# ------------------------------------------------------------------ errors


def test_problem_json_error_is_readable(run):
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, f"{API}/services", status=429, json={
            "title": "Too many requests", "code": "rate_limited",
            "detail": "Slow down.", "resolution": "Wait 30 seconds."},
            headers={"Retry-After": "0"})
        result = run("services", "list")
    assert result.exit_code == 1
    assert "Too many requests" in result.output
    assert "Wait 30 seconds." in result.output
    assert "rate_limited" in result.output


def test_offline_fallback_uses_stale_cache(run, api, config_home):
    run("config", "--cache-ttl", "1")
    assert "Inua Advocacy" in run("services", "list").output
    # Age the cache, then take the network away.
    for path in (config_home / "cache").glob("*.json"):
        entry = json.loads(path.read_text())
        entry["t"] -= 3600
        path.write_text(json.dumps(entry))
    api.replace(responses.GET, f"{API}/services", body=requests.ConnectionError("down"))
    result = run("services", "list")
    assert "Inua Advocacy" in result.output
    assert "Offline" in result.output


def test_no_cache_flag_bypasses_cache(run, api):
    run("services", "list")
    run("--no-cache", "services", "list")
    assert len([c for c in api.calls if c.request.url.endswith("/services")]) == 2


# ----------------------------------------------------------------- config


def test_config_direct(run, config_home):
    result = run("config", "--url", "direct-api.com", "--timeout", "60")
    assert "Configuration updated successfully" in result.output
    saved = yaml.safe_load((config_home / "config.yaml").read_text())
    assert saved["api_url"] == "https://direct-api.com/api"
    assert saved["timeout"] == 60


def test_config_interactive(run, config_home):
    result = run("config", "--interactive", input="https://new-api.com\n45\n")
    assert "Configuration has been updated successfully" in result.output
    assert yaml.safe_load((config_home / "config.yaml").read_text())["timeout"] == 45


def test_show_config(run):
    result = run("show-config")
    assert "Current Configuration" in result.output
    assert "services.dzaleka.com/api" in result.output
    assert "Current Configuration" in run("show_config").output


def test_invalid_config(run, config_home):
    config_home.mkdir(parents=True)
    (config_home / "config.yaml").write_text("api_url: [unclosed")
    result = CliRunner().invoke(cli, ["show-config"])
    assert result.exit_code == 1
    assert "Error reading" in result.output


def test_clear_cache(run, api):
    run("services", "list")
    assert "Removed 1 cached" in run("config", "--clear-cache").output


# ----------------------------------------------------------- files/export


def test_fetch_resource(run, api, tmp_path):
    out = tmp_path / "report.pdf"
    result = run("resources", "fetch", "--id", "annual-report", "--output", str(out))
    assert result.exit_code == 0
    assert "Resource successfully saved" in result.output
    assert out.read_bytes() == b"%PDF-1.4 test"


def test_batch_download(run, api, tmp_path):
    result = run("batch", "download", "--type", "photos", "--ids", "cardboard,missing",
                 "--output-dir", str(tmp_path / "dl"))
    assert "Download Complete" in result.output
    assert "1 of 2 files" in result.output
    assert (tmp_path / "dl" / "Cardboard Collection.jpg").read_bytes() == b"JPEGDATA"


def test_export_csv(run, api, tmp_path):
    out = tmp_path / "services.csv"
    result = run("export", "csv", "--type", "services", "--output", str(out))
    assert "2 rows exported" in result.output
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["contact_email"] == "info@inua.org"
    assert rows[0]["location_coordinates_lat"] == "-13.66"


def test_export_report_and_json(run, api, tmp_path):
    report = tmp_path / "jobs.md"
    run("export", "report", "--type", "jobs", "--output", str(report))
    assert "## Project Associate" in report.read_text()
    out = tmp_path / "wiki.json"
    run("export", "json", "--type", "encyclopedia", "--output", str(out))
    assert json.loads(out.read_text())[0]["id"] == "water-and-sanitation"


def test_export_all_single_request(run, api, tmp_path):
    out = tmp_path / "all.json"
    result = run("export", "all", "-o", str(out), "--collections", "services,jobs")
    assert "services: 2" in result.output
    assert set(json.loads(out.read_text())) == {"services", "jobs"}
    body = json.loads([c for c in api.calls if c.request.url.endswith("/export")][0].request.body)
    assert body == {"collections": ["services", "jobs"]}


def test_chart_list_and_draw(run, api):
    assert "population-growth" in run("chart", "--list").output
    result = run("chart", "population-growth", "--width", "60")
    assert result.exit_code == 0
    assert "Camp population" in result.output and "60k" in result.output
    result = run("chart", "-g", "needs", "--width", "60")
    assert "Service capacity" in result.output and "Aid distribution unrest" in result.output
    assert run("chart", "nope").exit_code == 2
