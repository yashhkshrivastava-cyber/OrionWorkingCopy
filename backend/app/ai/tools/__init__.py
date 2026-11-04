"""The tool layer. Importing this package registers every tool (``core.REGISTRY``)."""

from __future__ import annotations


def load_tools() -> None:
    """Import the modules that define tools. Safe to call more than once."""
    from app.ai.tools import actions, analytics, bank, forecast, records, tally  # noqa: F401


load_tools()
