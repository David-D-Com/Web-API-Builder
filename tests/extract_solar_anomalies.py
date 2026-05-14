"""Extract suspicious solar production incidents into per-site summaries and timelines."""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


WINDOW_DAYS_BEFORE = 10
WINDOW_DAYS_AFTER = 10
MIN_BASELINE_DAYS = 10
MIN_ACTIVE_SITE_DAYS = 10
OFFLINE_RATIO_THRESHOLD = 0.10
UNDERPERF_RATIO_THRESHOLD = 0.80
OFFLINE_MIN_EXPECTED_KWH = 5.0
UNDERPERF_MIN_EXPECTED_KWH = 5.0
OFFLINE_MIN_RUN_DAYS = 1
UNDERPERF_MIN_RUN_DAYS = 3
LOW_CONFIDENCE_MONTHS = {11, 12, 1, 2}


@dataclass
class RowRecord:
    provider: str
    site_id: str
    site_name: str
    inverter_id: str
    inverter_name: str
    inverter_serial: str
    inverter_model: str
    inverter_rated_kw: float | None
    inverter_rating_source: str
    day: date
    daily_energy_kwh: float
    source: dict[str, str]


@dataclass
class Incident:
    provider: str
    site_id: str
    site_name: str
    inverter_id: str
    inverter_name: str
    incident_type: str
    start_date: date
    end_date: date
    days: int
    baseline_share: float
    median_ratio: float
    min_ratio: float
    expected_kwh_min: float
    expected_kwh_max: float
    actual_kwh_min: float
    actual_kwh_max: float
    peer_inverter_count: int
    source_file: str
    confidence_score: int
    confidence_label: str
    reason: str
    incident_id: str = ""


@dataclass
class SiteData:
    provider: str
    site_id: str
    site_name: str
    source_file: str
    rows: list[RowRecord]
    incidents: list[Incident]
    metrics: dict[tuple[str, date], dict[str, float]]
    baseline_share_by_inverter: dict[str, float]
    rows_by_day: dict[date, dict[str, RowRecord]]
    ordered_inverters: list[tuple[str, str]]
    inverter_ratings: dict[str, float | None]
    all_days: list[date]


def safe_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_row(row: dict[str, str]) -> RowRecord:
    return RowRecord(
        provider=row.get("provider", ""),
        site_id=row.get("site_id", ""),
        site_name=row.get("site_name", ""),
        inverter_id=row.get("inverter_id", ""),
        inverter_name=row.get("inverter_name", ""),
        inverter_serial=row.get("inverter_serial", ""),
        inverter_model=row.get("inverter_model", ""),
        inverter_rated_kw=safe_float(row.get("inverter_rated_kw")),
        inverter_rating_source=row.get("inverter_rating_source", ""),
        day=datetime.strptime(row["date"], "%Y-%m-%d").date(),
        daily_energy_kwh=float(row.get("daily_energy_kwh") or 0.0),
        source=row,
    )


def read_site_rows(path: Path) -> list[RowRecord]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [parse_row(row) for row in reader]


def consecutive_groups(days: list[date]) -> list[list[date]]:
    if not days:
        return []
    groups: list[list[date]] = [[days[0]]]
    for current in days[1:]:
        if current == groups[-1][-1] + timedelta(days=1):
            groups[-1].append(current)
        else:
            groups.append([current])
    return groups


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def full_date_range(start: date, end: date) -> list[date]:
    result: list[date] = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(days=1)
    return result


def site_activity_threshold(site_totals: list[float]) -> float:
    positive = [value for value in site_totals if value > 0]
    if not positive:
        return math.inf
    typical = statistics.median(positive)
    return max(5.0, typical * 0.20)


def estimate_site_expected_from_neighbors(
    site_totals_by_day: dict[date, float],
    target_day: date,
    *,
    window_days: int = 7,
) -> float:
    values: list[float] = []
    for offset in range(1, window_days + 1):
        for candidate in (target_day - timedelta(days=offset), target_day + timedelta(days=offset)):
            value = site_totals_by_day.get(candidate)
            if value and value > 0:
                values.append(value)
    if not values:
        return 0.0
    return statistics.median(values)


