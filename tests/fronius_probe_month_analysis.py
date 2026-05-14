"""Probe one live Fronius monthly devwork response to verify export parsing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fronius_auth import load_credentials


TARGET_PV_SYSTEM_ID = "c79e1935-cfe2-4d86-b2ef-cbcf33b7e6d4"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use Windows Credential Manager or env vars.")

    client = FroniusClient().initialize(username=username, password=password)
    metadata = client.get_analysis_chart(
        TARGET_PV_SYSTEM_ID,
        year=2026,
        month=5,
        day=13,
        interval="month",
    )
    devices = metadata.get("deviceChannels", {}).get("devices", [])
    print("Devices:", len(devices))
    print("First device:", devices[0] if devices else None)

    device_ids = [str(item.get("deviceId")) for item in devices if item.get("deviceId")]
    month_data = client.get_analysis_chart(
        TARGET_PV_SYSTEM_ID,
        year=2026,
        month=5,
        day=13,
        interval="month",
        channels="devwork",
        devices=device_ids,
    )
    series = month_data.get("settings", {}).get("series", [])
    print("Series count:", len(series))
    if series:
        first = series[0]
        print("First series name:", first.get("name"))
        print("First point:", (first.get("data") or [None])[0])
        print("Sum value:", month_data.get("sumValue"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
