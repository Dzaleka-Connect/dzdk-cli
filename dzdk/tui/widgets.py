"""Widgets for the dzdk terminal UI."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import DataTable, Input, Label, Markdown, OptionList, Select, Sparkline, Static, Tree
from textual.widgets.option_list import Option

from dzdk.api import ApiError, item_id
from dzdk.catalog import COLLECTIONS, Collection, categories, filter_items, title_of
from dzdk.tui.logo import LOGO_COLOR, LOGO_MEDIUM, LOGO_SMALL
from dzdk.render import NA, bar, cell_text, entry_markdown, fmt_date, item_markdown, status_tone

if TYPE_CHECKING:
    from dzdk.tui.app import DzdkApp

GET_HELP_URL = "https://services.dzaleka.com/get-help-now"


def esc(value: Any) -> str:
    """Escape text for Textual content markup."""
    return Content(str(value)).markup


def error_markdown(error: Exception) -> str:
    text = f"# Could not load data\n\n{error}\n"
    if isinstance(error, ApiError):
        if error.detail:
            text += f"\n{error.detail}\n"
        if error.resolution:
            text += f"\n**How to fix:** {error.resolution}\n"
    return text + "\nPress **r** to try again."


def truncate(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Logo(Static):
    """The Dzaleka Online Services logo, drawn in quadrant blocks.

    Shows the medium rendering, or the small one when the app is in its
    compact layout (see DzdkApp.apply_layout).
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(LOGO_MEDIUM, **kwargs)
        self.styles.color = LOGO_COLOR

    def set_compact(self, compact: bool) -> None:
        self.update(LOGO_SMALL if compact else LOGO_MEDIUM)


