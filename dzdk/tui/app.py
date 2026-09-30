"""The dzdk Textual application."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Footer, Label, Markdown, TabbedContent, TabPane

from dzdk import __version__
from dzdk.api import DzdkClient
from dzdk.catalog import PRIMARY
from dzdk.config import load_config, save_config
from dzdk.render import WIKI_LINK_PREFIX
from dzdk.tui.commands import DzdkCommands
from dzdk.tui.charts import InsightsPane
from dzdk.tui.widgets import CollectionPane, DzdkPane, EncyclopediaPane, HomePane, SearchPane

# Green from Malawi's flag as the single accent; red is reserved for alerts.
DZALEKA_DARK = Theme(
    name="dzaleka",
    primary="#4FB25E",
    secondary="#7D8B96",
    accent="#4FB25E",
    warning="#D9A441",
    error="#E0524A",
    success="#4FB25E",
    foreground="#DCE1E5",
    background="#111416",
    surface="#171B1E",
    panel="#20252A",
    dark=True,
)
DZALEKA_LIGHT = Theme(
    name="dzaleka-light",
    primary="#23813A",
    secondary="#5F6B75",
    accent="#23813A",
    warning="#A86B00",
    error="#C0322A",
    success="#23813A",
    foreground="#1D2226",
    background="#FAFAF8",
    surface="#FFFFFF",
    panel="#EEF0EE",
    dark=False,
)

HELP_TEXT = f"""
# dzdk {__version__}

*Dzaleka Online Services in your terminal*

## Moving around

