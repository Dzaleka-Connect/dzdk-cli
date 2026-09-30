"""Terminal UI tests driven through Textual's pilot."""
import asyncio

import pytest
from textual.widgets import DataTable, Input, Markdown, OptionList, Static, TabbedContent, Tree

from dzdk.api import DzdkClient
from dzdk.config import load_config
from dzdk.tui.app import DzdkApp, HelpScreen
from dzdk.tui.commands import DzdkCommands
from dzdk.tui.widgets import CollectionPane, EncyclopediaPane, Stat


def make_app(tab="home"):
    config = load_config()
    return DzdkApp(DzdkClient.from_config(config), dict(config), initial_tab=tab)


async def settle(pilot, seconds=0.3):
    await asyncio.sleep(seconds)
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def markdown_text(widget: Markdown) -> str:
    return widget.source


async def test_home_dashboard(api):
    app = make_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        assert "55,425" in str(app.query_one("#stat-pop", Stat).query_one(".stat-value").render())
        assert "18% funded" in str(app.query_one("#stat-funding", Stat).query_one(".stat-value").render())
        alerts = str(app.query_one("#home-alerts", Static).render())
        assert "Cholera outbreak" in alerts and "Strong winds" in alerts
        assert "Project Associate" in str(app.query_one("#home-jobs", Static).render())
        assert "Old Job" not in str(app.query_one("#home-jobs", Static).render())
        assert app.theme == "dzaleka"


async def test_services_tab_filter_and_detail(api):
    app = make_app("services")
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        pane = app.query_one("#services").query_one(CollectionPane)
        table = pane.query_one(DataTable)
        assert table.row_count == 2
        assert isinstance(app.focused, DataTable)
        assert "# Dzaleka Health Centre" in markdown_text(pane.query_one(Markdown))
        await pilot.press("down")
        await settle(pilot)
        assert "# Inua Advocacy" in markdown_text(pane.query_one(Markdown))
        await pilot.press("slash", *"legal")
        await settle(pilot)
        assert table.row_count == 1
        assert pane.current_url() == "https://services.dzaleka.com/services/inua-advocacy"


async def test_sort_cycles(api):
    app = make_app("jobs")
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        pane = app.query_one("#jobs").query_one(CollectionPane)
        assert "sorted by role" in pane.query_one(".sidebar").border_subtitle
        await pilot.press("s")
        await settle(pilot)
        assert "sorted by organization" in pane.query_one(".sidebar").border_subtitle
        assert [j["organization"] for j in pane.shown] == ["NGO", "UNHCR Malawi"]


async def test_encyclopedia_opens_entry(api):
    app = make_app("wiki")
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        pane = app.query_one(EncyclopediaPane)
        assert pane.query_one(OptionList).option_count == 1
        await settle(pilot)
        article = markdown_text(pane.query_one("#wiki-article", Markdown))
        assert "# Water and sanitation" in article
        assert "wiki:dzaleka-refugee-camp" in article


async def test_search_and_jump_to_item(api):
    app = make_app("search")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert isinstance(app.focused, Input)
        await pilot.press(*"legal", "enter")
        await settle(pilot, 0.6)
        tree = app.query_one(Tree)
        assert [str(n.label).split()[0] for n in tree.root.children] == ["Services", "Encyclopedia"]
        await pilot.press("down", "enter")
        await settle(pilot)
        assert app.query_one("#tabs", TabbedContent).active == "services"
        pane = app.query_one("#services").query_one(CollectionPane)
        assert pane.current["id"] == "inua-advocacy"


async def test_number_keys_switch_tabs(api):
    app = make_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("4")
        await pilot.pause()
        assert app.query_one("#tabs", TabbedContent).active == "wiki"
        await pilot.press("6")
        await pilot.pause()
        assert app.query_one("#tabs", TabbedContent).active == "jobs"
        await pilot.press("0")
        await pilot.pause()
        assert app.query_one("#tabs", TabbedContent).active == "search"


async def test_help_screen(api):
    app = make_app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_command_palette_finds_loaded_items(api):
    app = make_app("services")
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        provider = DzdkCommands(app.screen)
        hits = [hit async for hit in provider.search("inua")]
        assert any("Inua Advocacy" in str(hit.match_display) for hit in hits)
        hits = [hit async for hit in provider.search("zzzz")]
        assert not any("Inua" in str(hit.match_display) for hit in hits)


