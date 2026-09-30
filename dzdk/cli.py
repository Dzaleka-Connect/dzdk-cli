"""Click command-line interface for dzdk."""
import csv
import functools
import json
import os
import shlex
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import click
import yaml
from rich.box import ROUNDED, SIMPLE_HEAD
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from dzdk import __version__
from dzdk.api import ApiError, DzdkClient, item_id
from dzdk.catalog import COLLECTIONS, PRIMARY, Collection, categories, filter_items, resolve, title_of
from dzdk.config import (
    DEFAULT_API_URL,
    cache_dir,
    config_dir,
    config_file,
    load_config,
    normalize_api_url,
    save_config,
)
from dzdk.render import NA, bar, cell_text, entry_markdown, fmt_date, item_markdown, status_tone

# One accent colour (green, from Malawi's flag); red only for errors and alerts.
console = Console(theme=Theme({
    "accent": "green",
    "info": "default",
    "warning": "yellow",
    "danger": "red",
    "success": "green",
    "title": "bold",
    "subtitle": "dim",
    "highlight": "bold",
    "muted": "dim",
}))
BORDER = "grey42"

GET_HELP_URL = "https://services.dzaleka.com/get-help-now"
EXPORTABLE = sorted(list(COLLECTIONS) + ["encyclopedia", "population"])


# ---------------------------------------------------------------- helpers


def create_header(title: str, subtitle: Optional[str] = None) -> Text:
    header = Text(title, style="title")
    if subtitle:
        header.append(f"  {subtitle}", style="subtitle")
    header.append("\n")
    return header


def create_info_panel(title: str, content: Any, style: str = BORDER) -> Panel:
    return Panel(content, title=title, title_align="left", border_style=style, box=ROUNDED,
                 padding=(0, 1))


def new_table(title: Optional[str] = None, **kwargs: Any) -> Table:
    """Borderless table with a rule under the header, used for all list output."""
    options = dict(box=SIMPLE_HEAD, header_style="bold", title_style="bold",
                   title_justify="left", border_style=BORDER, pad_edge=False)
    options.update(kwargs)
    return Table(title=title, **options)


def print_api_error(error: ApiError) -> None:
    lines = [f"[danger]{escape(str(error))}[/danger]"]
    if error.detail:
        lines.append(escape(error.detail))
    if error.resolution:
        lines.append(f"\n[highlight]How to fix:[/highlight] {escape(error.resolution)}")
    if error.code:
        lines.append(f"[dim]code: {error.code}[/dim]")
    console.print(create_info_panel("Error", "\n".join(lines), style="red"))


def api_command(func: Callable) -> Callable:
    """Turn ApiError into a readable panel and exit code 1."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ApiError as error:
            print_api_error(error)
            sys.exit(1)

    return wrapper


def get_config() -> Dict[str, Any]:
    ctx = click.get_current_context()
    root = ctx.find_root()
    root.ensure_object(dict)
    if "config" not in root.obj:
        try:
            root.obj["config"] = load_config()
        except (yaml.YAMLError, OSError) as error:
            console.print(f"[red]Error reading {config_file()}: {escape(str(error))}[/red]")
            sys.exit(1)
    return root.obj["config"]


def get_client() -> DzdkClient:
    ctx = click.get_current_context()
    root = ctx.find_root()
    root.ensure_object(dict)
    if "client" not in root.obj:
        root.obj["client"] = DzdkClient.from_config(get_config(),
                                                    use_cache=not root.obj.get("no_cache"))
    return root.obj["client"]


def warn_if_stale(client: DzdkClient) -> None:
    if client.last_was_stale:
        console.print("[warning]Offline: showing cached data, which may be out of date.[/warning]")


def echo_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


def paginate(items: List[Any], page: int, per_page: int):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages, start


def styled_cell(collection: Collection, item: Dict[str, Any], column) -> Any:
    text = cell_text(item, column)
    if column.kind == "status":
        status = str(item.get("status", "")).lower()
        color = {"good": "green", "bad": "red", "muted": "dim"}.get(status_tone(status), "yellow")
        return f"[{color}]●[/{color}] {escape(status or '?')}"
    if column.path == "contact.email" and text != NA:
        return f"[link=mailto:{text}]{escape(text)}[/link]"
    if column.path == "contact.phone" and text != NA:
        digits = "".join(ch for ch in text if ch.isdigit() or ch == "+")
        return f"[link=tel:{digits}]{escape(text)}[/link]"
    if column.path == "title":
        url = item.get("resourceUrl") or item.get("downloadUrl")
        if url:
            return f"[link={url}]{escape(text)}[/link]"
    return escape(text)


def collection_table(collection: Collection, items: List[Dict[str, Any]], title: str,
                     show_id: bool = True) -> Table:
    table = new_table(title, expand=True)
    for i, column in enumerate(collection.columns):
        table.add_column(column.header, style="bold" if i == 0 else "",
                         ratio=column.width, overflow="fold")
    if show_id:
        table.add_column("ID", style="dim", ratio=20, overflow="fold")
    for item in items:
        cells = [styled_cell(collection, item, c) for c in collection.columns]
        if show_id:
            cells.append(escape(item_id(item)))
        table.add_row(*cells)
    return table


def navigation_panel(command: str, page: int, pages: int, start: int, shown: int, total: int,
                     noun: str) -> Text:
    """One muted line: position, then the next commands to try."""
    hints = [f"{start + 1 if total else 0}-{start + shown} of {total} {noun}"]
    if page < pages:
        hints.append(f"next: {command} --page {page + 1}")
    hints.append(f"details: {command.replace(' list', ' get')} <ID>")
    return Text("  ·  ".join(hints), style="dim")


def print_document(markdown: str) -> None:
    """Print a detail view: bold title line, then the Markdown body (no box)."""
    first, _, rest = markdown.partition("\n")
    if first.startswith("# "):
        console.print(Text(first[2:].strip(), style="bold"))
        markdown = rest
    console.print(Markdown(markdown))


def flatten(item: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in item.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}_"))
        elif isinstance(value, list):
            flat[name] = ", ".join(
                title_of(v) if isinstance(v, dict) else str(v) for v in value)
        else:
            flat[name] = value
    return flat


def safe_filename(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in name).strip()
    return keep[:120] or "download"


# ------------------------------------------------------------------- root


WELCOME = f"""[bold]dzdk[/bold] [dim]{__version__}[/dim]  Dzaleka Online Services from the terminal

