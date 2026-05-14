"""Shared recursive helpers for normalizing vendor solar payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DROP_KEY = "__DROP__"
NORMALIZED_DAILY_INVERTER_FIELDS = [
    "provider",
    "date",
    "site_id",
    "site_name",
    "inverter_id",
    "inverter_name",
    "inverter_serial",
    "inverter_model",
    "inverter_rated_kw",
    "inverter_rating_source",
    "daily_energy_kwh",
    "sun_hours",
    "revenue_amount",
]

STANDARD_KEY_MAP: dict[str, str] = {
    "pv_system_id": "site_id",
    "station_id": "site_id",
    "pv_system_name": "site_name",
    "station_name": "site_name",
    "device_id": "inverter_id",
    "inverter_sn": "inverter_serial",
    "daily_output_kwh": "daily_energy_kwh",
    "daily_production_kwh": "daily_energy_kwh",
    "full_hour": "sun_hours",
    "money": "revenue_amount",
    "raw_energy_value": DROP_KEY,
    "raw_energy_unit": DROP_KEY,
    "raw_energy_scale": DROP_KEY,
    "source_interval": DROP_KEY,
    "source_channel": DROP_KEY,
}


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _merge_values(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _merge_values(merged[key], value)
            else:
                merged[key] = value
        return merged
    if existing in ("", None, [], {}):
        return incoming
    return incoming


def normalize_solar_data(
    data: Any,
    *,
    key_map: Mapping[str, str] | None = None,
    drop_marker: str = DROP_KEY,
) -> Any:
    """Recursively copy and normalize a solar payload.

    - Dict keys found in ``key_map`` are renamed.
    - Dict keys mapped to ``drop_marker`` are removed.
    - Lists/tuples are copied recursively.
    - Unknown keys are preserved as-is.
    """

    effective_key_map = key_map or STANDARD_KEY_MAP

    if isinstance(data, Mapping):
        normalized: dict[str, Any] = {}
        for key, value in data.items():
            action = effective_key_map.get(str(key), str(key))
            if action == drop_marker:
                continue
            normalized_value = normalize_solar_data(value, key_map=effective_key_map, drop_marker=drop_marker)
            if action in normalized:
                normalized[action] = _merge_values(normalized[action], normalized_value)
            else:
                normalized[action] = normalized_value
        return normalized

    if _is_sequence(data):
        return [normalize_solar_data(item, key_map=effective_key_map, drop_marker=drop_marker) for item in data]

    return data


def normalize_daily_inverter_row(provider: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a flat daily inverter output row to the shared schema."""

    normalized = normalize_solar_data(dict(row))
    normalized["provider"] = provider

    if provider == "fronius":
        normalized.setdefault("inverter_name", str(row.get("inverter_name") or ""))
        normalized.setdefault("inverter_serial", "")
        normalized.setdefault("inverter_model", "")
        normalized.setdefault("sun_hours", "")
        normalized.setdefault("revenue_amount", "")
    elif provider == "solis":
        normalized["inverter_name"] = str(row.get("inverter_sn") or row.get("inverter_model") or "")
        normalized.setdefault("inverter_serial", str(row.get("inverter_sn") or ""))
        normalized.setdefault("inverter_model", str(row.get("inverter_model") or ""))
        normalized.setdefault("inverter_rating_source", "")

    return {key: value for key, value in normalized.items() if value != ""}