class Stat(Vertical):
    """A small label / value / note block for the home screen."""

    def __init__(self, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.label = label

    def compose(self) -> ComposeResult:
        yield Label(self.label, classes="stat-label")
        yield Label("…", classes="stat-value")
        yield Label("", classes="stat-note")

    def set(self, value: str, note: str = "") -> None:
        self.query_one(".stat-value", Label).update(value)
        self.query_one(".stat-note", Label).update(note)


class Pane(Vertical):
    """A bordered pane with its title set into the border, Harlequin-style.

    Panes can be zoomed to fill the screen (`z`), so they opt in to maximizing.
    """

    ALLOW_MAXIMIZE = True

    def __init__(self, *children, title: str = "", **kwargs) -> None:
        kwargs["classes"] = f"pane {kwargs.get('classes', '')}".strip()
        super().__init__(*children, **kwargs)
        self.border_title = title


class ScrollPane(VerticalScroll):
    """A scrolling Pane."""

    ALLOW_MAXIMIZE = True

    def __init__(self, *children, title: str = "", **kwargs) -> None:
        kwargs["classes"] = f"pane {kwargs.get('classes', '')}".strip()
        super().__init__(*children, **kwargs)
        self.border_title = title


class Section(Pane):
    """A titled pane on the Home tab."""

    def __init__(self, title: str, *children, **kwargs) -> None:
        super().__init__(*children, title=title, **kwargs)


class DzdkPane(Container):
    """Base class for tab contents. Loads lazily the first time it is shown."""

    loaded = False

    @property
    def dzdk(self) -> "DzdkApp":
        return self.app  # type: ignore[return-value]

    def activate(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.reload()

    def reload(self, force: bool = False) -> None:  # pragma: no cover - overridden
        pass

    def focus_search(self) -> None:
        inputs = self.query(Input)
        if inputs:
            inputs.first().focus()

    def focus_default(self) -> None:
        """Focus the pane's main list when its tab is shown."""

    def current_url(self) -> Optional[str]:
        return None

    async def fetch(self, func, *args, **kwargs):
        """Run a blocking client call off the event loop and refresh the status line."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        finally:
            self.dzdk.update_status()


# --------------------------------------------------------------------- home


class HomePane(DzdkPane):
    """Overview: key numbers, alerts, latest news, open jobs."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="home"):
            with Horizontal(id="masthead"):
                yield Logo(id="logo")
                with Vertical(id="masthead-text"):
                    yield Label("Dzaleka Online Services", id="masthead-title")
                    yield Label("Directory, news and open data for Dzaleka Refugee Camp, "
                                "Dowa District, Malawi", id="masthead-sub")
                    yield Static(f"[b $error]Urgent help[/]  [@click=app.open_link('{GET_HELP_URL}')]"
                                 "services.dzaleka.com/get-help-now[/]", id="urgent")
                    yield Static("[dim]Press [/]F1[dim] for help · [/]Ctrl+P[dim] to jump anywhere · "
                                 "[/]2[dim] for charts[/]", id="masthead-hint")
            with Horizontal(id="stats"):
                yield Stat("Population", id="stat-pop")
                yield Stat("New arrivals", id="stat-arrivals")
                yield Stat("Funding", id="stat-funding")
                yield Stat("Weather, Dowa", id="stat-weather")
            with Horizontal(classes="home-row"):
                yield Section("Alerts", Static("Loading…", id="home-alerts"), id="sec-alerts")
                yield Section("Latest news", Static("Loading…", id="home-news"), id="sec-news")
            with Horizontal(classes="home-row"):
                yield Section("Open jobs", Static("Loading…", id="home-jobs"), id="sec-jobs")
                with Section("Population", id="sec-population"):
                    yield Static("", id="nationalities")
                    yield Sparkline([], id="trend")
                    yield Label("", id="trend-label")
            yield Static("", id="api-line")

    def reload(self, force: bool = False) -> None:
        self.load_population()
        self.load_funding()
        self.load_weather()
        self.load_alerts()
        self.load_news()
        self.load_jobs()
        self.load_api()

    def _fail(self, target: str, error: Exception) -> None:
        widget = self.query_one(f"#{target}")
        if isinstance(widget, Stat):
            widget.set("—", "unavailable")
        else:
            widget.update(f"[$error]{esc(error)}[/]")  # type: ignore[attr-defined]

    @work(group="home-population", exclusive=True)
    async def load_population(self) -> None:
        try:
            data = await self.fetch(self.dzdk.client.population)
        except ApiError as error:
            self._fail("stat-pop", error)
            return self._fail("nationalities", error)
        total, arrivals = data.get("total"), data.get("newArrivals")
        demo = data.get("demographics") or {}
        self.query_one("#stat-pop", Stat).set(
            f"{total:,}" if isinstance(total, int) else NA,
            " · ".join(f"{k} {v}%" for k, v in demo.items()))
        self.query_one("#stat-arrivals", Stat).set(
            f"{arrivals:,}" if isinstance(arrivals, int) else NA, "recent registrations")
        nats = sorted((data.get("nationalities") or {}).items(), key=lambda kv: -kv[1])
        self.query_one("#nationalities", Static).update("\n".join(
            f"{esc(name):<10}[$primary]{bar(pct, 100, 24):<24}[/] [dim]{pct:>5}%[/]"
            for name, pct in nats[:5]))
        trends = data.get("trends") or {}
        labels, values = trends.get("labels") or [], trends.get("values") or []
        self.query_one("#trend", Sparkline).data = values
        if labels and values:
            self.query_one("#trend-label", Label).update(
                f"{labels[0]}  {values[0]:,}  →  {labels[-1]}  {values[-1]:,}")

    @work(group="home-funding", exclusive=True)
    async def load_funding(self) -> None:
        try:
            data = await self.fetch(self.dzdk.client.finance)
        except ApiError as error:
            return self._fail("stat-funding", error)
        budget, funded = data.get("budget") or 0, data.get("funded") or 0
        pct = funded / budget * 100 if budget else 0
        self.query_one("#stat-funding", Stat).set(
            f"{pct:.0f}% funded", f"${funded / 1e6:.1f}M of ${budget / 1e6:.1f}M")

    @work(group="home-weather", exclusive=True)
    async def load_weather(self) -> None:
        try:
            data = await self.fetch(self.dzdk.client.weather)
        except ApiError as error:
            return self._fail("stat-weather", error)
        cur = (data.get("forecast") or {}).get("current") or {}
        note = str(cur.get("condition", ""))
        if data.get("stale"):
            note += " · stale"
        self.query_one("#stat-weather", Stat).set(f"{cur.get('temperature', NA)}°C", note)

    @work(group="home-alerts", exclusive=True)
    async def load_alerts(self) -> None:
        client = self.dzdk.client
        try:
            alerts = await self.fetch(client.alerts)
            weather_alerts = await self.fetch(client.weather_alerts)
        except ApiError as error:
            return self._fail("home-alerts", error)
        tone = {"critical": "$error", "warning": "$warning", "alert": "$warning"}
        entries = [(a.get("type"), a.get("title"), a.get("date"), a.get("message")) for a in alerts]
        entries += [(a.get("type"), a.get("title"), a.get("publishedAt"), a.get("description"))
                    for a in weather_alerts]
        blocks = []
        for kind, title, date, message in entries:
            color = tone.get(str(kind).lower(), "$text-muted")
            blocks.append(f"[{color}]●[/] [b]{esc(title or 'Alert')}[/]  [dim]{fmt_date(date)}[/]\n"
                          f"  [dim]{esc(truncate(message, 150))}[/]")
        self.query_one("#home-alerts", Static).update("\n\n".join(blocks) or "[dim]No active alerts[/]")

    @work(group="home-news", exclusive=True)
    async def load_news(self) -> None:
        try:
            items = await self.fetch(self.dzdk.client.list_collection, "news")
        except ApiError as error:
            return self._fail("home-news", error)
        self.dzdk.register_items("news", items)
        latest = sorted(items, key=lambda i: str(i.get("date", "")), reverse=True)[:8]
        self.query_one("#home-news", Static).update("\n".join(
            f"[dim]{fmt_date(i.get('date'))}[/]  "
            f"[@click=app.show_item('news','{item_id(i)}')]{esc(truncate(title_of(i), 44))}[/]"
            for i in latest) or "[dim]No news[/]")

    @work(group="home-jobs", exclusive=True)
    async def load_jobs(self) -> None:
        try:
            items = await self.fetch(self.dzdk.client.list_collection, "jobs")
        except ApiError as error:
            return self._fail("home-jobs", error)
        self.dzdk.register_items("jobs", items)
        open_jobs = [i for i in items if str(i.get("status", "")).lower() == "open"]
        shown = sorted(open_jobs, key=lambda i: str(i.get("deadline", "")))[:8]
        lines = [f"[dim]{'closes ' + fmt_date(i['deadline']) if i.get('deadline') else 'no deadline      '}[/]  "
                 f"[@click=app.show_item('jobs','{item_id(i)}')]{esc(truncate(title_of(i), 48))}[/]"
                 for i in shown]
        summary = f"[dim]{len(open_jobs)} open of {len(items)} listed[/]"
        self.query_one("#home-jobs", Static).update("\n".join(lines + ["", summary]) if lines else summary)

    @work(group="home-api", exclusive=True)
    async def load_api(self) -> None:
        client = self.dzdk.client
        try:
            status = await self.fetch(client.status)
        except ApiError as error:
            return self._fail("api-line", error)
        mcp = status.get("mcp", "")
        self.query_one("#api-line", Static).update(
            f"API {esc(status.get('status', '?'))} · v{esc(status.get('version', '?'))} · "
            f"{client.rate_limit.remaining}/{client.rate_limit.limit} requests left this minute · "
            f"MCP [@click=app.open_link('{mcp}')]{esc(mcp.replace('https://', ''))}[/]")


# -------------------------------------------------------------- collections


class CollectionPane(DzdkPane):
    """Filterable table of a collection with a Markdown detail view."""

    BINDINGS = [
        Binding("escape", "focus_table", "Table", show=False),
        Binding("s", "cycle_sort", "Sort"),
    ]

    def __init__(self, collection: Collection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.collection = collection
        self.items: List[Dict[str, Any]] = []
        self.shown: List[Dict[str, Any]] = []
        self.current: Optional[Dict[str, Any]] = None
        self.pending_select: Optional[str] = None
        self.sort_index = 0
        self.sort_reverse = collection.sort_fields[0] in ("date", "deadline", "posted")

    def compose(self) -> ComposeResult:
        c = self.collection
        with Horizontal(classes="split"):
            with Pane(title=c.label, classes="sidebar"):
                with Horizontal(classes="toolbar"):
                    yield Input(placeholder=f"Filter {c.label.lower()}", compact=True,
                                classes="filter")
                    if c.filter_field:
                        yield Select([], prompt="All categories", compact=True,
                                     classes="category")
                yield DataTable(cursor_type="row", cell_padding=1)
            with ScrollPane(title="Details", classes="detail"):
                yield Markdown("", open_links=False)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for column in self.collection.columns:
            table.add_column(column.header, width=column.width, key=column.path)
        # Default sort: the first sort field, if it is one of the columns.
        paths = [col.path for col in self.collection.columns]
        if self.collection.sort_fields[0] in paths:
            self.sort_index = paths.index(self.collection.sort_fields[0])

    def reload(self, force: bool = False) -> None:
        self.load(force)

    @work(exclusive=True)
    async def load(self, force: bool = False) -> None:
        table = self.query_one(DataTable)
        table.loading = True
        try:
            self.items = await self.fetch(self.dzdk.client.list_collection, self.collection.name,
                                          cache=not force)
        except ApiError as error:
            await self.query_one(Markdown).update(error_markdown(error))
            self.notify(str(error), title=self.collection.label, severity="error")
            return
        finally:
            table.loading = False
        self.dzdk.register_items(self.collection.name, self.items)
        if self.collection.filter_field:
            self.query_one(Select).set_options(
                (name, name) for name in categories(self.items, self.collection))
        self.apply_filters()
        if self.dzdk.client.last_was_stale:
            self.notify("Offline: showing cached data", severity="warning")

    @on(Input.Changed, ".filter")
    @on(Select.Changed, ".category")
    def filters_changed(self) -> None:
        self.apply_filters()

    def _cell(self, item: Dict[str, Any], column) -> Any:
        text = cell_text(item, column)
        if column.kind != "status":
            return text
        theme = self.app.current_theme
        color = {"good": theme.success, "bad": theme.error, "muted": theme.secondary}.get(
            status_tone(item.get("status")), theme.warning)
        return Text.assemble(("● ", color or ""), text)

    def apply_filters(self) -> None:
        text = self.query_one(Input).value.strip()
        category = None
        if self.collection.filter_field:
            value = self.query_one(Select).value
            category = value if isinstance(value, str) else None
        sort_column = self.collection.columns[self.sort_index]
        self.shown = filter_items(self.items, self.collection, search=text or None,
                                  category=category, sort_by=sort_column.path,
                                  sort_order="desc" if self.sort_reverse else "asc")
        table = self.query_one(DataTable)
        table.clear()
        for index, item in enumerate(self.shown):
            table.add_row(*(self._cell(item, c) for c in self.collection.columns), key=str(index))
        arrow = "↓" if self.sort_reverse else "↑"
        count = (f"{len(self.shown)} of {len(self.items)}" if len(self.shown) != len(self.items)
                 else f"{len(self.items)} {self.collection.label.lower()}")
        self.query_one(".sidebar").border_subtitle = f"{count} · sorted by {sort_column.header.lower()} {arrow}"
        if self.pending_select:
            self.select_item(self.pending_select)
        elif self.shown:
            self.show_detail(self.shown[0])
        else:
            self.current = None
            self.query_one(Markdown).update("*Nothing matches this filter.*")

    def select_item(self, ident: str) -> None:
        if not self.items:
            self.pending_select = ident
            self.activate()
            return
        self.pending_select = None
        for index, item in enumerate(self.shown):
            if item_id(item) == ident:
                self.query_one(DataTable).move_cursor(row=index)
                self.show_detail(item)
                return
        # Hidden by the current filter: clear the filters and retry once they apply.
        if len(self.shown) != len(self.items):
            self.pending_select = ident
            self.query_one(Input).value = ""
            if self.collection.filter_field:
                self.query_one(Select).clear()

    @on(DataTable.RowHighlighted)
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value is not None and int(event.row_key.value) < len(self.shown):
            self.show_detail(self.shown[int(event.row_key.value)])

    @on(DataTable.RowSelected)
    def row_selected(self) -> None:
        self.query_one(".detail").focus()

    @on(DataTable.HeaderSelected)
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.column_index == self.sort_index:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_index, self.sort_reverse = event.column_index, False
        self.apply_filters()

    def action_cycle_sort(self) -> None:
        self.sort_index = (self.sort_index + 1) % len(self.collection.columns)
        self.sort_reverse = False
        self.apply_filters()

    def action_focus_table(self) -> None:
        self.query_one(DataTable).focus()

    def focus_default(self) -> None:
        self.query_one(DataTable).focus()

    def show_detail(self, item: Dict[str, Any]) -> None:
        if item is self.current:
            return
        self.current = item
        self.query_one(Markdown).update(
            item_markdown(self.collection, item, self.dzdk.client.site_url))
        self.query_one(".detail", VerticalScroll).scroll_home(animate=False)

    def current_url(self) -> Optional[str]:
        if self.current:
            return self.collection.web_url(self.dzdk.client.site_url, self.current)
        return f"{self.dzdk.client.site_url}/{self.collection.name}"


# ------------------------------------------------------------- encyclopedia


class EncyclopediaPane(DzdkPane):
    """Search-as-you-type encyclopedia with linked related entries."""

    BINDINGS = [
        Binding("backspace", "back", "Back"),
        Binding("escape", "focus_list", "List", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entries: List[Dict[str, Any]] = []
        self.current: Optional[Dict[str, Any]] = None
        self.history: List[str] = []
        self.pending_slug: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="split"):
            with Pane(title="Entries", classes="sidebar", id="wiki-sidebar"):
                with Horizontal(classes="toolbar"):
                    yield Input(placeholder="Search the encyclopedia", compact=True, id="wiki-q")
                    yield Select([], prompt="All categories", compact=True, id="wiki-category")
                yield OptionList(id="wiki-list")
            with ScrollPane(title="Article", classes="detail", id="wiki-scroll"):
                yield Markdown(
                    "# Dzaleka Encyclopedia\n\n*Sourced reference entries*\n\n"
                    "The history, people, places and institutions of Dzaleka Refugee Camp. "
                    "Every entry cites its sources.\n\nChoose an entry on the left, or type to search.",
                    open_links=False, id="wiki-article")

    def reload(self, force: bool = False) -> None:
        self.load_facets()
        self.search()

    def focus_default(self) -> None:
        self.query_one("#wiki-list").focus()

    @work(group="wiki-facets")
    async def load_facets(self) -> None:
        try:
            facets = await self.fetch(self.dzdk.client.encyclopedia_facets)
        except ApiError:
            return
        cats = facets.get("categories") or {}
        self.query_one("#wiki-category", Select).set_options(
            (f"{name} ({count})", name) for name, count in sorted(cats.items()))

    @on(Input.Changed, "#wiki-q")
    @on(Select.Changed, "#wiki-category")
    def query_changed(self) -> None:
        self.search(debounce=0.35)

    @work(exclusive=True, group="wiki-search")
    async def search(self, debounce: float = 0) -> None:
        if debounce:
            await asyncio.sleep(debounce)  # a newer keystroke cancels this worker
        q = self.query_one("#wiki-q", Input).value.strip() or None
        category = self.query_one("#wiki-category", Select).value
        category = category if isinstance(category, str) else None
        option_list = self.query_one("#wiki-list", OptionList)
        option_list.loading = True
        client = self.dzdk.client
        try:
            entries, meta = await self.fetch(client.encyclopedia, q=q, category=category,
                                             per_page=100)
            page = 1
            while meta.get("totalPages", 1) > page and page < 5:
                page += 1
                more, meta = await self.fetch(client.encyclopedia, q=q, category=category,
                                              per_page=100, page=page)
                entries += more
        except ApiError as error:
            await self.query_one("#wiki-article", Markdown).update(error_markdown(error))
            return
        finally:
            option_list.loading = False
        self.entries = entries
        if not q and not category:
            self.dzdk.register_items("encyclopedia", entries)
        option_list.clear_options()
        option_list.add_options(
            Option(Text.assemble(e.get("title", ""), "  ", (e.get("category") or "", "dim")),
                   id=e.get("id"))
            for e in entries)
        self.query_one("#wiki-sidebar").border_subtitle = (
            f"{len(entries)} entries" + (f" matching “{q}”" if q else ""))
        if self.pending_slug:
            slug, self.pending_slug = self.pending_slug, None
            self.open_entry(slug)
        elif entries:
            option_list.highlighted = 0  # previews the first entry, like the other tabs

    @on(OptionList.OptionHighlighted, "#wiki-list")
    @on(OptionList.OptionSelected, "#wiki-list")
    def option_chosen(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id and (not self.current or self.current.get("id") != event.option.id):
            self.open_entry(event.option.id)

    def open_entry(self, slug: str, remember: bool = True) -> None:
        if not self.loaded:
            self.pending_slug = slug
            self.activate()
            return
        if remember and self.current and self.current.get("id") != slug:
            self.history.append(self.current["id"])
        self.load_entry(slug)

    @work(exclusive=True, group="wiki-entry")
    async def load_entry(self, slug: str) -> None:
        article = self.query_one("#wiki-article", Markdown)
        scroll = self.query_one("#wiki-scroll", VerticalScroll)
        try:
            entry = await self.fetch(self.dzdk.client.encyclopedia_entry, slug)
        except ApiError as error:
            await article.update(error_markdown(error))
            return
        self.current = entry
        await article.update(entry_markdown(entry, wiki_links=True))
        scroll.scroll_home(animate=False)

    def action_back(self) -> None:
        if self.history:
            self.open_entry(self.history.pop(), remember=False)
        else:
            self.notify("No previous entry")

    def action_focus_list(self) -> None:
        self.query_one("#wiki-list").focus()

    def current_url(self) -> Optional[str]:
        if self.current:
            return self.current.get("url")
        return f"{self.dzdk.client.site_url}/encyclopedia"


# ------------------------------------------------------------------- search


class SearchPane(DzdkPane):
    """Cross-collection search via /api/search, grouped in a tree."""

    BINDINGS = [Binding("escape", "focus_results", "Results", show=False)]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.current: Optional[Dict[str, Any]] = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="split"):
            with Pane(title="Results", classes="sidebar", id="search-sidebar") as sidebar:
                sidebar.border_subtitle = "type 3+ characters"
                with Horizontal(classes="toolbar"):
                    yield Input(placeholder="Search services, jobs, events, news, encyclopedia",
                                compact=True, id="global-q")
                tree: Tree[Dict[str, Any]] = Tree("Results", id="results")
                tree.show_root = False
                tree.guide_depth = 2
                yield tree
            with ScrollPane(title="Preview", classes="detail"):
                yield Markdown("# Search\n\n*Everything on Dzaleka Online Services*\n\n"
                               "Results are grouped by collection. Use ↑ ↓ to preview and "
                               "**Enter** to open a result in its tab.",
                               open_links=False, id="result-detail")

    def activate(self) -> None:
        self.loaded = True

    def focus_default(self) -> None:
        self.focus_search()

    def action_focus_results(self) -> None:
        self.query_one("#results").focus()

    def reload(self, force: bool = False) -> None:
        self.run_search(0)

    @on(Input.Changed, "#global-q")
    def query_changed(self, event: Input.Changed) -> None:
        if len(event.value.strip()) >= 3:
            self.run_search(0.5)

    @on(Input.Submitted, "#global-q")
    def query_submitted(self) -> None:
        self.run_search(0)

    def set_query(self, query: str) -> None:
        self.query_one("#global-q", Input).value = query
        self.run_search(0)

    @work(exclusive=True, group="global-search")
    async def run_search(self, debounce: float) -> None:
        if debounce:
            await asyncio.sleep(debounce)
        query = self.query_one("#global-q", Input).value.strip()
        if not query:
            return
        tree = self.query_one("#results", Tree)
        tree.loading = True
        try:
            data = await self.fetch(self.dzdk.client.search, query, limit=15)
        except ApiError as error:
            await self.query_one("#result-detail", Markdown).update(error_markdown(error))
            return
        finally:
            tree.loading = False
        tree.clear()
        results: Dict[str, List[Dict[str, Any]]] = data.get("results") or {}
        for name, hits in results.items():
            if not hits:
                continue
            label = COLLECTIONS[name].label if name in COLLECTIONS else name.replace("-", " ").title()
            branch = tree.root.add(Text.assemble((label, "bold"), "  ", (str(len(hits)), "dim")),
                                   expand=True)
            for hit in hits:
                branch.add_leaf(truncate(hit.get("title", "Untitled"), 60),
                                data={**hit, "_collection": name})
        self.query_one("#search-sidebar").border_subtitle = (
            f"{data.get('totalResults', 0)} results for “{query}”")
        if tree.root.children:
            tree.focus()
            tree.move_cursor(tree.root.children[0])

    @on(Tree.NodeHighlighted)
    def preview(self, event: Tree.NodeHighlighted) -> None:
        hit = event.node.data
        if not hit:
            return
        self.current = hit
        name = hit.get("_collection", "")
        label = COLLECTIONS[name].label if name in COLLECTIONS else name.title()
        meta = " · ".join(x for x in (label, hit.get("category"),
                                       "featured" if hit.get("featured") else None) if x)
        md = [f"# {hit.get('title', 'Untitled')}", f"*{meta}*", "", str(hit.get("description") or "")]
        opens = "in its tab" if name in COLLECTIONS or name == "encyclopedia" else "in your browser"
        md.append(f"\n---\n\nPress **Enter** to open {opens}.")
        if hit.get("url"):
            url = self.absolute(hit["url"])
            md.append(f"\n[{url.replace('https://', '')}]({url})")
        self.query_one("#result-detail", Markdown).update("\n".join(md))

    @on(Tree.NodeSelected)
    def open_hit(self, event: Tree.NodeSelected) -> None:
        hit = event.node.data
        if not hit:
            return
        name = hit.get("_collection")
        slug = str(hit.get("slug") or hit.get("id") or "")
        if name == "encyclopedia":
            self.dzdk.show_wiki(slug)
        elif name in self.dzdk.collection_tabs:
            self.dzdk.show_item(name, slug)
        elif hit.get("url"):
            self.dzdk.open_link(self.absolute(hit["url"]))

    def absolute(self, url: str) -> str:
        return url if url.startswith("http") else f"{self.dzdk.client.site_url}{url}"

    def current_url(self) -> Optional[str]:
        url = (self.current or {}).get("url")
        return self.absolute(url) if url else None
