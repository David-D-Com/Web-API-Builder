"""Export Fronius daily per-inverter output from captured analysis responses.

This is a replay-oriented proof script. It parses captured
`Chart/GetAnalysisChart` responses and writes one CSV row per inverter per day.
For a future live mode, the same endpoint shape is enough, but authenticated
requests would still need to be wired up.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import parse_qs, urlparse


TARGET_PV_SYSTEM_ID = "c79e1935-cfe2-4d86-b2ef-cbcf33b7e6d4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        default=r"har\fronius\20260513-090923",
        help="Capture directory containing Fronius request JSON files.",
    )
    parser.add_argument(
        "--pv-system-id",
        default=TARGET_PV_SYSTEM_ID,
        help="Target pvSystemId to export.",
    )
    parser.add_argument(
        "--out",
        default=r"C:\tmp\fronius_c79e1935_inverter_daily_output_sample.csv",
        help="CSV output path.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_sum_value_kwh(sum_value: str | None) -> float | None:
    if not sum_value:
        return None
    text = sum_value.replace(",", "").strip()
    parts = text.split()
    if not parts:
        return None
    value = float(parts[0])
    unit = parts[1].lower() if len(parts) > 1 else "kwh"
    if unit == "mwh":
        return value * 1000.0
    return value


def infer_step_hours(series_data: list[list[float]]) -> float:
    if len(series_data) < 2:
        return 5.0 / 60.0
    deltas = []
    for current, nxt in zip(series_data, series_data[1:]):
        delta_ms = float(nxt[0]) - float(current[0])
        if delta_ms > 0:
            deltas.append(delta_ms / 3_600_000.0)
    if not deltas:
        return 5.0 / 60.0
    return median(deltas)


def integrate_series_kwh(series_data: list[list[float]]) -> float:
    if not series_data:
        return 0.0
    step_hours = infer_step_hours(series_data)
    total = 0.0
    for point in series_data:
        if len(point) < 2:
            continue
        total += float(point[1]) * step_hours
    return total


def build_device_lookup(metadata_payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    devices = metadata_payload.get("response", {}).get("text")
    if not devices:
        return result
    body = json.loads(devices)
    for device in body.get("deviceChannels", {}).get("devices", []):
        device_id = str(device.get("deviceId") or "")
        name = str(device.get("displayName") or "")
        if device_id and name:
            result[name] = device_id
    return result


def export_rows(capture_dir: Path, pv_system_id: str) -> list[dict[str, Any]]:
    files = sorted(capture_dir.glob("www.solarweb.com_Chart_GetAnalysisChart*.json"))
    metadata_file = None
    for path in files:
        payload = load_json(path)
        query = parse_qs(urlparse(payload["request"]["url"]).query)
        if query.get("pvSystemId", [""])[0] != pv_system_id:
            continue
        if "devices" not in query and query.get("channels", [""]) == [""]:
            metadata_file = payload
            break
        if "devices" not in query:
            metadata_file = payload
            break
    if metadata_file is None:
        raise RuntimeError("Could not find analysis metadata capture for target system.")

    name_to_device = build_device_lookup(metadata_file)
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for path in files:
        payload = load_json(path)
        request_url = payload.get("request", {}).get("url", "")
        query = parse_qs(urlparse(request_url).query)
        if query.get("pvSystemId", [""])[0] != pv_system_id:
            continue
        if query.get("channels", [""]) != ["devwork"]:
            continue
        if "devices" not in query:
            continue

        date_str = f"{query['year'][0]}-{int(query['month'][0]):02d}-{int(query['day'][0]):02d}"
        body = json.loads(payload.get("response", {}).get("text", "{}"))
        for series in body.get("settings", {}).get("series", []):
            name = str(series.get("name") or "")
            if not name.startswith("Total Power | "):
                continue
            inverter_name = name.split(" | ", 1)[1].strip()
            series_data = series.get("data") or []
            if not series_data:
                continue
            total_energy_kwh = integrate_series_kwh(series_data)
            peak_power_kw = max(float(point[1]) for point in series_data if len(point) >= 2)
            key = (date_str, inverter_name)
            row = {
                "date": date_str,
                "pv_system_id": pv_system_id,
                "device_id": name_to_device.get(inverter_name, ""),
                "inverter_name": inverter_name,
                "total_energy_kwh": round(total_energy_kwh, 3),
                "peak_power_kw": round(peak_power_kw, 3),
                "point_count": len(series_data),
                "source_file": path.name,
                "response_sum_value_kwh": parse_sum_value_kwh(body.get("sumValue")),
            }
            existing = rows_by_key.get(key)
            if existing is None or int(row["point_count"]) > int(existing["point_count"]):
                rows_by_key[key] = row

    return sorted(rows_by_key.values(), key=lambda item: (item["date"], item["inverter_name"]))


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "pv_system_id",
        "device_id",
        "inverter_name",
        "total_energy_kwh",
        "peak_power_kw",
        "point_count",
        "response_sum_value_kwh",
        "source_file",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    capture_dir = Path(args.capture_dir)
    rows = export_rows(capture_dir, args.pv_system_id)
    write_csv(rows, Path(args.out))
    print(f"Wrote {len(rows)} rows to {args.out}")
    if rows:
        print("First row:", rows[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
