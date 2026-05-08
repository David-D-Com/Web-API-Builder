"""Compare the target 100 kW Solis inverter against the same model fleet.

This script finds every inverter in the accessible Solis account that matches
the target inverter's machine/model family, then compares recent daily
performance across the fleet.

The core question is not whether the target unit *can* hit nameplate, but
whether it falls away from its peers more sharply on weaker days.
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

from soliscloud_web_api import SolisSession, SolisWebApiClient, SolisWebApiError
from solis_inverter_cap_report import (
    InverterMeta,
    build_meta_from_index_record,
    build_session as build_base_session,
    print_header,
    print_json,
    print_kv,
    safe_float,
)


TARGET_INVERTER_ID = "1308675217949337487"
TARGET_SN = "40130B1248129102"
TARGET_MACHINE = "S5-GC100K-US/S5-GC100K-HV"


def build_session() -> SolisSession:
    """Build a session tuned for research work.

    We deliberately enable broad caching here so repeated fleet comparisons do
    not keep re-hitting the same inventory and historical endpoints.
    """

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


def infer_interval_minutes(times: list[dt.datetime]) -> float:
    if len(times) < 2:
        return 0.0
    deltas = [
        (later - earlier).total_seconds() / 60.0
        for earlier, later in zip(times, times[1:])
        if later > earlier
    ]
    return statistics.median(deltas) if deltas else 0.0


def parse_day_series(payload: dict[str, Any], *, series_key: str = "pac") -> tuple[list[dt.datetime], list[float]]:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return [], []
    time_values = data.get("timeStr", [])
    series_values = data.get(series_key, [])
    if not isinstance(time_values, list) or not isinstance(series_values, list):
        return [], []
    points: list[tuple[dt.datetime, float]] = []
    for time_value, raw_value in zip(time_values, series_values):
        if not isinstance(time_value, str):
            continue
        try:
            timestamp = dt.datetime.fromisoformat(time_value)
        except ValueError:
            continue
        points.append((timestamp, safe_float(raw_value) / 1000.0))
    return [item[0] for item in points], [item[1] for item in points]


def daily_metrics(
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
    times, kw_values = parse_day_series(chart_payload, series_key="pac")
    interval_minutes = infer_interval_minutes(times)
    positive = [value for value in kw_values if value > 0.1]
    max_kw = max(positive) if positive else 0.0
    p95_threshold = meta.rated_kw * 0.95 if meta.rated_kw else 0.0
    p90_threshold = meta.rated_kw * 0.90 if meta.rated_kw else 0.0
    hours_ge_95 = sum(value >= p95_threshold for value in kw_values) * interval_minutes / 60.0
    hours_ge_90 = sum(value >= p90_threshold for value in kw_values) * interval_minutes / 60.0
    energy_data = energy_payload.get("data", {})
    if not isinstance(energy_data, dict):
        energy_data = {}
    return {
        "date": day_str,
        "max_kw": max_kw,
        "max_pct_nameplate": (max_kw / meta.rated_kw * 100.0) if meta.rated_kw else 0.0,
        "hours_ge_95pct": hours_ge_95,
        "hours_ge_90pct": hours_ge_90,
        "full_hour": safe_float(energy_data.get("fullHour")),
        "energy_kwh": safe_float(energy_data.get("energy")),
        "point_count": len(kw_values),
    }


def find_matching_fleet(client: SolisWebApiClient) -> list[InverterMeta]:
    sites = client.list_all_sites(page_size=100, station_type="1")
    matches: list[InverterMeta] = []
    for site in sites:
        station_id = str(site.get("id") or "")
        if not station_id:
            continue
        try:
            payload = client.inverter_index_list(station_id=station_id, page_size=200)
        except SolisWebApiError:
            continue
        page = (payload.get("data") or {}).get("page") or {}
        records = page.get("records") or []
        if not isinstance(records, list):
            continue
        for record in records:
            meta = build_meta_from_index_record(record)
            if meta.machine == TARGET_MACHINE and abs(meta.rated_kw - 100.0) < 0.5:
                matches.append(meta)
    matches.sort(key=lambda item: (item.station_name.lower(), item.sn))
    return matches


def summarize_unit(meta: InverterMeta, rows: list[dict[str, Any]], *, focus_dates: list[str]) -> dict[str, Any]:
    producing = [row for row in rows if row["full_hour"] > 0.25]
    if not producing:
        return {
            "station_name": meta.station_name,
            "sn": meta.sn,
            "best_full_hour": 0.0,
            "best_hours95": 0.0,
            "focus_days": {},
        }
    best_full_hour = max(row["full_hour"] for row in producing)
    best_hours95 = max(row["hours_ge_95pct"] for row in producing)
    best_max_pct = max(row["max_pct_nameplate"] for row in producing)

    focus_summary: dict[str, Any] = {}
    for focus_date in focus_dates:
        row = next((item for item in rows if item["date"] == focus_date), None)
        if row is None:
            continue
        focus_summary[focus_date] = {
            "full_hour": row["full_hour"],
            "hours_ge_95pct": row["hours_ge_95pct"],
            "max_pct_nameplate": row["max_pct_nameplate"],
            "full_hour_vs_best": (row["full_hour"] / best_full_hour) if best_full_hour else None,
            "hours95_vs_best": (row["hours_ge_95pct"] / best_hours95) if best_hours95 else None,
            "max_pct_vs_best": (row["max_pct_nameplate"] / best_max_pct) if best_max_pct else None,
        }

    return {
        "station_name": meta.station_name,
        "station_id": meta.station_id,
        "inverter_id": meta.inverter_id,
        "sn": meta.sn,
        "machine": meta.machine,
        "best_full_hour": best_full_hour,
        "best_hours95": best_hours95,
        "best_max_pct_nameplate": best_max_pct,
        "mean_full_hour": statistics.mean(row["full_hour"] for row in producing),
        "mean_hours95": statistics.mean(row["hours_ge_95pct"] for row in producing),
        "focus_days": focus_summary,
    }


def fleet_focus_table(
    summaries: list[dict[str, Any]],
    *,
    focus_date: str,
    target_sn: str,
) -> dict[str, Any]:
    rows = []
    for item in summaries:
        focus = item["focus_days"].get(focus_date)
        if not focus:
            continue
        rows.append(
            {
                "station_name": item["station_name"],
                "sn": item["sn"],
                "full_hour": focus["full_hour"],
                "hours_ge_95pct": focus["hours_ge_95pct"],
                "max_pct_nameplate": focus["max_pct_nameplate"],
                "full_hour_vs_best": focus["full_hour_vs_best"],
                "hours95_vs_best": focus["hours95_vs_best"],
                "is_target": item["sn"] == target_sn,
            }
        )
    rows.sort(key=lambda row: (row["full_hour_vs_best"] or -1.0))
    target = next((row for row in rows if row["is_target"]), None)
    peers = [row for row in rows if not row["is_target"]]
    return {
        "focus_date": focus_date,
        "rows": rows,
        "target": target,
        "peer_median_full_hour_vs_best": (
            statistics.median(row["full_hour_vs_best"] for row in peers if row["full_hour_vs_best"] is not None)
            if peers
            else None
        ),
        "peer_median_hours95_vs_best": (
            statistics.median(row["hours95_vs_best"] for row in peers if row["hours95_vs_best"] is not None)
            if peers
            else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare the target 100 kW inverter against same-model peers.")
    parser.add_argument("--days", type=int, default=21, help="Trailing days to analyze ending today.")
    parser.add_argument(
        "--focus-date",
        action="append",
        default=[],
        help="Specific YYYY-MM-DD dates to highlight. May be supplied more than once.",
    )
    parser.add_argument("--json-out", help="Optional path to write the full report JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=max(args.days - 1, 0))
    focus_dates = list(dict.fromkeys(args.focus_date or ["2026-04-28", "2026-05-04", "2026-05-05"]))

    try:
        client = SolisWebApiClient(build_session())
        fleet = find_matching_fleet(client)
        if not fleet:
            raise SolisWebApiError("No matching 100 kW fleet units were found.")
        target = next((meta for meta in fleet if meta.sn == TARGET_SN or meta.inverter_id == TARGET_INVERTER_ID), None)
        if target is None:
            raise SolisWebApiError("Target inverter was not found in the matching fleet list.")

        print_header("Matching 100 kW Fleet")
        print_kv("Fleet count", len(fleet))
        print_json(
            [
                {
                    "station_name": meta.station_name,
                    "station_id": meta.station_id,
                    "inverter_id": meta.inverter_id,
                    "sn": meta.sn,
                }
                for meta in fleet
            ]
        )

        profile_time_zone = safe_float((client.profile().get("data") or {}).get("timeZone"), -7.0)
        days = daterange(start_date, end_date)
        all_rows: dict[str, list[dict[str, Any]]] = {}
        for meta in fleet:
            all_rows[meta.sn] = [
                daily_metrics(client, meta, day=day, time_zone=profile_time_zone)
                for day in days
            ]

        summaries = [
            summarize_unit(meta, all_rows[meta.sn], focus_dates=focus_dates)
            for meta in fleet
        ]

        print_header("Fleet Summary")
        print_json(summaries)

        focus_tables = [
            fleet_focus_table(summaries, focus_date=focus_date, target_sn=target.sn)
            for focus_date in focus_dates
        ]
        for table in focus_tables:
            print_header(f"Fleet Focus {table['focus_date']}")
            print_json(table)

        target_summary = next(item for item in summaries if item["sn"] == target.sn)
        findings: list[str] = []
        for table in focus_tables:
            target_row = table["target"]
            if not target_row:
                continue
            peer_full = table["peer_median_full_hour_vs_best"]
            peer_h95 = table["peer_median_hours95_vs_best"]
            if peer_full is not None and target_row["full_hour_vs_best"] is not None:
                delta = target_row["full_hour_vs_best"] - peer_full
                if delta <= -0.15:
                    findings.append(
                        f"On {table['focus_date']}, the target full-hour ratio versus its own best day "
                        f"was {abs(delta):.2%} below the peer median."
                    )
            if peer_h95 is not None and target_row["hours95_vs_best"] is not None:
                delta = target_row["hours95_vs_best"] - peer_h95
                if delta <= -0.15:
                    findings.append(
                        f"On {table['focus_date']}, the target >=95% duration ratio versus its own best day "
                        f"was {abs(delta):.2%} below the peer median."
                    )

        report = {
            "window": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": args.days,
            },
            "target": {
                "station_name": target.station_name,
                "station_id": target.station_id,
                "inverter_id": target.inverter_id,
                "sn": target.sn,
            },
            "fleet_count": len(fleet),
            "summaries": summaries,
            "focus_tables": focus_tables,
            "findings": findings,
        }

        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        print_header("Key Findings")
        print_json({"findings": findings, "target_summary": target_summary})
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