def classify_incident(
    *,
    incident_type: str,
    start_date: date,
    end_date: date,
    days: int,
    median_ratio: float,
    min_ratio: float,
    expected_kwh_min: float,
    expected_kwh_max: float,
    actual_kwh_min: float,
    actual_kwh_max: float,
    peer_inverter_count: int,
) -> tuple[int, str, str]:
    months_in_window: set[int] = set()
    current = start_date
    while current <= end_date:
        months_in_window.add(current.month)
        current += timedelta(days=1)
    winter_window = bool(months_in_window & LOW_CONFIDENCE_MONTHS)

    if incident_type == "site_missing_data":
        expected_strength = clamp(expected_kwh_max / 150.0, 0.0, 1.0)
        duration_strength = clamp(days / 3.0, 0.0, 1.0)
        score = round(80 + 10 * expected_strength + 10 * duration_strength)
        reason = (
            f"Missing site data: no rows were present for {days} day(s), so the API appears to have omitted "
            f"the entire site. Estimated expected site energy was between {expected_kwh_min:.1f} and "
            f"{expected_kwh_max:.1f} kWh."
        )
    elif incident_type == "offline_or_near_zero":
        severity = clamp(1.0 - median_ratio, 0.0, 1.0)
        expected_strength = clamp(expected_kwh_max / 150.0, 0.0, 1.0)
        duration_strength = clamp(days / 3.0, 0.0, 1.0)
        score = round(55 + 25 * severity + 10 * expected_strength + 10 * duration_strength)
        if median_ratio <= 0.02 and expected_kwh_max >= 100:
            score = max(score, 95)
        reason = (
            f"Likely outage/near-zero production: actual output was {median_ratio:.1%} of expected "
            f"for {days} day(s), with expected daily energy between {expected_kwh_min:.1f} and "
            f"{expected_kwh_max:.1f} kWh."
        )
    else:
        severity = clamp(1.0 - median_ratio, 0.0, 1.0)
        duration_strength = clamp(days / 7.0, 0.0, 1.0)
        expected_strength = clamp(expected_kwh_max / 150.0, 0.0, 1.0)
        peer_strength = clamp(peer_inverter_count / 6.0, 0.0, 1.0)
        score = round(35 + 30 * severity + 15 * duration_strength + 10 * expected_strength + 10 * peer_strength)
        if winter_window:
            score -= 10
        if expected_kwh_max < 80:
            score -= 8
        if days <= 3:
            score -= 5
        reason = (
            f"Sustained underperformance: actual output was typically {median_ratio:.1%} of expected "
            f"for {days} day(s), bottoming at {min_ratio:.1%}, while peers remained active."
        )

    score = int(clamp(score, 0, 100))
    if score >= 85:
        label = "high"
    elif score >= 65:
        label = "medium"
    else:
        label = "low"
    return score, label, reason


