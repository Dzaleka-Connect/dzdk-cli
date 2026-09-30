# Changelog

## 0.2.0

### Added

- `dzdk tui`: a full-screen app with Home, Services, Encyclopedia, Events, Jobs, News,
  Resources, Photos and Search tabs. It has a command palette, keyboard navigation, and dark
  and light themes.
- An Insights tab in the app with 14 charts in five groups (Population, Needs,
  Directory, Activity, Weather), drawn with textual-plotext, plus an incidents timeline.
- `dzdk chart` prints the same charts in an ordinary terminal.
- Panes have titles set into their borders; the focused pane is outlined in green.
- The Dzaleka Online Services logo in the app's header and the CLI welcome, drawn in
  Unicode quadrant blocks.
- `dzdk tui` grows a small terminal window to 140×42 on launch (macOS Terminal, iTerm2,
  xterm) and restores it on exit. `--size`, `--no-resize` and `config --window-size`
  control this.
- The layout adapts to small windows and to live resizing. `[` and `]` resize the list
  pane, and `z` zooms the focused pane or chart.
- `dzdk serve` runs the app in a web browser (requires the `serve` extra).
- New command groups: `jobs`, `news` and `wiki` (alias `encyclopedia`). New commands:
  `browse`, `alerts`, `weather`, `status`, `mcp`, `stats overview`, `export json` and
  `export all`.
- `search` now uses the API's own search endpoint, which covers every collection including
  the encyclopedia.
- `--json` on list and detail commands. `open` subcommands open items in the browser.
- A response cache, with offline fallback to cached data.
- The client respects the API's rate limit and retries after a 429. It shows the API's error
  details, including how to fix the problem.

### Changed

- `dzdk.py` is now the `dzdk` package: `api`, `catalog`, `render`, `cli` and `tui`.
- `get` commands take the ID as an argument (`dzdk services get inua-advocacy`). `--id`
  still works.
- `health` checks `/api/status` and every main collection, and exits with 1 on failure.
- CLI output uses borderless tables, one accent colour and no emoji.
- Python 3.9 or later is required. `pandas` and `tabulate` are no longer dependencies.

### Removed

These commands called endpoints that the public API does not provide, so they always failed:

- `photos upload`, `photos edit`, `photos metadata` and `photos album ...`
- `batch upload`
- `stats usage`, which showed made-up sample numbers

The public API is read-only. To add or change content, use the forms on
services.dzaleka.com.

### Fixed

- `resources fetch` now downloads the file itself rather than the API's JSON response.
- `batch download --type photos` uses the photo's `image` URL.
- `population stats` no longer crashes when a value is missing.
