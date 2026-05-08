"""CLI entry points for the package."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .client import SolisSession, SolisWebApiClient, SolisWebApiError

DISPLAY_LANGUAGE = "en"


def _prune_language_variants(value: Any, *, preferred_language: str) -> Any:
    """Light display-only cleanup for CLI output.

    The core client can already normalize payloads, but the CLI also supports a
    last-mile display preference so console output stays readable.
    """
    if isinstance(value, list):
        return [
            _prune_language_variants(item, preferred_language=preferred_language)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    pruned: dict[str, Any] = {}
    keys = {str(key) for key in value}
    for key, raw_item in value.items():
        key_str = str(key)
        if preferred_language in {"en", "cn"}:
            if preferred_language == "en" and key_str.endswith("Cn"):
                sibling = key_str[:-2] + "En"
                if sibling in keys:
                    continue
            if preferred_language == "cn" and key_str.endswith("En"):
                sibling = key_str[:-2] + "Cn"
                if sibling in keys:
                    continue
        pruned[key_str] = _prune_language_variants(raw_item, preferred_language=preferred_language)
    return pruned


def render_json(data: Any) -> None:
    """Pretty-print JSON with color when `rich` is available."""
    data = _prune_language_variants(data, preferred_language=DISPLAY_LANGUAGE)
    json_text = json.dumps(data, indent=2, ensure_ascii=True)
    try:
        from rich.console import Console
        from rich.syntax import Syntax
    except ImportError:
        print(json_text)
        return
    Console(force_terminal=True, color_system="auto").print(
        Syntax(json_text, "json", theme="monokai", word_wrap=True)
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal operator-facing CLI."""
    parser = argparse.ArgumentParser(description="SolisCloud web API CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--login", action="store_true", help="Only perform login.")
    group.add_argument("--profile", action="store_true", help="Fetch /api/user/find.")
    group.add_argument(
        "--list-sites",
        action="store_true",
        help="Fetch /api/station/list and print the aggregated records.",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--station-type", default="1")
    parser.add_argument(
        "--filter-results",
        action="store_true",
        help="Apply payload cleanup in the client before returning results.",
    )
    parser.add_argument(
        "--display-language",
        choices=("en", "cn", "both"),
        default="en",
        help="Preferred language for console display when both *En and *Cn keys are present.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI entry point."""
    args = build_parser().parse_args(argv)
    global DISPLAY_LANGUAGE
    DISPLAY_LANGUAGE = args.display_language
    try:
        client = SolisWebApiClient(
            SolisSession.from_env(
                filter_results=args.filter_results,
                preferred_language=args.display_language,
            )
        )
        if args.login:
            result: Any = client.login()
        elif args.profile:
            result = client.profile()
        else:
            result = client.list_all_sites(
                page_size=args.page_size,
                station_type=args.station_type,
            )
    except SolisWebApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    render_json(result)
    return 0
