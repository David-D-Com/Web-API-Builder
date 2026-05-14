"""Export live Solis daily per-inverter production for every site into dumps/."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from solis_inverter_cap_report import build_session
from soliscloud_web_api import (
    NORMALIZED_DAILY_INVERTER_FIELDS,
    SolisWebApiClient,
    normalize_daily_inverter_row,
)


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


def parse_energy_kwh(row: dict[str, object]) -> float:
    value = float(row.get("energy") or 0.0)
    unit = str(row.get("energyStr") or "kWh").lower()
    scale = float(row.get("energyPec") or 1.0)
    scaled = value * scale
    if unit == "mwh":
        return scaled * 1000.0
    if unit == "wh":
        return scaled / 1000.0
    return scaled


def export_site_rows(
    client: SolisWebApiClient,
    station_id: str,
    station_name: str,
    records: list[dict[str, object]],
    *,
    months: list[tuple[int, int]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for inverter in records:
        inverter_id = str(inverter.get("id") or inverter.get("inverterId") or "")
        inverter_sn = str(inverter.get("sn") or inverter.get("inverterSn") or "")
        inverter_model = str(inverter.get("model") or inverter.get("productModel") or "")
        inverter_power_kw = float(inverter.get("power") or 0.0)
        if not inverter_id:
            continue
        for year, month in months:
            month_payload = client.inverter_chart_month(inverter_id, month=f"{year:04d}-{month:02d}")
            month_rows = month_payload.get("data") or []
            if not isinstance(month_rows, list):
                continue
            for item in month_rows:
                if not isinstance(item, dict):
                    continue
                date_str = str(item.get("dateStr") or "")
                if not date_str:
                    continue
                rows.append(
                    {
                        "date": date_str,
                        "station_id": station_id,
                        "station_name": station_name,
                        "inverter_id": inverter_id,
                        "inverter_sn": inverter_sn,
                        "inverter_model": inverter_model,
                        "inverter_rated_kw": inverter_power_kw,
                        "daily_production_kwh": round(parse_energy_kwh(item), 3),
                        "full_hour": float(item.get("fullHour") or 0.0),
                        "money": float(item.get("money") or 0.0),
                        "raw_energy_value": item.get("energy"),
                        "raw_energy_unit": item.get("energyStr"),
                        "raw_energy_scale": item.get("energyPec"),
                    }
                )
    rows.sort(key=lambda item: (str(item["date"]), str(item["inverter_sn"])))
    return rows


def write_site_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "station_id",
                "station_name",
                "inverter_id",
                "inverter_sn",
                "inverter_model",
                "inverter_rated_kw",
                "daily_production_kwh",
                "full_hour",
                "money",
                "raw_energy_value",
                "raw_energy_unit",
                "raw_energy_scale",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_normalized_site_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    normalized_rows = [normalize_daily_inverter_row("solis", row) for row in rows]
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
    parser.add_argument(
        "--years-back",
        type=int,
        default=2,
        help="How many years of monthly history to export. Default: 2.",
    )
    parser.add_argument(
        "--output-subdir",
        default="",
        help="Optional subdirectory under dumps/ to write output files into, such as raw or normalized.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    dumps_dir = repo_root / "dumps"
    if args.output_subdir:
        dumps_dir = dumps_dir / args.output_subdir

    today = dt.date.today()
    start = dt.date(today.year - max(args.years_back, 1), today.month, 1)
    months = month_range(start.year, start.month, today.year, today.month)

    session = build_session()
    client = SolisWebApiClient(session)
    sites = client.list_all_sites(page_size=100, station_type="1")
    if not sites:
        raise RuntimeError("No Solis sites returned.")

    total_rows = 0
    written_files = 0
    for index, site in enumerate(sites, start=1):
        station_id = str(site.get("id") or "")
        station_name = str(site.get("stationName") or f"site_{index}")
        if not station_id:
            continue
        index_payload = client.inverter_index_list(station_id=station_id)
        records = index_payload.get("data", {}).get("page", {}).get("records", [])
        if not isinstance(records, list) or not records:
            print(f"[{index}/{len(sites)}] Skipped {station_name}: no inverters.")
            continue
        rows = export_site_rows(client, station_id, station_name, records, months=months)
        if not rows:
            print(f"[{index}/{len(sites)}] Skipped {station_name}: no daily output rows.")
            continue
        output_path = dumps_dir / f"solis__{slugify(station_name)}__{station_id}.csv"
        if args.normalized:
            write_normalized_site_csv(output_path, rows)
        else:
            write_site_csv(output_path, rows)
        written_files += 1
        total_rows += len(rows)
        print(f"[{index}/{len(sites)}] Wrote {len(rows)} rows to {output_path.name}")

    print(f"Completed: {written_files} file(s), {total_rows} total row(s), output folder {dumps_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
