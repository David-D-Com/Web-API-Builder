"""Extract suspicious solar production incidents into per-site summaries and timelines."""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from html import escape


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
NORMAL_DAYS_TO_CLOSE_INCIDENT = 3
ALBERTA_RETAIL_VALUE_CAD_PER_KWH = 0.1201
ALBERTA_GRID_DISPLACEMENT_TCO2E_PER_MWH = 0.57
ALBERTA_CARBON_VALUE_BY_YEAR = {
    2024: 80.0,
    2025: 95.0,
    2026: 110.0,
}
CHART_BOOKEND_DAYS = 5
CHART_PALETTE = [
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#be185d",
    "#4f46e5",
]


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


@dataclass
class IncidentGroup:
    group_id: str
    provider: str
    site_id: str
    site_name: str
    start_date: date
    end_date: date
    status: str
    affected_inverters: list[str]
    affected_inverter_ids: list[str]
    confidence_score: int
    confidence_label: str
    estimated_lost_production_kwh: float
    member_incidents: list[Incident]
    reason: str


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


def short_inverter_suffix(serial: str, inverter_id: str) -> str:
    candidate = (serial or "").strip()
    if candidate:
        cleaned = "".join(ch for ch in candidate if ch.isalnum())
        if cleaned:
            return cleaned[-6:].upper()
    cleaned_id = "".join(ch for ch in (inverter_id or "") if ch.isalnum())
    return cleaned_id[-6:].upper()


