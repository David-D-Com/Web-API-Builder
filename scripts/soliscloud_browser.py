"""Browser-driven SolisCloud site discovery.

This script avoids the undocumented web signing problem by automating the real
SolisCloud web UI in Chromium through Playwright. It listens for JSON API
responses and extracts the first response that looks like a station/site list.

Setup:
    py -m pip install playwright
    playwright install chromium

Usage:
    set SOLIS_USERNAME=you@example.com
    set SOLIS_PASSWORD=your-password
    python soliscloud_browser.py

Optional:
    python soliscloud_browser.py --headed
    python soliscloud_browser.py --debug-network
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any


LOGIN_URL = "https://www.soliscloud.com/login?"
STATION_URL = "https://www.soliscloud.com/station"


class SolisBrowserError(RuntimeError):
    """Raised when browser automation cannot complete the task."""


@dataclass
class SiteDiscoveryResult:
    endpoint: str | None
    sites: list[dict[str, Any]]
    captures: list[dict[str, Any]]


def _looks_like_site_record(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    keys = set(item)
    return any(
        {"stationName", "stationId", "sno", "addr", "capacity"} & keys
    ) and ("id" in keys or "stationId" in keys or "stationName" in keys)


def _extract_site_records(payload: Any) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        nonlocal matches
        if isinstance(node, list):
            if node and all(_looks_like_site_record(item) for item in node):
                matches = [item for item in node if isinstance(item, dict)]
                return
            for item in node:
                if matches:
                    return
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                if matches:
                    return
                walk(value)

    walk(payload)
    return matches


def _pick_login_input(page: Any, candidates: list[str]) -> Any | None:
    for selector in candidates:
        locator = page.locator(selector)
        if locator.count():
            return locator.first
    return None


def discover_sites(
    username: str,
    password: str,
    *,
    headed: bool = False,
    debug_network: bool = False,
    timeout_ms: int = 30000,
) -> SiteDiscoveryResult:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SolisBrowserError(
            "Playwright is not installed. Run `py -m pip install playwright` "
            "and `playwright install chromium`."
        ) from exc

    captures: list[dict[str, Any]] = []
    chosen_endpoint: str | None = None
    chosen_sites: list[dict[str, Any]] = []

    def on_response(response: Any) -> None:
        nonlocal chosen_endpoint, chosen_sites
        try:
            if "/api/" not in response.url:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                return
            payload = response.json()
        except Exception:
            return

        record = {
            "url": response.url,
            "status": response.status,
        }

        sites = _extract_site_records(payload)
        if sites:
            record["site_count"] = len(sites)
            if chosen_endpoint is None:
                chosen_endpoint = response.url
                chosen_sites = sites

        if debug_network:
            if sites:
                record["sample"] = sites[:3]
            captures.append(record)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()
        page.on("response", on_response)

        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            user_input = _pick_login_input(
                page,
                [
                    'input[autocomplete="username"]',
                    'input[type="email"]',
                    'input[placeholder*="Email"]',
                    'input[placeholder*="email"]',
                    'input[name="userInfo"]',
                    'input[name="username"]',
                    'input[type="text"]',
                ],
            )
            password_input = _pick_login_input(
                page,
                [
                    'input[autocomplete="current-password"]',
                    'input[type="password"]',
                    'input[name="passWord"]',
                    'input[name="password"]',
                ],
            )
            if user_input is None or password_input is None:
                raise SolisBrowserError(
                    "Could not find the SolisCloud login inputs. "
                    "Run with `--headed` and inspect the page."
                )

            user_input.fill(username)
            password_input.fill(password)

            submit = _pick_login_input(
                page,
                [
                    'button[type="submit"]',
                    'button:has-text("Login")',
                    'button:has-text("Sign in")',
                    'button:has-text("Log in")',
                    'input[type="submit"]',
                ],
            )
            if submit is None:
                raise SolisBrowserError(
                    "Could not find the SolisCloud login button."
                )

            submit.click()

            # The app may redirect, show a dashboard, or stay in the SPA shell.
            # We intentionally ignore the exact landing URL and move to /station.
            time.sleep(3)
            page.goto(STATION_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            # Give XHRs time to settle and emit responses.
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            time.sleep(3)

            if not chosen_sites:
                raise SolisBrowserError(
                    "No site list was detected from network traffic. "
                    "Run again with `--headed --debug-network` to inspect "
                    "the captured API responses."
                )

            return SiteDiscoveryResult(
                endpoint=chosen_endpoint,
                sites=chosen_sites,
                captures=captures,
            )
        except PlaywrightTimeoutError as exc:
            raise SolisBrowserError(
                "Timed out waiting for SolisCloud to load. "
                "The site may be slow or the login may need extra interaction."
            ) from exc
        finally:
            browser.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    parser.add_argument(
        "--debug-network",
        action="store_true",
        help="Include a compact summary of captured JSON API responses.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Per-navigation timeout in milliseconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    username = os.environ.get("SOLIS_USERNAME")
    password = os.environ.get("SOLIS_PASSWORD")

    if not username or not password:
        print(
            "Error: set SOLIS_USERNAME and SOLIS_PASSWORD first.",
            file=sys.stderr,
        )
        return 1

    try:
        result = discover_sites(
            username=username,
            password=password,
            headed=args.headed,
            debug_network=args.debug_network,
            timeout_ms=args.timeout_ms,
        )
    except SolisBrowserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output: dict[str, Any] = {
        "endpoint": result.endpoint,
        "sites": result.sites,
    }
    if args.debug_network:
        output["captures"] = result.captures

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