- **1–9, 0** switch tabs (press **Esc** first if you are typing in a box)
- **/** jump to the filter or search box, **Esc** to leave it
- **↑ ↓** move through a list; the right-hand side updates as you go
- **Enter** open the result or move into the details
- **Ctrl+P** command palette: jump to any item, tab or page by name
- **Insights** has its own sub-tabs of charts: click them or use the arrow keys on the tab strip

## Actions

- **o** open the current item on services.dzaleka.com
- **y** copy its link
- **s** change the sort column (or click a column header)
- **r** reload, bypassing the cache
- **z** zoom the focused pane to fill the screen (press again to restore)
- **[** and **]** make the list pane narrower or wider
- **Backspace** go back to the previous encyclopedia entry
- **q** quit

Change the colour theme with **Ctrl+P → Change theme**. Your choice is saved.

## About the data

Content comes from the public Dzaleka Online Services API and is published under
CC BY-SA 4.0 unless a page says otherwise. Community listings may be unverified.
Responses are cached, so recently viewed pages still work on a poor connection.

For urgent help, go to services.dzaleka.com/get-help-now.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,f1,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog"):
            yield Markdown(HELP_TEXT, open_links=False)

    @on(Markdown.LinkClicked)
    def link(self, event: Markdown.LinkClicked) -> None:
        self.app.open_url(event.href)


class TopBar(Horizontal):
    """One-line title bar: name on the left, connection status on the right."""

    def compose(self) -> ComposeResult:
        yield Label("[b]dzdk[/]  [$text-muted]Dzaleka Online Services[/]", id="brand")
        yield Label("", id="status")


class DzdkApp(App):
    """Browse Dzaleka Online Services in the terminal."""

    CSS_PATH = Path(__file__).parent / "dzdk.tcss"  # absolute, so subclasses elsewhere work
    TITLE = "dzdk"
    COMMANDS = App.COMMANDS | {DzdkCommands}
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "focus_search", "Search"),
        Binding("o", "open_browser", "Open"),
        Binding("y", "copy_link", "Copy link"),
        Binding("r", "refresh", "Reload"),
        Binding("z", "zoom", "Zoom pane"),
        Binding("left_square_bracket", "resize_sidebar(-5)", "Narrower list", show=False),
        Binding("right_square_bracket", "resize_sidebar(5)", "Wider list", show=False),
        Binding("f1", "help", "Help"),
        *[Binding(str(i), f"show_tab_index({i - 1})", show=False) for i in range(1, 10)],
        Binding("0", "show_tab_index(9)", show=False),
    ]

    def __init__(self, client: Optional[DzdkClient] = None,
                 config: Optional[Dict[str, Any]] = None, initial_tab: str = "home") -> None:
        super().__init__()
        # With no arguments (e.g. `textual run --dev dzdk.tui.app:DzdkApp`), use saved settings.
        self.config = config if config is not None else load_config()
        self.client = client or DzdkClient.from_config(self.config)
        self.initial_tab = initial_tab
        self.item_index: Dict[str, List[Dict[str, Any]]] = {}
        self.collection_tabs = [c.name for c in PRIMARY]
        # Tab order: Home, Services, Encyclopedia, the other collections, Search.
        labels = {c.name: c.label for c in PRIMARY}
        self.tab_labels: Dict[str, str] = {
            "home": "Home",
            "insights": "Insights",
            "services": labels.pop("services"),
            "wiki": "Encyclopedia",
            **labels,
            "search": "Search",
        }
        self.sidebar_width = self._clamp_sidebar(self.config.get("sidebar_width", 46))
        self.register_theme(DZALEKA_DARK)
        self.register_theme(DZALEKA_LIGHT)

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with TabbedContent(initial=self.initial_tab, id="tabs"):
            for tab_id, label in self.tab_labels.items():
                with TabPane(label, id=tab_id):
                    if tab_id == "home":
                        yield HomePane()
                    elif tab_id == "insights":
                        yield InsightsPane()
                    elif tab_id == "wiki":
                        yield EncyclopediaPane()
                    elif tab_id == "search":
                        yield SearchPane()
                    else:
                        yield CollectionPane(next(c for c in PRIMARY if c.name == tab_id))
        yield Footer(compact=True)

    def on_mount(self) -> None:
        theme = self.config.get("theme")
        self.theme = theme if theme in self.available_themes else DZALEKA_DARK.name
        self.watch(self, "theme", self._save_theme, init=False)
        self.apply_layout()
        pane = self.active_pane()
        pane.activate()
        # TabbedContent focuses its tab strip while mounting; move focus afterwards.
        self.call_after_refresh(pane.focus_default)

    # --------------------------------------------------------------- layout

    # Breakpoints for the responsive layout, in terminal cells.
    NARROW_WIDTH = 110   # below this, lists stack above details and grids use one column
    SHORT_HEIGHT = 34    # below this, the home header uses the small logo

    def on_resize(self, event) -> None:
        # self.size still holds the old size while this event is handled.
        self.apply_layout(event.size)

    def apply_layout(self, size=None) -> None:
        """Adapt to the terminal size; called on start-up, resize and `[` / `]`."""
        width, height = size or self.size
        narrow = width < self.NARROW_WIDTH
        short = height < self.SHORT_HEIGHT
        self.set_class(narrow, "-narrow")
        self.set_class(short, "-short")
        self.set_class(width < 80, "-tiny")
        for logo in self.query("Logo"):
            logo.set_compact(narrow or short)  # type: ignore[attr-defined]
        for split in self.query(".split"):
            sidebar = split.query_one(".sidebar")
            if narrow:
                split.styles.layout = "vertical"
                sidebar.styles.width = "1fr"
                sidebar.styles.height = f"{self.sidebar_width}%"
            else:
                split.styles.layout = "horizontal"
                sidebar.styles.width = f"{self.sidebar_width}%"
                sidebar.styles.height = "1fr"

    @staticmethod
    def _clamp_sidebar(value: Any) -> int:
        try:
            return max(25, min(75, int(value)))
        except (TypeError, ValueError):
            return 46

    def action_resize_sidebar(self, delta: int) -> None:
        self.sidebar_width = self._clamp_sidebar(self.sidebar_width + delta)
        self.apply_layout()
        self.config["sidebar_width"] = self.sidebar_width
        self._write_config()
        self.notify(f"List pane {self.sidebar_width}%", timeout=1.5)

    def action_zoom(self) -> None:
        """Toggle the focused pane between its place in the layout and full screen."""
        if self.screen.maximized is not None:
            self.screen.minimize()
            self.apply_layout()  # put back the list pane's width/height
            return
        node = self.focused
        while node is not None and not node.has_class("pane"):
            node = node.parent
        if node is None:
            self.notify("Move into a list or details pane first", timeout=2)
            return
        # apply_layout sets inline sizes on list panes; let the zoomed pane fill the screen.
        node.styles.width = "1fr"
        node.styles.height = "1fr"
        self.screen.maximize(node, container=False)

    def _write_config(self) -> None:
        try:
            save_config(self.config)
        except OSError:
            pass

    def _save_theme(self, theme: str) -> None:
        if self.config.get("theme") != theme:
            self.config["theme"] = theme
            self._write_config()

    # -------------------------------------------------------------- helpers

    def active_pane(self) -> DzdkPane:
        tabs = self.query_one(TabbedContent)
        return tabs.get_pane(tabs.active).query_one(DzdkPane)

    def pane_for(self, tab_id: str) -> DzdkPane:
        return self.query_one(TabbedContent).get_pane(tab_id).query_one(DzdkPane)

    @on(TabbedContent.TabActivated, "#tabs")
    def tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane = event.pane.query_one(DzdkPane)
        pane.activate()
        pane.focus_default()

    def register_items(self, name: str, items: List[Dict[str, Any]]) -> None:
        self.item_index[name] = items

    def update_status(self) -> None:
        rate = self.client.rate_limit
        parts = []
        if self.client.last_was_stale:
            parts.append("[$warning]offline, showing cached data[/]")
        if rate.remaining is not None:
            parts.append(f"[$text-muted]{rate.remaining}/{rate.limit} requests left[/]")
        parts.append(f"[$text-muted]v{__version__}[/]")
        try:
            self.query_one("#status", Label).update("  ·  ".join(parts))
        except NoMatches:
            pass  # a request finished while the app was closing

    # ------------------------------------------------------------ navigation

    def show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_show_tab_index(self, index: int) -> None:
        tabs = list(self.tab_labels)
        if index < len(tabs):
            self.show_tab(tabs[index])

    def show_item(self, collection: str, ident: str) -> None:
        self.show_tab(collection)
        pane = self.pane_for(collection)
        assert isinstance(pane, CollectionPane)
        pane.select_item(ident)

    def show_wiki(self, slug: str) -> None:
        self.show_tab("wiki")
        pane = self.pane_for("wiki")
        assert isinstance(pane, EncyclopediaPane)
        pane.open_entry(slug)

    def search_everything(self, query: str) -> None:
        self.show_tab("search")
        pane = self.pane_for("search")
        assert isinstance(pane, SearchPane)
        pane.set_query(query)

    def open_link(self, url: str) -> None:
        if url.startswith(WIKI_LINK_PREFIX):
            self.show_wiki(url[len(WIKI_LINK_PREFIX):])
        elif url:
            self.open_url(url)
            self.notify(url, title="Opening in browser", timeout=3)

    def action_open_link(self, url: str) -> None:
        self.open_link(url)

    def action_show_item(self, collection: str, ident: str) -> None:
        self.show_item(collection, ident)

    @on(Markdown.LinkClicked)
    def markdown_link(self, event: Markdown.LinkClicked) -> None:
        self.open_link(event.href)

    # --------------------------------------------------------------- actions

    def action_focus_search(self) -> None:
        self.active_pane().focus_search()

    def action_refresh(self) -> None:
        pane = self.active_pane()
        pane.loaded = True
        pane.reload(force=True)
        self.notify("Reloading…", timeout=2)

    def action_open_browser(self) -> None:
        url = self.active_pane().current_url()
        if url:
            self.open_link(url)

    def action_copy_link(self) -> None:
        url = self.active_pane().current_url()
        if url:
            self.copy_to_clipboard(url)
            self.notify(url, title="Link copied", timeout=3)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_clear_cache(self) -> None:
        removed = self.client.cache.clear()
        self.notify(f"Removed {removed} cached responses")
