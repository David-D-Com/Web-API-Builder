"""Core SolisCloud web API client.

This module implements the same signed request flow used by the SolisCloud web
application. The important behaviors are:

- Browser-style authentication via ``/user/login2``
- HMAC request signing for both POST and GET endpoints
- Optional payload cleanup for language/UI-heavy responses
- Persistent request caching for historical and stable endpoints
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import random
import string
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import format_datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


BASE_URL = "https://www.soliscloud.com"
API_PREFIX = "/api"
WEB_KEY_ID = "2424"
WEB_SECRET = "5704383536604a8bb94c83ebc059aa8c"
CONTENT_TYPE = "application/json;charset=UTF-8"
SIGN_CONTENT_TYPE = "application/json"
APP_VERSION = "5.2.401"
CLOUD_PLATFORM = "GLY"
CONFIG_DIR = Path.home() / ".soliscloud_web_api"
CONFIG_PATH = CONFIG_DIR / "config.json"
CACHE_DIR = CONFIG_DIR / "cache"
FILTERED_DROP_KEYS = {
    "functionIds",
    "tableParams",
    "stationSearchParam",
    "collectorSearchParam",
    "styleSwitchList",
}
SMART_CACHE_HISTORICAL_FIELDS = {
    "time",
    "month",
    "year",
    "beginTime",
    "endTime",
}
SMART_CACHE_STABLE_PATHS = {
    "/station/detailMix",
    "/station/configDetail",
    "/station/deviceCount",
    "/station/stationUser",
    "/station/stationVisitor",
    "/inverter/detail",
    "/inverter/atCheck",
    "/inverter/config",
    "/inverter/listSearchTemp",
    "/collector/detail",
    "/collector/iot/packetLossRate",
    "/opt/configList",
    "/opt/station/detail",
    "/system/right/check",
    "/system/config/global/v2",
    "/v2/devUp/notice",
    "/v2/devUp/upgradeFail/notice",
    "/v2/devUp/user/notice/count",
}
NON_CACHEABLE_PATHS = {
    "/user/login2",
    "/user/find",
    "/station/list",
    "/alarm/list",
    "/alarm/detail",
    "/warning/warningList",
    "/warning/queryErrorCorrectionRecord",
}


class SolisWebApiError(RuntimeError):
    """Raised when a web API call fails."""


def _random_device_id(length: int = 64) -> str:
    alphabet = string.digits + string.ascii_lowercase + string.ascii_uppercase
    return "".join(random.choice(alphabet) for _ in range(length))


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_or_create_device_id() -> str:
    config = _load_config()
    device_id = config.get("device_id")
    if isinstance(device_id, str) and device_id:
        return device_id
    device_id = _random_device_id()
    config["device_id"] = device_id
    _save_config(config)
    return device_id


@dataclass
class SolisSession:
    """Session configuration for a SolisCloud user.

    The session stores both authentication inputs and client-side behavior
    toggles. Keeping these on the session makes it easy for multiple scripts to
    share one consistent policy for filtering and caching.
    """

    username: str
    password: str
    device_id: str
    token: str = ""
    filter_results: bool = False
    preferred_language: str = "both"
    cache_enabled: bool = True
    cache_policy: str = "smart"
    cache_dir: Path = CACHE_DIR
    cache_live_data: bool = False

    @classmethod
    def from_credentials(
        cls,
        username: str,
        password: str,
        *,
        filter_results: bool = False,
        preferred_language: str = "both",
        cache_enabled: bool = True,
        cache_policy: str = "smart",
        cache_dir: Path | str | None = None,
        cache_live_data: bool = False,
    ) -> "SolisSession":
        if not username or not password:
            raise SolisWebApiError("Username and password are required.")
        return cls(
            username=username,
            password=password,
            device_id=get_or_create_device_id(),
            filter_results=filter_results,
            preferred_language=preferred_language,
            cache_enabled=cache_enabled,
            cache_policy=cache_policy,
            cache_dir=Path(cache_dir) if cache_dir is not None else CACHE_DIR,
            cache_live_data=cache_live_data,
        )

    @classmethod
    def from_env(
        cls,
        *,
        filter_results: bool = False,
        preferred_language: str = "both",
        cache_enabled: bool = True,
        cache_policy: str = "smart",
        cache_dir: Path | str | None = None,
        cache_live_data: bool = False,
    ) -> "SolisSession":
        username = os.environ.get("SOLIS_USERNAME")
        password = os.environ.get("SOLIS_PASSWORD")
        missing = [
            name
            for name, value in (
                ("SOLIS_USERNAME", username),
                ("SOLIS_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise SolisWebApiError(
                "Missing environment variables: " + ", ".join(missing)
            )
        return cls.from_credentials(
            username,
            password,
            filter_results=filter_results,
            preferred_language=preferred_language,
            cache_enabled=cache_enabled,
            cache_policy=cache_policy,
            cache_dir=cache_dir,
            cache_live_data=cache_live_data,
        )


class SolisWebApiClient:
    """High-level SolisCloud web client.

    The client owns the HTTP cookie jar and the request signer. Most public
    methods correspond directly to one web-app endpoint.
    """

    def __init__(self, session: SolisSession, timeout: float = 30.0) -> None:
        self.session = session
        self.timeout = timeout
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def clear_cache(self) -> int:
        """Delete cached JSON responses and return the number removed."""
        cache_root = self._cache_root()
        if not cache_root.exists():
            return 0
        removed = 0
        for path in cache_root.rglob("*.json"):
            path.unlink()
            removed += 1
        return removed

    def bootstrap(self) -> None:
        """Prime the cookie jar with the login page before authenticating."""
        request = urllib.request.Request(
            url=f"{BASE_URL}/login?",
            headers={"User-Agent": self._user_agent()},
            method="GET",
        )
        try:
            self.opener.open(request, timeout=self.timeout).read()
        except urllib.error.URLError as exc:
            raise SolisWebApiError(f"Failed to open login page: {exc}") from exc

    def login(self) -> dict[str, Any]:
        """Authenticate and persist the anti-CSRF token used by later calls."""
        self.bootstrap()
        body = {
            # The browser hashes the password client-side before sending it.
            "userInfo": self.session.username,
            "passWord": hashlib.md5(self.session.password.encode("utf-8")).hexdigest(),
            "yingZhenType": 1,
        }
        payload = self._post("/user/login2", body, include_token=False)
        token = payload.get("csrfToken") or payload.get("data", {}).get("token")
        if not token:
            raise SolisWebApiError(f"Login succeeded but no token was returned: {payload}")
        self.session.token = token
        return payload

    def profile(self) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/user/find", {})

    # Site and station endpoints -------------------------------------------------

    def list_sites(
        self,
        *,
        page_no: int = 1,
        page_size: int = 20,
        station_type: int | str = 1,
        extra_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        body: dict[str, Any] = {
            "pageNo": page_no,
            "pageSize": page_size,
            "stationType": station_type,
        }
        if extra_filters:
            body.update(extra_filters)
        return self._post("/station/list", body)

    def list_all_sites(
        self,
        *,
        page_size: int = 100,
        station_type: int | str = 1,
        extra_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        page_no = 1
        records: list[dict[str, Any]] = []
        while True:
            payload = self.list_sites(
                page_no=page_no,
                page_size=page_size,
                station_type=station_type,
                extra_filters=extra_filters,
            )
            data = payload.get("data", {})
            page = data.get("page", data)
            batch = page.get("records", [])
            if not isinstance(batch, list):
                raise SolisWebApiError(
                    f"Unexpected station/list response shape: {payload}"
                )
            records.extend(batch)
            total_pages = int(page.get("pages", 1) or 1)
            if page_no >= total_pages:
                return records
            page_no += 1

    def station_detail(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/station/detailMix", {"id": station_id})

    def station_all_energy(
        self,
        station_id: str,
        *,
        begin_time: str,
        energy_type: int = 0,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/station/stationAllEnergy",
            {
                "type": energy_type,
                "id": station_id,
                "beginTime": begin_time,
            },
        )

    def station_chart_day(
        self,
        station_id: str,
        *,
        day: str,
        time_zone: int | float,
        money: str,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/station/day/v2",
            {
                "id": station_id,
                "time": day,
                "timeZone": time_zone,
                "money": money,
                "version": version,
            },
        )

    def station_chart_month(
        self,
        station_id: str,
        *,
        month: str,
        time_zone: int | float,
        money: str,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/station/month",
            {
                "id": station_id,
                "month": month,
                "timeZone": time_zone,
                "money": money,
                "version": version,
            },
        )

    def station_chart_year(
        self,
        station_id: str,
        *,
        year: int | str,
        time_zone: int | float,
        money: str,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/station/year",
            {
                "id": station_id,
                "year": str(year),
                "timeZone": time_zone,
                "money": money,
                "version": version,
            },
        )

    def station_chart_all(
        self,
        station_id: str,
        *,
        time_zone: int | float,
        money: str,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/station/all",
            {
                "id": station_id,
                "timeZone": time_zone,
                "money": money,
                "version": version,
            },
        )

    # Alarm and warning endpoints ------------------------------------------------

    def alarm_list(
        self,
        *,
        station_id: str,
        fault_type: int = 0,
        page_no: int = 1,
        page_size: int = 10,
        state: int = 0,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/alarm/list",
            {
                "faultType": fault_type,
                "pageNo": page_no,
                "pageSize": page_size,
                "state": state,
                "stationId": station_id,
            },
        )

    def alarm_detail(
        self,
        *,
        alarm_device_sn: str,
        alarm_code: str | int,
        alarm_begin_time: str | int,
        warning_info_data: str | int = 0,
        alarm_device_type: str | int,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/alarm/detail",
            {
                "alarmDeviceSn": str(alarm_device_sn),
                "alarmCode": str(alarm_code),
                "alarmBeginTime": str(alarm_begin_time),
                "warningInfoData": str(warning_info_data),
                "alarmDeviceType": str(alarm_device_type),
            },
        )

    def warning_list(
        self,
        *,
        station_id: str,
        warning_type: int = 0,
        fault_type: int = 2,
        page_no: int = 1,
        page_size: int = 10,
        state: int = 0,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/warning/warningList",
            {
                "warningType": warning_type,
                "faultType": fault_type,
                "pageNo": page_no,
                "pageSize": page_size,
                "state": state,
                "stationId": station_id,
            },
        )

    def warning_correction_records(
        self,
        *,
        station_id: str,
        warning_type: int = 0,
        page_no: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/warning/queryErrorCorrectionRecord",
            {
                "stationId": station_id,
                "pageNo": page_no,
                "pageSize": page_size,
                "warningType": warning_type,
            },
        )

    # Inverter endpoints ---------------------------------------------------------

    def inverter_list(
        self,
        *,
        station_id: str,
        station_type: int | str = 0,
        page_no: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/inverter/listV2",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "stationId": station_id,
                "stationType": str(station_type),
            },
        )

    def inverter_index_list(
        self,
        *,
        station_id: str,
        station_type: int | str = 0,
        page_no: int = 1,
        page_size: int = 20,
        order_by: str = "name",
        order_by_asc: bool = True,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/inverter/index/list",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "stationId": station_id,
                "stationType": int(station_type),
                "orderBy": order_by,
                "orderByAsc": "true" if order_by_asc else "false",
            },
        )

    def inverter_detail(self, inverter_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/inverter/detail", {"id": inverter_id})

    def inverter_all_energy(
        self,
        inverter_id: str,
        *,
        begin_time: str,
        energy_type: int = 0,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/inverterAllEnergy",
            {
                "type": energy_type,
                "beginTime": begin_time,
                "id": inverter_id,
            },
        )

    def inverter_chart_month(
        self,
        inverter_id: str,
        *,
        month: str,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/inverter/month",
            {
                "id": inverter_id,
                "month": month,
                "version": version,
            },
        )

    def inverter_chart_year(
        self,
        inverter_id: str,
        *,
        year: str | int,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/inverter/year",
            {
                "id": inverter_id,
                "year": str(year),
                "version": version,
            },
        )

    def inverter_chart_all(
        self,
        inverter_id: str,
        *,
        version: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/inverter/all",
            {
                "id": inverter_id,
                "version": version,
            },
        )

    def inverter_chart_day(
        self,
        inverter_id: str,
        *,
        day: str,
        time_zone: int | float,
        search_info: str = "pac",
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/chart/inverter/day/v2",
            {
                "id": inverter_id,
                "timeZone": time_zone,
                "searchInfo": search_info,
                "time": day,
            },
        )

    def inverter_at_check(self, inverter_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/inverter/atCheck", {"inverterId": inverter_id})

    def inverter_config(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/inverter/config", {"stationId": station_id})

    def inverter_dispersion_list(
        self,
        *,
        station_id: str,
        begin_time: str,
        end_time: str,
        time_zone: int | float,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/inverter/dispersionList",
            {
                "beginTime": begin_time,
                "endTime": end_time,
                "stationId": station_id,
                "timeZone": time_zone,
            },
        )

    def inverter_iv_info(
        self,
        *,
        page_no: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/inverter/ivInfo",
            {
                "pageNo": page_no,
                "pageSize": page_size,
            },
        )

    def inverter_list_search_temp(self, *, search_type: int = 0) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/inverter/listSearchTemp", {"type": search_type})

    # Station metadata endpoints -------------------------------------------------

    def station_config_detail(
        self,
        station_id: str,
        *,
        config_type: int = 0,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/station/configDetail",
            {
                "type": config_type,
                "stationId": station_id,
            },
        )

    def station_device_count(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/station/deviceCount", {"id": station_id})

    def station_user(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/station/stationUser", {"id": station_id})

    def station_visitor(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/station/stationVisitor", {"id": station_id})

    # Collector and related device endpoints ------------------------------------

    def collector_list(
        self,
        *,
        station_id: str,
        station_type: int | str = 0,
        page_size: int = 20,
        order_by: str = "name",
        order_by_asc: bool = True,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/collector/listV2",
            {
                "pageSize": page_size,
                "stationId": station_id,
                "stationType": int(station_type),
                "orderBy": order_by,
                "orderByAsc": order_by_asc,
            },
        )

    def collector_detail(self, collector_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/collector/detail", {"id": collector_id})

    def collector_day(
        self,
        collector_id: str,
        *,
        day: str,
        time_zone: int | float,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/collector/collector/day",
            {
                "id": collector_id,
                "time": day,
                "timeZone": time_zone,
            },
        )

    def collector_packet_loss_rate(self, *, sn: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/collector/iot/packetLossRate", {"sn": sn})

    def ammeter_list(
        self,
        *,
        collector_id: str,
        page_no: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/ammeter/list",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "collectorId": collector_id,
            },
        )

    def epm_list(
        self,
        *,
        collector_id: str,
        page_no: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/epm/listV2",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "collectorId": collector_id,
            },
        )

    def weather_list(
        self,
        *,
        collector_id: str,
        page_no: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/weather/list",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "collectorId": collector_id,
            },
        )

    def device_second_upload_check_station_data(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/deviceSecondUpload/checkStationSecondData",
            {"stationId": station_id},
        )

    # Optimizer endpoints --------------------------------------------------------

    def opt_config_list(self) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/opt/configList", {})

    def opt_panel_list(self, station_id: str) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/opt/panel/list", {"stationId": station_id})

    def opt_station_detail(
        self,
        station_id: str,
        *,
        query_inverter_list: bool = True,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/opt/station/detail",
            {
                "stationId": station_id,
                "queryInverterList": query_inverter_list,
            },
        )

    # Notification and bootstrap endpoints --------------------------------------

    def alarm_read_all(self) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/alarm/alarmReadAll", {})

    def gly_message_record_list(
        self,
        *,
        page_no: int = 1,
        page_size: int = 10,
        template_state: int = 1,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/glyMessageRecord/list",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "templateState": template_state,
            },
        )

    def gly_message_record_realtime(self, *, platform: int = 3) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/glyMessageRecord/realtime", {"platform": platform})

    def message_list(
        self,
        *,
        page_no: int = 1,
        page_size: int = 10,
        platform: str | int = "3",
        entrance: int = 3,
        state: int = 2,
    ) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post(
            "/message/list",
            {
                "pageNo": page_no,
                "pageSize": page_size,
                "platform": str(platform),
                "entrance": entrance,
                "state": state,
            },
        )

    def system_right_check(self) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/system/right/check", {})

    def system_config_global_v2(self, *, language: str | int = "2") -> dict[str, Any]:
        self._ensure_logged_in()
        return self._get("/system/config/global/v2", {"language": str(language)})

    def devup_notice(self, *, language: str | int = "2") -> dict[str, Any]:
        self._ensure_logged_in()
        return self._get("/v2/devUp/notice", {"language": str(language)})

    def devup_upgrade_fail_notice(self, *, language: str | int = "2") -> dict[str, Any]:
        self._ensure_logged_in()
        return self._get("/v2/devUp/upgradeFail/notice", {"language": str(language)})

    def devup_user_notice_count(self) -> dict[str, Any]:
        self._ensure_logged_in()
        return self._post("/v2/devUp/user/notice/count", {})

    def _ensure_logged_in(self) -> None:
        """Lazy-login so callers can use the client without manual setup."""
        if not self.session.token:
            self.login()

    def _filter_payload(self, value: Any) -> Any:
        """Trim UI-heavy payload noise and collapse language variants.

        This is intentionally opinionated. It is meant for downstream scripts
        that prefer a cleaner, more stable shape over the exact raw Solis
        response.
        """
        preferred_language = self.session.preferred_language
        if isinstance(value, list):
            return [self._filter_payload(item) for item in value]
        if not isinstance(value, dict):
            return value

        filtered: dict[str, Any] = {}
        keys = {str(key) for key in value}
        for key, raw_item in value.items():
            key_str = str(key)
            if key_str in FILTERED_DROP_KEYS:
                continue
            if preferred_language == "en":
                if key_str.endswith("Cn"):
                    continue
                if key_str.endswith("En") and (key_str[:-2] + "Cn") in keys:
                    filtered[key_str[:-2]] = self._filter_payload(raw_item)
                    continue
            elif preferred_language == "cn":
                if key_str.endswith("En"):
                    continue
                if key_str.endswith("Cn") and (key_str[:-2] + "En") in keys:
                    filtered[key_str[:-2]] = self._filter_payload(raw_item)
                    continue
            filtered[key_str] = self._filter_payload(raw_item)
        return filtered

    def _post(
        self,
        path: str,
        body_obj: dict[str, Any],
        *,
        include_token: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Send a signed POST request that matches the web application's flow."""
        cache_entry = self._cache_entry(
            path,
            body_obj,
            include_token=include_token,
            force_refresh=force_refresh,
        )
        if cache_entry is not None:
            return cache_entry

        # Solis includes these transient fields in almost every POST body.
        body_with_common = dict(body_obj)
        body_with_common["localTime"] = int(dt.datetime.now().timestamp() * 1000)
        body_with_common["localTimeZone"] = self._local_timezone_offset_hours()
        body_with_common["language"] = "2"

        body = json.dumps(
            body_with_common,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        content_md5 = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
        time_header = format_datetime(dt.datetime.now(dt.timezone.utc), usegmt=True)
        auth = self._authorization("POST", content_md5, time_header, path)

        headers = {
            "User-Agent": self._user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": CONTENT_TYPE,
            "X-Cloud-Platform": CLOUD_PLATFORM,
            "Content-MD5": content_md5,
            "Authorization": auth,
            "Time": time_header,
            "language": "2",
            "Device-Id": self.session.device_id,
            "Version": APP_VERSION,
            "platform": "Web",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        }
        if include_token and self.session.token:
            headers["token"] = self.session.token

        request = urllib.request.Request(
            url=f"{BASE_URL}{API_PREFIX}{path}",
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise SolisWebApiError(
                f"HTTP {exc.code} calling {path}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SolisWebApiError(f"Network error calling {path}: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SolisWebApiError(f"Invalid JSON from {path}: {raw}") from exc

        if not payload.get("success", False) or str(payload.get("code")) != "0":
            raise SolisWebApiError(
                f"Solis web API error for {path}: "
                f"code={payload.get('code')} msg={payload.get('msg')} payload={payload}"
            )
        if self.session.filter_results:
            payload = self._filter_payload(payload)
        self._write_cache_entry(
            path,
            body_obj,
            include_token=include_token,
            payload=payload,
            force_refresh=force_refresh,
        )
        return payload

    def _get(
        self,
        path: str,
        query_obj: dict[str, Any],
        *,
        include_token: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Send a signed GET request using the same query-signing style as the SPA."""
        cache_entry = self._cache_entry(
            path,
            query_obj,
            include_token=include_token,
            force_refresh=force_refresh,
        )
        if cache_entry is not None:
            return cache_entry

        query_with_common = dict(query_obj)
        # For GET endpoints, Solis signs the full query string rather than a
        # path-only resource.
        query_with_common["localTime"] = int(dt.datetime.now().timestamp() * 1000)
        query_with_common["localTimeZone"] = self._local_timezone_offset_hours()
        query_with_common["language"] = str(query_with_common.get("language", "2"))

        md5_body = json.dumps(
            query_with_common,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        content_md5 = base64.b64encode(hashlib.md5(md5_body).digest()).decode("ascii")
        query_string = urllib.parse.urlencode(query_with_common)
        path_with_query = f"{path}?{query_string}"
        time_header = format_datetime(dt.datetime.now(dt.timezone.utc), usegmt=True)
        auth = self._authorization("GET", content_md5, time_header, path_with_query)

        headers = {
            "User-Agent": self._user_agent(),
            "Accept": "application/json, text/plain, */*",
            "X-Cloud-Platform": CLOUD_PLATFORM,
            "Content-MD5": content_md5,
            "Authorization": auth,
            "Time": time_header,
            "language": str(query_with_common["language"]),
            "Device-Id": self.session.device_id,
            "Version": APP_VERSION,
            "platform": "Web",
            "Referer": f"{BASE_URL}/",
        }
        if include_token and self.session.token:
            headers["token"] = self.session.token

        request = urllib.request.Request(
            url=f"{BASE_URL}{API_PREFIX}{path_with_query}",
            method="GET",
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise SolisWebApiError(
                f"HTTP {exc.code} calling {path_with_query}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SolisWebApiError(f"Network error calling {path_with_query}: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SolisWebApiError(f"Invalid JSON from {path_with_query}: {raw}") from exc

        if not payload.get("success", False) or str(payload.get("code")) != "0":
            raise SolisWebApiError(
                f"Solis web API error for {path_with_query}: "
                f"code={payload.get('code')} msg={payload.get('msg')} payload={payload}"
            )
        if self.session.filter_results:
            payload = self._filter_payload(payload)
        self._write_cache_entry(
            path,
            query_obj,
            include_token=include_token,
            payload=payload,
            force_refresh=force_refresh,
        )
        return payload

    def _cache_root(self) -> Path:
        return Path(self.session.cache_dir)

    def _cache_entry(
        self,
        path: str,
        body_obj: dict[str, Any],
        *,
        include_token: bool,
        force_refresh: bool,
    ) -> dict[str, Any] | None:
        cache_path = self._cache_path(
            path,
            body_obj,
            include_token=include_token,
            force_refresh=force_refresh,
        )
        if cache_path is None or not cache_path.exists():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache_entry(
        self,
        path: str,
        body_obj: dict[str, Any],
        *,
        include_token: bool,
        payload: dict[str, Any],
        force_refresh: bool,
    ) -> None:
        cache_path = self._cache_path(
            path,
            body_obj,
            include_token=include_token,
            force_refresh=force_refresh,
        )
        if cache_path is None:
            return
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _cache_path(
        self,
        path: str,
        body_obj: dict[str, Any],
        *,
        include_token: bool,
        force_refresh: bool,
    ) -> Path | None:
        """Build the on-disk cache path for one logical request shape."""
        if force_refresh or not include_token:
            return None
        if not self._should_cache(path, body_obj):
            return None
        normalized = self._cache_key_payload(body_obj)
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "path": path,
                    "body": normalized,
                    "filter_results": self.session.filter_results,
                    "preferred_language": self.session.preferred_language,
                },
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        safe_name = path.strip("/").replace("/", "__") or "root"
        return self._cache_root() / safe_name / f"{cache_key}.json"

    def _should_cache(self, path: str, body_obj: dict[str, Any]) -> bool:
        """Decide whether a request should be cached under the current policy."""
        if not self.session.cache_enabled:
            return False
        policy = self.session.cache_policy.lower()
        if policy == "off":
            return False
        if policy == "all":
            return True
        if path in NON_CACHEABLE_PATHS:
            return False
        if path in SMART_CACHE_STABLE_PATHS:
            return True
        if any(field in body_obj for field in SMART_CACHE_HISTORICAL_FIELDS):
            return True
        if self.session.cache_live_data:
            return True
        return False

    @staticmethod
    def _cache_key_payload(value: Any) -> Any:
        """Normalize payloads so volatile timestamp/language fields do not fork the cache."""
        if isinstance(value, dict):
            return {
                key: SolisWebApiClient._cache_key_payload(raw_value)
                for key, raw_value in sorted(value.items())
                if key not in {"localTime", "localTimeZone", "language"}
            }
        if isinstance(value, list):
            return [SolisWebApiClient._cache_key_payload(item) for item in value]
        return value

    @staticmethod
    def _authorization(
        method: str,
        content_md5: str,
        time_header: str,
        url_path: str,
    ) -> str:
        """Build the Solis `Authorization: WEB ...` signature header."""
        string_to_sign = "\n".join(
            [method.upper(), content_md5, SIGN_CONTENT_TYPE, time_header, url_path]
        )
        digest = hmac.new(
            WEB_SECRET.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(digest).decode("ascii")
        return f"WEB {WEB_KEY_ID}:{signature}"

    @staticmethod
    def _local_timezone_offset_hours() -> int:
        """Return the local timezone offset in whole hours, matching Solis usage."""
        now = dt.datetime.now().astimezone()
        offset = now.utcoffset()
        if offset is None:
            return 0
        return int(offset.total_seconds() // 3600)

    @staticmethod
    def _user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        )