def analyze_site_file(path: Path) -> SiteData | None:
    rows = read_site_rows(path)
    if not rows:
        return None

    by_date: dict[date, list[RowRecord]] = defaultdict(list)
    by_inverter: dict[str, list[RowRecord]] = defaultdict(list)
    inverter_names: dict[str, str] = {}
    inverter_ratings: dict[str, float | None] = {}
    rows_by_day: dict[date, dict[str, RowRecord]] = defaultdict(dict)
    for row in rows:
        by_date[row.day].append(row)
        by_inverter[row.inverter_id].append(row)
        inverter_names[row.inverter_id] = row.inverter_name or row.inverter_serial or row.inverter_model or row.inverter_id
        if row.inverter_rated_kw is not None and inverter_ratings.get(row.inverter_id) is None:
            inverter_ratings[row.inverter_id] = row.inverter_rated_kw
        rows_by_day[row.day][row.inverter_id] = row

    if len(by_inverter) < 2:
        return None

    ordered_inverters = sorted(inverter_names.items(), key=lambda item: item[1])
    all_days = full_date_range(min(by_date), max(by_date))
    site_totals_by_day = {day: sum(item.daily_energy_kwh for item in items) for day, items in by_date.items()}
    threshold = site_activity_threshold(list(site_totals_by_day.values()))

    expected_site_total_by_day: dict[date, float] = {}
    active_days: set[date] = set()
    for day in all_days:
        actual_total = site_totals_by_day.get(day)
        if actual_total is not None:
            expected_site_total_by_day[day] = actual_total
            if actual_total >= threshold:
                active_days.add(day)
            continue
        estimated_total = estimate_site_expected_from_neighbors(site_totals_by_day, day)
        expected_site_total_by_day[day] = estimated_total
        if estimated_total >= threshold:
            active_days.add(day)

    if len(active_days) < MIN_ACTIVE_SITE_DAYS:
        return None

    baseline_share_by_inverter: dict[str, float] = {}
    metrics: dict[tuple[str, date], dict[str, float]] = {}
    for inverter_id, inverter_rows in by_inverter.items():
        shares: list[float] = []
        for row in inverter_rows:
            site_total = site_totals_by_day.get(row.day, 0.0)
            if row.day not in active_days or site_total <= 0:
                continue
            shares.append(row.daily_energy_kwh / site_total)
        if len(shares) >= MIN_BASELINE_DAYS:
            baseline_share_by_inverter[inverter_id] = statistics.median(shares)

    incidents: list[Incident] = []
    sample_row = rows[0]

    missing_site_days = sorted(
        day
        for day in all_days
        if day not in by_date and expected_site_total_by_day.get(day, 0.0) >= threshold
    )
    for group in consecutive_groups(missing_site_days):
        expected_values = [expected_site_total_by_day.get(day, 0.0) for day in group]
        expected_values = [value for value in expected_values if value > 0]
        if not expected_values:
            continue
        for day_value in group:
            metrics[("__SITE__", day_value)] = {
                "site_total_kwh": 0.0,
                "expected_kwh": expected_site_total_by_day.get(day_value, 0.0),
                "performance_ratio": 0.0,
                "baseline_share": 1.0,
            }
        confidence_score, confidence_label, reason = classify_incident(
            incident_type="site_missing_data",
            start_date=group[0],
            end_date=group[-1],
            days=len(group),
            median_ratio=0.0,
            min_ratio=0.0,
            expected_kwh_min=min(expected_values),
            expected_kwh_max=max(expected_values),
            actual_kwh_min=0.0,
            actual_kwh_max=0.0,
            peer_inverter_count=len(by_inverter),
        )
        incidents.append(
            Incident(
                provider=sample_row.provider,
                site_id=sample_row.site_id,
                site_name=sample_row.site_name,
                inverter_id="__SITE__",
                inverter_name="ALL_INVERTERS",
                incident_type="site_missing_data",
                start_date=group[0],
                end_date=group[-1],
                days=len(group),
                baseline_share=1.0,
                median_ratio=0.0,
                min_ratio=0.0,
                expected_kwh_min=min(expected_values),
                expected_kwh_max=max(expected_values),
                actual_kwh_min=0.0,
                actual_kwh_max=0.0,
                peer_inverter_count=len(by_inverter),
                source_file=path.name,
                confidence_score=confidence_score,
                confidence_label=confidence_label,
                reason=reason,
            )
        )

    for inverter_id, baseline_share in baseline_share_by_inverter.items():
        ratios_by_day: dict[date, float] = {}
        expected_by_day: dict[date, float] = {}
        actual_by_day: dict[date, float] = {}
        for current_day in sorted(active_days):
            site_total = site_totals_by_day.get(current_day)
            if site_total is None:
                continue
            expected = site_total * baseline_share
            if expected <= 0:
                continue
            row = rows_by_day[current_day].get(inverter_id)
            actual = row.daily_energy_kwh if row is not None else 0.0
            ratio = actual / expected
            ratios_by_day[current_day] = ratio
            expected_by_day[current_day] = expected
            actual_by_day[current_day] = actual
            metrics[(inverter_id, current_day)] = {
                "site_total_kwh": site_total,
                "expected_kwh": expected,
                "performance_ratio": ratio,
                "baseline_share": baseline_share,
            }

        offline_days = sorted(
            day for day, ratio in ratios_by_day.items()
            if ratio < OFFLINE_RATIO_THRESHOLD and expected_by_day[day] >= OFFLINE_MIN_EXPECTED_KWH
        )
        underperf_days = sorted(
            day for day, ratio in ratios_by_day.items()
            if OFFLINE_RATIO_THRESHOLD <= ratio < UNDERPERF_RATIO_THRESHOLD and expected_by_day[day] >= UNDERPERF_MIN_EXPECTED_KWH
        )

        def build_incidents(days: list[date], incident_type: str, min_run_days: int) -> None:
            for group in consecutive_groups(days):
                if len(group) < min_run_days:
                    continue
                group_ratios = [ratios_by_day[day] for day in group]
                group_expected = [expected_by_day[day] for day in group]
                group_actual = [actual_by_day[day] for day in group]
                sample_inverter_row = by_inverter[inverter_id][0]
                confidence_score, confidence_label, reason = classify_incident(
                    incident_type=incident_type,
                    start_date=group[0],
                    end_date=group[-1],
                    days=len(group),
                    median_ratio=statistics.median(group_ratios),
                    min_ratio=min(group_ratios),
                    expected_kwh_min=min(group_expected),
                    expected_kwh_max=max(group_expected),
                    actual_kwh_min=min(group_actual),
                    actual_kwh_max=max(group_actual),
                    peer_inverter_count=len(by_inverter) - 1,
                )
                incidents.append(
                    Incident(
                        provider=sample_inverter_row.provider,
                        site_id=sample_inverter_row.site_id,
                        site_name=sample_inverter_row.site_name,
                        inverter_id=inverter_id,
                        inverter_name=inverter_names[inverter_id],
                        incident_type=incident_type,
                        start_date=group[0],
                        end_date=group[-1],
                        days=len(group),
                        baseline_share=baseline_share,
                        median_ratio=statistics.median(group_ratios),
                        min_ratio=min(group_ratios),
                        expected_kwh_min=min(group_expected),
                        expected_kwh_max=max(group_expected),
                        actual_kwh_min=min(group_actual),
                        actual_kwh_max=max(group_actual),
                        peer_inverter_count=len(by_inverter) - 1,
                        source_file=path.name,
                        confidence_score=confidence_score,
                        confidence_label=confidence_label,
                        reason=reason,
                    )
                )

        build_incidents(offline_days, "offline_or_near_zero", OFFLINE_MIN_RUN_DAYS)
        build_incidents(underperf_days, "sustained_underperformance", UNDERPERF_MIN_RUN_DAYS)

    incidents.sort(key=lambda item: (item.start_date, item.end_date, item.inverter_name, item.incident_type))
    return SiteData(
        provider=sample_row.provider,
        site_id=sample_row.site_id,
        site_name=sample_row.site_name,
        source_file=path.name,
        rows=rows,
        incidents=incidents,
        metrics=metrics,
        baseline_share_by_inverter=baseline_share_by_inverter,
        rows_by_day=rows_by_day,
        ordered_inverters=ordered_inverters,
        inverter_ratings=inverter_ratings,
        all_days=all_days,
    )


