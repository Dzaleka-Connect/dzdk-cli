# dzdk reference

This is the complete reference for `dzdk` 0.2. For an introduction, see the [README](README.md).

- [Configuration](#configuration)
- [Global options](#global-options)
- [Collections](#collections)
- [Search](#search)
- [Encyclopedia](#encyclopedia)
- [Live data](#live-data)
- [Charts](#charts)
- [Downloads and exports](#downloads-and-exports)
- [Diagnostics](#diagnostics)
- [The app](#the-app)
- [Interactive shell](#interactive-shell)
- [How dzdk uses the API](#how-dzdk-uses-the-api)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Configuration

Settings live in `~/.config/dzdk/config.yaml`. Set `DZDK_CONFIG_DIR` to use another
directory. The file is created the first time you change a setting; until then the defaults
apply.

| Setting | Default | Meaning |
|---|---|---|
| `api_url` | `https://services.dzaleka.com/api` | API base URL. `/api` is added if missing. |
| `timeout` | `30` | Seconds before a request is abandoned |
| `cache_ttl` | `300` | Seconds a cached response counts as fresh. `0` turns the cache off. |
| `offline_fallback` | `true` | When the network fails, show the last cached copy instead of an error |
| `theme` | `dzaleka` | Theme for `dzdk tui` |
| `window_size` | `140x42` | Size `dzdk tui` grows a smaller terminal window to, as `COLUMNSxROWS`, or `off` |
| `sidebar_width` | `46` | Width of the list pane in the app, in percent (25–75). Changed with `[` and `]`. |

```bash
dzdk show-config                       # current settings and file locations
dzdk config --interactive              # prompts for URL and timeout
dzdk config --url https://services.dzaleka.com/api --timeout 60
dzdk config --cache-ttl 3600
dzdk config --no-offline-fallback
dzdk config --theme dzaleka-light
dzdk config --window-size 160x48       # or: off
dzdk config --clear-cache
dzdk config --reset                    # restore every default
```

## Global options

| Option | Meaning |
|---|---|
| `--no-cache` | Skip the cache for this command. Put it before the command: `dzdk --no-cache jobs list`. |
| `--version` | Print the version |
| `-h`, `--help` | Help for any command |

## Collections

Six collections have their own command group: `services`, `events`, `jobs`, `news`,
`resources` and `photos`. Each group has `list`, `get` and `open`.

### list

```bash
dzdk <collection> list [options]
```

| Option | Meaning |
|---|---|
| `-s`, `--search TEXT` | Keep items whose title, description, category and similar fields contain TEXT |
| `-c`, `--category TEXT` | Keep items whose category contains TEXT (not available for photos) |
| `--status TEXT` | Exact status, for example `active`, `open` or `past` |
| `--sort-by FIELD` | Sort field; the choices depend on the collection |
| `--sort-order asc\|desc` | Sort direction |
| `--page N` | Page to show |
| `--per-page N` | Items per page (default 12) |
| `--categories` | Print the categories in use, one per line, then exit |
| `--json` | Print every matching item as JSON, ignoring pagination |

Examples:

```bash
dzdk services list --category health
dzdk jobs list --status open --sort-by deadline
dzdk news list --sort-by date --sort-order desc --per-page 5
dzdk resources list --search "annual report" --json
```

### get

```bash
dzdk <collection> get <ID>
dzdk <collection> get --id <ID>
```

Shows every field for one item: contact details, location with an OpenStreetMap link,
registration details for events, skills and deadlines for jobs, download links for resources.
IDs appear in the last column of `list`. Add `--json` for the raw record.

### open

```bash
dzdk <collection> open [ID]
```

Opens the item on services.dzaleka.com in your web browser. Without an ID, opens the
collection page.

### resources fetch

```bash
dzdk resources fetch --id <ID> [--output FILE]
```

Downloads the resource's file. Without `--output`, the file is named after the resource's title.

### Other collections

The API has more collections than the six above. `dzdk browse` lists them all. To browse one:

```bash
dzdk browse                      # list every collection
dzdk browse poets
dzdk browse marketplace --search food
dzdk browse courses --id <ID>
dzdk browse artists --json
```

The available collections are `courses`, `community-voices`, `talents`, `profiles`,
`artists`, `artworks`, `poets`, `dancers`, `marketplace`, `stores`, `rights` and `docs`.

## Search

```bash
dzdk search QUERY [--type COLLECTION ...] [--limit N] [--json]
```

Searches every collection in one request (`GET /api/search`), including the encyclopedia and
docs. Results are grouped by collection. `--type` narrows the search and can be repeated.
`--limit` is the maximum per collection (default 10). The older `--query` form still works.

```bash
dzdk search "legal aid"
dzdk search school --type services --type jobs
```

## Encyclopedia

The Dzaleka Encyclopedia holds sourced entries on the camp's history, people, places and
institutions. `dzdk encyclopedia` is an alias for `dzdk wiki`.

| Command | Purpose |
|---|---|
| `dzdk wiki list` | Browse entries. Options: `--category`, `--type`, `--status reviewed\|developing`, `--featured`, `--sort title\|updated`, `--order`, `--page`, `--per-page`, `--json` |
| `dzdk wiki search QUERY` | Full-text search |
| `dzdk wiki get SLUG` | Read an entry: summary, facts, body, related entries and numbered sources. An unknown slug suggests close matches. |
| `dzdk wiki suggest TEXT` | Turn a name into slugs |
| `dzdk wiki categories` | Counts by category, entry type and review status |

## Live data

| Command | Shows |
|---|---|
| `dzdk alerts` | Emergency alerts and weather warnings, and the urgent-help link |
| `dzdk weather` | Current conditions and today's forecast for Dowa District (MET Malawi) |
| `dzdk population stats` | Total population, new arrivals, demographics, nationalities, trend |
| `dzdk stats services` | Services by category and status. `--output FILE` saves a Markdown report. |
| `dzdk stats overview` | Item counts for every collection and UNHCR Malawi funding |

All of these accept `--json` except `stats services`.

## Charts

```bash
dzdk chart --list                          # every chart, with its ID and group
dzdk chart population-growth nationalities # one or more charts by ID
dzdk chart --group Needs                   # a whole group
dzdk chart funding --width 80 --height 12
```

These are the charts from the app's Insights tab, drawn with plotext in the current
terminal.

| ID | Group | Shows | Data |
|---|---|---|---|
| `population-growth` | Population | Camp population, 1994–2024 | `/api/charts` |
| `nationalities` | Population | Residents by nationality | `/api/population` |
| `demographics` | Population | Women, children and men | `/api/population` |
| `challenges` | Needs | Challenge impact scores | `/api/charts` |
| `capacity` | Needs | Service capacity against demand | `/api/charts` |
| `funding` | Needs | UNHCR Malawi budget, funded and gap | `/api/finance` |
| `services-by-category` | Directory | Services by category | `/api/services` |
| `encyclopedia-categories` | Directory | Entries by category | `/api/encyclopedia/facets` |
| `resources-by-category` | Directory | Resources by category | `/api/resources` |
| `news-per-month` | Activity | News published in each of the last 12 months | `/api/news` |
| `events-per-month` | Activity | Events in each of the last 18 months | `/api/events` |
| `jobs-by-type` | Activity | Jobs by type | `/api/jobs` |
| `temperature` | Weather | Temperature over the next hours | `/api/weather` |
| `rainfall` | Weather | Rainfall over the next hours | `/api/weather` |

`--group Needs` also prints the major incidents timeline from `/api/charts`.

## Downloads and exports

| Command | Output |
|---|---|
| `dzdk export csv --type T -o FILE` | CSV; nested fields are flattened, e.g. `contact_email` |
| `dzdk export json --type T -o FILE` | JSON array |
| `dzdk export report --type T -o FILE` | Markdown report with one section per item |
| `dzdk export all -o FILE [--collections a,b]` | Many collections in one request (`POST /api/export`) |
| `dzdk batch download --type resources\|photos --ids a,b,c [--output-dir DIR]` | Downloads files for several items |

`--type` accepts any collection, plus `encyclopedia` and `population`.

## Diagnostics

| Command | Purpose |
|---|---|
| `dzdk health` | Checks the status endpoint and each main collection, with timings. Exits with 1 if any check fails. |
| `dzdk status` | API version, documentation links and your remaining rate limit |
| `dzdk mcp` | Tools offered by the Dzaleka MCP server, with setup instructions |

## The app

```bash
dzdk tui [--tab home|insights|services|wiki|events|jobs|news|resources|photos|search]
         [--size COLSxROWS] [--no-resize]
dzdk serve [--host HOST] [--port PORT]       # needs: pip install "dzdk[serve]"
```

Each tab loads its data the first time you open it, so starting the app costs only the
requests needed for the Home tab. The Insights tab works the same way for each chart group.

### Window size and layout

If the terminal window is smaller than `window_size` (140×42 by default), `dzdk tui` asks
the terminal to grow it with the standard `CSI 8 ; rows ; cols t` sequence, and restores the
original size on exit. It only asks macOS Terminal, iTerm2 and xterm, which are known to
honour the request. It never shrinks a window, and never grows one dimension past what is
needed. `--size` overrides the target for one run; `--no-resize` or
`dzdk config --window-size off` turns this off.

Whatever the size, the layout adapts, and it updates live when you resize the window:

| Window | Layout |
|---|---|
| 110 columns or wider | Lists beside their details; dashboard and charts in two or more columns |
| Narrower than 110 | Lists stacked above details; dashboard stats in a 2×2 grid; charts in one column |
| Narrower than 80 | Stats in one column; the title bar drops the product name |
| Shorter than 34 rows | Smaller logo and a tighter header |

In any layout, `[` and `]` change the list pane's share of the space, and `z` zooms the
focused pane or chart to the full window.

Every list and detail area is a titled pane. The title shows what the pane holds, and the
bottom edge shows counts and sort order. The pane with keyboard focus has a green border. The key bindings are listed in the [README](README.md#keys)
and in the app under `F1`.

The command palette (`Ctrl+P`) searches:

- tabs, and pages such as the map, datasets and urgent help
- every item already loaded in this session, by title
- the whole site, through the "Search everything" entry

## Interactive shell

```bash
dzdk shell
```

This is a prompt that runs `dzdk` commands without typing `dzdk` each time. It has
tab completion for commands and subcommands, suggestions from your history (stored in
`~/.config/dzdk/history`), and `help`, `clear` and `exit`.

## How dzdk uses the API

- **Read-only.** The public API accepts no uploads or edits. To add or change a listing, use
  the forms on services.dzaleka.com.
- **Rate limit.** The API allows 60 requests a minute per IP address. `dzdk` reads the
  `RateLimit-*` headers; the app shows the remaining count in its top bar. If the limit is hit,
  `dzdk` waits for the time given in `Retry-After` (at most 10 seconds) and retries up to twice.
- **Errors.** The API describes problems in RFC 9457 `problem+json` format. `dzdk` shows the
  message, the detail, how to fix it, and the error code.
- **Versioning.** Every request sends `API-Version: 1.0.0`, so a future major version will not
  change the responses dzdk receives without warning.
- **Identification.** Requests carry a `User-Agent` naming dzdk and its version.
- **Item lookups.** The API has no per-item URLs, so `get` fetches the collection (usually from
  the cache) and picks the item by ID.

## Troubleshooting

**"Network error" or a timeout.** Check your connection and `dzdk show-config`. If you
viewed the data recently, `dzdk` shows the cached copy, marked as offline. Raise
`--timeout` on slow links.

**"HTTP 429: Too many requests".** You have used the 60 requests allowed this minute. Wait for
the reset time shown by `dzdk status`. Keep the cache on (`cache_ttl` above 0) so repeated
commands don't use requests.

**"The endpoint returned a web page, not JSON".** `api_url` points at the website rather than
the API. Run `dzdk config --url https://services.dzaleka.com/api`.

**Garbled borders or missing colours in the app.** Use a terminal with Unicode and 256-colour
support, for example Windows Terminal, iTerm2, GNOME Terminal or kitty. Over SSH, make sure
`TERM` is set (for example `xterm-256color`).

**`ModuleNotFoundError: No module named 'dzdk'` from an editable install on macOS.** If the
project is in an iCloud-synced folder such as `Documents`, iCloud marks files inside
dot-folders like `.venv` as hidden, and Python 3.13 skips hidden `.pth` files. Name the
environment `venv` instead, or run `chflags -R nohidden .venv`.

**The window does not grow when the app starts.** Only macOS Terminal, iTerm2 and xterm are
asked. In iTerm2, check that "Disable session-initiated window resizing" is off (Settings →
Profiles → Terminal). Other terminals, such as VS Code's, keep their size; resize the window
yourself, or use `z` to zoom a pane.

**The logo looks blocky or broken.** It is drawn with Unicode quadrant blocks (`▗ ▖ ▟ ▙` and
similar). Use a font that includes them; most modern terminal fonts do.

**Charts look like scattered dots.** The line charts use braille characters. Use a font with
braille glyphs (most modern terminal fonts have them), or compare with the bar charts,
which use block characters.

**Links don't open.** `o` and `open` use your system's default browser. Over SSH, copy the
link with `y` instead.

## Development

```bash
pip install -e ".[dev]"
pytest                                  # tests with a coverage report
textual run --dev dzdk.tui.app:DzdkApp  # app with live stylesheet reloading
textual console                         # in a second terminal: logs and print output
```

| Path | Contents |
|---|---|
| `dzdk/api.py` | `DzdkClient`: requests, `ApiError`, rate limit tracking, response cache |
| `dzdk/config.py` | Loading and saving `config.yaml` |
| `dzdk/catalog.py` | The collection registry: labels, table columns, search fields, sort fields |
| `dzdk/render.py` | Markdown detail views and formatting helpers, shared by the commands and the app |
| `dzdk/insights.py` | Chart specs and data helpers, shared by `dzdk chart` and the Insights tab |
| `dzdk/cli.py` | Click commands |
| `dzdk/tui/app.py` | `DzdkApp`, themes, help screen, navigation |
| `dzdk/tui/widgets.py` | Home, collection, encyclopedia and search panes |
| `dzdk/tui/charts.py` | Insights tab: chart widgets drawn with textual-plotext |
| `dzdk/tui/commands.py` | Command palette provider |
| `dzdk/tui/terminal.py` | Growing and restoring the terminal window around `dzdk tui` |
| `dzdk/tui/logo.py` | The logo as quadrant-block text (generated) |
| `scripts/make_logo.py` | Regenerates `logo.py` from `docs/images/dzaleka-logo.png`: `uv run --with pillow scripts/make_logo.py` |
| `dzdk/tui/dzdk.tcss` | App stylesheet |
| `tests/` | `responses`-mocked API tests and Textual pilot tests |

To add a chart, add a `ChartSpec` to `CHARTS` in `dzdk/insights.py`. It then appears in the
app and in `dzdk chart`, and the tests draw it automatically.

To add a collection, add an entry to `COLLECTIONS` in `dzdk/catalog.py`. Set `primary=True`
to give it its own command group and app tab. For a custom detail view, add a renderer in
`dzdk/render.py`.

Releases are published to PyPI by the GitHub workflow when a GitHub release is created.
