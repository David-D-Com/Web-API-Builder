"""Fronius Solar.web API client.

This module provides a reusable client for the production-oriented
JSON endpoints captured from Solar.web. It can talk to the live site or replay
captured request/response JSON files from a session folder.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


JsonDict = dict[str, Any]
QueryValue = str | int | float | bool
QueryParams = dict[str, QueryValue | list[QueryValue] | tuple[QueryValue, ...]]


@dataclass(frozen=True)
class ReplayKey:
    """Normalized request identity used for capture replay lookup."""

    method: str
    path: str
    params: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HttpResponseData:
    """Small response wrapper used by the live auth/bootstrap flow."""

    url: str
    status: int
    headers: dict[str, str]
    text: str


class _FormParser(HTMLParser):
    """Extract the first form and its input fields from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.form_action: str | None = None
        self.inputs: dict[str, str] = {}
        self._inside_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "form" and not self._inside_form:
            self._inside_form = True
            self.form_action = attrs_dict.get("action")
            return
        if self._inside_form and tag == "input":
            name = attrs_dict.get("name")
            if name:
                self.inputs[name] = attrs_dict.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside_form:
            self._inside_form = False


class FroniusClient:
    """Small client for Fronius Solar.web JSON endpoints.

    The client defaults to live HTTP requests. For deterministic testing and
    offline reverse-engineering work, pass `capture_dir` to replay captured
    JSON files instead.
    """

    def __init__(
        self,
        base_url: str = "https://www.solarweb.com",
        *,
        capture_dir: str | Path | None = None,
        prefer_capture: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/") or "https://www.solarweb.com"
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.prefer_capture = prefer_capture
        self._replay_index: dict[ReplayKey, JsonDict] = {}
        self._cookie_jar = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookie_jar))
        self._authenticated = False
        if self.capture_dir:
            self._replay_index = self._build_replay_index(self.capture_dir)

    def initialize(self, *, username: str | None = None, password: str | None = None) -> "FroniusClient":
        """Standard module entrypoint for auth/session setup.

        Replay mode does not need credentials. For live use we bootstrap the
        same Fronius hosted login flow captured from the browser session:
        Solar.web external login -> Fronius login form -> commonauth ->
        authorize auto-post -> Solar.web callback.
        """

        if self.capture_dir and self.prefer_capture:
            return self
        if self._authenticated:
            return self

        resolved_username = username or os.getenv("FRONIUS_USERNAME")
        resolved_password = password or os.getenv("FRONIUS_PASSWORD")
        if not resolved_username or not resolved_password:
            raise ValueError(
                "Fronius live login requires username/password or the "
                "FRONIUS_USERNAME / FRONIUS_PASSWORD environment variables."
            )

        external_login = self._open_text(
            "GET",
            self._build_url("/Account/ExternalLogin", {}),
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "upgrade-insecure-requests": "1",
            },
        )

        login_page = external_login
        if "authenticationendpoint/login.do" not in login_page.url and "loginForm" not in login_page.text:
            if self._looks_authenticated():
                self._authenticated = True
                return self
            raise RuntimeError("Did not reach the Fronius login page while initializing the client.")

        login_action, login_fields = self._parse_form(login_page)
        login_fields["usernameUserInput"] = resolved_username
        login_fields["username"] = resolved_username
        login_fields["password"] = resolved_password
        login_fields["chkRemember"] = "on"

        authorize_auto_post = self._open_text(
            "POST",
            login_action,
            data=login_fields,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://login.fronius.com",
                "referer": login_page.url,
                "upgrade-insecure-requests": "1",
            },
        )

        callback_action, callback_fields = self._parse_form(authorize_auto_post)
        self._open_text(
            "POST",
            callback_action,
            data=callback_fields,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://login.fronius.com",
                "referer": authorize_auto_post.url,
                "upgrade-insecure-requests": "1",
            },
        )

        if not self._looks_authenticated():
            # Solar.web occasionally needs one extra beat before the auth cookie
            # becomes usable for the JSON endpoints.
            time.sleep(0.5)
        if not self._looks_authenticated() and not self._has_solarweb_cookie():
            raise RuntimeError("Fronius login flow completed, but Solar.web API verification failed.")

        self._authenticated = True
        return self

    def initialize_browser_page(
        self,
        page: Any,
        *,
        context: Any | None = None,
        target_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> bool:
        """Optional browser bootstrap hook used by the builder's route opener.

        We drive the hosted login page directly so the Overview route opener can
        land on an authenticated Solar.web page instead of the login screen.
        """

        resolved_username = username or os.getenv("FRONIUS_USERNAME")
        resolved_password = password or os.getenv("FRONIUS_PASSWORD")
        login_entry_url = self._build_url("/Account/ExternalLogin", {})

        page.goto(login_entry_url, wait_until="domcontentloaded", timeout=60000)
        if "login.fronius.com" in page.url:
            if not resolved_username or not resolved_password:
                return False
            page.fill("#usernameUserInput", resolved_username)
            page.fill("#password", resolved_password)
            try:
                page.check("#chkRemember")
            except Exception:
                pass
            page.click("#login-button")
            page.wait_for_url(re.compile(r"^https://www\.solarweb\.com/"), timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=60000)

        if target_url:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        return True

    @classmethod
    def from_capture_dir(
        cls,
        capture_dir: str | Path,
        *,
        base_url: str = "https://www.solarweb.com",
    ) -> "FroniusClient":
        """Create a client that serves responses from a capture folder."""

        return cls(base_url=base_url, capture_dir=capture_dir, prefer_capture=True)

    def healthcheck(self) -> dict[str, Any]:
        """Return simple client metadata for discovery and smoke tests."""

        return {
            "status": "ok",
            "base_url": self.base_url,
            "capture_dir": str(self.capture_dir) if self.capture_dir else None,
            "replay_entries": len(self._replay_index),
        }

    def get_pv_systems_for_list_view(self) -> JsonDict:
        return self._get_json("/PvSystems/GetPvSystemsForListView")

    def get_actual_values(self, *, with_online_state: bool = True) -> list[JsonDict]:
        return self._get_json(
            "/ActualData/GetActualValues",
            {"withOnlineState": str(with_online_state)},
        )

    def get_actual_pv_system_data(self, pv_system_id: str) -> JsonDict:
        return self._get_json(
            "/ActualData/GetActualPvSystemData",
            {"pvSystemId": pv_system_id},
        )

    def get_compare_data_for_pv_system(self, pv_system_id: str) -> JsonDict:
        return self._get_json(
            "/ActualData/GetCompareDataForPvSystem",
            {"pvSystemId": pv_system_id},
        )

    def get_weather_widget_data(self, pv_system_id: str) -> JsonDict:
        return self._get_json(
            "/PvSystems/GetWeatherWidgetData",
            {"pvSystemId": pv_system_id},
        )

    def get_pv_system_productions_and_earnings(self, pv_system_id: str) -> JsonDict:
        return self._get_json(
            "/PvSystems/GetPvSystemProductionsAndEarnings",
            {"pvSystemId": pv_system_id},
        )

    def get_chart_new(
        self,
        pv_system_id: str,
        *,
        year: int,
        month: int,
        day: int,
        interval: str = "day",
        view: str = "production",
    ) -> JsonDict:
        return self._get_json(
            "/Chart/GetChartNew",
            {
                "pvSystemId": pv_system_id,
                "year": str(year),
                "month": str(month),
                "day": str(day),
                "interval": interval,
                "view": view,
            },
        )

    def get_widget_chart(self, pv_system_id: str) -> JsonDict:
        return self._get_json("/Chart/GetWidgetChart", {"PvSystemId": pv_system_id})

    def get_analysis_chart(
        self,
        pv_system_id: str,
        *,
        year: int,
        month: int,
        day: int,
        interval: str = "month",
        channels: str | None = None,
        devices: list[str] | tuple[str, ...] | None = None,
        compare_view: bool = False,
        kwhkwp_view: bool = False,
    ) -> JsonDict:
        params: QueryParams = {
            "pvSystemId": pv_system_id,
            "year": year,
            "month": month,
            "day": day,
            "interval": interval,
            "compareView": str(compare_view).lower(),
            "kwhkwpView": str(kwhkwp_view).lower(),
        }
        if channels:
            params["channels"] = channels
        if devices:
            params["devices"] = list(devices)
        return self._get_json("/Chart/GetAnalysisChart", params)

    def get_default_pv_system_id(self) -> str | None:
        systems = self.get_pv_systems_for_list_view().get("data", [])
        if not systems:
            return None
        return systems[0].get("PvSystemId")

    def get_pv_system_by_name(self, name: str) -> JsonDict | None:
        systems = self.get_pv_systems_for_list_view().get("data", [])
        for system in systems:
            if system.get("PvSystemName") == name:
                return system
        return None

    def _get_json(self, path: str, params: QueryParams | None = None) -> Any:
        params = params or {}
        if self.capture_dir and self.prefer_capture:
            replay = self._replay_json("GET", path, params)
            if replay is not None:
                return replay

        response = self._open_text(
            "GET",
            self._build_url(path, params),
            headers={
                "accept": "application/json, text/javascript, */*; q=0.01",
                "x-requested-with": "XMLHttpRequest",
            },
        )
        return json.loads(response.text)

    def _build_url(self, path: str, params: QueryParams) -> str:
        base = urljoin(f"{self.base_url}/", path.lstrip("/"))
        if not params:
            return base
        items: list[tuple[str, str]] = []
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                for entry in value:
                    items.append((key, str(entry)))
            else:
                items.append((key, str(value)))
        return f"{base}?{urlencode(items)}"

    def _replay_json(self, method: str, path: str, params: QueryParams) -> Any | None:
        key = ReplayKey(
            method=method.upper(),
            path=path,
            params=self._normalize_params(params),
        )
        payload = self._replay_index.get(key)
        if payload is None:
            return None
        response_text = payload.get("response", {}).get("text", "")
        return json.loads(response_text)

    def _open_text(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponseData:
        encoded_data = None
        if data is not None:
            encoded_data = urlencode(data).encode("utf-8")
        merged_headers = {
            "user-agent": "Web-API-Builder/1.0",
            **(headers or {}),
        }
        request = Request(url, data=encoded_data, headers=merged_headers, method=method.upper())
        with self._opener.open(request, timeout=30) as response:
            return HttpResponseData(
                url=response.geturl(),
                status=getattr(response, "status", response.getcode()),
                headers=dict(response.headers.items()),
                text=response.read().decode("utf-8", errors="replace"),
            )

    def _parse_form(self, response: HttpResponseData) -> tuple[str, dict[str, str]]:
        parser = _FormParser()
        parser.feed(response.text)
        if not parser.form_action:
            raise RuntimeError(f"Expected an HTML form in response from {response.url}")
        return urljoin(response.url, parser.form_action), dict(parser.inputs)

    def _looks_authenticated(self) -> bool:
        try:
            response = self._open_text(
                "GET",
                self._build_url("/PvSystems/GetPvSystemsForListView", {}),
                headers={
                    "accept": "application/json, text/javascript, */*; q=0.01",
                    "x-requested-with": "XMLHttpRequest",
                },
            )
            payload = json.loads(response.text)
        except Exception:
            return False
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)

    def _has_solarweb_cookie(self) -> bool:
        for cookie in self._cookie_jar:
            domain = (cookie.domain or "").lstrip(".").lower()
            if domain.endswith("solarweb.com"):
                return True
        return False

    def export_playwright_cookies(self) -> list[dict[str, Any]]:
        """Convert the authenticated cookie jar into Playwright cookie dicts."""

        cookies: list[dict[str, Any]] = []
        for cookie in self._cookie_jar:
            domain = cookie.domain or ""
            if not domain:
                continue
            item: dict[str, Any] = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
                "httpOnly": bool(cookie._rest.get("HttpOnly") or cookie._rest.get("httponly")),
                "secure": bool(cookie.secure),
            }
            if cookie.expires is not None:
                item["expires"] = float(cookie.expires)
            same_site = cookie._rest.get("SameSite") or cookie._rest.get("samesite")
            if same_site:
                same_site_text = str(same_site).strip().lower()
                mapping = {
                    "lax": "Lax",
                    "strict": "Strict",
                    "none": "None",
                }
                if same_site_text in mapping:
                    item["sameSite"] = mapping[same_site_text]
            cookies.append(item)
        return cookies

    @staticmethod
    def _normalize_params(params: QueryParams) -> tuple[tuple[str, str], ...]:
        normalized: list[tuple[str, str]] = []
        for key, value in params.items():
            if key == "_":
                continue
            if isinstance(value, (list, tuple)):
                normalized.extend((str(key), str(entry)) for entry in value)
            else:
                normalized.append((str(key), str(value)))
        return tuple(sorted(normalized))

    @classmethod
    def _build_replay_index(cls, capture_dir: Path) -> dict[ReplayKey, JsonDict]:
        index: dict[ReplayKey, JsonDict] = {}
        for path in sorted(capture_dir.glob("*.json")):
            if path.name.startswith("_capture_"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            normalized = payload.get("normalizedRequest") or payload.get("request") or {}
            url = normalized.get("url")
            method = str(normalized.get("method", "GET")).upper()
            if not url:
                continue
            parsed = urlparse(url)
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            key = ReplayKey(
                method=method,
                path=parsed.path,
                params=cls._normalize_params(params),
            )
            index[key] = payload
        return index
