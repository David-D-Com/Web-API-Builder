"""Export live Fronius daily per-inverter output for every site into dumps/."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fronius_auth import load_credentials


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


def slugify(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return slug[:max_len] or "site"


def infer_rated_kw_from_name(inverter_name: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*\d", inverter_name)
    if match:
        return float(match.group(1))
    return None


def format_date_from_ms(timestamp_ms: float | int) -> str:
    dt = datetime.fromtimestamp(float(timestamp_ms) / 1000.0, tz=timezone.utc)
    return dt.date().isoformat()


def parse_device_map(metadata: dict[str, Any]) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for device in metadata.get("deviceChannels", {}).get("devices", []):
        device_id = str(device.get("deviceId") or "")
        display_name = str(device.get("displayName") or "")
        if device_id and display_name:
            devices.append({"device_id": device_id, "display_name": display_name})
    return devices


def export_site_rows(client: Any, pv_system_id: str, pv_system_name: str) -> list[dict[str, Any]]:
    today = date.today()
    start = date(today.year - 2, today.month, 1)
    months = month_range(start.year, start.month, today.year, today.month)

    metadata_probe = client.get_analysis_chart(
        pv_system_id,
        year=today.year,
        month=today.month,
        day=today.day,
        interval="month",
    )
    devices = parse_device_map(metadata_probe)
    if not devices:
        return []

    name_to_device = {item["display_name"]: item["device_id"] for item in devices}
    rows: list[dict[str, Any]] = []
    for year, month in months:
        month_body = client.get_analysis_chart(
            pv_system_id,
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
            device_id = name_to_device.get(inverter_name, "")
            for point in series.get("data") or []:
                if len(point) < 2 or point[1] is None:
                    continue
                rows.append(
                    {
                        "date": format_date_from_ms(point[0]),
                        "pv_system_id": pv_system_id,
                        "pv_system_name": pv_system_name,
                        "device_id": device_id,
                        "inverter_name": inverter_name,
                        "inverter_rated_kw": infer_rated_kw_from_name(inverter_name),
                        "inverter_rating_source": "parsed_from_inverter_name",
                        "daily_output_kwh": point[1],
                        "source_interval": "month",
                        "source_channel": "devwork",
                    }
                )
    rows.sort(key=lambda item: (item["date"], item["inverter_name"]))
    return rows


def write_site_csv(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "pv_system_id",
                "pv_system_name",
                "device_id",
                "inverter_name",
                "inverter_rated_kw",
                "inverter_rating_source",
                "daily_output_kwh",
                "source_interval",
                "source_channel",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_normalized_site_csv(output_path: Path, rows: list[dict[str, Any]]) -> None:
    from fronius import NORMALIZED_DAILY_INVERTER_FIELDS, normalize_daily_inverter_row

    normalized_rows = [normalize_daily_inverter_row("fronius", row) for row in rows]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=NORMALIZED_DAILY_INVERTER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(normalized_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--normalized",
        action="store_true",
        help="Write the shared normalized schema directly instead of vendor-specific columns.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient

    username, password = load_credentials()
    if not username or not password:
        raise SystemExit("No Fronius credentials available. Use Windows Credential Manager or env vars.")

    dumps_dir = repo_root / "dumps"
    client = FroniusClient().initialize(username=username, password=password)
    systems_payload = client.get_pv_systems_for_list_view()
    systems = systems_payload.get("data", [])
    if not systems:
        raise RuntimeError("No PvSystems were returned from Solar.web.")

    total_rows = 0
    written_files = 0
    for index, system in enumerate(systems, start=1):
        pv_system_id = str(system.get("PvSystemId") or "")
        pv_system_name = str(system.get("PvSystemName") or f"site_{index}")
        if not pv_system_id:
            continue
        rows = export_site_rows(client, pv_system_id, pv_system_name)
        if not rows:
            print(f"[{index}/{len(systems)}] Skipped {pv_system_name}: no inverter output rows.")
            continue
        filename = f"fronius_{slugify(pv_system_name)}__{pv_system_id}.csv"
        output_path = dumps_dir / filename
        legacy_output_path = dumps_dir / f"{slugify(pv_system_name)}__{pv_system_id}.csv"
        if legacy_output_path.exists():
            legacy_output_path.unlink()
        if args.normalized:
            write_normalized_site_csv(output_path, rows)
        else:
            write_site_csv(output_path, rows)
        total_rows += len(rows)
        written_files += 1
        print(f"[{index}/{len(systems)}] Wrote {len(rows)} rows to {output_path.name}")

    print(f"Completed: {written_files} file(s), {total_rows} total row(s), output folder {dumps_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
