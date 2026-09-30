"""dzdk - Dzaleka Online Services CLI and terminal UI."""

__version__ = "0.2.0"

from dzdk.cli import cli  # noqa: E402  (re-exported for `from dzdk import cli`)

__all__ = ["cli", "__version__"]
