"""Probe one live Solis monthly inverter chart payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from soliscloud_web_api import SolisWebApiClient
from solis_inverter_cap_report import build_session


def main() -> int:
    client = SolisWebApiClient(build_session())
    sites = client.list_all_sites(page_size=100, station_type="1")
    assert sites, "No Solis sites returned."
    site = None
    records = []
    station_id = ""
    station_name = ""
    for candidate in sites:
        candidate_station_id = str(candidate.get("id"))
        candidate_station_name = str(candidate.get("stationName") or "")
        index_payload = client.inverter_index_list(station_id=candidate_station_id)
        data = index_payload.get("data", {})
        candidate_records = data.get("page", {}).get("records", [])
        if candidate_records:
            site = candidate
            station_id = candidate_station_id
            station_name = candidate_station_name
            records = candidate_records
            break
    assert site is not None and records, "No Solis site with inverters was found."
    inverter = records[0]
    inverter_id = str(inverter.get("id"))

    month_payload = client.inverter_chart_month(inverter_id, month="2026-05")
    print(json.dumps(
        {
            "station_id": station_id,
            "station_name": station_name,
            "inverter_id": inverter_id,
            "inverter_sn": inverter.get("sn"),
            "payload": month_payload,
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
