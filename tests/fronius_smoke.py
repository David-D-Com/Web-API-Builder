"""Replay-backed smoke test for the Fronius Solar.web client."""

from __future__ import annotations

import sys
from pathlib import Path


TARGET_SYSTEM_NAME = "G and C farms north meter"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    capture_dir = repo_root / "har" / "fronius" / "20260513-090923"
    sys.path.insert(0, str(package_src))

    from fronius import FroniusClient

    client = FroniusClient.from_capture_dir(capture_dir).initialize()
    systems_payload = client.get_pv_systems_for_list_view()
    systems = systems_payload.get("data", [])
    assert systems, "Expected captured PvSystems list data."

    target = client.get_pv_system_by_name(TARGET_SYSTEM_NAME)
    assert target is not None, f"Did not find target system '{TARGET_SYSTEM_NAME}'."
    target_id = target["PvSystemId"]

    actual_values = client.get_actual_values(with_online_state=True)
    compare = client.get_compare_data_for_pv_system(target_id)
    actual_detail = client.get_actual_pv_system_data(target_id)
    weather = client.get_weather_widget_data(target_id)
    production = client.get_pv_system_productions_and_earnings(target_id)
    chart_day = client.get_chart_new(
        target_id,
        year=2026,
        month=5,
        day=13,
        interval="day",
        view="production",
    )
    widget_chart = client.get_widget_chart(target_id)

    assert any(item.get("PvSystemId") == target_id for item in actual_values), "Missing target in actual values."
    assert compare.get("P_PV") is not None, "Expected compare data to include P_PV."
    assert actual_detail.get("series"), "Expected realtime inverter series data."
    assert weather.get("data", {}).get("Forecast"), "Expected weather forecast data."
    assert production.get("data", {}).get("Productions", {}).get("Today"), "Expected production totals."
    assert chart_day.get("settings", {}).get("series"), "Expected day chart series."
    assert widget_chart.get("chart", {}).get("series"), "Expected widget chart series."

    print("Healthcheck:", client.healthcheck())
    print(f"Systems discovered: {len(systems)}")
    print(f"Target system: {target['PvSystemName']} ({target_id})")
    print(f"Live production reading: {compare['P_PV']} W")
    print(f"Today's energy: {production['data']['Productions']['Today']} {production['data']['Productions']['TodayUnit']}")
    print(f"Day chart sum: {chart_day['sumValue']}")
    print(f"Weather now: {weather['data']['Current']['TextSummary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
