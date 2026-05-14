"""Export live Fronius daily per-inverter output to a CSV in .\\dumps."""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path
from typing import Any

from fronius_auth import load_credentials


TARGET_PV_SYSTEM_ID = "c79e1935-cfe2-4d86-b2ef-cbcf33b7e6d4"
DEFAULT_OUTPUT = r"dumps\fronius_c79e1935_inverter_daily_output_2y.csv"


def month_range(start_year: int, start_month: int, end_year: int, end_month: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def parse_device_map(metadata: dict[str, Any]) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for device in metadata.get("deviceChannels", {}).get("devices", []):
        device_id = str(device.get("deviceId") or "")
        display_name = str(device.get("displayName") or "")
        if device_id and display_name:
            devices.append({"device_id": device_id, "display_name": display_name})
    return devices


def format_date_from_ms(timestamp_ms: float | int) -> str:
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(float(timestamp_ms) / 1000.0, tz=timezone.utc)
    return dt.date().isoformat()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use Windows Credential Manager or env vars.")

    output_path = repo_root / DEFAULT_OUTPUT
    client = FroniusClient().initialize(username=username, password=password)

    today = date.today()
    start = date(today.year - 2, today.month, 1)
    months = month_range(start.year, start.month, today.year, today.month)

    metadata_probe = client.get_analysis_chart(
        TARGET_PV_SYSTEM_ID,
        year=today.year,
        month=today.month,
        day=today.day,
        interval="month",
    )
    devices = parse_device_map(metadata_probe)
    if not devices:
        raise RuntimeError("No inverter devices were returned by GetAnalysisChart metadata.")

    rows: list[dict[str, Any]] = []
    for year, month in months:
        month_body = client.get_analysis_chart(
            TARGET_PV_SYSTEM_ID,
            year=year,
            month=month,
            day=1,
            interval="month",
            channels="devwork",
            devices=[item["device_id"] for item in devices],
        )
        for series in month_body.get("settings", {}).get("series", []):
            name = str(series.get("name") or "")
            if " | " not in name:
                continue
            _, inverter_name = name.split(" | ", 1)
            inverter_name = inverter_name.strip()
            device_id = next((item["device_id"] for item in devices if item["display_name"] == inverter_name), "")
            for point in series.get("data") or []:
                if len(point) < 2:
                    continue
                rows.append(
                    {
                        "date": format_date_from_ms(point[0]),
                        "pv_system_id": TARGET_PV_SYSTEM_ID,
                        "device_id": device_id,
                        "inverter_name": inverter_name,
                        "daily_output_kwh": point[1],
                        "source_interval": "month",
                        "source_channel": "devwork",
                    }
                )

    rows.sort(key=lambda item: (item["date"], item["inverter_name"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "pv_system_id",
                "device_id",
                "inverter_name",
                "daily_output_kwh",
                "source_interval",
                "source_channel",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_path}")
    if rows:
        print("First row:", rows[0])
        print("Last row:", rows[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
