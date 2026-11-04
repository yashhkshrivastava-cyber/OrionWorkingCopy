"""Minimising what goes to a cloud model: names in retrieved data are replaced by neutral labels, and put back in the answer.

This reduces what a cloud provider learns about who the figures belong to. It does not make the data safe to send, and it is
not what permits sending: the organisation's policy decides that. Anything that still looks like a private identifier after
this is stopped (``sensitivity``), and the volume is capped.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai import config

# The fields of tool results that hold the name of a client, case or other party.
NAME_KEYS = {"name", "client", "client_name", "case", "case_name", "party", "party_name", "label", "place", "domain", "business_domain", "employee", "employee_name"}


class Pseudonymiser:
    def __init__(self) -> None:
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}

    def alias(self, name: str) -> str:
        if name not in self.forward:
            label = f"Party {len(self.forward) + 1}"
            self.forward[name], self.reverse[label] = label, name
        return self.forward[name]

    def _collect(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, sub in value.items():
                if key in NAME_KEYS and isinstance(sub, str) and len(sub.strip()) >= 3 and not re.fullmatch(r"[\d\W]+", sub):
                    self.alias(sub.strip())
                else:
                    self._collect(sub)
        elif isinstance(value, list):
            for sub in value:
                self._collect(sub)

    def _replace(self, value: Any) -> Any:
        if isinstance(value, str):
            for name in sorted(self.forward, key=len, reverse=True):
                if name in value:
                    value = value.replace(name, self.forward[name])
            return value
        if isinstance(value, dict):
            return {k: self._replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace(v) for v in value]
        return value

    def scrub(self, data: Any) -> Any:
        """A copy of ``data`` with every name found in it replaced by its label."""
        self._collect(data)
        return self._replace(data)

    def scrub_text(self, text: str) -> str:
        return self._replace(text)

    def restore(self, text: str) -> str:
        """The answer with the labels turned back into the names they stood for."""
        for label in sorted(self.reverse, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(label)}\b", lambda _m, label=label: self.reverse[label], text)
        return text

    @property
    def used(self) -> bool:
        return bool(self.forward)


def cap(text: str) -> str:
    """Never more than the configured amount in one cloud request."""
    limit = config.CLOUD_MAX_CONTEXT_CHARS
    return text if len(text) <= limit else text[:limit] + "…"
