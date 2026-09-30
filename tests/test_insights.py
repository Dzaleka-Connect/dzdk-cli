"""Chart data helpers and chart drawing."""
from datetime import datetime

import plotext
import pytest

from dzdk.insights import CHARTS, Palette, compact, counts_by, hex_to_rgb, incidents, per_month
from tests.conftest import CHARTS_PAYLOAD, EVENTS, JOBS, NEWS, POPULATION, RESOURCES, SERVICES

DATA = {
    "charts": CHARTS_PAYLOAD,
    "population": POPULATION,
    "finance": {"budget": 26300000, "funded": 4679887, "gap": 21620113},
    "weather": {"forecast": {"hourly": [{"time": "18:00", "maxTemp": "19", "rainfall": "5"},
                                        {"time": "19:00", "maxTemp": "18", "rainfall": "6"}]}},
    "facets": {"total": 1, "categories": {"Infrastructure": 1}},
    "services": SERVICES, "news": NEWS, "events": EVENTS, "jobs": JOBS, "resources": RESOURCES,
}


@pytest.mark.parametrize("spec", CHARTS, ids=lambda s: s.id)
def test_every_chart_draws(spec):
    plotext.clf()
    plotext.plotsize(60, 14)
    spec.draw(plotext, DATA, Palette(background=(17, 20, 22)))
    assert plotext.build().strip()
    assert isinstance(spec.subtitle(DATA), str)


def test_counts_by_groups_the_tail():
    items = [{"c": "a"}] * 3 + [{"c": "b"}] * 2 + [{"c": "c"}, {"c": None}]
    assert counts_by(items, "c", top=2) == [("a", 3), ("b", 2), ("Other", 2)]


def test_per_month():
    items = [{"d": "2026-09-03T00:00:00Z"}, {"d": "2026-09-20T00:00:00Z"}, {"d": "2026-07-01"},
             {"d": "2020-01-01"}, {"d": None}]
    assert per_month(items, "d", months=3, today=datetime(2026, 9, 30)) == [
        ("Jul 26", 1), ("Aug 26", 0), ("Sep 26", 2)]


def test_formatting_helpers():
    assert compact(12000) == "12k"
    assert compact(1500000) == "1.5M"
    assert compact(32.45) == "32.5"
    assert hex_to_rgb("#4FB25E") == (79, 178, 94)
    assert incidents(DATA) == [("Nov 2022", "Aid distribution unrest")]
