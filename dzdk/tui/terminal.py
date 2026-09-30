"""Ask the terminal window to grow before the app starts, and restore it after.

Uses the xterm window-manipulation sequence `CSI 8 ; rows ; cols t`. Only
terminals known to honour it are asked; everywhere else the app simply adapts
its layout to whatever size it gets.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Optional, Tuple

Size = Tuple[int, int]  # (columns, rows)

# TERM_PROGRAM values of terminals that resize their window on request.
RESIZABLE_TERMINALS = {"Apple_Terminal", "iTerm.app"}


def parse_size(value: object) -> Optional[Size]:
    """"140x42" -> (140, 42); "off", "" or anything invalid -> None."""
    try:
        cols, rows = str(value).lower().split("x")
        size = int(cols), int(rows)
    except ValueError:
        return None
    return size if size[0] >= 40 and size[1] >= 12 else None


def _out():
    """The stream the terminal is attached to (a function so tests can swap it)."""
    return sys.stdout


def can_resize() -> bool:
    if not _out().isatty():
        return False
    if os.environ.get("TERM_PROGRAM") in RESIZABLE_TERMINALS:
        return True
    # A real xterm (not an emulator borrowing its TERM name) sets XTERM_VERSION.
    return bool(os.environ.get("XTERM_VERSION"))


def current_size() -> Size:
    size = shutil.get_terminal_size()
    return size.columns, size.lines


def _request(size: Size) -> None:
    cols, rows = size
    out = _out()
    out.write(f"\x1b[8;{rows};{cols}t")
    out.flush()


def grow_window(target: Size, wait: float = 0.6) -> Optional[Size]:
    """Grow the window to at least `target`. Returns the previous size if it changed."""
    if not can_resize():
        return None
    before = current_size()
    wanted = (max(before[0], target[0]), max(before[1], target[1]))
    if wanted == before:
        return None
    _request(wanted)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and current_size() == before:
        time.sleep(0.05)
    return before if current_size() != before else None


def restore_window(size: Optional[Size]) -> None:
    if size and can_resize():
        _request(size)