[bold]Browse[/bold]
  dzdk tui                           full-screen app
  dzdk search "legal aid"            search every collection
  dzdk services list -s health       also: events, jobs, news, resources, photos
  dzdk services get <ID>             details for one item
  dzdk wiki get dzaleka-refugee-camp read an encyclopedia entry
  dzdk browse                        list every collection

[bold]Data[/bold]
  dzdk alerts · weather · population stats · stats overview
  dzdk export csv --type jobs -o jobs.csv

[bold]Setup[/bold]
  dzdk health · status · mcp · config --interactive

[red]Urgent help:[/red] {GET_HELP_URL}
"""


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--no-cache", is_flag=True, help="Bypass the local response cache.")
@click.version_option(__version__, prog_name="dzdk")
@click.pass_context
def cli(ctx: click.Context, no_cache: bool) -> None:
    """dzdk - Dzaleka Online Services CLI.

    Browse services, events, jobs, news, resources, photos and the Dzaleka
    Encyclopedia from the terminal. Run `dzdk tui` for the full-screen app.
    """
    ctx.ensure_object(dict)
    ctx.obj["no_cache"] = no_cache
    if ctx.invoked_subcommand is None:
        from rich.table import Table as Grid

        from dzdk.tui.logo import LOGO_COLOR, LOGO_SMALL

        header = Grid.grid(padding=(0, 3))
        header.add_row(Text(LOGO_SMALL, style=LOGO_COLOR), WELCOME.split("\n\n", 1)[0].strip()
                       + "\n\n[dim]Directory, news and open data for Dzaleka Refugee Camp[/dim]")
        console.print(header)
        console.print()
        console.print(WELCOME.split("\n\n", 1)[1])
        click.echo(ctx.get_help())


# ----------------------------------------------------------------- config


@cli.command("config")
@click.option("--url", help="API base URL")
@click.option("--timeout", type=int, help="Request timeout in seconds")
@click.option("--cache-ttl", type=int, help="Seconds to cache responses (0 disables)")
@click.option("--theme", help="Textual theme for `dzdk tui`")
@click.option("--window-size", metavar="COLSxROWS|off",
              help="Window size `dzdk tui` grows the terminal to, or `off`")
@click.option("--offline-fallback/--no-offline-fallback", default=None,
              help="Serve stale cached data when offline")
@click.option("--clear-cache", is_flag=True, help="Delete cached API responses")
@click.option("--reset", is_flag=True, help="Restore default settings")
@click.option("--interactive", is_flag=True, help="Start interactive configuration mode")
def config_command(url, timeout, cache_ttl, theme, window_size, offline_fallback, clear_cache,
                   reset, interactive):
    """Configure CLI settings."""
    from dzdk.api import ResponseCache
    from dzdk.config import DEFAULT_CONFIG

    config = dict(DEFAULT_CONFIG) if reset else get_config()

    if clear_cache:
        removed = ResponseCache(cache_dir(), 1).clear()
        console.print(f"[green]Removed {removed} cached responses[/green]")

    if interactive:
        console.print(create_header("Interactive Configuration", "Configure your CLI settings"))
        console.print(create_info_panel(
            "Current Configuration",
            f"API URL: {config['api_url']}\nTimeout: {config['timeout']} seconds\n"
            f"Cache TTL: {config.get('cache_ttl')} seconds",
        ))
        new_url = normalize_api_url(click.prompt("Enter API URL", default=config["api_url"],
                                                 show_default=True))
        new_timeout = click.prompt("Enter timeout in seconds", default=config["timeout"],
                                   type=int, show_default=True)
        config.update(api_url=new_url, timeout=new_timeout)
        save_config(config)
        console.print(create_info_panel(
            "Configuration Updated",
            "[success]Configuration has been updated successfully![/success]\n\n"
            f"[highlight]New Settings:[/highlight]\nAPI URL: {new_url}\n"
            f"Timeout: {new_timeout} seconds",
        ))
        return

    if url:
        config["api_url"] = normalize_api_url(url)
    if timeout:
        config["timeout"] = timeout
    if cache_ttl is not None:
        config["cache_ttl"] = cache_ttl
    if theme:
        config["theme"] = theme
    if window_size:
        from dzdk.tui.terminal import parse_size

        if window_size.lower() != "off" and parse_size(window_size) is None:
            raise click.BadParameter("use COLSxROWS, e.g. 140x42, or off",
                                     param_hint="--window-size")
        config["window_size"] = window_size.lower()
    if offline_fallback is not None:
        config["offline_fallback"] = offline_fallback

    changed = any(v not in (None, False) for v in (url, timeout, cache_ttl, theme, window_size,
                                                   offline_fallback)) or reset
    if changed or not clear_cache:
        save_config(config)
        console.print("[green]Configuration updated successfully[/green]")
        console.print(f"[info]API URL: {config['api_url']}[/info]")
        console.print(f"[info]Timeout: {config['timeout']} seconds[/info]")
        console.print(f"[info]Cache TTL: {config.get('cache_ttl')} seconds[/info]")


@cli.command("show-config", short_help="Show current CLI configuration")
def show_config():
    """Show current CLI configuration."""
    config = get_config()
    path = config_file()
    modified = (datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                if path.exists() else "not saved yet (using defaults)")
    console.print(create_header("Current Configuration", "Your CLI settings"))
    table = new_table(show_header=False)
    table.add_column(style="bold")
    table.add_column()
    for key, value in [
        ("API URL", config.get("api_url")),
        ("Timeout", f"{config.get('timeout')} seconds"),
        ("Cache TTL", f"{config.get('cache_ttl')} seconds"),
        ("Offline fallback", "on" if config.get("offline_fallback") else "off"),
        ("TUI theme", config.get("theme")),
        ("TUI window size", config.get("window_size")),
        ("Config file", str(path)),
        ("Last modified", modified),
        ("Cache directory", str(cache_dir())),
    ]:
        table.add_row(key, escape(str(value)))
    console.print(create_info_panel("Configuration Details", table))
    console.print(create_info_panel(
        "How to Update",
        f'dzdk config --url "{DEFAULT_API_URL}" --timeout 30\n'
        "dzdk config --interactive\n"
        "dzdk config --clear-cache\n"
        f"or edit {path}",
    ))


@cli.command("show_config", hidden=True)
@click.pass_context
def show_config_alias(ctx):
    """Alias for show-config."""
    ctx.invoke(show_config)


# ----------------------------------------------------------------- health


@cli.command()
def health():
    """Check API health: status endpoint plus every main collection."""
    client = get_client()
    console.print(create_header("API Health Check", f"Monitoring {client.base_url}"))
    table = new_table(header_style="bold", expand=True)
    table.add_column("Endpoint")
    table.add_column("Status", justify="center")
    table.add_column("Time", justify="right")
    table.add_column("Details", overflow="fold")

    all_healthy = True
    checks = [("status", "/status")] + [(c.name, f"/{c.name}") for c in PRIMARY]
    checks += [("encyclopedia", "/encyclopedia"), ("population", "/population")]
    for name, path in checks:
        start = time.perf_counter()
        try:
            data = client.get(path, cache=False)
            elapsed = f"{time.perf_counter() - start:.2f}s"
            count = len(data["data"].get(name, [])) if isinstance(data, dict) and isinstance(
                data.get("data"), dict) and name in data["data"] else None
            detail = f"OK · {count} items" if count is not None else "OK"
            table.add_row(name, "[bold green]✓[/bold green]", elapsed, detail)
        except ApiError as error:
            all_healthy = False
            table.add_row(name, "[bold red]✗[/bold red]", "N/A",
                          escape(error.detail or str(error)))
    console.print(table)
    console.print(f"[dim]Rate limit: {client.rate_limit}[/dim]")
    if all_healthy:
        console.print("[green]✓ All endpoints are healthy[/green]")
        return
    console.print("[red]✗ Some endpoints are not responding[/red]")
    console.print(
        f"\n[bold yellow]Troubleshooting[/bold yellow]\n"
        f"1. Check your network connection\n"
        f"2. Verify the API URL ({client.base_url})\n"
        f"3. Update it with: dzdk config --url <correct-url>"
    )
    sys.exit(1)


@cli.command()
@api_command
def status():
    """Show API status, version, rate limit and discovery links."""
    client = get_client()
    data = client.status()
    table = new_table(show_header=False)
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    for key in ("status", "service", "version", "apiBase", "documentation", "openapi", "mcp",
                "agentGuidance", "deprecationPolicy", "checkedAt"):
        if key in data:
            value = data[key]
            if isinstance(value, str) and value.startswith("http"):
                value = f"[link={value}]{value}[/link]"
            table.add_row(key, str(value))
    table.add_row("rate limit", str(client.rate_limit))
    console.print(create_info_panel("API Status", table))


# ------------------------------------------------------------ collections


def list_command_for(collection: Collection, command_prefix: str):
    sort_choices = click.Choice(list(collection.sort_fields))

    @click.command("list")
    @click.option("--search", "-s", help="Filter by text")
    @click.option("--category", "-c", help="Filter by category")
    @click.option("--status", help="Filter by status (e.g. active, open, upcoming)")
    @click.option("--sort-by", type=sort_choices, default=collection.sort_fields[0],
                  show_default=True, help="Sort field")
    @click.option("--sort-order", type=click.Choice(["asc", "desc"]), default="asc",
                  help="Sort order")
    @click.option("--page", type=int, default=1, help="Page number to view")
    @click.option("--per-page", type=int, default=12, show_default=True, help="Items per page")
    @click.option("--categories", "show_categories", is_flag=True,
                  help="List available categories and exit")
    @click.option("--json", "as_json", is_flag=True, help="Print raw JSON (all matches)")
    @api_command
    def list_cmd(search, category, status, sort_by, sort_order, page, per_page,
                 show_categories, as_json):
        client = get_client()
        with console.status(f"[bold green]Fetching {collection.label.lower()}..."):
            items = client.list_collection(collection.name)
        if show_categories:
            for name in categories(items, collection):
                click.echo(name)
            return
        items = filter_items(items, collection, search=search, category=category, status=status,
                             sort_by=sort_by, sort_order=sort_order)
        if as_json:
            echo_json(items)
            return
        warn_if_stale(client)
        if not items:
            console.print(create_info_panel(
                "Notice", f"[warning]No {collection.label.lower()} match the filters[/warning]",
                style=""))
            return
        page_items, page, pages, start = paginate(items, page, per_page)
        console.print(collection_table(
            collection, page_items,
            f"{collection.label}  page {page} of {pages}"))
        console.print(navigation_panel(f"{command_prefix} list", page, pages, start,
                                       len(page_items), len(items), collection.label.lower()))

    list_cmd.help = f"List {collection.label.lower()}."
    return list_cmd


def get_command_for(collection: Collection):
    @click.command("get")
    @click.argument("identifier", required=False)
    @click.option("--id", "id_option", help=f"{collection.label} ID or slug")
    @click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
    @api_command
    def get_cmd(identifier, id_option, as_json):
        ident = id_option or identifier
        if not ident:
            raise click.UsageError("Provide an ID, e.g. --id <id>")
        client = get_client()
        with console.status(f"[bold green]Fetching {ident}..."):
            item = client.get_item(collection.name, ident)
        if as_json:
            echo_json(item)
            return
        warn_if_stale(client)
        print_document(item_markdown(collection, item, client.site_url))

    get_cmd.help = f"Show full details for one {collection.label.lower()[:-1] or 'item'}."
    return get_cmd


def open_command_for(collection: Collection):
    @click.command("open")
    @click.argument("identifier", required=False)
    @api_command
    def open_cmd(identifier):
        client = get_client()
        if identifier:
            url = collection.web_url(client.site_url, client.get_item(collection.name, identifier))
        else:
            url = f"{client.site_url}/{collection.web_path or collection.name}"
        console.print(f"Opening [link={url}]{url}[/link]")
        webbrowser.open(url)

    open_cmd.help = f"Open {collection.label.lower()} (or one item) in your web browser."
    return open_cmd


def make_collection_group(collection: Collection) -> click.Group:
    group = click.Group(collection.name, help=f"Browse {collection.label.lower()}.")
    group.add_command(list_command_for(collection, f"dzdk {collection.name}"))
    group.add_command(get_command_for(collection))
    group.add_command(open_command_for(collection))
    return group


for _collection in PRIMARY:
    cli.add_command(make_collection_group(_collection))

services = cli.commands["services"]
events = cli.commands["events"]
jobs = cli.commands["jobs"]
news = cli.commands["news"]
resources = cli.commands["resources"]
photos = cli.commands["photos"]


@resources.command("fetch")
@click.option("--id", "identifier", required=True, help="Resource ID or slug")
@click.option("--output", "-o", type=click.Path(dir_okay=False),
              help="Output file name (defaults to the resource title)")
@api_command
def fetch_resource(identifier, output):
    """Download a resource file."""
    client = get_client()
    console.print(create_header("Fetch Resource", f"Downloading resource {identifier}"))
    resource = client.get_item("resources", identifier)
    url = resource.get("downloadUrl") or resource.get("resourceUrl")
    if not url:
        console.print("[red]No download URL available for this resource[/red]")
        sys.exit(1)
    dest = Path(output or safe_filename(f"{title_of(resource)}.{resource.get('fileType') or 'pdf'}"))
    _download_with_progress(client, url, dest)
    console.print(f"[green]Resource successfully saved to {dest}[/green]")


def _download_with_progress(client: DzdkClient, url: str, dest: Path) -> int:
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), DownloadColumn(), console=console, transient=True) as progress:
        task = progress.add_task(f"[accent]{dest.name}", total=None)

        def on_progress(done: int, total: Optional[int]) -> None:
            progress.update(task, completed=done, total=total)

        return client.download(url, dest, on_progress)


@cli.command("browse")
@click.argument("collection_name", metavar="COLLECTION", required=False)
@click.option("--id", "identifier", help="Show one item")
@click.option("--search", "-s", help="Filter by text")
@click.option("--page", type=int, default=1)
@click.option("--per-page", type=int, default=12)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
@api_command
def browse(collection_name, identifier, search, page, per_page, as_json):
    """Browse any collection, e.g. `dzdk browse poets`. Run without arguments to list them."""
    client = get_client()
    if not collection_name:
        table = new_table(title="Collections")
        table.add_column("Name")
        table.add_column("Label")
        table.add_column("Command", style="dim")
        for c in COLLECTIONS.values():
            cmd = f"dzdk {c.name} list" if c.primary else f"dzdk browse {c.name}"
            table.add_row(c.name, c.label, cmd)
        table.add_row("encyclopedia", "Encyclopedia", "dzdk wiki list")
        console.print(table)
        return
    collection = resolve(collection_name)
    if not collection:
        raise click.BadParameter(
            f"Unknown collection. Choose from: {', '.join(COLLECTIONS)}",
            param_hint="COLLECTION")
    if identifier:
        item = client.get_item(collection.name, identifier)
        if as_json:
            echo_json(item)
        else:
            print_document(item_markdown(collection, item, client.site_url))
        return
    with console.status(f"[bold green]Fetching {collection.label.lower()}..."):
        items = client.list_collection(collection.name)
    items = filter_items(items, collection, search=search, sort_by="title")
    if as_json:
        echo_json(items)
        return
    warn_if_stale(client)
    page_items, page, pages, start = paginate(items, page, per_page)
    console.print(collection_table(collection, page_items,
                                   f"{collection.label}  page {page} of {pages}"))
    console.print(f"[dim]Showing {start + 1 if items else 0}-{start + len(page_items)} of "
                  f"{len(items)} · details: dzdk browse {collection.name} --id <ID>[/dim]")


# ----------------------------------------------------------------- search


@cli.command()
@click.argument("query_arg", metavar="QUERY", required=False)
@click.option("--query", "-q", help="Search query")
@click.option("--type", "types", multiple=True,
              help="Limit to a collection (repeatable), e.g. --type services --type jobs")
@click.option("--limit", type=int, default=10, show_default=True, help="Results per collection")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
@api_command
def search(query_arg, query, types, limit, as_json):
    """Search services, resources, events, jobs, news, photos and the encyclopedia."""
    query = query or query_arg
    if not query:
        raise click.UsageError('Provide a query, e.g. dzdk search "legal aid"')
    types = [t for t in types if t != "all"]
    client = get_client()
    with console.status(f"[bold green]Searching for {query!r}..."):
        data = client.search(query, collections=types or None, limit=limit)
    if as_json:
        echo_json(data)
        return
    warn_if_stale(client)
    results: Dict[str, List[Dict[str, Any]]] = data.get("results", {}) or {}
    total = data.get("totalResults", sum(len(v) for v in results.values()))
    console.print(create_header("Search Results", f"{total} results for “{query}”"))
    if not total:
        console.print(create_info_panel("No Results", "[warning]No matching items found[/warning]",
                                        style=""))
        return
    for name, hits in results.items():
        if not hits:
            continue
        coll = COLLECTIONS.get(name)
        label = coll.label if coll else name.replace("-", " ").title()
        table = new_table(title=f"{label} ({len(hits)})",
                      expand=True)
        table.add_column("Title", style="bold", ratio=2, overflow="fold")
        table.add_column("Description", ratio=4, overflow="fold")
        table.add_column("ID", style="dim", ratio=2, overflow="fold")
        for hit in hits[:limit]:
            url = hit.get("url") or ""
            title = escape(hit.get("title", "Untitled"))
            table.add_row(f"[link={url}]{title}[/link]" if url else title,
                          escape(str(hit.get("description") or "")[:200]),
                          escape(str(hit.get("slug") or hit.get("id") or "")))
        console.print(table)
    console.print("[dim]Tip: `dzdk <collection> get --id <ID>` or `dzdk wiki get <ID>` for details[/dim]")


# ----------------------------------------------------------- encyclopedia


@cli.group("wiki")
def wiki():
    """Dzaleka Encyclopedia: sourced reference entries."""


cli.add_command(wiki, "encyclopedia")


def _entries_table(entries: List[Dict[str, Any]], title: str) -> Table:
    table = new_table(title=title, expand=True)
    table.add_column("Title", style="bold", ratio=3, overflow="fold")
    table.add_column("Category", ratio=1)
    table.add_column("Slug", style="dim", ratio=2, overflow="fold")
    for e in entries:
        table.add_row(escape(e.get("title", "")), escape(e.get("category") or NA),
                      escape(e.get("id") or ""))
    return table


@wiki.command("list")
@click.option("--category", "-c", help="Filter by category (e.g. People, History)")
@click.option("--type", "entry_type", help="Filter by entry type (e.g. person, topic)")
@click.option("--status", type=click.Choice(["reviewed", "developing"]))
@click.option("--featured", is_flag=True, default=None, help="Only featured entries")
@click.option("--sort", type=click.Choice(["title", "updated"]), default="title")
@click.option("--order", type=click.Choice(["asc", "desc"]), default="asc")
@click.option("--page", type=int, default=1)
@click.option("--per-page", type=int, default=15)
@click.option("--json", "as_json", is_flag=True)
@api_command
def wiki_list(category, entry_type, status, featured, sort, order, page, per_page, as_json):
    """List encyclopedia entries."""
    client = get_client()
    entries, meta = client.encyclopedia(category=category, entry_type=entry_type, status=status,
                                        featured=featured, page=page, per_page=per_page,
                                        sort=sort, order=order)
    if as_json:
        echo_json({"entries": entries, "meta": meta})
        return
    console.print(_entries_table(
        entries, f"Encyclopedia  page {meta.get('page', page)} of {meta.get('totalPages', '?')}  "
                 f"({meta.get('total', len(entries))} entries)"))
    if meta.get("totalPages", 1) > page:
        console.print(f"[dim]Next: dzdk wiki list --page {page + 1}[/dim]")


@wiki.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=15)
@click.option("--json", "as_json", is_flag=True)
@api_command
def wiki_search(query, limit, as_json):
    """Full-text search of the encyclopedia."""
    entries, meta = get_client().encyclopedia(q=query, per_page=limit)
    if as_json:
        echo_json(entries)
        return
    if not entries:
        console.print(f"[warning]No encyclopedia entries match {query!r}[/warning]")
        return
    console.print(_entries_table(entries, f"{meta.get('total', len(entries))} entries for “{query}”"))


@wiki.command("get")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True)
@api_command
def wiki_get(slug, as_json):
    """Read an encyclopedia entry (with facts, body and sources)."""
    client = get_client()
    try:
        entry = client.encyclopedia_entry(slug)
    except ApiError as error:
        if error.status != 404:
            raise
        suggestions = client.encyclopedia_suggest(slug.replace("-", " "), limit=5) if len(slug) >= 2 else []
        if not suggestions:
            raise
        console.print(f"[warning]No entry '{escape(slug)}'. Did you mean:[/warning]")
        for s in suggestions:
            console.print(f"  • [accent]{escape(s['id'])}[/accent] — {escape(s.get('title', ''))}")
        sys.exit(1)
    if as_json:
        echo_json(entry)
        return
    print_document(entry_markdown(entry))


@wiki.command("suggest")
@click.argument("query")
@click.option("--limit", type=int, default=8)
@api_command
def wiki_suggest(query, limit):
    """Resolve a name to encyclopedia slugs."""
    for s in get_client().encyclopedia_suggest(query, limit=limit):
        console.print(f"[accent]{escape(s['id'])}[/accent]  {escape(s.get('title', ''))} "
                      f"[dim]({escape(s.get('category') or '')})[/dim]")


@wiki.command("categories")
@api_command
def wiki_categories():
    """Show categories, entry types and review status counts."""
    facets = get_client().encyclopedia_facets()
    for key in ("categories", "entryTypes", "statuses"):
        values = facets.get(key) or {}
        if not values:
            continue
        table = new_table(title=key)
        table.add_column("Name")
        table.add_column("Entries", justify="right")
        table.add_column("")
        top = max(values.values())
        for name, count in sorted(values.items(), key=lambda kv: -kv[1]):
            table.add_row(name, str(count), f"[accent]{bar(count, top, 25)}[/accent]")
        console.print(table)


# ------------------------------------------------------------- dashboards


@cli.group()
def population():
    """Population statistics."""


@population.command("stats")
@click.option("--json", "as_json", is_flag=True)
@api_command
def population_stats(as_json):
    """Show the current population snapshot."""
    client = get_client()
    with console.status("[bold green]Fetching population statistics..."):
        data = client.population()
    if as_json:
        echo_json(data)
        return
    warn_if_stale(client)

    def number(v: Any) -> str:
        return f"{v:,}" if isinstance(v, (int, float)) else str(v or NA)

    console.print(Panel(f"[bold]Total population:[/bold] {number(data.get('total'))}\n"
                        f"[bold]New arrivals:[/bold] {number(data.get('newArrivals'))}",
                        title="Population Overview", border_style=BORDER, box=ROUNDED))
    for key, title, color in (("demographics", "Demographics (%)", "yellow"),
                              ("nationalities", "Nationalities (%)", "magenta")):
        values = data.get(key) or {}
        if not values:
            continue
        table = new_table(title=title)
        table.add_column("Group")
        table.add_column("%", justify="right")
        table.add_column("")
        for name, pct in sorted(values.items(), key=lambda kv: -kv[1]):
            table.add_row(str(name).capitalize() if key == "demographics" else str(name),
                          f"{pct}%", f"[accent]{bar(pct, 100, 40)}[/accent]")
        console.print(table)
    trends = data.get("trends") or {}
    values = trends.get("values") or []
    if values:
        table = new_table(title="Population Trend")
        table.add_column("Year")
        table.add_column("Population", justify="right")
        table.add_column("")
        for label, value in zip(trends.get("labels", []), values):
            table.add_row(str(label), f"{value:,}", f"[accent]{bar(value, max(values), 40)}[/accent]")
        console.print(table)


@cli.command()
@click.option("--json", "as_json", is_flag=True)
@api_command
def alerts(as_json):
    """Show emergency and weather alerts."""
    client = get_client()
    emergency = client.alerts()
    weather_alerts = client.weather_alerts()
    if as_json:
        echo_json({"alerts": emergency, "weather": weather_alerts})
        return
    colors = {"critical": "red", "warning": "yellow", "info": "cyan"}
    for alert in emergency:
        color = colors.get(str(alert.get("type")).lower(), "cyan")
        console.print(Panel(escape(alert.get("message", "")),
                            title=f"[bold]{escape(alert.get('title', 'Alert'))}[/bold]",
                            subtitle=f"{alert.get('type', '')} · {fmt_date(alert.get('date'))}",
                            border_style=color, box=ROUNDED))
    for alert in weather_alerts:
        color = colors.get(str(alert.get("type")).lower(), "cyan")
        console.print(Panel(escape(alert.get("description", "")),
                            title=f"Weather: {escape(alert.get('title', 'alert'))}",
                            subtitle=fmt_date(alert.get("publishedAt")),
                            border_style=color, box=ROUNDED))
    if not emergency and not weather_alerts:
        console.print("[green]No active alerts.[/green]")
    console.print(f"[danger]Urgent help:[/danger] [link={GET_HELP_URL}]{GET_HELP_URL}[/link]")


@cli.command()
@click.option("--json", "as_json", is_flag=True)
@api_command
def weather(as_json):
    """Show the Dowa District weather forecast (MET Malawi)."""
    client = get_client()
    data = client.weather()
    if as_json:
        echo_json(data)
        return
    forecast = data.get("forecast") or {}
    current = forecast.get("current") or {}
    console.print(Panel(
        f"[bold]{escape(current.get('condition', NA))}[/bold]\n"
        f"🌡 {current.get('temperature', NA)}°C (max {current.get('maxTemp', NA)}°C)   "
        f"🌧 {current.get('rainfall', NA)} mm   💨 {current.get('windSpeed', NA)} km/h "
        f"{current.get('windDirection', '')}",
        title=f"{escape(data.get('location', 'Weather'))} · {data.get('date', '')} {current.get('time', '')}",
        subtitle=escape(data.get("sourceLabel", "")) + (" · stale" if data.get("stale") else ""),
        border_style=BORDER, box=ROUNDED))
    hourly = forecast.get("hourly") or []
    if hourly:
        table = new_table()
        for col in ("Time", "Condition", "Max °C", "Rain mm", "Wind"):
            table.add_column(col)
        for h in hourly:
            table.add_row(str(h.get("time", "")), escape(str(h.get("condition", ""))),
                          str(h.get("maxTemp", "")), str(h.get("rainfall", "")),
                          f"{h.get('windSpeed', '')} {h.get('windDirection', '')}")
        console.print(table)


@cli.group()
def stats():
    """Statistics and analytics."""


@stats.command("services")
@click.option("--output", type=click.Path(dir_okay=False), help="Save a Markdown report")
@api_command
def service_statistics(output):
    """Show service distribution by category and status."""
    client = get_client()
    with console.status("[bold green]Analyzing services..."):
        items = client.list_collection("services")
    if not items:
        console.print(create_info_panel("Notice", "[warning]No services found[/warning]"))
        return
    total = len(items)
    by_category: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for s in items:
        cat = s.get("category") or "Uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
        st = str(s.get("status") or "unknown").lower()
        by_status[st] = by_status.get(st, 0) + 1
    console.print(create_header("Service Statistics", f"{total} services"))
    status_lines = "\n".join(f"{k.title()}: {v} ({v / total * 100:.1f}%)"
                             for k, v in sorted(by_status.items(), key=lambda kv: -kv[1]))
    console.print(Panel(f"[bold]Total Services:[/bold] {total}\n\n[bold]Status[/bold]\n{status_lines}",
                        title="Overall Statistics", border_style=BORDER, box=ROUNDED))
    table = new_table(title="Category Distribution")
    table.add_column("Category")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    table.add_column("")
    ranked = sorted(by_category.items(), key=lambda kv: -kv[1])
    for cat, count in ranked:
        table.add_row(escape(cat), str(count), f"{count / total * 100:.1f}%",
                      f"[accent]{bar(count, ranked[0][1], 30)}[/accent]")
    console.print(table)
    if output:
        lines = [f"# Service Statistics Report", f"Generated on: {datetime.now():%Y-%m-%d %H:%M:%S}",
                 "", f"- Total Services: {total}", "", "## Status"]
        lines += [f"- {k}: {v} ({v / total * 100:.1f}%)" for k, v in by_status.items()]
        lines += ["", "## Categories"]
        lines += [f"- {c}: {n} ({n / total * 100:.1f}%)" for c, n in ranked]
        Path(output).write_text("\n".join(lines) + "\n")
        console.print(create_info_panel("Report Generated", f"Saved to: {output}"))


@stats.command("overview")
@click.option("--json", "as_json", is_flag=True)
@api_command
def stats_overview(as_json):
    """Item counts for every collection (one request) plus funding data."""
    client = get_client()
    names = [c.name for c in COLLECTIONS.values()]
    with console.status("[bold green]Exporting collections..."):
        data = client.export(names)
        try:
            finance = client.finance()
        except ApiError:
            finance = {}
    counts = {name: len(items) for name, items in data.items()}
    if as_json:
        echo_json({"counts": counts, "finance": finance})
        return
    table = new_table(title="Collections")
    table.add_column("Collection")
    table.add_column("Items", justify="right")
    table.add_column("")
    top = max(counts.values() or [1])
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        c = COLLECTIONS[name]
        table.add_row(c.label, str(count), f"[accent]{bar(count, top, 30)}[/accent]")
    console.print(table)
    if finance.get("budget"):
        funded = finance.get("funded", 0) / finance["budget"] * 100
        console.print(Panel(
            f"Budget: ${finance['budget']:,}\nFunded: ${finance.get('funded', 0):,} ({funded:.1f}%)\n"
            f"Gap:    ${finance.get('gap', 0):,}\n[green]{bar(funded, 100, 40)}[/green]\n"
            f"[dim]Source: {escape(str(finance.get('source', '')))} · "
            f"{fmt_date(finance.get('lastUpdated'))}[/dim]",
            title="UNHCR Malawi funding", border_style=BORDER, box=ROUNDED))


# ------------------------------------------------------------ batch/export


@cli.group()
def batch():
    """Batch downloads."""


@batch.command("download")
@click.option("--type", "kind", type=click.Choice(["resources", "photos"]), required=True,
              help="Type of content to download")
@click.option("--ids", required=True, help="Comma-separated list of IDs to download")
@click.option("--output-dir", type=click.Path(file_okay=False), default="downloads",
              help="Output directory")
@api_command
def batch_download(kind, ids, output_dir):
    """Download several resources or photos."""
    client = get_client()
    console.print(create_header("Batch Download", f"Downloading {kind}"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    items = {item_id(i): i for i in client.list_collection(kind)}
    ok = 0
    for ident in wanted:
        item = items.get(ident)
        if not item:
            console.print(f"[yellow]Not found: {escape(ident)}[/yellow]")
            continue
        url = item.get("downloadUrl") if kind == "resources" else (item.get("image") or item.get("url"))
        if not url:
            console.print(f"[yellow]No download URL for {escape(ident)}[/yellow]")
            continue
        suffix = item.get("fileType") if kind == "resources" else (
            Path(url.split("?")[0]).suffix.lstrip(".") or "jpg")
        dest = output / safe_filename(f"{title_of(item)}.{suffix or 'bin'}")
        try:
            _download_with_progress(client, url, dest)
            console.print(f"[green]Downloaded: {dest.name}[/green]")
            ok += 1
        except ApiError as error:
            console.print(f"[red]Error downloading {escape(ident)}: {escape(str(error))}[/red]")
    console.print(create_info_panel(
        "Download Complete", f"{ok} of {len(wanted)} files saved to: {output.absolute()}"))


@cli.group()
def export():
    """Export data to CSV, Markdown or JSON."""


def _export_items(client: DzdkClient, kind: str) -> List[Dict[str, Any]]:
    if kind == "population":
        return [client.population()]
    if kind == "encyclopedia":
        entries, meta = client.encyclopedia(per_page=100)
        page = 1
        while meta.get("totalPages", 1) > page:
            page += 1
            more, meta = client.encyclopedia(per_page=100, page=page)
            entries += more
        return entries
    return client.list_collection(kind)


@export.command("csv")
@click.option("--type", "kind", type=click.Choice(EXPORTABLE), required=True)
@click.option("--output", "-o", type=click.Path(dir_okay=False), required=True)
@api_command
def export_csv(kind, output):
    """Export a collection to CSV (nested fields are flattened)."""
    client = get_client()
    console.print(create_header("CSV Export", f"Exporting {kind} data"))
    items = [flatten(i) for i in _export_items(client, kind)]
    if not items:
        console.print(create_info_panel("No Data", "[warning]No data found to export[/warning]"))
        return
    fields: List[str] = []
    for i in items:
        fields += [k for k in i if k not in fields]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(items)
    console.print(create_info_panel("Export Complete",
                                    f"{len(items)} rows exported to: {output}"))


@export.command("report")
@click.option("--type", "kind", type=click.Choice(EXPORTABLE), required=True)
@click.option("--output", "-o", type=click.Path(dir_okay=False), required=True)
@api_command
def export_report(kind, output):
    """Generate a Markdown report."""
    client = get_client()
    console.print(create_header("Report Generation", f"Generating {kind} report"))
    items = _export_items(client, kind)
    if not items:
        console.print(create_info_panel("No Data", "[warning]No data found to report[/warning]"))
        return
    collection = COLLECTIONS.get(kind)
    parts = [f"# {kind.replace('-', ' ').title()} Report\n",
             f"Generated on {datetime.now():%Y-%m-%d %H:%M:%S} from {client.base_url}\n",
             f"Total items: {len(items)}\n",
             "Content: Dzaleka Online Services, CC BY-SA 4.0 unless stated otherwise.\n"]
    for item in items:
        if collection:
            parts.append(item_markdown(collection, item, client.site_url).replace("# ", "## ", 1))
        elif kind == "encyclopedia":
            parts.append(entry_markdown(item).replace("# ", "## ", 1))
        else:
            parts.append("```json\n" + json.dumps(item, indent=2, ensure_ascii=False) + "\n```")
    Path(output).write_text("\n\n".join(parts), encoding="utf-8")
    console.print(create_info_panel("Report Generated", f"Report has been saved to: {output}"))


@export.command("json")
@click.option("--type", "kind", type=click.Choice(EXPORTABLE), required=True)
@click.option("--output", "-o", type=click.Path(dir_okay=False), required=True)
@api_command
def export_json(kind, output):
    """Export a collection as JSON."""
    items = _export_items(get_client(), kind)
    Path(output).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(create_info_panel("Export Complete", f"{len(items)} items saved to: {output}"))


@export.command("all")
@click.option("--output", "-o", type=click.Path(dir_okay=False), required=True)
@click.option("--collections", help="Comma-separated subset (default: all)")
@api_command
def export_all(output, collections):
    """Export many collections in a single API request (POST /api/export)."""
    names = [c.strip() for c in collections.split(",")] if collections else list(COLLECTIONS)
    with console.status("[bold green]Exporting..."):
        data = get_client().export(names)
    Path(output).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = ", ".join(f"{k}: {len(v)}" for k, v in data.items())
    console.print(create_info_panel("Export Complete", f"Saved to {output}\n[dim]{summary}[/dim]"))


# ------------------------------------------------------------------ chart


@cli.command()
@click.argument("chart_ids", metavar="[CHART]...", nargs=-1)
@click.option("--group", "-g", help="Draw every chart in a group, e.g. Population or Needs")
@click.option("--list", "list_only", is_flag=True, help="List the available charts")
@click.option("--width", type=int, help="Chart width (default: terminal width)")
@click.option("--height", type=int, default=16, show_default=True, help="Chart height")
@api_command
def chart(chart_ids, group, list_only, width, height):
    """Draw charts in the terminal, the same ones as the app's Insights tab.

    Run `dzdk chart --list` to see them, then e.g. `dzdk chart population-growth`
    or `dzdk chart --group Needs`.
    """
    import plotext

    from dzdk.insights import CHARTS, CHARTS_BY_ID, GROUPS, Palette, fetch_for, incidents

    if list_only or (not chart_ids and not group):
        table = new_table("Charts")
        table.add_column("ID", style="bold")
        table.add_column("Group")
        table.add_column("Shows")
        for spec in CHARTS:
            table.add_row(spec.id, spec.group, spec.title)
        console.print(table)
        console.print(Text("Draw one with: dzdk chart <ID>   or a group with: dzdk chart -g "
                           + GROUPS[0], style="dim"))
        return
    specs = []
    if group:
        specs += [s for s in CHARTS if s.group.lower() == group.lower()]
        if not specs:
            raise click.BadParameter(f"Choose from: {', '.join(GROUPS)}", param_hint="--group")
    for chart_id in chart_ids:
        if chart_id not in CHARTS_BY_ID:
            raise click.BadParameter(f"Unknown chart '{chart_id}'. Run: dzdk chart --list",
                                     param_hint="CHART")
        specs.append(CHARTS_BY_ID[chart_id])
    client = get_client()
    with console.status("[bold green]Fetching data..."):
        data = fetch_for(client, specs)
    warn_if_stale(client)
    palette = Palette()
    for spec in specs:
        plotext.clf()
        plotext.theme("clear")
        plotext.plotsize(width or min(console.width, 100), height)
        spec.draw(plotext, data, palette)
        console.print(Text.assemble((spec.title, "bold"), "  ", (spec.subtitle(data), "dim")))
        console.print(Text.from_ansi(plotext.build()))
        console.print()
    if any(s.group == "Needs" for s in specs) and group:
        console.print(Text("Major incidents", style="bold"))
        for when, what in incidents(data):
            console.print(f"  [dim]{escape(when):<9}[/dim] [red]●[/red] {escape(what)}")


# -------------------------------------------------------------------- mcp


@cli.command()
@api_command
def mcp():
    """Show the Dzaleka MCP server and how to connect AI assistants to it."""
    client = get_client()
    card = client.mcp_card()
    streamable = next((t for t in card.get("transports", []) if t.get("type") == "streamable-http"),
                      {})
    endpoint = streamable.get("endpoint", f"{client.site_url}/.well-known/mcp")
    table = new_table(title=f"{card.get('serverInfo', {}).get('title', 'MCP server')} tools")
    table.add_column("Tool", style="bold")
    table.add_column("Description", overflow="fold")
    for tool in card.get("tools", []):
        table.add_row(tool.get("name", ""), escape(tool.get("description", "")))
    console.print(table)
    console.print(create_info_panel("Connect", (
        f"[bold]Endpoint:[/bold] {endpoint} (streamable HTTP, no auth, read-only)\n\n"
        f"[bold]Claude Code:[/bold]\n  claude mcp add --transport http dzaleka {endpoint}\n\n"
        f"[bold]JSON config:[/bold]\n"
        f'  {{"mcpServers": {{"dzaleka": {{"type": "http", "url": "{endpoint}"}}}}}}\n\n'
        f"[dim]Docs: {card.get('documentationUrl', '')}[/dim]")))


# -------------------------------------------------------------- tui/serve


@cli.command()
@click.option("--tab", type=click.Choice(["home", "insights", "wiki", "search"] + [c.name for c in PRIMARY]),
              default="home", help="Tab to open first")
@click.option("--size", metavar="COLSxROWS",
              help="Grow the terminal window to at least this size (default from config: 140x42)")
@click.option("--no-resize", is_flag=True, help="Leave the terminal window size alone")
def tui(tab, size, no_resize):
    """Launch the full-screen terminal app (Textual).

    If the window is smaller than the app needs, dzdk asks the terminal to grow it
    (macOS Terminal, iTerm2 and xterm support this) and puts it back when you quit.
    The layout also adapts to small and resized windows.
    """
    from dzdk.tui.app import DzdkApp
    from dzdk.tui.terminal import grow_window, parse_size, restore_window

    config = get_config()
    target = None if no_resize else parse_size(size or config.get("window_size", "140x42"))
    if size and not no_resize and target is None:
        raise click.BadParameter("use COLSxROWS, e.g. 160x48", param_hint="--size")
    previous = grow_window(target) if target else None
    try:
        DzdkApp(client=get_client(), config=config, initial_tab=tab).run()
    finally:
        restore_window(previous)


@cli.command()
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
def serve(host, port):
    """Serve the terminal app in a web browser (needs `pip install dzdk[serve]`)."""
    try:
        from textual_serve.server import Server
    except ImportError:
        console.print("[red]textual-serve is not installed.[/red] Run: pip install 'dzdk[serve]'")
        sys.exit(1)
    command = f"{shlex.quote(sys.executable)} -m dzdk tui"
    console.print(f"Serving dzdk at [link=http://{host}:{port}]http://{host}:{port}[/link]")
    Server(command, host=host, port=port, title="dzdk").serve()


# ------------------------------------------------------------------ shell


@cli.command()
def shell():
    """Start an interactive shell with history and completion."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import NestedCompleter
    from prompt_toolkit.history import FileHistory

    def tree(command: click.Command) -> Any:
        if isinstance(command, click.Group):
            return {name: tree(sub) for name, sub in command.commands.items() if not sub.hidden}
        return None

    completions = tree(cli)
    completions.update({"help": None, "exit": None, "clear": None})
    history = config_dir() / "history"
    history.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(history=FileHistory(str(history)),
                            auto_suggest=AutoSuggestFromHistory(),
                            completer=NestedCompleter.from_nested_dict(completions))
    console.print(Panel("[bold cyan]dzdk interactive shell[/bold cyan]\n"
                        "[dim]Tab to complete · 'help' for commands · 'exit' or Ctrl-D to quit[/dim]",
                        border_style=BORDER, box=ROUNDED))
    root = click.get_current_context().find_root()
    while True:
        try:
            line = session.prompt("dzdk> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line == "clear":
            console.clear()
            continue
        args = shlex.split(line)
        if args[0] == "help":
            args = args[1:] + ["--help"]
        if args and args[0] == "dzdk":
            args = args[1:]
        if args and args[0] in ("shell", "tui"):
            console.print("[yellow]Run that from your normal terminal.[/yellow]")
            continue
        try:
            cli.main(args=args, standalone_mode=False, obj=dict(root.obj))
        except click.ClickException as error:
            error.show()
        except click.exceptions.Abort:
            pass
        except SystemExit:
            pass
    console.print("[green]Goodbye![/green]")


def main() -> None:  # console_scripts entry point
    cli(prog_name="dzdk")


if __name__ == "__main__":
    main()