def build_inverter_display_labels(rows_by_inverter: dict[str, list[RowRecord]]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for inverter_id, inverter_rows in rows_by_inverter.items():
        sample = inverter_rows[0]
        base = sample.inverter_name or sample.inverter_model or sample.inverter_serial or inverter_id
        serial_text = (sample.inverter_serial or "").strip()
        if serial_text and base.strip().lower().endswith(serial_text.lower()):
            resolved[inverter_id] = base
            continue
        suffix = short_inverter_suffix(sample.inverter_serial, inverter_id)
        resolved[inverter_id] = f"{base} ({suffix})" if suffix else base
    return resolved


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

    if incident_type in {"site_missing_data", "site_offline_or_missing"}:
        expected_strength = clamp(expected_kwh_max / 150.0, 0.0, 1.0)
        duration_strength = clamp(days / 3.0, 0.0, 1.0)
        score = round(80 + 10 * expected_strength + 10 * duration_strength)
        if incident_type == "site_missing_data":
            reason = (
                f"Missing site data: no rows were present for {days} day(s), so the API appears to have omitted "
                f"the entire site. Estimated expected site energy was between {expected_kwh_min:.1f} and "
                f"{expected_kwh_max:.1f} kWh."
            )
        else:
            reason = (
                f"Site-wide outage or missing telemetry: the whole site produced {median_ratio:.1%} of expected "
                f"for {days} day(s), with expected site energy between {expected_kwh_min:.1f} and "
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
    inverter_ratings: dict[str, float | None] = {}
    rows_by_day: dict[date, dict[str, RowRecord]] = defaultdict(dict)
    for row in rows:
        by_date[row.day].append(row)
        by_inverter[row.inverter_id].append(row)
        if row.inverter_rated_kw is not None and inverter_ratings.get(row.inverter_id) is None:
            inverter_ratings[row.inverter_id] = row.inverter_rated_kw
        rows_by_day[row.day][row.inverter_id] = row

    if len(by_inverter) < 2:
        return None

    inverter_names = build_inverter_display_labels(by_inverter)
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

    site_offline_days: list[date] = []
    site_expected_by_day: dict[date, float] = {}
    site_actual_by_day: dict[date, float] = {}
    site_ratio_by_day: dict[date, float] = {}
    for day in all_days:
        if day not in by_date:
            continue
        expected_total = expected_site_total_by_day.get(day, 0.0)
        actual_total = site_totals_by_day.get(day, 0.0)
        if expected_total < threshold or expected_total <= 0:
            continue
        ratio = actual_total / expected_total if expected_total > 0 else 0.0
        site_expected_by_day[day] = expected_total
        site_actual_by_day[day] = actual_total
        site_ratio_by_day[day] = ratio
        if ratio < OFFLINE_RATIO_THRESHOLD:
            site_offline_days.append(day)

    for group in consecutive_groups(sorted(site_offline_days)):
        group_ratios = [site_ratio_by_day[day] for day in group]
        group_expected = [site_expected_by_day[day] for day in group]
        group_actual = [site_actual_by_day[day] for day in group]
        for day_value in group:
            metrics[("__SITE__", day_value)] = {
                "site_total_kwh": site_actual_by_day.get(day_value, 0.0),
                "expected_kwh": site_expected_by_day.get(day_value, 0.0),
                "performance_ratio": site_ratio_by_day.get(day_value, 0.0),
                "baseline_share": 1.0,
            }
        confidence_score, confidence_label, reason = classify_incident(
            incident_type="site_offline_or_missing",
            start_date=group[0],
            end_date=group[-1],
            days=len(group),
            median_ratio=statistics.median(group_ratios),
            min_ratio=min(group_ratios),
            expected_kwh_min=min(group_expected),
            expected_kwh_max=max(group_expected),
            actual_kwh_min=min(group_actual),
            actual_kwh_max=max(group_actual),
            peer_inverter_count=len(by_inverter),
        )
        incidents.append(
            Incident(
                provider=sample_row.provider,
                site_id=sample_row.site_id,
                site_name=sample_row.site_name,
                inverter_id="__SITE__",
                inverter_name="ALL_INVERTERS",
                incident_type="site_offline_or_missing",
                start_date=group[0],
                end_date=group[-1],
                days=len(group),
                baseline_share=1.0,
                median_ratio=statistics.median(group_ratios),
                min_ratio=min(group_ratios),
                expected_kwh_min=min(group_expected),
                expected_kwh_max=max(group_expected),
                actual_kwh_min=min(group_actual),
                actual_kwh_max=max(group_actual),
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

    incidents = merge_adjacent_incidents(incidents)
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


def merge_adjacent_incidents(incidents: list[Incident]) -> list[Incident]:
    if not incidents:
        return []
    merged: list[Incident] = []
    for incident in sorted(incidents, key=lambda item: (item.start_date, item.end_date, item.inverter_name, item.incident_type)):
        if not merged:
            merged.append(incident)
            continue
        previous = merged[-1]
        same_track = (
            previous.inverter_id == incident.inverter_id
            and previous.incident_type == incident.incident_type
        )
        if not same_track:
            merged.append(incident)
            continue
        actual_gap_days = (incident.start_date - previous.end_date).days - 1
        if actual_gap_days >= NORMAL_DAYS_TO_CLOSE_INCIDENT:
            merged.append(incident)
            continue
        previous.start_date = min(previous.start_date, incident.start_date)
        previous.end_date = max(previous.end_date, incident.end_date)
        previous.days = (previous.end_date - previous.start_date).days + 1
        previous.median_ratio = min(previous.median_ratio, incident.median_ratio)
        previous.min_ratio = min(previous.min_ratio, incident.min_ratio)
        previous.expected_kwh_min = min(previous.expected_kwh_min, incident.expected_kwh_min)
        previous.expected_kwh_max = max(previous.expected_kwh_max, incident.expected_kwh_max)
        previous.actual_kwh_min = min(previous.actual_kwh_min, incident.actual_kwh_min)
        previous.actual_kwh_max = max(previous.actual_kwh_max, incident.actual_kwh_max)
        previous.confidence_score = max(previous.confidence_score, incident.confidence_score)
        previous.peer_inverter_count = max(previous.peer_inverter_count, incident.peer_inverter_count)
        if previous.confidence_score >= 85:
            previous.confidence_label = "high"
        elif previous.confidence_score >= 65:
            previous.confidence_label = "medium"
        else:
            previous.confidence_label = "low"
        previous.reason = (
            f"Merged adjacent {previous.incident_type} periods because the fault only paused for "
            f"{max(actual_gap_days, 0)} normal day(s)."
        )
    return merged


def build_incident_groups(site: SiteData) -> list[IncidentGroup]:
    if not site.incidents:
        return []
    groups: list[IncidentGroup] = []
    current_members: list[Incident] = []

    def finalize_group(members: list[Incident], index: int) -> IncidentGroup:
        members = sorted(members, key=lambda item: (item.start_date, item.end_date, item.inverter_name))
        start_date = min(item.start_date for item in members)
        end_date = max(item.end_date for item in members)
        incident_types = {item.incident_type for item in members}
        if "site_missing_data" in incident_types:
            status = "site_missing_data"
        elif len(incident_types) == 1:
            status = next(iter(incident_types))
        else:
            status = "multiple_inverter_issues"
        affected_pairs = sorted({(item.inverter_id, item.inverter_name) for item in members}, key=lambda item: item[1])
        affected_inverter_ids = [item[0] for item in affected_pairs]
        affected_inverters = [item[1] for item in affected_pairs]
        confidence_score = max(item.confidence_score for item in members)
        if confidence_score >= 85:
            confidence_label = "high"
        elif confidence_score >= 65:
            confidence_label = "medium"
        else:
            confidence_label = "low"
        estimated_lost_production_kwh = 0.0
        reasons: list[str] = []
        for incident in members:
            reasons.append(f"{incident.inverter_name}: {incident.reason}")
            for day_value in full_date_range(incident.start_date, incident.end_date):
                metric = site.metrics.get((incident.inverter_id, day_value), {})
                expected = float(metric.get("expected_kwh", 0.0) or 0.0)
                actual_row = site.rows_by_day.get(day_value, {}).get(incident.inverter_id)
                actual = actual_row.daily_energy_kwh if actual_row is not None else 0.0
                if incident.inverter_id == "__SITE__":
                    expected = float(site.metrics.get(("__SITE__", day_value), {}).get("expected_kwh", 0.0) or 0.0)
                    actual = sum(row.daily_energy_kwh for row in site.rows_by_day.get(day_value, {}).values())
                estimated_lost_production_kwh += max(expected - actual, 0.0)
        return IncidentGroup(
            group_id=f"{site.provider.upper()}-{slugify(site.site_id, 24)}-G{index:03d}",
            provider=site.provider,
            site_id=site.site_id,
            site_name=site.site_name,
            start_date=start_date,
            end_date=end_date,
            status=status,
            affected_inverters=affected_inverters,
            affected_inverter_ids=affected_inverter_ids,
            confidence_score=confidence_score,
            confidence_label=confidence_label,
            estimated_lost_production_kwh=estimated_lost_production_kwh,
            member_incidents=members,
            reason=" | ".join(reasons),
        )

    for incident in sorted(site.incidents, key=lambda item: (item.start_date, item.end_date, item.inverter_name, item.incident_type)):
        if not current_members:
            current_members = [incident]
            continue
        current_end = max(item.end_date for item in current_members)
        actual_gap_days = (incident.start_date - current_end).days - 1
        if actual_gap_days < NORMAL_DAYS_TO_CLOSE_INCIDENT:
            current_members.append(incident)
        else:
            groups.append(finalize_group(current_members, len(groups) + 1))
            current_members = [incident]
    if current_members:
        groups.append(finalize_group(current_members, len(groups) + 1))
    return groups


def build_site_sections(groups: list[IncidentGroup]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    if not groups:
        return sections

    for index, group in enumerate(groups):
        if index == 0:
            start_date = group.start_date - timedelta(days=WINDOW_DAYS_BEFORE)
        else:
            previous_group = groups[index - 1]
            gap_days = max((group.start_date - previous_group.end_date).days - 1, 0)
            shown_gap_days = min(gap_days, 10)
            after_days = shown_gap_days // 2
            before_days = shown_gap_days - after_days
            sections[index - 1]["end_date"] = previous_group.end_date + timedelta(days=after_days)
            start_date = group.start_date - timedelta(days=before_days)
        if index == len(groups) - 1:
            end_date = group.end_date + timedelta(days=WINDOW_DAYS_AFTER)
        else:
            end_date = group.end_date
        sections.append(
            {
                "group": group,
                "start_date": start_date,
                "end_date": end_date,
                "omitted_days_before": 0,
            }
        )

    for index in range(1, len(groups)):
        previous_group = groups[index - 1]
        current_group = groups[index]
        gap_days = max((current_group.start_date - previous_group.end_date).days - 1, 0)
        shown_gap_days = min(gap_days, 10)
        omitted_days = max(gap_days - shown_gap_days, 0)
        sections[index]["omitted_days_before"] = omitted_days

    return sections


def build_timeline_fieldnames(site: SiteData) -> list[str]:
    fieldnames = [
        "site_name",
        "date",
        "status",
        "site_total_kwh",
        "incident_id",
        "focus_inverter_name",
    ]
    for _, label in site.ordered_inverters:
        fieldnames.append(f"{label}__rated_kw")
        fieldnames.append(f"{label}__daily_energy_kwh")
        fieldnames.append(f"{label}__specific_yield_kwh_per_kw")
        fieldnames.append(f"{label}__relative_specific_yield_vs_site_avg")
    return fieldnames


def build_timeline_row(site: SiteData, day: date, group: IncidentGroup) -> dict[str, object]:
    day_rows = site.rows_by_day.get(day, {})
    site_total = sum(row.daily_energy_kwh for row in day_rows.values())
    if site_total <= 0 and any(member.inverter_id == "__SITE__" for member in group.member_incidents):
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
            group.status
            if group.start_date <= day <= group.end_date
            else "Normal"
        ),
        "site_total_kwh": round(site_total, 6) if site_total else "",
        "incident_id": group.group_id if group.start_date <= day <= group.end_date else "",
        "focus_inverter_name": ", ".join(group.affected_inverters) if group.start_date <= day <= group.end_date else "",
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


def carbon_value_for_day(day_value: date) -> float:
    return ALBERTA_CARBON_VALUE_BY_YEAR.get(day_value.year, max(ALBERTA_CARBON_VALUE_BY_YEAR.values()))


def estimate_group_carbon_value(site: SiteData, group: IncidentGroup) -> tuple[float, float]:
    lost_tco2e = 0.0
    lost_carbon_value = 0.0
    for day_value in full_date_range(group.start_date, group.end_date):
        day_loss_kwh = 0.0
        for incident in group.member_incidents:
            if incident.start_date <= day_value <= incident.end_date:
                if incident.inverter_id == "__SITE__":
                    metric = site.metrics.get(("__SITE__", day_value), {})
                    expected = float(metric.get("expected_kwh", 0.0) or 0.0)
                    actual = float(metric.get("site_total_kwh", 0.0) or 0.0)
                else:
                    metric = site.metrics.get((incident.inverter_id, day_value), {})
                    expected = float(metric.get("expected_kwh", 0.0) or 0.0)
                    actual_row = site.rows_by_day.get(day_value, {}).get(incident.inverter_id)
                    actual = actual_row.daily_energy_kwh if actual_row is not None else 0.0
                day_loss_kwh += max(expected - actual, 0.0)
        day_tco2e = (day_loss_kwh / 1000.0) * ALBERTA_GRID_DISPLACEMENT_TCO2E_PER_MWH
        lost_tco2e += day_tco2e
        lost_carbon_value += day_tco2e * carbon_value_for_day(day_value)
    return lost_tco2e, lost_carbon_value


def svg_polyline(points: list[tuple[float, float]], stroke: str) -> str:
    if not points:
        return ""
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline fill="none" stroke="{stroke}" stroke-width="2" points="{coords}" />'


def svg_dashed_polyline(points: list[tuple[float, float]], stroke: str) -> str:
    if len(points) < 2:
        return ""
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (
        f'<polyline fill="none" stroke="{stroke}" stroke-width="2" '
        f'stroke-dasharray="6 4" points="{coords}" />'
    )


def svg_marker(x: float, y: float, stroke: str, *, filled: bool) -> str:
    fill = stroke if filled else "white"
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{fill}" stroke="{stroke}" stroke-width="2" />'


def round_up_to_step(value: float, step: float) -> float:
    if value <= 0:
        return step
    return math.ceil(value / step) * step


def humanize_status(status: str) -> str:
    mapping = {
        "offline_or_near_zero": "Inverter outage / near-zero production",
        "sustained_underperformance": "Sustained underperformance",
        "site_missing_data": "All inverters offline",
        "site_offline_or_missing": "All inverters offline",
        "multiple_inverter_issues": "Multiple inverters offline",
    }
    return mapping.get(status, status.replace("_", " ").title())


def describe_group_title(group: IncidentGroup) -> str:
    if len(group.affected_inverters) == 1:
        return f"{group.affected_inverters[0]} - {humanize_status(group.status)}"
    if len(group.affected_inverters) == 2:
        joined = " and ".join(group.affected_inverters)
        return f"{joined} - {humanize_status(group.status)}"
    return f"{len(group.affected_inverters)} inverters - {humanize_status(group.status)}"


def incident_heading(group: IncidentGroup) -> str:
    return f"{group.estimated_lost_production_kwh:,.1f} kWh lost: {describe_group_title(group)}"


def inverter_color_map(site: SiteData) -> dict[str, str]:
    return {
        label: CHART_PALETTE[index % len(CHART_PALETTE)]
        for index, (_inverter_id, label) in enumerate(site.ordered_inverters)
    }


def colorize_inverter_label(label: str, color_map: dict[str, str]) -> str:
    color = color_map.get(label)
    if not color:
        return escape(label)
    return f'<span style="color: {color}; font-weight: 600;">{escape(label)}</span>'


def colorize_inverter_list(labels: list[str], color_map: dict[str, str]) -> str:
    return ", ".join(colorize_inverter_label(label, color_map) for label in labels)


def colorized_group_title(group: IncidentGroup, color_map: dict[str, str]) -> str:
    if len(group.affected_inverters) == 1:
        inverter_text = colorize_inverter_label(group.affected_inverters[0], color_map)
    elif len(group.affected_inverters) == 2:
        inverter_text = " and ".join(colorize_inverter_label(label, color_map) for label in group.affected_inverters)
    else:
        inverter_text = f"{len(group.affected_inverters)} inverters"
    return f"{group.estimated_lost_production_kwh:,.1f} kWh lost: {inverter_text} - {escape(humanize_status(group.status))}"


def build_group_markdown_summary(group: IncidentGroup, color_map: dict[str, str]) -> list[str]:
    duration_days = (group.end_date - group.start_date).days + 1
    lines: list[str] = []
    if group.status in {"site_missing_data", "site_offline_or_missing"}:
        lines.append(
            f"The site appears to have gone fully offline for about `{duration_days}` day(s), affecting "
            f"`{len(group.affected_inverters)}` inverter(s)."
        )
    elif group.status == "multiple_inverter_issues":
        lines.append(
            f"Multiple inverters appear to have dropped out during the same incident window lasting about "
            f"`{duration_days}` day(s)."
        )
    else:
        lines.append(
            f"This incident lasted about `{duration_days}` day(s) and affected "
            f"`{len(group.affected_inverters)}` inverter(s)."
        )

    by_inverter: dict[str, list[Incident]] = defaultdict(list)
    for incident in group.member_incidents:
        by_inverter[incident.inverter_name].append(incident)

    if len(by_inverter) == 1:
        label = next(iter(by_inverter))
        incidents = by_inverter[label]
        total_days = sum(item.days for item in incidents)
        max_expected = max(item.expected_kwh_max for item in incidents)
        lines.append(
            f"{colorize_inverter_label(label, color_map)} was the main affected inverter, with about "
            f"`{total_days}` day(s) of severe underproduction and up to `{max_expected:,.1f} kWh/day` expected output."
        )
    else:
        lines.append("Affected inverter summary:")
        for label in sorted(by_inverter):
            incidents = by_inverter[label]
            total_days = sum(item.days for item in incidents)
            longest = max(item.days for item in incidents)
            max_expected = max(item.expected_kwh_max for item in incidents)
            lines.append(
                f"- {colorize_inverter_label(label, color_map)}: `{total_days}` total affected day(s), "
                f"longest contiguous run `{longest}` day(s), expected up to `{max_expected:,.1f} kWh/day`."
            )
    return lines


def write_incident_chart_svg(output_path: Path, site: SiteData, group: IncidentGroup, start_date: date, end_date: date) -> None:
    days = full_date_range(start_date, end_date)
    labels = [label for _, label in site.ordered_inverters]
    series: dict[str, list[float | None]] = {}
    max_value = 0.0
    for inverter_id, label in site.ordered_inverters:
        values: list[float | None] = []
        for day_value in days:
            row = site.rows_by_day.get(day_value, {}).get(inverter_id)
            value = row.daily_energy_kwh if row is not None else None
            values.append(value)
            if value is not None:
                max_value = max(max_value, value)
        series[label] = values

    width = 1080
    height = 420
    left = 60
    right = 20
    top = 40
    bottom = 90
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_max = round_up_to_step(max_value * 1.1, 50.0)

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white" />',
        f'<text x="{left}" y="24" font-family="Segoe UI, Arial, sans-serif" font-size="18" fill="#111827">'
        f'{escape(site.site_name)} - {escape(describe_group_title(group))}'
        '</text>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#374151" />',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#374151" />',
    ]

    guide_step = 25.0
    label_step = 50.0
    guide_value = 0.0
    while guide_value <= y_max + 0.001:
        y = top + plot_height - ((guide_value / y_max) * plot_height)
        svg_lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#e5e7eb" />')
        if abs((guide_value / label_step) - round(guide_value / label_step)) < 1e-9:
            svg_lines.append(
                f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" '
                f'font-size="11" fill="#4b5563">{guide_value:.0f}</text>'
            )
        guide_value += guide_step

    x_step = plot_width / max(len(days) - 1, 1)
    for index, day_value in enumerate(days):
        x = left + index * x_step
        if index == 0 or index == len(days) - 1:
            label = day_value.strftime("%Y-%m-%d")
        else:
            label = day_value.strftime("%m-%d")
        svg_lines.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 18}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="9" fill="#4b5563">{label}</text>'
        )

    for index, label in enumerate(labels):
        color = CHART_PALETTE[index % len(CHART_PALETTE)]
        values = series[label]
        solid_segments: list[list[tuple[float, float]]] = []
        dashed_segments: list[list[tuple[float, float]]] = []
        filled_dot_points: list[tuple[float, float]] = []
        open_dot_points: list[tuple[float, float]] = []
        current_solid: list[tuple[float, float]] = []
        missing_run_indices: list[int] = []

        def point_for(day_index: int, value: float) -> tuple[float, float]:
            x = left + day_index * x_step
            y = top + plot_height - ((value / y_max) * plot_height)
            return (x, y)

        for day_index, value in enumerate(values):
            if value is not None:
                point = point_for(day_index, value)
                if missing_run_indices:
                    if current_solid:
                        run_points: list[tuple[float, float]] = [current_solid[-1]]
                        for missing_index in missing_run_indices:
                            run_points.append(point_for(missing_index, 0.0))
                        run_points.append(point)
                        dashed_segments.append(run_points)
                        open_dot_points.append(current_solid[-1])
                        open_dot_points.append(point)
                        current_solid = [point]
                    else:
                        current_solid = [point]
                    missing_run_indices = []
                    continue
                current_solid.append(point)
            else:
                if len(current_solid) == 1:
                    filled_dot_points.append(current_solid[0])
                elif len(current_solid) >= 2:
                    solid_segments.append(current_solid)
                current_solid = current_solid[-1:] if current_solid else []
                missing_run_indices.append(day_index)

        if len(current_solid) == 1:
            filled_dot_points.append(current_solid[0])
        elif len(current_solid) >= 2:
            solid_segments.append(current_solid)

        for segment in solid_segments:
            svg_lines.append(svg_polyline(segment, color))
        for segment in dashed_segments:
            svg_lines.append(svg_dashed_polyline(segment, color))
        for x, y in open_dot_points:
            svg_lines.append(svg_marker(x, y, color, filled=False))
        for x, y in filled_dot_points:
            svg_lines.append(svg_marker(x, y, color, filled=True))

    legend_x = left
    legend_y = height - 42
    for index, label in enumerate(labels):
        color = CHART_PALETTE[index % len(CHART_PALETTE)]
        y = legend_y + (index // 3) * 16
        x = legend_x + (index % 3) * 320
        svg_lines.append(f'<rect x="{x}" y="{y - 10}" width="12" height="4" fill="{color}" />')
        svg_lines.append(
            f'<text x="{x + 18}" y="{y - 6}" font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#111827">'
            f'{escape(label)}</text>'
        )

    svg_lines.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(svg_lines), encoding="utf-8")


def write_site_markdown_report(output_dir: Path, site: SiteData) -> None:
    groups = build_incident_groups(site)
    sections = build_site_sections(groups)
    charts_dir = output_dir / "charts"
    color_map = inverter_color_map(site)
    total_lost_kwh = sum(group.estimated_lost_production_kwh for group in groups)
    total_energy_value = total_lost_kwh * ALBERTA_RETAIL_VALUE_CAD_PER_KWH
    group_carbon = {group.group_id: estimate_group_carbon_value(site, group) for group in groups}
    total_lost_tco2e = sum(values[0] for values in group_carbon.values())
    total_carbon_value = sum(values[1] for values in group_carbon.values())
    groups_for_report = sorted(
        groups,
        key=lambda group: (-group.estimated_lost_production_kwh, group.start_date, group.group_id),
    )

    prefix_value = f"{round(total_lost_kwh):06d}_kWh_lost"
    report_path = output_dir / f"{prefix_value}__{site_file_prefix(site)}__report.md"
    lines = [
        f"# {site.site_name} Incident Report",
        "",
        f"- Site: `{site.site_id}`",
        f"- Total estimated lost production: `{total_lost_kwh:,.1f} kWh`",
        f"- Estimated energy value lost: `${total_energy_value:,.2f} CAD`",
        f"- Estimated missed avoided emissions: `{total_lost_tco2e:,.2f} tCO2e`",
        f"- Estimated carbon-credit-equivalent value: `${total_carbon_value:,.2f} CAD`",
        "",
        "## Assumptions",
        "",
        f"- Energy value uses a flat Alberta retail proxy of `{ALBERTA_RETAIL_VALUE_CAD_PER_KWH:.4f} CAD/kWh`.",
        f"- Avoided emissions use `{ALBERTA_GRID_DISPLACEMENT_TCO2E_PER_MWH:.2f} tCO2e/MWh` as a distributed renewable grid displacement factor proxy.",
        "- Carbon value schedule used for all incidents in this report:",
        f"  2024 = `${ALBERTA_CARBON_VALUE_BY_YEAR[2024]:.0f}/tCO2e`, 2025 = `${ALBERTA_CARBON_VALUE_BY_YEAR[2025]:.0f}/tCO2e`, 2026 = `${ALBERTA_CARBON_VALUE_BY_YEAR[2026]:.0f}/tCO2e`.",
        "",
        "## Incidents",
        "",
    ]

    section_by_group = {section["group"].group_id: section for section in sections}
    for group in groups_for_report:
        lost_tco2e, carbon_value = group_carbon[group.group_id]
        section = section_by_group[group.group_id]
        chart_name = f"{site_file_prefix(site)}__{group.group_id}.svg"
        chart_path = charts_dir / chart_name
        chart_start = max(section["start_date"], group.start_date - timedelta(days=CHART_BOOKEND_DAYS))
        chart_end = min(section["end_date"], group.end_date + timedelta(days=CHART_BOOKEND_DAYS))
        write_incident_chart_svg(chart_path, site, group, chart_start, chart_end)
        lines.extend(
            [
                f"### {group.start_date.isoformat()} - {group.estimated_lost_production_kwh:,.1f} kWh - {describe_group_title(group)}",
                "",
                f"- Time range: `{group.start_date.isoformat()}` to `{group.end_date.isoformat()}`",
                f"- Affected inverters: {colorize_inverter_list(group.affected_inverters, color_map)}",
                f"- Confidence: `{group.confidence_label}` (`{group.confidence_score}`)",
                f"- Estimated lost production: `{group.estimated_lost_production_kwh:,.1f} kWh`",
                f"- Estimated energy value lost: `${group.estimated_lost_production_kwh * ALBERTA_RETAIL_VALUE_CAD_PER_KWH:,.2f} CAD`",
                f"- Estimated missed avoided emissions: `{lost_tco2e:,.2f} tCO2e`",
                f"- Estimated carbon-credit-equivalent value: `${carbon_value:,.2f} CAD`",
                "",
                f"![{describe_group_title(group)} production chart](charts/{chart_name})",
                "",
            ]
        )
        lines.extend(build_group_markdown_summary(group, color_map))
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_site_incident_summary(output_dir: Path, site: SiteData) -> None:
    prefix = site_file_prefix(site)
    output_path = output_dir / f"{prefix}__incidents.csv"
    groups = build_incident_groups(site)
    fieldnames = [
        "incident_id",
        "site_name",
        "affected_inverters",
        "status",
        "start_date",
        "end_date",
        "days",
        "confidence_score",
        "confidence_label",
        "estimated_lost_production_kwh",
        "member_incident_count",
        "reason",
        "source_file",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for group in groups:
            writer.writerow(
                {
                    "incident_id": group.group_id,
                    "site_name": site.site_name,
                    "affected_inverters": " | ".join(group.affected_inverters),
                    "status": group.status,
                    "start_date": group.start_date.isoformat(),
                    "end_date": group.end_date.isoformat(),
                    "days": (group.end_date - group.start_date).days + 1,
                    "confidence_score": group.confidence_score,
                    "confidence_label": group.confidence_label,
                    "estimated_lost_production_kwh": round(group.estimated_lost_production_kwh, 6),
                    "member_incident_count": len(group.member_incidents),
                    "reason": group.reason,
                    "source_file": site.source_file,
                }
            )


def write_site_timeline(output_dir: Path, site: SiteData) -> None:
    prefix = site_file_prefix(site)
    output_path = output_dir / f"{prefix}__timeline.csv"
    fieldnames = build_timeline_fieldnames(site)
    groups = build_incident_groups(site)
    sections = build_site_sections(groups)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, section in enumerate(sections):
            group = section["group"]
            start_date = section["start_date"]
            end_date = section["end_date"]
            omitted_days_before = int(section["omitted_days_before"])
            if index > 0 and omitted_days_before > 0:
                writer.writerow(
                    {
                        "site_name": site.site_name,
                        "date": "",
                        "status": f"Marker - {omitted_days_before} additional day(s) without incident",
                        "site_total_kwh": "",
                        "incident_id": "",
                        "focus_inverter_name": "",
                    }
                )
            elif index > 0:
                writer.writerow(
                    {
                        "site_name": site.site_name,
                        "date": "",
                        "status": "Marker - 0 additional day(s) without incident",
                        "site_total_kwh": "",
                        "incident_id": "",
                        "focus_inverter_name": "",
                    }
                )
            for day in full_date_range(start_date, end_date):
                writer.writerow(build_timeline_row(site, day, group))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = repo_root / "dumps" / "normalized"
    output_dir = repo_root / "dumps" / "extracted"
    charts_dir = output_dir / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing_csv in output_dir.glob("*.csv"):
        existing_csv.unlink()
    for existing_md in output_dir.glob("*.md"):
        existing_md.unlink()
    if charts_dir.exists():
        for existing_svg in charts_dir.glob("*.svg"):
            existing_svg.unlink()

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
        total_incidents += len(build_incident_groups(site_data))

    sites_with_incidents.sort(key=lambda item: (item.provider, item.site_name))
    for site in sites_with_incidents:
        write_site_incident_summary(output_dir, site)
        write_site_timeline(output_dir, site)
        write_site_markdown_report(output_dir, site)

    print(f"Scanned {scanned_files} site file(s).")
    print(f"Found {total_incidents} suspect incident(s) across {len(sites_with_incidents)} site(s).")
    print(f"Wrote per-site incident summaries, timelines, and markdown reports to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
