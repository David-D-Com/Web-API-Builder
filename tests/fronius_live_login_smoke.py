"""Live smoke test for Fronius Solar.web login and a few useful endpoints."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fronius_auth import load_credentials


TARGET_SYSTEM_NAME = os.getenv("FRONIUS_TARGET_SYSTEM", "G and C farms north meter")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use Windows Credential Manager or env vars.")

    client = FroniusClient().initialize(username=username, password=password)
    systems_payload = client.get_pv_systems_for_list_view()
    systems = systems_payload.get("data", [])
    assert systems, "Expected PvSystems list data after live login."

    target = client.get_pv_system_by_name(TARGET_SYSTEM_NAME) or systems[0]
    target_id = target["PvSystemId"]

    compare = client.get_compare_data_for_pv_system(target_id)
    production = client.get_pv_system_productions_and_earnings(target_id)

    print(f"Systems discovered: {len(systems)}")
    print(f"Selected system: {target['PvSystemName']} ({target_id})")
    print(f"Current production: {compare.get('P_PV')} W")
    today = production.get("data", {}).get("Productions", {}).get("Today")
    today_unit = production.get("data", {}).get("Productions", {}).get("TodayUnit")
    print(f"Today's energy: {today} {today_unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
