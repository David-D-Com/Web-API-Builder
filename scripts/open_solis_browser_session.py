"""Open a browser from an authenticated API session and optionally capture responses.

This script:
1. Loads credentials from Windows Credential Manager on Windows, or env vars.
2. Logs into SolisCloud through the Python web API client.
3. Copies cookies and key localStorage values into a Playwright browser context.
4. Opens the SolisCloud web app using that hydrated state.
5. Optionally captures matching responses continuously, with deduping support.

Usage:
    python scripts/open_solis_browser_session.py
    python scripts/open_solis_browser_session.py --headless
    python scripts/open_solis_browser_session.py --capture-json
    python scripts/open_solis_browser_session.py --capture-json --capture-url-contains /api/
    python scripts/open_solis_browser_session.py --capture-json --capture-mode last
    python scripts/open_solis_browser_session.py --station-id 1298491919450216523
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PACKAGE_SRC = Path(__file__).resolve().parent.parent / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from soliscloud_web_api import SolisSession, SolisWebApiClient, SolisWebApiError


KEYRING_SERVICE = "soliscloud_web_api"
KEYRING_USERNAME_KEY = "__solis_username__"
BASE_URL = "https://www.soliscloud.com"
APP_URL = f"{BASE_URL}/overview/plantStation"
HAR_DIR = Path(__file__).resolve().parent.parent / "har"


def build_app_url(*, station_id: str | None = None) -> str:
    if station_id:
        return f"{BASE_URL}/station/stationDetails/generalSituation/{station_id}"
    return APP_URL


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
        return SolisSession.from_credentials(username, password)
    return SolisSession.from_env()


def cookiejar_to_playwright_cookies(client: SolisWebApiClient) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for cookie in client.cookie_jar:
        item: dict[str, Any] = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": bool(cookie.secure),
            "httpOnly": False,
        }
        if cookie.expires is not None:
            item["expires"] = float(cookie.expires)
        cookies.append(item)
    return cookies


def build_local_storage_state(client: SolisWebApiClient, profile_payload: dict[str, Any]) -> dict[str, str]:
    return {
        "lang": "2",
        "headerDeviceId": client.session.device_id,
        "token": client.session.token,
        "userInfo": json.dumps(profile_payload.get("data", {}), ensure_ascii=False),
    }


def build_capture_session_dir(prefix: str = "solis-json-capture", root: Path | None = None) -> Path:
    base_dir = root or HAR_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base_dir / f"{prefix}-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_capture_control(capture_dir: Path, *, enabled: bool) -> Path:
    control_path = capture_dir / "_capture_control.json"
    control_path.write_text(
        json.dumps({"enabled": enabled}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return control_path


def capture_enabled(capture_dir: Path) -> bool:
    control_path = capture_dir / "_capture_control.json"
    if not control_path.exists():
        return True
    try:
        payload = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(payload.get("enabled", True))


def _safe_slug(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not slug:
        slug = "response"
    return slug[:max_len]


def _response_text(response: Any) -> tuple[str | None, int]:
    try:
        body = response.body()
    except Exception:
        return None, 0
    size = len(body)
    if not body:
        return "", 0
    try:
        return body.decode("utf-8", errors="replace"), size
    except Exception:
        return None, size


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _normalize_request_body(post_data: str | None) -> Any:
    if not post_data:
        return None
    try:
        payload = json.loads(post_data)
    except json.JSONDecodeError:
        return post_data
    if isinstance(payload, dict):
        for key in ("localTime", "localTimeZone", "language"):
            payload.pop(key, None)
    return payload


def _request_fingerprint(request: Any) -> tuple[str, dict[str, Any]]:
    normalized = {
        "method": request.method,
        "url": _normalize_url(request.url),
        "postData": _normalize_request_body(request.post_data),
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
    return digest, normalized


def _matches_capture_filters(
    response: Any,
    *,
    capture_json: bool,
    capture_content_kinds: list[str],
    capture_url_contains: list[str],
    capture_domain_contains: list[str],
) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    effective_kinds = [kind.lower() for kind in capture_content_kinds if kind]
    if capture_json and "json" not in effective_kinds:
        effective_kinds.append("json")
    if effective_kinds and "all" not in effective_kinds:
        matched = False
        if "json" in effective_kinds and "json" in content_type:
            matched = True
        if "html" in effective_kinds and "html" in content_type:
            matched = True
        if "js" in effective_kinds and ("javascript" in content_type or "ecmascript" in content_type):
            matched = True
        if "text" in effective_kinds and content_type.startswith("text/") and "html" not in content_type:
            matched = True
        if "other" in effective_kinds:
            known = (
                "json" in content_type
                or "html" in content_type
                or "javascript" in content_type
                or "ecmascript" in content_type
                or content_type.startswith("text/")
            )
            if not known:
                matched = True
        if not matched:
            return False
    elif capture_json and "json" not in content_type:
        return False
    url = response.url
    if capture_url_contains and not any(token in url for token in capture_url_contains):
        return False
    if capture_domain_contains:
        host = urlsplit(url).netloc.lower()
        if not any(token.lower() in host for token in capture_domain_contains):
            return False
    return True


def install_response_capture(
    context: Any,
    *,
    capture_dir: Path,
    capture_json: bool,
    capture_content_kinds: list[str],
    capture_url_contains: list[str],
    capture_domain_contains: list[str],
    capture_mode: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "count": 0,
        "unique_count": 0,
        "duplicate_count": 0,
        "capture_dir": str(capture_dir),
        "capture_mode": capture_mode,
        "entries": {},
    }
    write_capture_control(capture_dir, enabled=True)

    def on_response(response: Any) -> None:
        if not capture_enabled(capture_dir):
            return
        if not _matches_capture_filters(
            response,
            capture_json=capture_json,
            capture_content_kinds=capture_content_kinds,
            capture_url_contains=capture_url_contains,
            capture_domain_contains=capture_domain_contains,
        ):
            return

        state["count"] += 1
        request = response.request
        response_text, response_size = _response_text(response)
        fingerprint, normalized_request = _request_fingerprint(request)
        parsed = re.sub(r"^https?://", "", _normalize_url(response.url)).replace("/", "_")

        existing = state["entries"].get(fingerprint)
        occurrence_count = 1
        if existing:
            state["duplicate_count"] += 1
            occurrence_count = int(existing["occurrenceCount"]) + 1
        else:
            state["unique_count"] += 1

        if capture_mode == "all":
            filename = f"{state['count']:04d}-{_safe_slug(parsed)}.json"
        else:
            filename = f"{_safe_slug(parsed)}--{fingerprint}.json"
        output_path = capture_dir / filename

        payload = {
            "capturedAt": datetime.utcnow().isoformat() + "Z",
            "firstCapturedAt": (
                existing.get("firstCapturedAt", existing.get("capturedAt"))
                if existing
                else None
            ),
            "lastCapturedAt": datetime.utcnow().isoformat() + "Z",
            "requestFingerprint": fingerprint,
            "normalizedRequest": normalized_request,
            "occurrenceCount": occurrence_count,
            "request": {
                "method": request.method,
                "url": request.url,
                "headers": request.headers,
                "postData": request.post_data,
            },
            "response": {
                "status": response.status,
                "statusText": response.status_text,
                "headers": response.headers,
                "contentType": response.headers.get("content-type", ""),
                "size": response_size,
                "text": response_text,
            },
        }
        if payload["firstCapturedAt"] is None:
            payload["firstCapturedAt"] = payload["capturedAt"]
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        state["entries"][fingerprint] = {
            "filename": filename,
            "url": request.url,
            "method": request.method,
            "occurrenceCount": occurrence_count,
            "firstCapturedAt": payload["firstCapturedAt"],
            "lastCapturedAt": payload["lastCapturedAt"],
        }
        if existing and capture_mode == "last":
            print(f"Updated: {output_path.name} (occurrence {occurrence_count})")
        else:
            print(f"Captured: {output_path.name}")

    context.on("response", on_response)
    return state


def write_capture_summary(capture_dir: Path, capture_state: dict[str, Any]) -> None:
    summary = {
        "captureMode": capture_state["capture_mode"],
        "matchedResponses": capture_state["count"],
        "uniqueRequests": capture_state["unique_count"],
        "duplicateResponses": capture_state["duplicate_count"],
        "entries": sorted(
            capture_state["entries"].values(),
            key=lambda item: (item["filename"], item["method"], item["url"]),
        ),
    }
    summary_path = capture_dir / "_capture_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def open_browser_from_client(
    client: SolisWebApiClient,
    *,
    headless: bool = False,
    timeout_ms: int = 30000,
    capture_json: bool = False,
    capture_content_kinds: list[str] | None = None,
    capture_url_contains: list[str] | None = None,
    capture_domain_contains: list[str] | None = None,
    capture_mode: str = "last",
    station_id: str | None = None,
    app_url: str | None = None,
    capture_root: Path | None = None,
    start_capture_paused: bool = False,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SolisWebApiError(
            "Playwright is not installed. Run `py -m pip install playwright` "
            "and `py -m playwright install chromium`."
        ) from exc

    capture_url_contains = capture_url_contains or []
    capture_content_kinds = capture_content_kinds or []
    capture_domain_contains = capture_domain_contains or []
    login_payload = client.login()
    profile_payload = client.profile()
    cookies = cookiejar_to_playwright_cookies(client)
    local_storage = build_local_storage_state(client, profile_payload)
    capture_dir: Path | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(no_viewport=True)
        if cookies:
            context.add_cookies(cookies)

        storage_json = json.dumps(local_storage, ensure_ascii=False)
        context.add_init_script(
            f"""
            (() => {{
              const storage = {storage_json};
              for (const [key, value] of Object.entries(storage)) {{
                window.localStorage.setItem(key, value);
              }}
            }})();
            """
        )

        capture_state: dict[str, Any] | None = None
        if capture_json or capture_content_kinds or capture_url_contains or capture_domain_contains:
            capture_dir = build_capture_session_dir(root=capture_root)
            capture_state = install_response_capture(
                context,
                capture_dir=capture_dir,
                capture_json=capture_json,
                capture_content_kinds=capture_content_kinds,
                capture_url_contains=capture_url_contains,
                capture_domain_contains=capture_domain_contains,
                capture_mode=capture_mode,
            )
            if start_capture_paused:
                write_capture_control(capture_dir, enabled=False)

        page = context.new_page()

        try:
            page.goto(
                app_url or build_app_url(station_id=station_id),
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        result = {
            "login_success": bool(login_payload.get("success")),
            "profile_success": bool(profile_payload.get("success")),
            "url": page.url,
            "title": page.title(),
            "cookies_loaded": len(cookies),
            "local_storage_keys": sorted(local_storage),
            "token_present_in_page": page.evaluate("() => localStorage.getItem('token') !== null"),
        }
        if capture_dir:
            result["capture_dir"] = str(capture_dir)
            result["capture_count"] = capture_state["count"] if capture_state else 0
            result["capture_unique_count"] = capture_state["unique_count"] if capture_state else 0
            result["capture_duplicate_count"] = (
                capture_state["duplicate_count"] if capture_state else 0
            )

        if headless:
            if capture_dir and capture_state:
                write_capture_summary(capture_dir, capture_state)
            result["body_text_snippet"] = page.locator("body").first.inner_text()[:500]
            context.close()
            browser.close()
            return result

        print(json.dumps(result, indent=2, ensure_ascii=False))
        if capture_dir:
            print(f"CAPTURE_DIR={capture_dir}")
            print(f"Continuous capture active: {capture_dir}")
            if capture_json:
                print("Filter: JSON responses only")
            if capture_content_kinds:
                print(f"Content kinds: {capture_content_kinds}")
            if capture_url_contains:
                print(f"URL filters: {capture_url_contains}")
            if capture_domain_contains:
                print(f"Domain filters: {capture_domain_contains}")
            print(f"Capture mode: {capture_mode}")
            if start_capture_paused:
                print("Capture starts paused.")
        print("Browser is open. Close it manually when finished.")
        page.wait_for_event("close", timeout=0)
        if capture_dir and capture_state:
            write_capture_summary(capture_dir, capture_state)
        context.close()
        browser.close()
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser invisibly and print a summary instead of leaving a window open.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation timeout in milliseconds.",
    )
    parser.add_argument(
        "--capture-json",
        action="store_true",
        help="Continuously capture JSON responses into one file per response.",
    )
    parser.add_argument(
        "--capture-content-kind",
        action="append",
        default=[],
        choices=("all", "json", "html", "js", "text", "other"),
        help="Optional response content categories to capture. Can be passed multiple times.",
    )
    parser.add_argument(
        "--capture-url-contains",
        action="append",
        default=[],
        help="Optional substring filter for response URLs. Can be passed multiple times.",
    )
    parser.add_argument(
        "--capture-domain-contains",
        action="append",
        default=[],
        help="Optional substring filter for response hostnames. Can be passed multiple times.",
    )
    parser.add_argument(
        "--capture-mode",
        choices=("all", "last"),
        default="last",
        help="Keep every matching response or only the latest copy of each unique request.",
    )
    parser.add_argument(
        "--station-id",
        help="Open directly to a station details page instead of the top-level station overview.",
    )
    parser.add_argument(
        "--app-url",
        help="Open a specific absolute app URL instead of the default overview/station route.",
    )
    parser.add_argument(
        "--capture-root",
        help="Optional directory under which this browser session should create its capture folder.",
    )
    parser.add_argument(
        "--start-capture-paused",
        action="store_true",
        help="Create the capture session immediately but leave it disabled until resumed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = SolisWebApiClient(build_session())
        result = open_browser_from_client(
            client,
            headless=args.headless,
            timeout_ms=args.timeout_ms,
            capture_json=args.capture_json,
            capture_content_kinds=args.capture_content_kind,
            capture_url_contains=args.capture_url_contains,
            capture_domain_contains=args.capture_domain_contains,
            capture_mode=args.capture_mode,
            station_id=args.station_id,
            app_url=args.app_url,
            capture_root=Path(args.capture_root) if args.capture_root else None,
            start_capture_paused=args.start_capture_paused,
        )
    except SolisWebApiError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.headless:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
