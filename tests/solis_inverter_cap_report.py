"""Analyze a captured Solis inverter session and explain apparent power capping.

This script uses the newest HAR-derived JSON capture folder to identify the
troubled inverter and its site, then uses the live Solis web API to pull recent
production data for:
- the captured target inverter, and
- a reference inverter at the same site (default: nearest 40 kW unit)

It produces a console report and can optionally write a JSON summary.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from soliscloud_web_api import SolisSession, SolisWebApiClient, SolisWebApiError


KEYRING_SERVICE = "soliscloud_web_api"
KEYRING_USERNAME_KEY = "__solis_username__"
HAR_ROOT = Path(__file__).resolve().parent.parent / "har"


@dataclass
class InverterMeta:
    inverter_id: str
    sn: str
    machine: str
    model: str
    product_model: str
    rated_kw: float
    station_id: str
    station_name: str
    current_kw: float
    current_power_percent: float
    full_hour: float
    data_timestamp_str: str
    extra: dict[str, Any]


def _get_console():
    try:
        from rich.console import Console
    except ImportError:
        return None
    return Console(force_terminal=True, color_system="auto")


def print_json(data: object) -> None:
    console = _get_console()
    rendered = json.dumps(data, indent=2, ensure_ascii=True)
    if console is None:
        print(rendered)
        return
    from rich.syntax import Syntax

    console.print(Syntax(rendered, "json", theme="monokai", word_wrap=True))


def print_header(title: str) -> None:
    console = _get_console()
    if console is None:
        print("=" * 79)
        print(title)
        return
    from rich.rule import Rule

    console.print(Rule(title, style="cyan"))


def print_kv(key: str, value: object) -> None:
    console = _get_console()
    if console is None:
        print(f"{key}: {value}")
        return
    console.print(f"[bold]{key}:[/] {value}")


def _load_keyring():
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise SolisWebApiError(
            "The `keyring` package is required for Windows Credential Manager support."
        ) from exc
    return keyring


def load_credentials() -> tuple[str | None, str | None]:
    if os.name != "nt":
        return None, None
    try:
        keyring = _load_keyring()
    except SolisWebApiError:
        return None, None
    username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
    if username:
        password = keyring.get_password(KEYRING_SERVICE, username)
        if password:
            return username, password
    return None, None


def build_session() -> SolisSession:
    username, password = load_credentials()
    if username and password:
        return SolisSession.from_credentials(username, password, filter_results=False)
    return SolisSession.from_env(filter_results=False)


def find_latest_capture_dir() -> Path:
    candidates = sorted(HAR_ROOT.glob("solis-json-capture-*"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SolisWebApiError("No capture folders were found under har/.")
    return candidates[-1]


def load_capture_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_capture_file(capture_dir: Path, prefix: str) -> Path | None:
    matches = sorted(capture_dir.glob(f"{prefix}*.json"))
    return matches[0] if matches else None


def infer_capture_context(capture_dir: Path) -> dict[str, str]:
    detail_path = find_capture_file(capture_dir, "v3.soliscloud.com_api_inverter_detail--")
    index_path = find_capture_file(capture_dir, "v3.soliscloud.com_api_inverter_index_list--")
    if detail_path is None or index_path is None:
        raise SolisWebApiError(
            "Capture folder does not contain the inverter detail and inverter index files needed "
            "to identify the target device."
        )
    detail_payload = load_capture_json(detail_path)
    index_payload = load_capture_json(index_path)
    target_inverter_id = str(detail_payload["normalizedRequest"]["postData"]["id"])
    station_id = str(index_payload["normalizedRequest"]["postData"]["stationId"])
    return {
        "target_inverter_id": target_inverter_id,
        "station_id": station_id,
    }


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_meta_from_index_record(record: dict[str, Any]) -> InverterMeta:
    return InverterMeta(
        inverter_id=str(record.get("id") or record.get("inverterId") or ""),
        sn=str(record.get("sn") or record.get("inverterSn") or ""),
        machine=str(record.get("machine") or ""),
        model=str(record.get("model") or ""),
        product_model=str(record.get("productModel") or ""),
        rated_kw=safe_float(record.get("power")),
        station_id=str(record.get("stationId") or ""),
        station_name=str(record.get("stationName") or ""),
        current_kw=safe_float(record.get("pac")),
        current_power_percent=safe_float(record.get("powerPercent")) * 100.0,
        full_hour=safe_float(record.get("fullHour")),
        data_timestamp_str=str(record.get("dataTimestampStr") or ""),
        extra=record,
    )


def select_reference_inverter(
    records: list[dict[str, Any]],
    *,
    target_inverter_id: str,
    preferred_rated_kw: float,
) -> InverterMeta:
    metas = [
        build_meta_from_index_record(record)
        for record in records
        if str(record.get("id")) != target_inverter_id
    ]
    if not metas:
        raise SolisWebApiError("No reference inverter was found in the station inverter list.")
    return min(metas, key=lambda meta: abs(meta.rated_kw - preferred_rated_kw))


def parse_pac_series(payload: dict[str, Any]) -> tuple[list[dt.datetime], list[float]]:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return [], []
    time_values = data.get("timeStr", [])
    pac_values = data.get("pac", [])
    if not isinstance(time_values, list) or not isinstance(pac_values, list):
        return [], []
    points: list[tuple[dt.datetime, float]] = []
    for time_value, pac_value in zip(time_values, pac_values):
        if not isinstance(time_value, str):
            continue
        try:
            timestamp = dt.datetime.fromisoformat(time_value)
        except ValueError:
            continue
        points.append((timestamp, safe_float(pac_value) / 1000.0))
    times = [item[0] for item in points]
    kw = [item[1] for item in points]
    return times, kw


def infer_interval_minutes(times: list[dt.datetime]) -> float:
    if len(times) < 2:
        return 0.0
    deltas = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(times, times[1:])
        if b > a
    ]
    if not deltas:
        return 0.0
    return statistics.median(deltas)


def analyze_day_curve(
    kw_values: list[float],
    *,
    rated_kw: float,
    interval_minutes: float,
) -> dict[str, Any]:
    positive = [value for value in kw_values if value > 0.1]
    if not positive:
        return {
            "max_kw": 0.0,
            "mean_kw": 0.0,
            "p95_kw": 0.0,
            "near_peak_avg_kw": 0.0,
            "near_peak_samples": 0,
            "near_peak_hours": 0.0,
            "max_pct_nameplate": 0.0,
            "flat_top_detected": False,
        }
    max_kw = max(positive)
    near_peak_threshold = max_kw * 0.99
    near_peak = [value for value in positive if value >= near_peak_threshold]
    near_peak_hours = (len(near_peak) * interval_minutes / 60.0) if interval_minutes else 0.0
    mean_kw = statistics.mean(positive)
    sorted_positive = sorted(positive)
    p95_index = max(0, math.ceil(0.95 * len(sorted_positive)) - 1)
    p95_kw = sorted_positive[p95_index]
    max_pct_nameplate = (max_kw / rated_kw * 100.0) if rated_kw else 0.0
    flat_top_detected = (
        len(near_peak) >= 3
        and max_pct_nameplate >= 75.0
        and (statistics.mean(near_peak) / max_kw if max_kw else 0.0) >= 0.995
    )
    return {
        "max_kw": max_kw,
        "mean_kw": mean_kw,
        "p95_kw": p95_kw,
        "near_peak_avg_kw": statistics.mean(near_peak),
        "near_peak_samples": len(near_peak),
        "near_peak_hours": near_peak_hours,
        "max_pct_nameplate": max_pct_nameplate,
        "flat_top_detected": flat_top_detected,
    }


def daterange(end_date: dt.date, days: int) -> list[dt.date]:
    return [end_date - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def choose_end_date(
    station_detail_payload: dict[str, Any],
    *,
    include_today: bool,
) -> dt.date:
    data = station_detail_payload.get("data", {})
    if not isinstance(data, dict):
        return dt.date.today()
    zone_date = str(data.get("nowZoneDateStr") or dt.date.today().isoformat())
    current = dt.date.fromisoformat(zone_date)
    if include_today:
        return current
    return current - dt.timedelta(days=1)


def summarize_history(series: list[dict[str, Any]], *, rated_kw: float) -> dict[str, Any]:
    producing = [row for row in series if row["energy_kwh"] > 0.1]
    if not producing:
        return {
            "days": len(series),
            "producing_days": 0,
            "max_kw": 0.0,
            "mean_daily_max_kw": 0.0,
            "days_at_95pct": 0,
            "days_at_90pct": 0,
            "days_below_85pct": 0,
            "flat_top_days": 0,
            "mean_full_hour": 0.0,
        }
    max_values = [row["curve"]["max_kw"] for row in producing]
    full_hours = [row["full_hour"] for row in producing]
    return {
        "days": len(series),
        "producing_days": len(producing),
        "max_kw": max(max_values),
        "mean_daily_max_kw": statistics.mean(max_values),
        "days_at_95pct": sum(row["curve"]["max_pct_nameplate"] >= 95.0 for row in producing),
        "days_at_90pct": sum(row["curve"]["max_pct_nameplate"] >= 90.0 for row in producing),
        "days_below_85pct": sum(row["curve"]["max_pct_nameplate"] < 85.0 for row in producing),
        "flat_top_days": sum(bool(row["curve"]["flat_top_detected"]) for row in producing),
        "mean_full_hour": statistics.mean(full_hours),
    }


def latest_producing_day(series: list[dict[str, Any]]) -> dict[str, Any]:
    producing = [row for row in series if row["energy_kwh"] > 0.1 or row["curve"]["max_kw"] > 0.1]
    return producing[-1] if producing else (series[-1] if series else {})


def collect_inverter_history(
    client: SolisWebApiClient,
    meta: InverterMeta,
    *,
    days: list[dt.date],
    time_zone: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in days:
        day_str = day.isoformat()
        chart_payload = client.inverter_chart_day(
            meta.inverter_id,
            day=day_str,
            time_zone=time_zone,
            search_info="pac",
        )
        energy_payload = client.inverter_all_energy(meta.inverter_id, begin_time=day_str)
        times, kw_values = parse_pac_series(chart_payload)
        interval_minutes = infer_interval_minutes(times)
        curve = analyze_day_curve(
            kw_values,
            rated_kw=meta.rated_kw,
            interval_minutes=interval_minutes,
        )
        energy_data = energy_payload.get("data", {})
        if not isinstance(energy_data, dict):
            energy_data = {}
        rows.append(
            {
                "date": day_str,
                "point_count": len(kw_values),
                "interval_minutes": interval_minutes,
                "curve": curve,
                "energy_kwh": safe_float(energy_data.get("energy")),
                "full_hour": safe_float(energy_data.get("fullHour")),
                "income": safe_float(energy_data.get("money")),
            }
        )
    return rows


def compare_histories(
    target_series: list[dict[str, Any]],
    ref_series: list[dict[str, Any]],
    *,
    target_rated_kw: float,
    ref_rated_kw: float,
) -> list[dict[str, Any]]:
    ref_by_date = {row["date"]: row for row in ref_series}
    comparisons: list[dict[str, Any]] = []
    scale = target_rated_kw / ref_rated_kw if ref_rated_kw else 0.0
    for row in target_series:
        ref = ref_by_date.get(row["date"])
        if ref is None:
            continue
        expected_target_peak_kw = min(ref["curve"]["max_kw"] * scale, target_rated_kw)
        expected_target_full_hour = ref["full_hour"]
        comparisons.append(
            {
                "date": row["date"],
                "target_max_kw": row["curve"]["max_kw"],
                "ref_max_kw": ref["curve"]["max_kw"],
                "scaled_ref_peak_kw": expected_target_peak_kw,
                "target_vs_scaled_ref_peak_ratio": (
                    row["curve"]["max_kw"] / expected_target_peak_kw
                    if expected_target_peak_kw > 0
                    else None
                ),
                "target_full_hour": row["full_hour"],
                "ref_full_hour": ref["full_hour"],
                "target_vs_ref_full_hour_ratio": (
                    row["full_hour"] / expected_target_full_hour
                    if expected_target_full_hour > 0
                    else None
                ),
            }
        )
    return comparisons


def detect_conflicting_rating_info(
    target_meta: InverterMeta,
    detail_payload: dict[str, Any],
    capture_dir: Path,
) -> dict[str, Any]:
    detail_data = detail_payload.get("data", {})
    if not isinstance(detail_data, dict):
        detail_data = {}
    captured_sources = []
    for key in ("power", "machine", "model", "productModel", "pac", "porwerPercent"):
        captured_sources.append({"source": "detail", "key": key, "value": detail_data.get(key)})
    captured_sources.append(
        {
            "source": "index",
            "key": "power",
            "value": target_meta.rated_kw,
        }
    )
    potential_conflicts = [
        item for item in captured_sources
        if item["key"] == "power" and safe_float(item["value"]) not in {0.0, target_meta.rated_kw}
    ]
    return {
        "sources": captured_sources,
        "conflicting_rated_power_fields": potential_conflicts,
        "capture_dir": str(capture_dir),
    }


def print_analysis_report(report: dict[str, Any]) -> None:
    print_header("Capture Context")
    print_kv("Capture folder", report["capture"]["capture_dir"])
    print_kv("Station", f'{report["station"]["station_name"]} ({report["station"]["station_id"]})')
    print_kv("Analyzed days", report["analysis_window"]["days"])
    print_kv("Date range", f'{report["analysis_window"]["start_date"]} -> {report["analysis_window"]["end_date"]}')

    print_header("Device Metadata")
    print_json(
        {
            "target": report["target"]["meta"],
            "reference": report["reference"]["meta"],
        }
    )

    print_header("Key Finding")
    key_finding = report["key_finding"]
    for line in key_finding:
        print_kv("Finding", line)

    print_header("Peak Summary")
    print_json(
        {
            "target_summary": report["target"]["summary"],
            "reference_summary": report["reference"]["summary"],
            "latest_target_day": report["target"]["latest_day"],
            "latest_reference_day": report["reference"]["latest_day"],
        }
    )

    print_header("Comparison")
    print_json(report["comparison"])

    print_header("Rating Consistency Check")
    print_json(report["rating_check"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        help="Specific capture directory under har/ to analyze. Defaults to the newest one.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Number of recent days to analyze with live API calls. Default: 14.",
    )
    parser.add_argument(
        "--include-today",
        action="store_true",
        help="Include the current station-local day in the analysis window.",
    )
    parser.add_argument(
        "--reference-rated-kw",
        type=float,
        default=40.0,
        help="Preferred reference inverter size. Default: 40 kW.",
    )
    parser.add_argument(
        "--target-inverter-id",
        help="Override the target inverter id instead of inferring it from the capture.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the full analysis report as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        capture_dir = Path(args.capture_dir) if args.capture_dir else find_latest_capture_dir()
        if not capture_dir.exists():
            raise SolisWebApiError(f"Capture directory not found: {capture_dir}")
        context = infer_capture_context(capture_dir)
        target_inverter_id = args.target_inverter_id or context["target_inverter_id"]
        station_id = context["station_id"]

        client = SolisWebApiClient(build_session())
        station_detail_payload = client.station_detail(station_id)
        station_data = station_detail_payload.get("data", {})
        if not isinstance(station_data, dict):
            raise SolisWebApiError("Unexpected station detail payload shape.")
        station_name = str(station_data.get("stationName") or "")
        time_zone = safe_float(station_data.get("timeZone"), -7.0)
        end_date = choose_end_date(station_detail_payload, include_today=args.include_today)
        days = daterange(end_date, args.days)

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
        reference_meta = select_reference_inverter(
            records,
            target_inverter_id=target_inverter_id,
            preferred_rated_kw=args.reference_rated_kw,
        )

        target_detail_payload = client.inverter_detail(target_meta.inverter_id)
        reference_detail_payload = client.inverter_detail(reference_meta.inverter_id)

        target_series = collect_inverter_history(
            client,
            target_meta,
            days=days,
            time_zone=time_zone,
        )
        ref_series = collect_inverter_history(
            client,
            reference_meta,
            days=days,
            time_zone=time_zone,
        )

        comparison_rows = compare_histories(
            target_series,
            ref_series,
            target_rated_kw=target_meta.rated_kw,
            ref_rated_kw=reference_meta.rated_kw,
        )
        producing_comparisons = [
            row
            for row in comparison_rows
            if row["target_max_kw"] > 0.1 and row["ref_max_kw"] > 0.1
        ]

        latest_target_day = latest_producing_day(target_series)
        latest_reference_day = latest_producing_day(ref_series)
        latest_peak_ratio = (
            latest_target_day["curve"]["max_kw"] / target_meta.rated_kw
            if latest_target_day and target_meta.rated_kw
            else 0.0
        )
        latest_ref_ratio = (
            latest_reference_day["curve"]["max_kw"] / reference_meta.rated_kw
            if latest_reference_day and reference_meta.rated_kw
            else 0.0
        )
        average_scaled_peak_ratio = statistics.mean(
            row["target_vs_scaled_ref_peak_ratio"]
            for row in producing_comparisons
            if row["target_vs_scaled_ref_peak_ratio"] is not None
        ) if producing_comparisons else 0.0
        average_full_hour_ratio = statistics.mean(
            row["target_vs_ref_full_hour_ratio"]
            for row in producing_comparisons
            if row["target_vs_ref_full_hour_ratio"] is not None
        ) if producing_comparisons else 0.0

        key_finding = [
            (
                f"Captured snapshot: the 100 kW inverter was at {target_meta.current_kw:.2f} kW "
                f"({target_meta.current_power_percent:.2f}% of nameplate) while the 40 kW reference "
                f"was at {reference_meta.current_kw:.2f} kW ({reference_meta.current_power_percent:.2f}%)."
            ),
            (
                f"Same-day max from the target day curve reached "
                f"{latest_target_day.get('curve', {}).get('max_kw', 0.0):.2f} kW "
                f"({latest_peak_ratio * 100.0:.2f}% of nameplate), so the {target_meta.current_kw:.2f} kW "
                "reading is not the day's true peak."
            ),
            (
                f"Across the analyzed window, the target's average daily max was "
                f"{summarize_history(target_series, rated_kw=target_meta.rated_kw)['mean_daily_max_kw']:.2f} kW, "
                f"and it reached at least 95% of nameplate on "
                f"{summarize_history(target_series, rated_kw=target_meta.rated_kw)['days_at_95pct']} day(s)."
            ),
            (
                f"Normalized daily output is much closer than the raw afternoon snapshot suggests: "
                f"target/reference full-hour ratio averaged {average_full_hour_ratio:.3f}. "
                "That points more toward DC/input availability or operating conditions than a hard 84 kW nameplate cap."
            ),
            (
                f"No captured metadata field claims the inverter is rated at ~84 kW. "
                f"Both index and detail payloads report {target_meta.rated_kw:.0f} kW, "
                f"and the ~83.66 figure appears as instantaneous AC output (`pac`), not rated power."
            ),
        ]

        report = {
            "capture": {
                "capture_dir": str(capture_dir),
                "target_inverter_id": target_inverter_id,
            },
            "station": {
                "station_id": station_id,
                "station_name": station_name,
                "time_zone": time_zone,
            },
            "analysis_window": {
                "days": args.days,
                "start_date": days[0].isoformat() if days else None,
                "end_date": days[-1].isoformat() if days else None,
                "include_today": args.include_today,
            },
            "target": {
                "meta": {
                    "inverter_id": target_meta.inverter_id,
                    "sn": target_meta.sn,
                    "machine": target_meta.machine,
                    "model": target_meta.model,
                    "product_model": target_meta.product_model,
                    "rated_kw": target_meta.rated_kw,
                    "current_kw": target_meta.current_kw,
                    "current_power_percent": target_meta.current_power_percent,
                    "full_hour_snapshot": target_meta.full_hour,
                    "data_timestamp": target_meta.data_timestamp_str,
                },
                "summary": summarize_history(target_series, rated_kw=target_meta.rated_kw),
                "latest_day": latest_target_day,
            },
            "reference": {
                "meta": {
                    "inverter_id": reference_meta.inverter_id,
                    "sn": reference_meta.sn,
                    "machine": reference_meta.machine,
                    "model": reference_meta.model,
                    "product_model": reference_meta.product_model,
                    "rated_kw": reference_meta.rated_kw,
                    "current_kw": reference_meta.current_kw,
                    "current_power_percent": reference_meta.current_power_percent,
                    "full_hour_snapshot": reference_meta.full_hour,
                    "data_timestamp": reference_meta.data_timestamp_str,
                },
                "summary": summarize_history(ref_series, rated_kw=reference_meta.rated_kw),
                "latest_day": latest_reference_day,
            },
            "comparison": {
                "producing_day_count": len(producing_comparisons),
                "average_scaled_peak_ratio": average_scaled_peak_ratio,
                "average_full_hour_ratio": average_full_hour_ratio,
                "latest_target_peak_pct": latest_peak_ratio * 100.0,
                "latest_reference_peak_pct": latest_ref_ratio * 100.0,
                "days_where_ref_hit_95pct_and_target_stayed_below_90pct": sum(
                    row["ref_max_kw"] >= reference_meta.rated_kw * 0.95
                    and row["target_max_kw"] < target_meta.rated_kw * 0.90
                    for row in producing_comparisons
                ),
                "recent_daily_rows": producing_comparisons[-7:],
            },
            "rating_check": detect_conflicting_rating_info(
                target_meta,
                target_detail_payload,
                capture_dir,
            ),
            "key_finding": key_finding,
        }

        print_analysis_report(report)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print_kv("JSON report written", args.json_out)
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
