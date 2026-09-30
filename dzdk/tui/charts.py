"""Insights tab: charts drawn with textual-plotext, grouped Dolphie-style."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Grid, Vertical, VerticalScroll
from textual.widgets import Static, TabbedContent, TabPane
from textual_plotext import PlotextPlot

from dzdk.api import ApiError
from dzdk.insights import CHARTS, GROUPS, ChartSpec, Palette, fetch_source, incidents
from dzdk.tui.widgets import DzdkPane, Pane, esc


def app_palette(app) -> Palette:
    theme = app.current_theme
    return Palette.from_hex(primary=theme.primary, muted=theme.secondary, warning=theme.warning,
                            error=theme.error, text=theme.foreground, background=theme.background)


class Chart(PlotextPlot):
    """A plotext chart that redraws itself when data arrives or the theme changes."""

    def __init__(self, spec: ChartSpec, **kwargs) -> None:
        super().__init__(**kwargs)
        self.spec = spec
        self.data: Optional[Dict[str, Any]] = None

    def on_mount(self) -> None:
        super().on_mount()
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.replot())

    def show(self, data: Dict[str, Any]) -> None:
        self.data = data
        self.replot()

    def render(self) -> Text:
        # Size the figure but skip PlotextPlot's theme call: replot() sets the
        # canvas to the app background so charts sit flush in their pane.
        self.plt.plotsize(self.size.width, self.size.height)
        self.plt._set_size(self.size.width, self.size.height)
        return Text.from_ansi(self.plt.build())

    def replot(self) -> None:
        if self.data is None:
            return
        self.plt.clear_figure()
        self.spec.draw(self.plt, self.data, app_palette(self.app))
        self.refresh()


class ChartPanel(Pane):
    """A titled pane holding one chart. Tab to it and press `z` to zoom it."""

    can_focus = True

    def __init__(self, spec: ChartSpec) -> None:
        super().__init__(title=spec.title, classes="chart-panel", id=f"chart-{spec.id}")
        self.spec = spec
        self.border_subtitle = "loading…"

    def compose(self) -> ComposeResult:
        yield Chart(self.spec)

    def show(self, data: Dict[str, Any]) -> None:
        try:
            self.query_one(Chart).show(data)
            self.border_subtitle = self.spec.subtitle(data)
        except Exception as error:  # a malformed series must not break the whole tab
            self.border_subtitle = f"could not draw: {error}"

    def fail(self, error: Exception) -> None:
        self.border_subtitle = f"unavailable: {error}"


class InsightsPane(DzdkPane):
    """Charts about the camp and the directory, loaded one group at a time."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.data: Dict[str, Any] = {}
        self.loaded_groups: set = set()

    def compose(self) -> ComposeResult:
        with TabbedContent(id="insight-groups"):
            for group in GROUPS:
                with TabPane(group, id=f"group-{group.lower()}"):
                    with VerticalScroll():
                        with Grid(classes="chart-grid"):
                            for spec in CHARTS:
                                if spec.group == group:
                                    yield ChartPanel(spec)
                            if group == "Needs":
                                with Pane(title="Major incidents", classes="chart-panel",
                                          id="incidents-panel") as panel:
                                    panel.border_subtitle = "timeline"
                                    yield Static("Loading…", id="incidents")

    def reload(self, force: bool = False) -> None:
        if force:
            self.data.clear()
            self.loaded_groups.clear()
        self.load_group(self.active_group(), force)

    def active_group(self) -> str:
        active = self.query_one("#insight-groups", TabbedContent).active or f"group-{GROUPS[0].lower()}"
        return next(g for g in GROUPS if f"group-{g.lower()}" == active)

    @on(TabbedContent.TabActivated, "#insight-groups")
    def group_activated(self, event: TabbedContent.TabActivated) -> None:
        event.stop()  # keep the app's top-level tab handler out of it
        if self.loaded:
            self.load_group(self.active_group())

    @work(group="insights", exclusive=False)
    async def load_group(self, group: str, force: bool = False) -> None:
        if group in self.loaded_groups and not force:
            return
        self.loaded_groups.add(group)
        specs = [s for s in CHARTS if s.group == group]
        needed: List[str] = list(dict.fromkeys(src for s in specs for src in s.sources))
        if group == "Needs" and "charts" not in needed:
            needed.append("charts")
        failures: Dict[str, Exception] = {}
        for name in needed:
            if name in self.data and not force:
                continue
            try:
                self.data[name] = await self.fetch(fetch_source, self.dzdk.client, name)
            except ApiError as error:
                failures[name] = error
        for spec in specs:
            panel = self.query_one(f"#chart-{spec.id}", ChartPanel)
            missing = [src for src in spec.sources if src in failures]
            if missing:
                panel.fail(failures[missing[0]])
            else:
                panel.show(self.data)
        if group == "Needs":
            self._show_incidents(failures.get("charts"))

    def _show_incidents(self, error: Optional[Exception]) -> None:
        target = self.query_one("#incidents", Static)
        if error:
            target.update(f"[$error]{esc(error)}[/]")
            return
        rows = incidents(self.data)
        target.update("\n".join(
            f"[dim]{esc(when):<9}[/] [$error]●[/] {esc(what)}" for when, what in rows)
            or "[dim]No incidents listed[/]")

    def focus_default(self) -> None:
        """Focus the first chart of the visible group, so Tab and `z` work straight away."""
        group = self.active_group().lower()
        panels = self.query(f"#group-{group} ChartPanel")
        if panels:
            panels.first().focus()

    def current_url(self) -> Optional[str]:
        return f"{self.dzdk.client.site_url}/datasets"
