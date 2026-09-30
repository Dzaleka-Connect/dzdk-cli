"""Chart definitions shared by the Insights tab (`dzdk tui`) and `dzdk chart`.

Each chart is a ChartSpec: what to fetch, and a draw function that receives a
plotext-compatible object. In the app that is `PlotextPlot.plt`; on the command
line it is the `plotext` module itself, so both render identical charts.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from dzdk.api import DzdkClient
from dzdk.render import parse_date

RGB = Tuple[int, int, int]


@dataclass
class Palette:
    """Colours handed to draw functions, taken from the active theme."""

    primary: RGB = (79, 178, 94)
    muted: RGB = (125, 139, 150)
    warning: RGB = (217, 164, 65)
    error: RGB = (224, 82, 74)
    text: RGB = (220, 225, 229)
    background: Optional[RGB] = None  # None keeps the terminal's own background

    @classmethod
    def from_hex(cls, **colors: Optional[str]) -> "Palette":
        values = {k: hex_to_rgb(v) for k, v in colors.items() if v}
        return cls(**values)


def hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")[:6]
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


# ------------------------------------------------------------------ helpers


def compact(n: float) -> str:
    """12000 -> 12k, 1500000 -> 1.5M"""
    n = float(n)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= size:
            text = f"{n / size:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{round(n, 1):g}"


def shorten(label: str, width: int = 22) -> str:
    return label if len(label) <= width else label[: width - 1] + "…"


def counts_by(items: Sequence[Dict[str, Any]], field: str, top: int = 10) -> List[Tuple[str, int]]:
    """Most common values of a field, largest first, with the rest grouped as Other."""
    counter = Counter(str(i.get(field) or "Unspecified").strip() for i in items)
    ranked = counter.most_common()
    head, tail = ranked[:top], ranked[top:]
    if tail:
        head.append(("Other", sum(n for _, n in tail)))
    return head


def per_month(items: Sequence[Dict[str, Any]], field: str, months: int = 12,
              today: Optional[datetime] = None) -> List[Tuple[str, int]]:
    """Item counts for each of the last `months` calendar months (oldest first)."""
    today = today or datetime.now()
    keys = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    keys.reverse()
    counts = Counter()
    for item in items:
        parsed = parse_date(item.get(field))
        if parsed:
            counts[(parsed.year, parsed.month)] += 1
    return [(datetime(y, m, 1).strftime("%b %y"), counts[(y, m)]) for y, m in keys]


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------ draw helpers


def _base(plt, palette: Palette) -> None:
    if palette.background:
        plt.canvas_color(palette.background)
        plt.axes_color(palette.background)
    plt.frame(False)
    plt.xaxes(True, False)
    plt.yaxes(True, False)
    plt.ticks_color(palette.muted)


def draw_hbar(plt, labels: Sequence[str], values: Sequence[float], palette: Palette,
              suffix: str = "", color: Optional[RGB] = None) -> None:
    _base(plt, palette)
    # plotext draws horizontal bars bottom-up; reverse so the largest is on top.
    labels = [shorten(label) for label in labels][::-1]
    values = list(values)[::-1]
    plt.bar(labels, values, orientation="horizontal", width=0.6, marker="sd",
            color=color or palette.primary)
    top = max(values or [1])
    ticks = [top * f for f in (0, 0.5, 1)]
    plt.xticks(ticks, [f"{compact(t)}{suffix}" for t in ticks])


def draw_vbar(plt, labels: Sequence[str], values: Sequence[float], palette: Palette,
              color: Optional[RGB] = None) -> None:
    _base(plt, palette)
    plt.bar(list(labels), list(values), width=0.5, marker="hd", color=color or palette.primary)
    top = max(values or [1]) or 1
    ticks = [top * f for f in (0, 0.5, 1)]
    plt.yticks(ticks, [compact(t) for t in ticks])


def draw_line(plt, labels: Sequence[str], values: Sequence[float], palette: Palette,
              color: Optional[RGB] = None, fill: bool = False) -> None:
    _base(plt, palette)
    xs = list(range(len(values)))
    # Interpolate between points so braille draws a continuous line, not dots.
    steps = 24
    dense_x, dense_y = [], []
    for i in range(len(values) - 1):
        for k in range(steps):
            t = k / steps
            dense_x.append(i + t)
            dense_y.append(values[i] + (values[i + 1] - values[i]) * t)
    if values:
        dense_x.append(len(values) - 1)
        dense_y.append(values[-1])
    plt.plot(dense_x, dense_y, marker="braille", color=color or palette.primary, fillx=fill)
    plt.scatter(xs, list(values), marker="●", color=color or palette.primary)
    plt.xticks(xs, list(labels))
    low, high = min(values or [0]), max(values or [1])
    ticks = [low, (low + high) / 2, high]
    plt.yticks(ticks, [compact(t) for t in ticks])


# ------------------------------------------------------------- the charts


@dataclass
class ChartSpec:
    id: str
    group: str
    title: str
    sources: Tuple[str, ...]
    draw: Callable[[Any, Dict[str, Any], Palette], None]
    subtitle: Callable[[Dict[str, Any]], str] = lambda data: ""


def _chart_data(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    """/api/charts nests its series under "population"; accept either layout."""
    charts = data["charts"]
    return (charts.get("population") or {}).get(key) or charts.get(key) or {}


def _population_growth(plt, data, palette):
    hist = _chart_data(data, "historical")
    draw_line(plt, hist.get("labels", []), hist.get("values", []), palette)


def _nationalities(plt, data, palette):
    nats = sorted(data["population"].get("nationalities", {}).items(), key=lambda kv: -kv[1])
    draw_hbar(plt, [k for k, _ in nats], [v for _, v in nats], palette, suffix="%")


def _demographics(plt, data, palette):
    demo = data["population"].get("demographics", {})
    draw_vbar(plt, [k.title() for k in demo], list(demo.values()), palette)


def _challenges(plt, data, palette):
    ch = _chart_data(data, "challenges")
    draw_hbar(plt, ch.get("labels", []), ch.get("values", []), palette, color=palette.warning)


def _capacity(plt, data, palette):
    svc = _chart_data(data, "services")
    labels, capacity = svc.get("labels", []), svc.get("capacity", [])
    gaps = [max(0, 100 - c) for c in capacity]
    _base(plt, palette)
    plt.stacked_bar(labels, [capacity, gaps], width=0.5, marker="hd",
                    color=[palette.primary, palette.muted])
    plt.yticks([0, 50, 100], ["0%", "50%", "100%"])


def _funding(plt, data, palette):
    fin = data["finance"]
    funded, gap = to_float(fin.get("funded")), to_float(fin.get("gap"))
    _base(plt, palette)
    plt.stacked_bar(["Budget"], [[funded / 1e6], [gap / 1e6]], orientation="horizontal", width=0.4,
                    marker="hd", color=[palette.primary, palette.error])
    total = (funded + gap) / 1e6
    plt.xticks([0, total / 2, total], ["$0", f"${total / 2:.0f}M", f"${total:.1f}M"])


def _services_by_category(plt, data, palette):
    ranked = counts_by(data["services"], "category", top=9)
    draw_hbar(plt, [k for k, _ in ranked], [v for _, v in ranked], palette)


def _encyclopedia_categories(plt, data, palette):
    cats = sorted((data["facets"].get("categories") or {}).items(), key=lambda kv: -kv[1])
    draw_hbar(plt, [k for k, _ in cats], [v for _, v in cats], palette)


def _news_per_month(plt, data, palette):
    series = per_month(data["news"], "date")
    draw_vbar(plt, [k for k, _ in series], [v for _, v in series], palette)


def _jobs_by_type(plt, data, palette):
    ranked = counts_by(data["jobs"], "type", top=6)
    draw_vbar(plt, [k for k, _ in ranked], [v for _, v in ranked], palette)


def _resources_by_category(plt, data, palette):
    ranked = counts_by(data["resources"], "category", top=8)
    draw_hbar(plt, [k for k, _ in ranked], [v for _, v in ranked], palette)


def _events_per_month(plt, data, palette):
    series = per_month(data["events"], "date", months=18)
    draw_vbar(plt, [k for k, _ in series], [v for _, v in series], palette)


def _hourly(data) -> List[Dict[str, Any]]:
    return ((data["weather"].get("forecast") or {}).get("hourly") or [])


def _temperature(plt, data, palette):
    hours = _hourly(data)
    draw_line(plt, [h.get("time", "") for h in hours], [to_float(h.get("maxTemp")) for h in hours],
              palette, color=palette.warning)


def _rainfall(plt, data, palette):
    hours = _hourly(data)
    draw_vbar(plt, [h.get("time", "") for h in hours], [to_float(h.get("rainfall")) for h in hours],
              palette, color=(86, 156, 214))


CHARTS: List[ChartSpec] = [
    ChartSpec("population-growth", "Population", "Camp population, 1994–2024", ("charts", "population"),
              _population_growth,
              lambda d: f"now {d['population'].get('total', 0):,} · +{d['population'].get('newArrivals', 0):,} new arrivals"),
    ChartSpec("nationalities", "Population", "Residents by nationality", ("population",), _nationalities,
              lambda d: "% of residents"),
    ChartSpec("demographics", "Population", "Women, children and men", ("population",), _demographics,
              lambda d: "% of residents"),
    ChartSpec("challenges", "Needs", "Challenges, impact score", ("charts",), _challenges,
              lambda d: "0–100, higher is worse"),
    ChartSpec("capacity", "Needs", "Service capacity against demand", ("charts",), _capacity,
              lambda d: "green = capacity · grey = unmet demand"),
    ChartSpec("funding", "Needs", "UNHCR Malawi funding", ("finance",), _funding,
              lambda d: f"green = funded · red = gap · {to_float(d['finance'].get('funded')) / max(to_float(d['finance'].get('budget')), 1):.0%} funded"),
    ChartSpec("services-by-category", "Directory", "Services by category", ("services",),
              _services_by_category, lambda d: f"{len(d['services'])} listed"),
    ChartSpec("encyclopedia-categories", "Directory", "Encyclopedia entries by category", ("facets",),
              _encyclopedia_categories, lambda d: f"{d['facets'].get('total', '')} entries"),
    ChartSpec("resources-by-category", "Directory", "Resources by category", ("resources",),
              _resources_by_category, lambda d: f"{len(d['resources'])} documents"),
    ChartSpec("news-per-month", "Activity", "News published per month", ("news",), _news_per_month,
              lambda d: "last 12 months"),
    ChartSpec("events-per-month", "Activity", "Events per month", ("events",), _events_per_month,
              lambda d: "last 18 months"),
    ChartSpec("jobs-by-type", "Activity", "Jobs by type", ("jobs",), _jobs_by_type,
              lambda d: f"{sum(1 for j in d['jobs'] if str(j.get('status')).lower() == 'open')} open now"),
    ChartSpec("temperature", "Weather", "Temperature, next hours", ("weather",), _temperature,
              lambda d: f"°C · {d['weather'].get('sourceLabel', '')}"),
    ChartSpec("rainfall", "Weather", "Rainfall, next hours", ("weather",), _rainfall,
              lambda d: "mm"),
]

CHARTS_BY_ID = {c.id: c for c in CHARTS}
GROUPS = list(dict.fromkeys(c.group for c in CHARTS))


def fetch_source(client: DzdkClient, name: str) -> Any:
    """Fetch one named dataset used by the charts."""
    if name == "charts":
        return client.charts()
    if name == "population":
        return client.population()
    if name == "finance":
        return client.finance()
    if name == "weather":
        return client.weather()
    if name == "facets":
        return client.encyclopedia_facets()
    return client.list_collection(name)


def fetch_for(client: DzdkClient, specs: Sequence[ChartSpec]) -> Dict[str, Any]:
    names = list(dict.fromkeys(src for spec in specs for src in spec.sources))
    return {name: fetch_source(client, name) for name in names}


# The incidents timeline is a list of dated events, not a series, so it is text.
def incidents(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    inc = _chart_data(data, "incidents")
    return list(zip(inc.get("labels", []), inc.get("events", [])))
