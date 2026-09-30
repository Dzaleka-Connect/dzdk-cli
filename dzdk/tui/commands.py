"""Command palette (Ctrl+P) provider: jump to tabs, pages and any loaded item."""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Hits, Provider

from dzdk.api import item_id
from dzdk.catalog import COLLECTIONS, title_of

if TYPE_CHECKING:
    from dzdk.tui.app import DzdkApp


class DzdkCommands(Provider):
    @property
    def dzdk(self) -> "DzdkApp":
        return self.app  # type: ignore[return-value]

    def _static_commands(self):
        app = self.dzdk
        site = app.client.site_url
        for tab_id, label in app.tab_labels.items():
            yield f"Go to {label}", partial(app.show_tab, tab_id), f"Switch to the {label} tab"
        pages = [
            ("Get help now (urgent contacts)", f"{site}/get-help-now"),
            ("Open Dzaleka Online Services website", site),
            ("Open API documentation", f"{site}/api-docs"),
            ("Open the map", f"{site}/map"),
            ("Open datasets", f"{site}/datasets"),
        ]
        for label, url in pages:
            yield label, partial(app.open_link, url), url
        yield "Refresh current tab", app.action_refresh, "Reload data, bypassing the cache"
        yield "Clear response cache", app.action_clear_cache, "Delete cached API responses"
        yield "Show help", app.action_help, "Key bindings and about"

    async def discover(self) -> Hits:
        for text, command, help_text in self._static_commands():
            yield DiscoveryHit(text, command, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self.dzdk
        for text, command, help_text in self._static_commands():
            score = matcher.match(text)
            if score > 0:
                yield Hit(score, matcher.highlight(text), command, help=help_text)
        # Items from any collection the user has already loaded this session.
        for name, items in list(app.item_index.items()):
            label = "Encyclopedia" if name == "encyclopedia" else (
                COLLECTIONS[name].label if name in COLLECTIONS else name.title())
            for item in items:
                title = title_of(item)
                text = title
                # Items need every query word as a substring; fuzzy matching over
                # hundreds of titles is too noisy to be useful.
                words = query.lower().split()
                if not words or not all(w in title.lower() for w in words):
                    continue
                score = max(matcher.match(title), 0.5)
                ident = item_id(item)
                command = (partial(app.show_wiki, ident) if name == "encyclopedia"
                           else partial(app.show_item, name, ident))
                yield Hit(score * 0.9, matcher.highlight(text), command,
                          help=f"{label} · {str(item.get('summary') or item.get('description') or '')[:80]}")
        if len(query) >= 3:
            yield Hit(0.1, f"Search everything for “{query}”",
                      partial(app.search_everything, query), help="Uses /api/search")
