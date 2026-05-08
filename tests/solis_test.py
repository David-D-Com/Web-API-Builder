"""Simple smoke test and Windows credential helper for the Solis web API client.

On Windows, this can store credentials in Windows Credential Manager through
`keyring`. On other systems, it falls back to SOLIS_USERNAME / SOLIS_PASSWORD.

Usage:
    python tests/solis_test.py --save-credentials
    python tests/solis_test.py --delete-credentials
    python tests/solis_test.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import sys
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from soliscloud_web_api import SolisSession, SolisWebApiClient, SolisWebApiError
from open_solis_browser_session import open_browser_from_client


KEYRING_SERVICE = "soliscloud_web_api"
KEYRING_USERNAME_KEY = "__solis_username__"
DISPLAY_LANGUAGE = "en"


def _get_console():
    try:
        from rich.console import Console
    except ImportError:
        return None
    return Console(force_terminal=True, color_system="auto")


def render_json(data: object) -> None:
    json_text = json.dumps(data, indent=2, ensure_ascii=True)
    console = _get_console()
    if console is None:
        print(json_text)
        return
    from rich.syntax import Syntax

    console.print(Syntax(json_text, "json", theme="monokai", word_wrap=True))


def _prune_language_variants(value: object, *, preferred_language: str) -> object:
    if isinstance(value, list):
        return [_prune_language_variants(item, preferred_language=preferred_language) for item in value]
    if not isinstance(value, dict):
        return value

    pruned: dict[str, object] = {}
    keys = {str(key) for key in value}
    for key, raw_item in value.items():
        key_str = str(key)
        if preferred_language in {"en", "cn"}:
            if preferred_language == "en" and key_str.endswith("Cn"):
                sibling = key_str[:-2] + "En"
                if sibling in keys:
                    continue
            if preferred_language == "cn" and key_str.endswith("En"):
                sibling = key_str[:-2] + "Cn"
                if sibling in keys:
                    continue
        pruned[key_str] = _prune_language_variants(raw_item, preferred_language=preferred_language)
    return pruned


def _sanitize_for_display(value: object) -> object:
    value = _prune_language_variants(value, preferred_language=DISPLAY_LANGUAGE)
    if isinstance(value, dict):
        return {str(k): _sanitize_for_display(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_display(item) for item in value]
    if isinstance(value, str):
        lower = value.lower()
        if "password" in lower:
            return "<password>"
        if value.startswith("token_"):
            return "<session token>"
        if re.fullmatch(r"[0-9a-fA-F]{24,}", value):
            return "<hex value>"
        return value
    return value


def print_test_section(
    *,
    title: str,
    purpose: str,
    inputs: dict[str, object] | None = None,
    response: object | None = None,
    passed: bool,
    status: str | None = None,
) -> None:
    console = _get_console()
    safe_inputs = _sanitize_for_display(inputs or {})
    safe_response = _sanitize_for_display(response)
    status_text = status or ("PASS" if passed else "FAIL")
    status_style = {
        "PASS": "bold green",
        "FAIL": "bold red",
        "SKIP": "bold yellow",
    }.get(status_text, "bold cyan")

    if console is None:
        print("=" * 79)
        print(title)
        print(purpose)
        if safe_inputs:
            print("Inputs:")
            print(json.dumps(safe_inputs, indent=2, ensure_ascii=True))
        if safe_response is not None:
            print("Response:")
            print(json.dumps(safe_response, indent=2, ensure_ascii=True))
        print(f"Result: {status_text}")
        print("\n")
        return

    from rich.rule import Rule

    console.print(Rule(title, style="cyan"))
    console.print(f"[bold]Purpose:[/] {purpose}")
    if safe_inputs:
        console.print("[bold]Inputs:[/]")
        render_json(safe_inputs)
    if safe_response is not None:
        console.print("[bold]Response:[/]")
        render_json(safe_response)
    console.print(f"[{status_style}]Result: {status_text}[/]")
    console.print()


def _load_keyring():
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise SolisWebApiError(
            "The `keyring` package is required for Windows Credential Manager support."
        ) from exc
    return keyring


def save_credentials(username: str, password: str) -> None:
    keyring = _load_keyring()
    keyring.set_password(KEYRING_SERVICE, username, password)
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY, username)


def delete_credentials() -> None:
    keyring = _load_keyring()
    username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
    if username:
        try:
            keyring.delete_password(KEYRING_SERVICE, username)
        except Exception:
            pass
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
    except Exception:
        pass


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
        return SolisSession.from_credentials(
            username,
            password,
            filter_results=True,
            preferred_language=DISPLAY_LANGUAGE,
        )
    return SolisSession.from_env(
        filter_results=True,
        preferred_language=DISPLAY_LANGUAGE,
    )


def select_station(
    sites: list[dict[str, object]],
    *,
    station_id: str | None,
) -> dict[str, object]:
    if not sites:
        raise SolisWebApiError("No sites were returned from /station/list.")
    if station_id is None:
        def station_score(site: dict[str, object]) -> tuple[float, float, float]:
            inverter_count = float(site.get("inverterCount") or 0)
            day_energy = float(site.get("dayEnergy") or 0)
            power = float(site.get("power") or 0)
            return (inverter_count, day_energy, power)

        return max(sites, key=station_score)
    for site in sites:
        if str(site.get("id")) == station_id:
            return site
    raise SolisWebApiError(f"Requested station id was not found in site list: {station_id}")


def _station_chart_context(station_detail_payload: dict[str, object]) -> dict[str, object]:
    data = station_detail_payload.get("data", {})
    if not isinstance(data, dict):
        raise SolisWebApiError("Unexpected station detail payload shape.")
    zone_date = str(data.get("nowZoneDateStr") or dt.date.today().isoformat())
    day = dt.date.fromisoformat(zone_date)
    money = str(data.get("money") or "CAD")
    time_zone = data.get("timeZone")
    if not isinstance(time_zone, (int, float)):
        time_zone = 0
    return {
        "day": day.isoformat(),
        "month": day.strftime("%Y-%m"),
        "year": day.strftime("%Y"),
        "money": money,
        "time_zone": time_zone,
    }


def _page_records(payload: dict[str, object]) -> list[dict[str, object]]:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []
    page = data.get("page", data)
    if not isinstance(page, dict):
        return []
    records = page.get("records", [])
    return records if isinstance(records, list) else []


def _data_list(payload: dict[str, object]) -> list[object]:
    data = payload.get("data", [])
    return data if isinstance(data, list) else []


def _site_preview(site: dict[str, object]) -> dict[str, object]:
    return {
        "id": site.get("id"),
        "stationName": site.get("stationName"),
        "state": site.get("state"),
        "inverterCount": site.get("inverterCount"),
        "dayEnergy": site.get("dayEnergy"),
        "power": site.get("power"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--save-credentials",
        action="store_true",
        help="Prompt for credentials and save them to Windows Credential Manager.",
    )
    parser.add_argument(
        "--delete-credentials",
        action="store_true",
        help="Delete saved Windows Credential Manager credentials.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the authenticated browser session after the smoke test without prompting.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not prompt to open the browser after the smoke test.",
    )
    parser.add_argument(
        "--station-id",
        help="Station/site id to use for deeper integration tests and browser opening.",
    )
    parser.add_argument(
        "--display-language",
        choices=("en", "cn", "both"),
        default="en",
        help="Preferred language for console display when both *En and *Cn keys are present.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    global DISPLAY_LANGUAGE
    DISPLAY_LANGUAGE = args.display_language

    if args.save_credentials:
        if os.name != "nt":
            print("Credential Manager save is only enabled in this helper on Windows.", file=sys.stderr)
            return 1
        try:
            username = input("Solis username/email: ").strip()
            password = getpass.getpass("Solis password: ")
            if not username or not password:
                raise SolisWebApiError("Username and password are required.")
            save_credentials(username, password)
        except SolisWebApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"saved": True, "service": KEYRING_SERVICE}, indent=2))
        return 0

    if args.delete_credentials:
        try:
            delete_credentials()
        except SolisWebApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"deleted": True, "service": KEYRING_SERVICE}, indent=2))
        return 0

    try:
        client = SolisWebApiClient(build_session())
        login_payload = client.login()
        print_test_section(
            title="Login Test",
            purpose="Authenticate against the SolisCloud web API and obtain a session token.",
            inputs={
                "username": client.session.username,
                "password": "<password>",
                "device_id": "<device id>",
            },
            response=login_payload,
            passed=bool(login_payload.get("success")),
        )
        profile_payload = client.profile()
        print_test_section(
            title="Profile Test",
            purpose="Fetch the authenticated user profile used by the web UI bootstrap flow.",
            inputs={},
            response=profile_payload,
            passed=bool(profile_payload.get("success")),
        )
        sites = client.list_all_sites(page_size=100, station_type="1")
        print_test_section(
            title="Site List Test",
            purpose="Fetch and aggregate the available sites/powerplants for the account.",
            inputs={
                "page_size": 100,
                "station_type": "1",
            },
            response={"records": sites, "count": len(sites)},
            passed=bool(sites),
        )
        selected_site = select_station(sites, station_id=args.station_id)
        selected_station_id = str(selected_site.get("id"))

        station_detail_payload = client.station_detail(selected_station_id)
        print_test_section(
            title="Station Detail Test",
            purpose="Fetch the primary site details page payload for the selected station.",
            inputs={"station_id": selected_station_id},
            response=station_detail_payload,
            passed=bool(station_detail_payload.get("success")),
        )
        station_config_detail_payload = client.station_config_detail(selected_station_id)
        print_test_section(
            title="Station Config Test",
            purpose="Fetch station configuration metadata used by the site details view.",
            inputs={"station_id": selected_station_id, "config_type": 0},
            response=station_config_detail_payload,
            passed=bool(station_config_detail_payload.get("success")),
        )
        station_device_count_payload = client.station_device_count(selected_station_id)
        print_test_section(
            title="Station Device Count Test",
            purpose="Fetch per-device-type counts for the selected station.",
            inputs={"station_id": selected_station_id},
            response=station_device_count_payload,
            passed=bool(station_device_count_payload.get("success")),
        )
        station_user_payload = client.station_user(selected_station_id)
        print_test_section(
            title="Station User Test",
            purpose="Fetch the current user's relationship flag for the selected station.",
            inputs={"station_id": selected_station_id},
            response=station_user_payload,
            passed=bool(station_user_payload.get("success")),
        )
        station_visitor_payload = client.station_visitor(selected_station_id)
        print_test_section(
            title="Station Visitor Test",
            purpose="Fetch the station sharing and visitor list for the selected station.",
            inputs={"station_id": selected_station_id},
            response=station_visitor_payload,
            passed=bool(station_visitor_payload.get("success")),
        )
        try:
            station_second_data_payload = client.device_second_upload_check_station_data(
                selected_station_id
            )
            print_test_section(
                title="Second Upload Config Test",
                purpose="Fetch second-level upload configuration support for the selected station.",
                inputs={"station_id": selected_station_id},
                response=station_second_data_payload,
                passed=bool(station_second_data_payload.get("success")),
            )
        except SolisWebApiError as exc:
            station_second_data_payload = {"success": False, "error": str(exc)}
            print_test_section(
                title="Second Upload Config Test",
                purpose="Fetch second-level upload configuration support for the selected station.",
                inputs={"station_id": selected_station_id},
                response=station_second_data_payload,
                passed=False,
                status="SKIP",
            )
        chart_context = _station_chart_context(station_detail_payload)
        station_all_energy_payload = client.station_all_energy(
            selected_station_id,
            begin_time=str(chart_context["day"]),
        )
        print_test_section(
            title="Station Energy Summary Test",
            purpose="Fetch the station-level daily energy summary used by the overview card.",
            inputs={
                "station_id": selected_station_id,
                "begin_time": chart_context["day"],
                "type": 0,
            },
            response=station_all_energy_payload,
            passed=bool(station_all_energy_payload.get("success")),
        )
        station_day_chart_payload = client.station_chart_day(
            selected_station_id,
            day=str(chart_context["day"]),
            time_zone=chart_context["time_zone"],
            money=str(chart_context["money"]),
        )
        print_test_section(
            title="Station Day Chart Test",
            purpose="Fetch the station intraday chart series for the selected site.",
            inputs={
                "station_id": selected_station_id,
                "day": chart_context["day"],
                "time_zone": chart_context["time_zone"],
                "money": chart_context["money"],
                "version": 1,
            },
            response=station_day_chart_payload,
            passed=bool(station_day_chart_payload.get("success")),
        )
        station_month_chart_payload = client.station_chart_month(
            selected_station_id,
            month=str(chart_context["month"]),
            time_zone=chart_context["time_zone"],
            money=str(chart_context["money"]),
        )
        print_test_section(
            title="Station Month Chart Test",
            purpose="Fetch the monthly station chart series for the selected site.",
            inputs={
                "station_id": selected_station_id,
                "month": chart_context["month"],
                "time_zone": chart_context["time_zone"],
                "money": chart_context["money"],
                "version": 1,
            },
            response=station_month_chart_payload,
            passed=bool(station_month_chart_payload.get("success")),
        )
        station_year_chart_payload = client.station_chart_year(
            selected_station_id,
            year=str(chart_context["year"]),
            time_zone=chart_context["time_zone"],
            money=str(chart_context["money"]),
        )
        print_test_section(
            title="Station Year Chart Test",
            purpose="Fetch the yearly station chart series for the selected site.",
            inputs={
                "station_id": selected_station_id,
                "year": chart_context["year"],
                "time_zone": chart_context["time_zone"],
                "money": chart_context["money"],
                "version": 1,
            },
            response=station_year_chart_payload,
            passed=bool(station_year_chart_payload.get("success")),
        )
        station_all_chart_payload = client.station_chart_all(
            selected_station_id,
            time_zone=chart_context["time_zone"],
            money=str(chart_context["money"]),
        )
        print_test_section(
            title="Station Lifetime Chart Test",
            purpose="Fetch the all-time station chart series grouped by year.",
            inputs={
                "station_id": selected_station_id,
                "time_zone": chart_context["time_zone"],
                "money": chart_context["money"],
                "version": 1,
            },
            response=station_all_chart_payload,
            passed=bool(station_all_chart_payload.get("success")),
        )
        alarm_list_payload = client.alarm_list(station_id=selected_station_id)
        print_test_section(
            title="Alarm List Test",
            purpose="Fetch the active alarm list for the selected station.",
            inputs={
                "station_id": selected_station_id,
                "fault_type": 0,
                "page_no": 1,
                "page_size": 10,
                "state": 0,
            },
            response=alarm_list_payload,
            passed=bool(alarm_list_payload.get("success")),
        )
        alarm_records = _page_records(alarm_list_payload)
        alarm_detail_payload: dict[str, object] | None = None
        if alarm_records:
            selected_alarm = alarm_records[0]
            alarm_detail_payload = client.alarm_detail(
                alarm_device_sn=str(selected_alarm.get("alarmDeviceSn") or ""),
                alarm_code=str(selected_alarm.get("alarmCode") or ""),
                alarm_begin_time=str(selected_alarm.get("alarmBeginTime") or ""),
                warning_info_data=str(selected_alarm.get("warningInfoData") or 0),
                alarm_device_type=str(selected_alarm.get("alarmDeviceType") or ""),
            )
            print_test_section(
                title="Alarm Detail Test",
                purpose="Fetch the detailed alarm view payload for one alarm record.",
                inputs={
                    "alarm_device_sn": selected_alarm.get("alarmDeviceSn"),
                    "alarm_code": selected_alarm.get("alarmCode"),
                    "alarm_begin_time": selected_alarm.get("alarmBeginTime"),
                    "warning_info_data": selected_alarm.get("warningInfoData"),
                    "alarm_device_type": selected_alarm.get("alarmDeviceType"),
                },
                response=alarm_detail_payload,
                passed=bool(alarm_detail_payload.get("success")),
            )
        warning_list_payload = client.warning_list(station_id=selected_station_id)
        print_test_section(
            title="Warning List Test",
            purpose="Fetch the warning or inefficient-generation records for the selected station.",
            inputs={
                "station_id": selected_station_id,
                "warning_type": 0,
                "fault_type": 2,
                "page_no": 1,
                "page_size": 10,
                "state": 0,
            },
            response=warning_list_payload,
            passed=bool(warning_list_payload.get("success")),
        )
        warning_correction_payload = client.warning_correction_records(
            station_id=selected_station_id
        )
        print_test_section(
            title="Warning Correction Test",
            purpose="Fetch the error-correction metadata associated with station warnings.",
            inputs={
                "station_id": selected_station_id,
                "warning_type": 0,
                "page_no": 1,
                "page_size": 10,
            },
            response=warning_correction_payload,
            passed=bool(warning_correction_payload.get("success")),
        )
        inverter_list_payload = client.inverter_list(station_id=selected_station_id)
        print_test_section(
            title="Inverter List Test",
            purpose="Fetch the inverter list for the selected station.",
            inputs={
                "station_id": selected_station_id,
                "station_type": 0,
                "page_no": 1,
                "page_size": 10,
            },
            response=inverter_list_payload,
            passed=bool(inverter_list_payload.get("success")),
        )
        inverter_index_payload = client.inverter_index_list(station_id=selected_station_id)
        print_test_section(
            title="Inverter Index Test",
            purpose="Fetch the indexed inverter listing used by the device page.",
            inputs={
                "station_id": selected_station_id,
                "station_type": 0,
                "page_no": 1,
                "page_size": 20,
                "order_by": "name",
                "order_by_asc": True,
            },
            response=inverter_index_payload,
            passed=bool(inverter_index_payload.get("success")),
        )
        collector_list_payload = client.collector_list(station_id=selected_station_id)
        print_test_section(
            title="Collector List Test",
            purpose="Fetch the collector list for the selected station.",
            inputs={
                "station_id": selected_station_id,
                "station_type": 0,
                "page_size": 20,
                "order_by": "name",
                "order_by_asc": True,
            },
            response=collector_list_payload,
            passed=bool(collector_list_payload.get("success")),
        )
        opt_config_list_payload = client.opt_config_list()
        print_test_section(
            title="Optimizer Config Test",
            purpose="Fetch optimizer configuration options exposed by the web UI.",
            inputs={},
            response=opt_config_list_payload,
            passed=bool(opt_config_list_payload.get("success")),
        )
        opt_station_detail_payload = client.opt_station_detail(selected_station_id)
        print_test_section(
            title="Optimizer Station Detail Test",
            purpose="Fetch optimizer-related data for the selected station.",
            inputs={"station_id": selected_station_id, "query_inverter_list": True},
            response=opt_station_detail_payload,
            passed=bool(opt_station_detail_payload.get("success")),
        )
        opt_panel_list_payload = client.opt_panel_list(selected_station_id)
        print_test_section(
            title="Optimizer Panel List Test",
            purpose="Fetch optimizer panel records for the selected station.",
            inputs={"station_id": selected_station_id},
            response=opt_panel_list_payload,
            passed=bool(opt_panel_list_payload.get("success")),
        )
        inverter_config_payload = client.inverter_config(selected_station_id)
        print_test_section(
            title="Inverter Config Test",
            purpose="Fetch inverter configuration metadata for the selected station.",
            inputs={"station_id": selected_station_id},
            response=inverter_config_payload,
            passed=bool(inverter_config_payload.get("success")),
        )
        inverter_iv_info_payload = client.inverter_iv_info()
        print_test_section(
            title="Inverter IV Info Test",
            purpose="Fetch the IV information listing used by the inverter diagnostics UI.",
            inputs={"page_no": 1, "page_size": 10},
            response=inverter_iv_info_payload,
            passed=bool(inverter_iv_info_payload.get("success")),
        )
        inverter_search_temp_payload = client.inverter_list_search_temp(search_type=0)
        print_test_section(
            title="Inverter Search Temp Test",
            purpose="Fetch the inverter quick-search helper data used by the UI.",
            inputs={"search_type": 0},
            response=inverter_search_temp_payload,
            passed=bool(inverter_search_temp_payload.get("success")),
        )
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    inverter_records = _page_records(inverter_list_payload)
    collector_records = _page_records(collector_list_payload)
    selected_inverter = inverter_records[0] if inverter_records else None
    selected_collector = collector_records[0] if collector_records else None
    inverter_detail_payload: dict[str, object] | None = None
    inverter_all_energy_payload: dict[str, object] | None = None
    inverter_day_chart_payload: dict[str, object] | None = None
    inverter_month_chart_payload: dict[str, object] | None = None
    inverter_year_chart_payload: dict[str, object] | None = None
    inverter_all_chart_payload: dict[str, object] | None = None
    inverter_at_check_payload: dict[str, object] | None = None
    inverter_dispersion_payload: dict[str, object] | None = None
    collector_detail_payload: dict[str, object] | None = None
    collector_day_payload: dict[str, object] | None = None
    collector_packet_loss_payload: dict[str, object] | None = None
    ammeter_list_payload: dict[str, object] | None = None
    epm_list_payload: dict[str, object] | None = None
    weather_list_payload: dict[str, object] | None = None
    if selected_inverter is not None:
        selected_inverter_id = str(selected_inverter.get("id"))
        try:
            inverter_detail_payload = client.inverter_detail(selected_inverter_id)
            print_test_section(
                title="Inverter Detail Test",
                purpose="Fetch the detailed inverter payload for the selected inverter.",
                inputs={"inverter_id": selected_inverter_id},
                response=inverter_detail_payload,
                passed=bool(inverter_detail_payload.get("success")),
            )
            inverter_all_energy_payload = client.inverter_all_energy(
                selected_inverter_id,
                begin_time=str(chart_context["day"]),
            )
            print_test_section(
                title="Inverter Energy Summary Test",
                purpose="Fetch the inverter-level daily energy summary used by the inverter overview.",
                inputs={
                    "inverter_id": selected_inverter_id,
                    "begin_time": chart_context["day"],
                    "type": 0,
                },
                response=inverter_all_energy_payload,
                passed=bool(inverter_all_energy_payload.get("success")),
            )
            inverter_day_chart_payload = client.inverter_chart_day(
                selected_inverter_id,
                day=str(chart_context["day"]),
                time_zone=chart_context["time_zone"],
            )
            print_test_section(
                title="Inverter Day Chart Test",
                purpose="Fetch the intraday inverter chart data for the selected inverter.",
                inputs={
                    "inverter_id": selected_inverter_id,
                    "day": chart_context["day"],
                    "time_zone": chart_context["time_zone"],
                    "search_info": "pac",
                },
                response=inverter_day_chart_payload,
                passed=bool(inverter_day_chart_payload.get("success")),
            )
            inverter_month_chart_payload = client.inverter_chart_month(
                selected_inverter_id,
                month=str(chart_context["month"]),
            )
            print_test_section(
                title="Inverter Month Chart Test",
                purpose="Fetch the monthly inverter chart series for the selected inverter.",
                inputs={
                    "inverter_id": selected_inverter_id,
                    "month": chart_context["month"],
                    "version": 1,
                },
                response=inverter_month_chart_payload,
                passed=bool(inverter_month_chart_payload.get("success")),
            )
            inverter_year_chart_payload = client.inverter_chart_year(
                selected_inverter_id,
                year=str(chart_context["year"]),
            )
            print_test_section(
                title="Inverter Year Chart Test",
                purpose="Fetch the yearly inverter chart series for the selected inverter.",
                inputs={
                    "inverter_id": selected_inverter_id,
                    "year": chart_context["year"],
                    "version": 1,
                },
                response=inverter_year_chart_payload,
                passed=bool(inverter_year_chart_payload.get("success")),
            )
            inverter_all_chart_payload = client.inverter_chart_all(selected_inverter_id)
            print_test_section(
                title="Inverter Lifetime Chart Test",
                purpose="Fetch the lifetime inverter chart series grouped by year.",
                inputs={"inverter_id": selected_inverter_id, "version": 1},
                response=inverter_all_chart_payload,
                passed=bool(inverter_all_chart_payload.get("success")),
            )
            inverter_at_check_payload = client.inverter_at_check(selected_inverter_id)
            print_test_section(
                title="Inverter AT Check Test",
                purpose="Fetch inverter advanced telemetry capability data for the selected inverter.",
                inputs={"inverter_id": selected_inverter_id},
                response=inverter_at_check_payload,
                passed=bool(inverter_at_check_payload.get("success")),
            )
            dispersion_begin = f"{chart_context['day']} 00:00:00"
            dispersion_end = f"{chart_context['day']} 23:59:59"
            inverter_dispersion_payload = client.inverter_dispersion_list(
                station_id=selected_station_id,
                begin_time=dispersion_begin,
                end_time=dispersion_end,
                time_zone=chart_context["time_zone"],
            )
            print_test_section(
                title="Inverter Dispersion Test",
                purpose="Fetch the station-level inverter dispersion view over the current day.",
                inputs={
                    "station_id": selected_station_id,
                    "begin_time": dispersion_begin,
                    "end_time": dispersion_end,
                    "time_zone": chart_context["time_zone"],
                },
                response=inverter_dispersion_payload,
                passed=bool(inverter_dispersion_payload.get("success")),
            )
        except SolisWebApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1

    if selected_collector is not None:
        selected_collector_id = str(selected_collector.get("id"))
        selected_collector_sn = str(selected_collector.get("sn") or "")
        try:
            collector_detail_payload = client.collector_detail(selected_collector_id)
            print_test_section(
                title="Collector Detail Test",
                purpose="Fetch the detailed collector payload for the selected collector.",
                inputs={"collector_id": selected_collector_id},
                response=collector_detail_payload,
                passed=bool(collector_detail_payload.get("success")),
            )
            collector_day_payload = client.collector_day(
                selected_collector_id,
                day=str(chart_context["day"]),
                time_zone=chart_context["time_zone"],
            )
            print_test_section(
                title="Collector Day Test",
                purpose="Fetch the collector day timeline for the selected collector.",
                inputs={
                    "collector_id": selected_collector_id,
                    "day": chart_context["day"],
                    "time_zone": chart_context["time_zone"],
                },
                response=collector_day_payload,
                passed=bool(collector_day_payload.get("success")),
            )
            collector_packet_loss_payload = client.collector_packet_loss_rate(
                sn=selected_collector_sn
            )
            print_test_section(
                title="Collector Packet Loss Test",
                purpose="Fetch packet-loss telemetry for the selected collector.",
                inputs={"sn": selected_collector_sn},
                response=collector_packet_loss_payload,
                passed=bool(collector_packet_loss_payload.get("success")),
            )
            ammeter_list_payload = client.ammeter_list(collector_id=selected_collector_id)
            print_test_section(
                title="Ammeter List Test",
                purpose="Fetch ammeter devices attached to the selected collector.",
                inputs={"collector_id": selected_collector_id, "page_no": 1, "page_size": 20},
                response=ammeter_list_payload,
                passed=bool(ammeter_list_payload.get("success")),
            )
            epm_list_payload = client.epm_list(collector_id=selected_collector_id)
            print_test_section(
                title="EPM List Test",
                purpose="Fetch EPM devices attached to the selected collector.",
                inputs={"collector_id": selected_collector_id, "page_no": 1, "page_size": 20},
                response=epm_list_payload,
                passed=bool(epm_list_payload.get("success")),
            )
            weather_list_payload = client.weather_list(collector_id=selected_collector_id)
            print_test_section(
                title="Weather List Test",
                purpose="Fetch weather-sensor devices attached to the selected collector.",
                inputs={"collector_id": selected_collector_id, "page_no": 1, "page_size": 20},
                response=weather_list_payload,
                passed=bool(weather_list_payload.get("success")),
            )
        except SolisWebApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1

    summary = {
        "login_success": bool(login_payload.get("success")),
        "profile_success": bool(profile_payload.get("success")),
        "site_count": len(sites),
        "selected_site": {
            "id": selected_station_id,
            "stationName": selected_site.get("stationName"),
            "stationType": selected_site.get("stationType"),
        },
        "sites_preview": [_site_preview(site) for site in sites[:3]],
        "station": {
            "detail_success": bool(station_detail_payload.get("success")),
            "config_success": bool(station_config_detail_payload.get("success")),
            "device_count_success": bool(station_device_count_payload.get("success")),
            "user_success": bool(station_user_payload.get("success")),
            "visitor_success": bool(station_visitor_payload.get("success")),
            "second_upload_success": bool(station_second_data_payload.get("success")),
            "second_upload_supported": bool(station_second_data_payload.get("success")),
            "all_energy_success": bool(station_all_energy_payload.get("success")),
            "day_chart_points": len(station_day_chart_payload.get("data", {}).get("time", [])),
            "month_chart_points": len(station_month_chart_payload.get("data", [])),
            "year_chart_points": len(station_year_chart_payload.get("data", [])),
            "all_chart_points": len(station_all_chart_payload.get("data", [])),
            "device_counts": station_device_count_payload.get("data"),
            "visitor_count": len(_data_list(station_visitor_payload)),
        },
        "alarms": {
            "list_success": bool(alarm_list_payload.get("success")),
            "record_count": len(alarm_records),
            "total": alarm_list_payload.get("data", {}).get("total"),
            "detail_success": bool(alarm_detail_payload and alarm_detail_payload.get("success")),
        },
        "warnings": {
            "list_success": bool(warning_list_payload.get("success")),
            "record_count": len(warning_list_payload.get("data", {}).get("records", [])),
            "total": warning_list_payload.get("data", {}).get("total"),
            "correction_success": bool(warning_correction_payload.get("success")),
            "is_correction": warning_correction_payload.get("data", {}).get("isCorrection"),
        },
        "inverters": {
            "list_success": bool(inverter_list_payload.get("success")),
            "list_count": len(inverter_records),
            "index_success": bool(inverter_index_payload.get("success")),
            "index_count": len(_page_records(inverter_index_payload)),
            "selected_inverter": (
                {
                    "id": selected_inverter.get("id"),
                    "sn": selected_inverter.get("sn"),
                    "model": selected_inverter.get("model"),
                }
                if selected_inverter
                else None
            ),
            "detail_success": bool(inverter_detail_payload and inverter_detail_payload.get("success")),
            "all_energy_success": bool(
                inverter_all_energy_payload and inverter_all_energy_payload.get("success")
            ),
            "day_chart_series": (
                len(inverter_day_chart_payload.get("data", {}))
                if isinstance(inverter_day_chart_payload, dict)
                and isinstance(inverter_day_chart_payload.get("data"), dict)
                else 0
            ),
            "month_chart_points": len(inverter_month_chart_payload.get("data", []))
            if isinstance(inverter_month_chart_payload, dict)
            else 0,
            "year_chart_points": len(inverter_year_chart_payload.get("data", []))
            if isinstance(inverter_year_chart_payload, dict)
            else 0,
            "all_chart_points": len(inverter_all_chart_payload.get("data", []))
            if isinstance(inverter_all_chart_payload, dict)
            else 0,
            "at_check_success": bool(inverter_at_check_payload and inverter_at_check_payload.get("success")),
            "config_success": bool(inverter_config_payload.get("success")),
            "iv_info_success": bool(inverter_iv_info_payload.get("success")),
            "iv_info_count": len(_page_records(inverter_iv_info_payload)),
            "search_temp_success": bool(inverter_search_temp_payload.get("success")),
            "dispersion_success": bool(
                inverter_dispersion_payload and inverter_dispersion_payload.get("success")
            ),
        },
        "collectors": {
            "list_success": bool(collector_list_payload.get("success")),
            "list_count": len(collector_records),
            "selected_collector": (
                {
                    "id": selected_collector.get("id"),
                    "sn": selected_collector.get("sn"),
                    "model": selected_collector.get("model"),
                }
                if selected_collector
                else None
            ),
            "detail_success": bool(collector_detail_payload and collector_detail_payload.get("success")),
            "day_points": len(collector_day_payload.get("data", []))
            if isinstance(collector_day_payload, dict)
            else 0,
            "packet_loss_success": bool(
                collector_packet_loss_payload and collector_packet_loss_payload.get("success")
            ),
            "ammeter_success": bool(ammeter_list_payload and ammeter_list_payload.get("success")),
            "ammeter_count": len(_page_records(ammeter_list_payload))
            if isinstance(ammeter_list_payload, dict)
            else 0,
            "epm_success": bool(epm_list_payload and epm_list_payload.get("success")),
            "epm_count": len(_page_records(epm_list_payload))
            if isinstance(epm_list_payload, dict)
            else 0,
            "weather_success": bool(weather_list_payload and weather_list_payload.get("success")),
            "weather_count": len(_page_records(weather_list_payload))
            if isinstance(weather_list_payload, dict)
            else 0,
        },
        "optimizers": {
            "config_success": bool(opt_config_list_payload.get("success")),
            "config_count": len(_data_list(opt_config_list_payload)),
            "station_detail_success": bool(opt_station_detail_payload.get("success")),
            "panel_list_success": bool(opt_panel_list_payload.get("success")),
            "panel_count": len(_data_list(opt_panel_list_payload)),
        },
    }
    print_test_section(
        title="Integration Summary",
        purpose="Summarize the overall status of the integration test run.",
        inputs={
            "selected_station_id": selected_station_id,
            "selected_inverter_id": (
                str(selected_inverter.get("id")) if selected_inverter is not None else None
            ),
        },
        response=summary,
        passed=all(
            [
                summary["login_success"],
                summary["profile_success"],
                summary["station"]["detail_success"],
                summary["station"]["config_success"],
                summary["station"]["device_count_success"],
                summary["station"]["user_success"],
                summary["station"]["visitor_success"],
                summary["station"]["all_energy_success"],
                summary["alarms"]["list_success"],
                summary["warnings"]["list_success"],
                summary["warnings"]["correction_success"],
                summary["inverters"]["list_success"],
                summary["inverters"]["index_success"],
                summary["inverters"]["config_success"],
                summary["inverters"]["iv_info_success"],
                summary["collectors"]["list_success"],
                summary["optimizers"]["config_success"],
                summary["optimizers"]["station_detail_success"],
                summary["optimizers"]["panel_list_success"],
            ]
        ),
    )

    should_open_browser = args.open_browser
    if not args.open_browser and not args.no_browser:
        try:
            answer = input("Open this station in an authenticated browser? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        should_open_browser = answer in {"y", "yes"}

    if should_open_browser:
        try:
            open_browser_from_client(
                client,
                headless=False,
                capture_json=True,
                capture_url_contains=["/api/"],
                capture_mode="last",
                station_id=selected_station_id,
            )
        except SolisWebApiError as exc:
            print(f"FAIL: browser open failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
