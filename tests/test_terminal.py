"""Window sizing on launch (dzdk.tui.terminal) and the `tui` command's options."""
import io

import pytest
from click.testing import CliRunner

from dzdk import cli
from dzdk.tui import terminal


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def tty(monkeypatch):
    out = FakeTTY()
    monkeypatch.setattr(terminal, "_out", lambda: out)
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.delenv("XTERM_VERSION", raising=False)
    return out


@pytest.mark.parametrize("value, expected", [
    ("140x42", (140, 42)), ("160X48", (160, 48)), ("off", None), ("", None),
    ("20x5", None), ("wide", None),
])
def test_parse_size(value, expected):
    assert terminal.parse_size(value) == expected


def test_grows_small_window_and_restores(tty, monkeypatch):
    sizes = iter([(80, 24), (140, 42), (140, 42)])
    monkeypatch.setattr(terminal, "current_size", lambda: next(sizes))
    previous = terminal.grow_window((140, 42))
    assert previous == (80, 24)
    assert tty.getvalue() == "\x1b[8;42;140t"
    terminal.restore_window(previous)
    assert tty.getvalue().endswith("\x1b[8;24;80t")


def test_never_shrinks_a_large_window(tty, monkeypatch):
    monkeypatch.setattr(terminal, "current_size", lambda: (200, 60))
    assert terminal.grow_window((140, 42)) is None
    assert tty.getvalue() == ""


def test_keeps_the_larger_dimension(tty, monkeypatch):
    sizes = iter([(200, 30), (200, 42), (200, 42)])
    monkeypatch.setattr(terminal, "current_size", lambda: next(sizes))
    terminal.grow_window((140, 42))
    assert tty.getvalue() == "\x1b[8;42;200t"


def test_unknown_terminal_is_left_alone(tty, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr(terminal, "current_size", lambda: (80, 24))
    assert terminal.grow_window((140, 42)) is None
    assert tty.getvalue() == ""


def test_tui_command_options(monkeypatch):
    calls = []
    monkeypatch.setattr(terminal, "grow_window", lambda size: calls.append(("grow", size)) or (80, 24))
    monkeypatch.setattr(terminal, "restore_window", lambda size: calls.append(("restore", size)))
    import dzdk.tui.app as app_module
    monkeypatch.setattr(app_module.DzdkApp, "run", lambda self: calls.append(("run", self.initial_tab)))

    runner = CliRunner()
    assert runner.invoke(cli, ["tui", "--tab", "insights"]).exit_code == 0
    assert calls == [("grow", (140, 42)), ("run", "insights"), ("restore", (80, 24))]

    calls.clear()
    runner.invoke(cli, ["tui", "--no-resize"])
    assert calls == [("run", "home"), ("restore", None)]

    calls.clear()
    runner.invoke(cli, ["tui", "--size", "160x48"])
    assert calls[0] == ("grow", (160, 48))

    assert runner.invoke(cli, ["tui", "--size", "big"]).exit_code == 2


def test_config_window_size(config_home):
    runner = CliRunner()
    assert runner.invoke(cli, ["config", "--window-size", "off"]).exit_code == 0
    assert "window_size: 'off'" in (config_home / "config.yaml").read_text()
    assert runner.invoke(cli, ["config", "--window-size", "tiny"]).exit_code == 2


def test_bare_dzdk_opens_the_app_at_a_terminal(monkeypatch):
    import sys

    import dzdk.tui.app as app_module

    cli_module = sys.modules["dzdk.cli"]  # `dzdk.cli` the attribute is the click group

    launched = []
    monkeypatch.setattr(cli_module, "is_interactive", lambda: True)
    monkeypatch.setattr(terminal, "grow_window", lambda size: None)
    monkeypatch.setattr(app_module.DzdkApp, "run", lambda self: launched.append(self.initial_tab))
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert launched == ["home"]


def test_bare_dzdk_prints_overview_when_piped():
    result = CliRunner().invoke(cli, [])  # CliRunner is not a terminal
    assert "open the full-screen app" in result.output
    assert "Usage:" in result.output


def test_help_command():
    result = CliRunner().invoke(cli, ["help"])
    assert result.exit_code == 0
    assert "open the full-screen app" in result.output and "Commands:" in result.output