def slugify(value: str, max_len: int = 50) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-")
    return cleaned[:max_len] or "value"


def site_file_prefix(site: SiteData) -> str:
    return f"{site.provider}__{slugify(site.site_name)}__{slugify(site.site_id, 36)}"


def incident_status(incident: Incident) -> str:
    return incident.incident_type


def build_site_sections(incidents: list[Incident]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    previous_end: date | None = None
    for incident in incidents:
        raw_start = incident.start_date - timedelta(days=WINDOW_DAYS_BEFORE)
        raw_end = incident.end_date + timedelta(days=WINDOW_DAYS_AFTER)
        adjusted_start = raw_start
        adjusted_end = raw_end
        omitted_days = 0
        if previous_end is not None:
            gap = (raw_start - previous_end).days - 1
            if gap < 0:
                overlap = -gap
                trim_previous = math.ceil(overlap / 2)
                trim_current = overlap // 2
                adjusted_start = raw_start + timedelta(days=trim_current)
                # Make sure we never trim into the incident itself.
                adjusted_start = min(adjusted_start, incident.start_date)
                adjusted_start = max(adjusted_start, raw_start)
                gap = (adjusted_start - previous_end).days - 1
                if gap < 0:
                    adjusted_start = previous_end + timedelta(days=1)
                    if adjusted_start > incident.start_date:
                        adjusted_start = incident.start_date
                    gap = (adjusted_start - previous_end).days - 1
                if sections:
                    previous_section_end = sections[-1]["end_date"]
                    previous_buffer_end = sections[-1]["incident"].end_date
                    new_previous_end = previous_section_end - timedelta(days=trim_previous)
                    if new_previous_end < previous_buffer_end:
                        new_previous_end = previous_buffer_end
                    sections[-1]["end_date"] = new_previous_end
                    previous_end = new_previous_end
                gap = (adjusted_start - previous_end).days - 1
            omitted_days = max(gap, 0)
        sections.append(
            {
                "incident": incident,
                "start_date": adjusted_start,
                "end_date": adjusted_end,
                "omitted_days_before": omitted_days,
            }
        )
        previous_end = adjusted_end
    return sections


def build_timeline_fieldnames(site: SiteData) -> list[str]:
    fieldnames = [
        "site_name",
        "date",
        "status",
        "site_total_kwh",
        "incident_id",
        "focus_inverter_name",
        "omitted_days",
    ]
    for _, label in site.ordered_inverters:
        fieldnames.append(f"{label}__rated_kw")
        fieldnames.append(f"{label}__daily_energy_kwh")
        fieldnames.append(f"{label}__specific_yield_kwh_per_kw")
        fieldnames.append(f"{label}__relative_specific_yield_vs_site_avg")
    return fieldnames


def build_timeline_row(site: SiteData, day: date, incident: Incident) -> dict[str, object]:
    day_rows = site.rows_by_day.get(day, {})
    site_total = sum(row.daily_energy_kwh for row in day_rows.values())
    if site_total <= 0 and incident.inverter_id == "__SITE__":
        site_total = float(site.metrics.get(("__SITE__", day), {}).get("expected_kwh", 0.0) or 0.0)

    specific_yield_by_inverter: dict[str, float | None] = {}
    for inverter_id, _label in site.ordered_inverters:
        row = day_rows.get(inverter_id)
        rated_kw = site.inverter_ratings.get(inverter_id)
        actual = row.daily_energy_kwh if row is not None else 0.0
        if rated_kw in (None, 0):
            specific_yield_by_inverter[inverter_id] = None
        else:
            specific_yield_by_inverter[inverter_id] = actual / float(rated_kw)

    comparable_specific_yields = [value for value in specific_yield_by_inverter.values() if value is not None]
    site_average_specific_yield = statistics.mean(comparable_specific_yields) if comparable_specific_yields else None

    row_data: dict[str, object] = {
        "site_name": site.site_name,
        "date": day.isoformat(),
        "status": (
            incident_status(incident)
            if incident.start_date <= day <= incident.end_date
            else "Normal"
        ),
        "site_total_kwh": round(site_total, 6) if site_total else "",
        "incident_id": incident.incident_id if incident.start_date <= day <= incident.end_date else "",
        "focus_inverter_name": incident.inverter_name if incident.start_date <= day <= incident.end_date else "",
        "omitted_days": "",
    }

    for inverter_id, label in site.ordered_inverters:
        source_row = day_rows.get(inverter_id)
        rated_kw = site.inverter_ratings.get(inverter_id)
        actual = source_row.daily_energy_kwh if source_row is not None else 0.0
        specific_yield = specific_yield_by_inverter.get(inverter_id)
        relative_specific_yield = (
            specific_yield / site_average_specific_yield
            if specific_yield is not None and site_average_specific_yield not in (None, 0)
            else ""
        )
        row_data[f"{label}__rated_kw"] = rated_kw if rated_kw is not None else ""
        row_data[f"{label}__daily_energy_kwh"] = round(actual, 6)
        row_data[f"{label}__specific_yield_kwh_per_kw"] = round(specific_yield, 6) if specific_yield is not None else ""
        row_data[f"{label}__relative_specific_yield_vs_site_avg"] = (
            round(relative_specific_yield, 6) if relative_specific_yield != "" else ""
        )
    return row_data


def write_site_incident_summary(output_dir: Path, site: SiteData) -> None:
    prefix = site_file_prefix(site)
    output_path = output_dir / f"{prefix}__incidents.csv"
    fieldnames = [
        "incident_id",
        "site_name",
        "inverter_name",
        "status",
        "start_date",
        "end_date",
        "days",
        "confidence_score",
        "confidence_label",
        "baseline_share",
        "median_ratio",
        "min_ratio",
        "expected_kwh_min",
        "expected_kwh_max",
        "actual_kwh_min",
        "actual_kwh_max",
        "peer_inverter_count",
        "reason",
        "source_file",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for incident in site.incidents:
            writer.writerow(
                {
                    "incident_id": incident.incident_id,
                    "site_name": site.site_name,
                    "inverter_name": incident.inverter_name,
                    "status": incident.incident_type,
                    "start_date": incident.start_date.isoformat(),
                    "end_date": incident.end_date.isoformat(),
                    "days": incident.days,
                    "confidence_score": incident.confidence_score,
                    "confidence_label": incident.confidence_label,
                    "baseline_share": round(incident.baseline_share, 6),
                    "median_ratio": round(incident.median_ratio, 6),
                    "min_ratio": round(incident.min_ratio, 6),
                    "expected_kwh_min": round(incident.expected_kwh_min, 6),
                    "expected_kwh_max": round(incident.expected_kwh_max, 6),
                    "actual_kwh_min": round(incident.actual_kwh_min, 6),
                    "actual_kwh_max": round(incident.actual_kwh_max, 6),
                    "peer_inverter_count": incident.peer_inverter_count,
                    "reason": incident.reason,
                    "source_file": incident.source_file,
                }
            )


def write_site_timeline(output_dir: Path, site: SiteData) -> None:
    prefix = site_file_prefix(site)
    output_path = output_dir / f"{prefix}__timeline.csv"
    fieldnames = build_timeline_fieldnames(site)
    sections = build_site_sections(site.incidents)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, section in enumerate(sections):
            incident = section["incident"]
            start_date = section["start_date"]
            end_date = section["end_date"]
            omitted_days_before = int(section["omitted_days_before"])
            if index > 0:
                writer.writerow(
                    {
                        "site_name": site.site_name,
                        "date": "",
                        "status": "Omitted",
                        "site_total_kwh": "",
                        "incident_id": "",
                        "focus_inverter_name": "",
                        "omitted_days": omitted_days_before,
                    }
                )
            for day in full_date_range(start_date, end_date):
                writer.writerow(build_timeline_row(site, day, incident))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = repo_root / "dumps" / "normalized"
    output_dir = repo_root / "dumps" / "extracted"
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing_csv in output_dir.glob("*.csv"):
        existing_csv.unlink()

    sites_with_incidents: list[SiteData] = []
    total_incidents = 0
    scanned_files = 0

    for path in sorted(input_dir.glob("*.csv")):
        scanned_files += 1
        site_data = analyze_site_file(path)
        if site_data is None or not site_data.incidents:
            continue
        for index, incident in enumerate(site_data.incidents, start=1):
            incident.incident_id = f"{site_data.provider.upper()}-{slugify(site_data.site_id, 24)}-{index:03d}"
        sites_with_incidents.append(site_data)
        total_incidents += len(site_data.incidents)

    sites_with_incidents.sort(key=lambda item: (item.provider, item.site_name))
    for site in sites_with_incidents:
        write_site_incident_summary(output_dir, site)
        write_site_timeline(output_dir, site)

    print(f"Scanned {scanned_files} site file(s).")
    print(f"Found {total_incidents} suspect incident(s) across {len(sites_with_incidents)} site(s).")
    print(f"Wrote per-site incident summaries and timelines to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
