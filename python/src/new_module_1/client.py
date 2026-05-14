"""Starter client for New Module 1."""

from __future__ import annotations


class NewModule1Client:
    """Placeholder browser-derived API client."""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url.rstrip("/")

    def healthcheck(self) -> dict[str, str]:
        """Simple placeholder so endpoint discovery has something to show."""
        return {"status": "ok", "base_url": self.base_url}