async def test_theme_choice_is_saved(api, config_home):
    app = make_app()
    async with app.run_test(size=(140, 45)) as pilot:
        app.theme = "dzaleka-light"
        await pilot.pause()
    assert load_config()["theme"] == "dzaleka-light"


async def test_api_error_is_shown(api):
    import responses as r
    from tests.conftest import API

    api.replace(r.GET, f"{API}/events", status=503, json={
        "title": "Service unavailable", "detail": "Maintenance.", "resolution": "Try later."})
    app = make_app("events")
    async with app.run_test(size=(140, 45)) as pilot:
        await settle(pilot)
        text = markdown_text(app.query_one("#events").query_one(Markdown))
        assert "Could not load data" in text and "Try later." in text


async def test_app_without_arguments_uses_saved_config(api):
    app = DzdkApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.client.base_url == "https://services.dzaleka.com/api"
        assert app.query_one("#tabs", TabbedContent).active == "home"


async def test_insights_charts_render(api):
    from dzdk.tui.charts import Chart, ChartPanel

    app = make_app("insights")
    async with app.run_test(size=(150, 50)) as pilot:
        await settle(pilot, 0.5)
        growth = app.query_one("#chart-population-growth", ChartPanel)
        assert growth.border_subtitle.startswith("now 55,425")
        assert "60k" in str(growth.query_one(Chart).render())
        # Switching group loads that group's data and draws its charts.
        app.query_one("#insight-groups", TabbedContent).active = "group-needs"
        await settle(pilot, 0.5)
        assert "18% funded" in app.query_one("#chart-funding", ChartPanel).border_subtitle
        assert "Aid distribution unrest" in str(app.query_one("#incidents", Static).render())
        assert app.query_one("#tabs", TabbedContent).active == "insights"


async def test_insights_failure_is_contained(api):
    import responses as r
    from tests.conftest import API
    from dzdk.tui.charts import ChartPanel

    api.replace(r.GET, f"{API}/charts", status=500, json={"title": "Server error"})
    app = make_app("insights")
    async with app.run_test(size=(150, 50)) as pilot:
        await settle(pilot, 0.5)
        assert "unavailable" in app.query_one("#chart-population-growth", ChartPanel).border_subtitle
        assert "% of residents" in app.query_one("#chart-nationalities", ChartPanel).border_subtitle


async def test_narrow_window_stacks_panes(api):
    app = make_app("services")
    async with app.run_test(size=(90, 30)) as pilot:
        await settle(pilot)
        assert app.has_class("-narrow")
        split = app.query_one("#services .split")
        assert split.styles.layout.name == "vertical"
        sidebar, detail = split.query_one(".sidebar"), split.query_one(".detail")
        assert sidebar.region.y < detail.region.y
        await pilot.resize_terminal(150, 45)
        await settle(pilot)
        assert not app.has_class("-narrow")
        assert split.styles.layout.name == "horizontal"
        assert sidebar.region.x < detail.region.x


async def test_sidebar_resize_is_saved(api, config_home):
    app = make_app("services")
    async with app.run_test(size=(150, 45)) as pilot:
        await settle(pilot)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.sidebar_width == 51
        for _ in range(10):
            await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.sidebar_width == 25
    assert load_config()["sidebar_width"] == 25


async def test_zoom_focused_pane(api):
    app = make_app("services")
    async with app.run_test(size=(150, 45)) as pilot:
        await settle(pilot)
        await pilot.press("z")
        await pilot.pause()
        zoomed = app.screen.maximized
        assert zoomed is not None and zoomed.has_class("sidebar")
        assert zoomed.region.width >= 148
        await pilot.press("z")
        await pilot.pause()
        assert app.screen.maximized is None
        assert app.query_one("#services .sidebar").region.width < 100


async def test_logo_switches_size(api):
    from dzdk.tui.logo import LOGO_MEDIUM, LOGO_SMALL
    from dzdk.tui.widgets import Logo

    app = make_app()
    async with app.run_test(size=(150, 45)) as pilot:
        await settle(pilot)
        logo = app.query_one(Logo)
        assert str(logo.render()) == LOGO_MEDIUM
        await pilot.resize_terminal(90, 28)
        await settle(pilot)
        assert str(logo.render()) == LOGO_SMALL
