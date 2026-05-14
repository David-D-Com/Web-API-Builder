"""Small Fronius helper for saving/loading Windows credentials and smoke testing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fronius_auth import delete_credentials, load_credentials, prompt_and_save_credentials


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-credentials", action="store_true", help="Prompt for credentials and save them.")
    parser.add_argument("--delete-credentials", action="store_true", help="Delete saved credentials.")
    parser.add_argument("--show-credentials-state", action="store_true", help="Show whether credentials are available.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.save_credentials:
        prompt_and_save_credentials()
        print(json.dumps({"saved": True, "service": "web-api-builder/fronius"}, indent=2))
        return 0
    if args.delete_credentials:
        delete_credentials()
        print(json.dumps({"deleted": True, "service": "web-api-builder/fronius"}, indent=2))
        return 0
    if args.show_credentials_state:
        username, password = load_credentials()
        print(
            json.dumps(
                {
                    "username_available": bool(username),
                    "password_available": bool(password),
                },
                indent=2,
            )
        )
        return 0

    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))
    from fronius import FroniusClient

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use --save-credentials or env vars.")
    client = FroniusClient().initialize(username=username, password=password)
    payload = client.get_pv_systems_for_list_view()
    systems = payload.get("data", [])
    print(json.dumps({"systems": len(systems)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
