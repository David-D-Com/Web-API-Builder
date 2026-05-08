"""Compare the 100 kW inverter against the 40 kW baseline around change dates.

This script uses the same captured site context as the other inverter analysis
tooling, then evaluates before/after windows around notable configuration dates.
The core comparison is normalized performance:

- full-hour ratio: target_100kw / reference_40kw
- hours >=95% of nameplate, compared on the same day
- daily max power as % of nameplate

If the 100 kW inverter behaves similarly to the 40 kW inverter, these ratios
should stay close to 1.0 on good production days.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from soliscloud_web_api import SolisWebApiClient, SolisWebApiError
from solis_inverter_cap_report import (
    InverterMeta,
    build_meta_from_index_record,
    build_session,
    find_latest_capture_dir,
    infer_capture_context,
    latest_producing_day,
    print_header,
    print_json,
    print_kv,
    safe_float,
    select_reference_inverter,
)


CHANGE_DATES = [
    dt.date(2025, 1, 12),
    dt.date(2025, 11, 7),
    dt.date(2026, 1, 28),
    dt.date(2026, 4, 1),
    dt.date(2026, 4, 30),
    dt.date(2026, 11, 2),
]


def daterange(start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    days: list[dt.date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += dt.timedelta(days=1)
    return days


def parse_day_metrics(
    client: SolisWebApiClient,
    meta: InverterMeta,
    *,
    day: dt.date,
    time_zone: float,
) -> dict[str, Any]:
    day_str = day.isoformat()
    chart_payload = client.inverter_chart_day(
        meta.inverter_id,
        day=day_str,
        time_zone=time_zone,
        search_info="pac",
    )
    energy_payload = client.inverter_all_energy(meta.inverter_id, begin_time=day_str)
    data = chart_payload.get("data", {})
    if not isinstance(data, dict):
        data = {}
    times = data.get("timeStr", [])
    pac = data.get("pac", [])
    if not isinstance(times, list) or not isinstance(pac, list):
        times = []
        pac = []
    kw_values = [safe_float(value) / 1000.0 for value in pac]
    positive = [value for value in kw_values if value > 0.1]
    interval_minutes = 5.0 if len(kw_values) >= 2 else 0.0
    energy_data = energy_payload.get("data", {})
    if not isinstance(energy_data, dict):
        energy_data = {}
    max_kw = max(positive) if positive else 0.0
    p95_threshold = meta.rated_kw * 0.95 if meta.rated_kw else 0.0
    p90_threshold = meta.rated_kw * 0.90 if meta.rated_kw else 0.0
    hours_ge_95 = sum(value >= p95_threshold for value in kw_values) * interval_minutes / 60.0
    hours_ge_90 = sum(value >= p90_threshold for value in kw_values) * interval_minutes / 60.0
    return {
        "date": day_str,
        "point_count": len(kw_values),
        "max_kw": max_kw,
        "max_pct_nameplate": (max_kw / meta.rated_kw * 100.0) if meta.rated_kw else 0.0,
        "hours_ge_95pct": hours_ge_95,
        "hours_ge_90pct": hours_ge_90,
        "energy_kwh": safe_float(energy_data.get("energy")),
        "full_hour": safe_float(energy_data.get("fullHour")),
    }


def collect_paired_metrics(
    client: SolisWebApiClient,
    target_meta: InverterMeta,
    ref_meta: InverterMeta,
    *,
    dates: list[dt.date],
    time_zone: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in dates:
        target = parse_day_metrics(client, target_meta, day=day, time_zone=time_zone)
        reference = parse_day_metrics(client, ref_meta, day=day, time_zone=time_zone)
        row = {
            "date": target["date"],
            "target": target,
            "reference": reference,
            "target_vs_ref_full_hour_ratio": (
                target["full_hour"] / reference["full_hour"]
                if reference["full_hour"] > 0
                else None
            ),
            "target_vs_ref_hours95_ratio": (
                target["hours_ge_95pct"] / reference["hours_ge_95pct"]
                if reference["hours_ge_95pct"] > 0
                else None
            ),
            "target_minus_ref_max_pct": (
                target["max_pct_nameplate"] - reference["max_pct_nameplate"]
            ),
        }
        rows.append(row)
    return rows


def filter_good_reference_days(rows: list[dict[str, Any]], *, min_ref_full_hour: float) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["reference"]["full_hour"] >= min_ref_full_hour
    ]


def summarize_window(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "days": 0,
            "mean_target_full_hour": 0.0,
            "mean_ref_full_hour": 0.0,
            "mean_full_hour_ratio": None,
            "mean_target_hours95": 0.0,
            "mean_ref_hours95": 0.0,
            "mean_hours95_ratio": None,
            "mean_target_max_pct": 0.0,
            "mean_ref_max_pct": 0.0,
            "mean_delta_max_pct": None,
        }

    def mean_of(values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None]
        return statistics.mean(clean) if clean else None

    return {
        "days": len(rows),
        "mean_target_full_hour": statistics.mean(row["target"]["full_hour"] for row in rows),
        "mean_ref_full_hour": statistics.mean(row["reference"]["full_hour"] for row in rows),
        "mean_full_hour_ratio": mean_of([row["target_vs_ref_full_hour_ratio"] for row in rows]),
        "mean_target_hours95": statistics.mean(row["target"]["hours_ge_95pct"] for row in rows),
        "mean_ref_hours95": statistics.mean(row["reference"]["hours_ge_95pct"] for row in rows),
        "mean_hours95_ratio": mean_of([row["target_vs_ref_hours95_ratio"] for row in rows]),
        "mean_target_max_pct": statistics.mean(row["target"]["max_pct_nameplate"] for row in rows),
        "mean_ref_max_pct": statistics.mean(row["reference"]["max_pct_nameplate"] for row in rows),
        "mean_delta_max_pct": statistics.mean(row["target_minus_ref_max_pct"] for row in rows),
    }


def compare_windows(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def delta(after_key: str) -> float | None:
        before_value = before.get(after_key)
        after_value = after.get(after_key)
        if before_value is None or after_value is None:
            return None
        return after_value - before_value

    return {
        "full_hour_ratio_change": delta("mean_full_hour_ratio"),
        "hours95_ratio_change": delta("mean_hours95_ratio"),
        "delta_max_pct_change": delta("mean_delta_max_pct"),
    }


def classify_change(comparison: dict[str, Any], *, improvement_threshold: float) -> str:
    fh = comparison.get("full_hour_ratio_change")
    h95 = comparison.get("hours95_ratio_change")
    dmax = comparison.get("delta_max_pct_change")
    positive_signals = 0
    negative_signals = 0
    if fh is not None:
        if fh >= improvement_threshold:
            positive_signals += 1
        elif fh <= -improvement_threshold:
            negative_signals += 1
    if h95 is not None:
        if h95 >= improvement_threshold:
            positive_signals += 1
        elif h95 <= -improvement_threshold:
            negative_signals += 1
    if dmax is not None:
        if dmax >= improvement_threshold * 100.0:
            positive_signals += 1
        elif dmax <= -improvement_threshold * 100.0:
            negative_signals += 1
    if positive_signals > negative_signals and positive_signals >= 2:
        return "improved"
    if negative_signals > positive_signals and negative_signals >= 2:
        return "worsened"
    return "no_clear_change"


def commissioning_floor_date(target_meta: InverterMeta, ref_meta: InverterMeta) -> dt.date | None:
    candidates = []
    for meta in (target_meta, ref_meta):
        fis = meta.extra.get("fisGenerateTime") or meta.extra.get("fisGenerateDate")
        if fis:
            try:
                candidates.append(dt.datetime.utcfromtimestamp(float(fis) / 1000.0).date())
            except (TypeError, ValueError, OSError):
                pass
    return min(candidates) if candidates else None


def evaluate_change_dates(
    client: SolisWebApiClient,
    target_meta: InverterMeta,
    ref_meta: InverterMeta,
    *,
    time_zone: float,
    window_days: int,
    min_ref_full_hour: float,
    improvement_threshold: float,
    today: dt.date,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    floor_date = commissioning_floor_date(target_meta, ref_meta)
    for change_date in CHANGE_DATES:
        if change_date > today:
            results.append(
                {
                    "change_date": change_date.isoformat(),
                    "status": "future",
                    "reason": "Date is after the current available production history.",
                }
            )
            continue
        if floor_date and change_date < floor_date:
            results.append(
                {
                    "change_date": change_date.isoformat(),
                    "status": "pre_commissioning",
                    "reason": f"Date is before inverter commissioning ({floor_date.isoformat()}).",
                }
            )
            continue

        before_start = change_date - dt.timedelta(days=window_days)
        before_end = change_date - dt.timedelta(days=1)
        after_start = change_date
        after_end = min(today, change_date + dt.timedelta(days=window_days - 1))

        before_rows = collect_paired_metrics(
            client,
            target_meta,
            ref_meta,
            dates=daterange(before_start, before_end),
            time_zone=time_zone,
        )
        after_rows = collect_paired_metrics(
            client,
            target_meta,
            ref_meta,
            dates=daterange(after_start, after_end),
            time_zone=time_zone,
        )

        before_good = filter_good_reference_days(before_rows, min_ref_full_hour=min_ref_full_hour)
        after_good = filter_good_reference_days(after_rows, min_ref_full_hour=min_ref_full_hour)
        before_summary = summarize_window(before_good)
        after_summary = summarize_window(after_good)
        comparison = compare_windows(before_summary, after_summary)

        results.append(
            {
                "change_date": change_date.isoformat(),
                "status": "analyzed",
                "before_window": {
                    "start": before_start.isoformat(),
                    "end": before_end.isoformat(),
                    "summary": before_summary,
                    "sample_days": before_good[-3:],
                },
                "after_window": {
                    "start": after_start.isoformat(),
                    "end": after_end.isoformat(),
                    "summary": after_summary,
                    "sample_days": after_good[:3],
                },
                "comparison": comparison,
                "classification": classify_change(
                    comparison,
                    improvement_threshold=improvement_threshold,
                ),
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        help="Specific capture directory under har/ to analyze. Defaults to the newest one.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Days before and after each change date to compare. Default: 7.",
    )
    parser.add_argument(
        "--min-ref-full-hour",
        type=float,
        default=4.0,
        help="Only include days where the 40 kW inverter had at least this many full hours. Default: 4.0.",
    )
    parser.add_argument(
        "--improvement-threshold",
        type=float,
        default=0.10,
        help="Relative ratio change treated as meaningful improvement or regression. Default: 0.10.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the full report as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        capture_dir = Path(args.capture_dir) if args.capture_dir else find_latest_capture_dir()
        context = infer_capture_context(capture_dir)
        station_id = context["station_id"]
        target_inverter_id = context["target_inverter_id"]

        client = SolisWebApiClient(build_session())
        station_detail_payload = client.station_detail(station_id)
        station_data = station_detail_payload.get("data", {})
        if not isinstance(station_data, dict):
            raise SolisWebApiError("Unexpected station detail payload shape.")
        time_zone = safe_float(station_data.get("timeZone"), -7.0)
        current_zone_date = dt.date.fromisoformat(
            str(station_data.get("nowZoneDateStr") or dt.date.today().isoformat())
        )

        inverter_index_payload = client.inverter_index_list(station_id=station_id)
        index_data = inverter_index_payload.get("data", {})
        page = index_data.get("page", {}) if isinstance(index_data, dict) else {}
        records = page.get("records", []) if isinstance(page, dict) else []
        if not isinstance(records, list):
            raise SolisWebApiError("Unexpected inverter index payload shape.")

        record_by_id = {str(record.get("id")): record for record in records if isinstance(record, dict)}
        if target_inverter_id not in record_by_id:
            raise SolisWebApiError(
                f"Target inverter {target_inverter_id} was not found in station {station_id} inverter list."
            )
        target_meta = build_meta_from_index_record(record_by_id[target_inverter_id])
        ref_meta = select_reference_inverter(
            records,
            target_inverter_id=target_inverter_id,
            preferred_rated_kw=40.0,
        )

        results = evaluate_change_dates(
            client,
            target_meta,
            ref_meta,
            time_zone=time_zone,
            window_days=args.window_days,
            min_ref_full_hour=args.min_ref_full_hour,
            improvement_threshold=args.improvement_threshold,
            today=current_zone_date,
        )

        report = {
            "station": {
                "station_id": station_id,
                "station_name": target_meta.station_name,
            },
            "target": {
                "inverter_id": target_meta.inverter_id,
                "sn": target_meta.sn,
                "rated_kw": target_meta.rated_kw,
                "machine": target_meta.machine,
            },
            "reference": {
                "inverter_id": ref_meta.inverter_id,
                "sn": ref_meta.sn,
                "rated_kw": ref_meta.rated_kw,
                "machine": ref_meta.machine,
            },
            "settings": {
                "window_days": args.window_days,
                "min_ref_full_hour": args.min_ref_full_hour,
                "improvement_threshold": args.improvement_threshold,
                "current_zone_date": current_zone_date.isoformat(),
            },
            "change_results": results,
        }

        print_header("Change Window Analysis")
        print_kv("Station", f"{target_meta.station_name} ({station_id})")
        print_kv("Target inverter", f"{target_meta.sn} ({target_meta.rated_kw:.0f} kW)")
        print_kv("Reference inverter", f"{ref_meta.sn} ({ref_meta.rated_kw:.0f} kW)")
        print_kv("Window days", args.window_days)
        print_kv("Reference full-hour floor", args.min_ref_full_hour)
        print_header("Results")
        print_json(report)

        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print_kv("JSON report written", args.json_out)
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
