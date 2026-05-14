"""Probe live Fronius inverter detail fields for rated-power metadata."""

from __future__ import annotations

import json
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
        raise SystemExit("No Fronius credentials available.")

    client = FroniusClient().initialize(username=username, password=password)
    payload = client.get_actual_pv_system_data(TARGET_PV_SYSTEM_ID)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
