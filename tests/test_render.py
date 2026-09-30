"""Markdown rendering and small formatting helpers."""
from dzdk.catalog import COLLECTIONS, filter_items
from dzdk.render import WIKI_LINK_PREFIX, bar, entry_markdown, fmt_date, item_markdown, status_tone
from tests.conftest import ENTRY, JOBS, SERVICES, SITE


def test_service_markdown():
    md = item_markdown(COLLECTIONS["services"], SERVICES[0], SITE)
    assert md.startswith("# Inua Advocacy\n")
    assert "*Advocacy · active · updated 2025-08-18 · Featured · Verified*" in md
    assert "[info@inua.org](mailto:info@inua.org)" in md
    assert "(tel:+265882717995)" in md
    assert "openstreetmap.org" in md
    assert f"({SITE}/services/inua-advocacy)" in md


def test_unverified_listing_is_flagged():
    item = dict(SERVICES[1], verified=False)
    assert "Unverified community listing" in item_markdown(COLLECTIONS["services"], item, SITE)


def test_job_markdown():
    md = item_markdown(COLLECTIONS["jobs"], JOBS[0], SITE)
    assert "- **Deadline:** 2026-04-27" in md
    assert "## Skills" in md


def test_entry_markdown_links():
    md = entry_markdown(ENTRY)
    assert "Also known as WASH." in md
    assert "- **Boreholes:** 12" in md
    assert "https://services.dzaleka.com/encyclopedia/dzaleka-refugee-camp" in md
    assert "1. [UNHCR report](https://unhcr.org/x), UNHCR" in md
    tui_md = entry_markdown(ENTRY, wiki_links=True)
    assert f"({WIKI_LINK_PREFIX}dzaleka-refugee-camp)" in tui_md


def test_filter_and_sort():
    services = COLLECTIONS["services"]
    assert [s["id"] for s in filter_items(SERVICES, services, sort_by="title", sort_order="desc")] == [
        "inua-advocacy", "dzaleka-health-centre"]
    assert filter_items(SERVICES, services, search="LEGAL")[0]["id"] == "inua-advocacy"
    assert filter_items(SERVICES, services, status="INACTIVE")[0]["id"] == "dzaleka-health-centre"


def test_helpers():
    assert fmt_date("2025-09-25T16:00:00.000Z", with_time=True) == "2025-09-25 16:00"
    assert fmt_date("30/09/2026") == "2026-09-30"
    assert fmt_date(None) == "—"
    assert bar(50, 100, 10) == "█████"
    assert bar(0, 100) == ""
    assert status_tone("Active") == "good"
    assert status_tone("past") == "muted"
    assert status_tone("weird") == "unknown"
