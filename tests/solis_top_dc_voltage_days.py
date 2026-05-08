"""Find the top N dates by maximum observed DC voltage for two inverters."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from soliscloud_web_api import SolisSession, SolisWebApiClient, SolisWebApiError
from solis_inverter_cap_report import build_session as build_base_session, print_header, print_json, print_kv, safe_float


TARGETS = [
    {
        "label": "100 kW target",
        "inverter_id": "1308675217949337487",
        "sn": "40130B1248129102",
        "default_start": dt.date(2025, 8, 22),
    },
    {
        "label": "40 kW reference",
        "inverter_id": "1308675217949416229",
        "sn": "1811450248060005",
        "default_start": dt.date(2025, 8, 22),
    },
]

SEARCH_INFO = ",".join(
    [f"u_pv{i}" for i in range(1, 21)] + [f"mppt_upv{i}" for i in range(1, 11)]
)


def build_session() -> SolisSession:
    base = build_base_session()
    return SolisSession(
        username=base.username,
        password=base.password,
        device_id=base.device_id,
        token=base.token,
        filter_results=False,
        preferred_language="both",
        cache_enabled=True,
        cache_policy="all",
        cache_dir=base.cache_dir,
        cache_live_data=True,
    )


def daterange(start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    days: list[dt.date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += dt.timedelta(days=1)
    return days


def day_max_dc_voltage(
    client: SolisWebApiClient,
    inverter_id: str,
    *,
    day: dt.date,
    time_zone: float,
) -> dict[str, Any]:
    payload = client.inverter_chart_day(
        inverter_id,
        day=day.isoformat(),
        time_zone=time_zone,
        search_info=SEARCH_INFO,
    )
    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}
    best_value = 0.0
    best_key = None
    best_index = None
    for key, values in data.items():
        if key == "timeStr" or not isinstance(values, list):
            continue
        if not (key.startswith("u_pv") or key.startswith("mppt_upv")):
            continue
        for index, raw_value in enumerate(values):
            value = safe_float(raw_value)
            if value > best_value:
                best_value = value
                best_key = key
                best_index = index
    time_values = data.get("timeStr", [])
    best_time = None
    if isinstance(time_values, list) and best_index is not None and 0 <= best_index < len(time_values):
        best_time = time_values[best_index]
    return {
        "date": day.isoformat(),
        "max_dc_voltage_v": best_value,
        "series": best_key,
        "time": best_time,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Top dates by maximum observed DC voltage.")
    parser.add_argument("--top", type=int, default=5, help="Number of dates to return per inverter.")
    parser.add_argument("--start-date", help="Optional YYYY-MM-DD override for the start date.")
    parser.add_argument("--end-date", help="Optional YYYY-MM-DD override for the end date.")
    parser.add_argument("--json-out", help="Optional path to write the report JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    end_date = dt.date.fromisoformat(args.end_date) if args.end_date else dt.date.today()
    try:
        client = SolisWebApiClient(build_session())
        profile = client.profile()
        time_zone = safe_float((profile.get("data") or {}).get("timeZone"), -7.0)
        report = {
            "window": {
                "start_date": args.start_date,
                "end_date": end_date.isoformat(),
            },
            "inverters": [],
        }

        for item in TARGETS:
            start_date = (
                dt.date.fromisoformat(args.start_date)
                if args.start_date
                else item["default_start"]
            )
            rows = [
                day_max_dc_voltage(
                    client,
                    item["inverter_id"],
                    day=day,
                    time_zone=time_zone,
                )
                for day in daterange(start_date, end_date)
            ]
            ranked = sorted(rows, key=lambda row: (row["max_dc_voltage_v"], row["date"]), reverse=True)
            report["inverters"].append(
                {
                    "label": item["label"],
                    "sn": item["sn"],
                    "inverter_id": item["inverter_id"],
                    "top_dates": ranked[: args.top],
                }
            )

        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        for inverter in report["inverters"]:
            print_header(inverter["label"])
            print_kv("SN", inverter["sn"])
            print_json(inverter["top_dates"])
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
