"""Headless browser check for Fronius login bootstrap."""

from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

from fronius_auth import load_credentials


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless instead of showing the window.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient
    from playwright.sync_api import sync_playwright

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use Windows Credential Manager or env vars.")

    client = FroniusClient()
    target_url = "https://www.solarweb.com/PvSystems/Widgets"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        handled = client.initialize_browser_page(
            page,
            target_url=target_url,
            username=username,
            password=password,
        )
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        print(f"Handled: {handled}")
        print(f"Final URL: {page.url}")
        print(f"Title: {page.title()}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
