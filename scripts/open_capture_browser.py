"""Open a generic browser session and optionally capture matching responses.

This helper is module-agnostic. It simply launches Chromium at the provided URL
and writes one JSON file per captured response into a session folder.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


HAR_DIR = Path(__file__).resolve().parent.parent / "har"
ACTIVE_CAPTURE_SESSION_FILE = "_active_capture_session.json"
LOCAL_SECRETS_ENV = Path(__file__).resolve().parent.parent / ".local-secrets" / ".env"

MODULE_KEYRING_MAP = {
    "fronius": ("web-api-builder/fronius", "__fronius_username__"),
    "soliscloud": ("soliscloud_web_api", "__solis_username__"),
}

MODULE_ENV_KEYS = {
    "fronius": ("FRONIUS_USERNAME", "FRONIUS_PASSWORD"),
    "soliscloud": ("SOLIS_USERNAME", "SOLIS_PASSWORD"),
}


def _load_local_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not LOCAL_SECRETS_ENV.exists():
        return values
    for raw_line in LOCAL_SECRETS_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        values[key] = value
    return values


def build_capture_session_dir(prefix: str = "", root: Path | None = None) -> Path:
    base_dir = root or HAR_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_name = f"{prefix}-{stamp}" if prefix else stamp
    path = base_dir / folder_name
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


def active_capture_session(capture_root: Path) -> Path | None:
    state_path = capture_root / ACTIVE_CAPTURE_SESSION_FILE
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    session_value = str(payload.get("active_session") or "").strip()
    if not session_value:
        return None
    session_path = Path(session_value)
    if session_path.exists():
        return session_path
    return None


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
    capture_root: Path,
    capture_json: bool,
    capture_content_kinds: list[str],
    capture_url_contains: list[str],
    capture_domain_contains: list[str],
    capture_mode: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "count": 0,
        "capture_root": str(capture_root),
        "capture_mode": capture_mode,
        "sessions": {},
    }

    def on_response(response: Any) -> None:
        capture_dir = active_capture_session(capture_root)
        if capture_dir is None or not capture_dir.exists():
            return
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
        session_state = state["sessions"].setdefault(
            str(capture_dir),
            {
                "count": 0,
                "unique_count": 0,
                "duplicate_count": 0,
                "capture_mode": capture_mode,
                "entries": {},
            },
        )
        session_state["count"] += 1
        request = response.request
        response_text, response_size = _response_text(response)
        fingerprint, normalized_request = _request_fingerprint(request)
        parsed = re.sub(r"^https?://", "", _normalize_url(response.url)).replace("/", "_")

        existing = session_state["entries"].get(fingerprint)
        occurrence_count = 1
        if existing:
            session_state["duplicate_count"] += 1
            occurrence_count = int(existing["occurrenceCount"]) + 1
        else:
            session_state["unique_count"] += 1

        if capture_mode == "all":
            filename = f"{session_state['count']:04d}-{_safe_slug(parsed)}.json"
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
        session_state["entries"][fingerprint] = {
            "filename": filename,
            "url": request.url,
            "method": request.method,
            "occurrenceCount": occurrence_count,
            "firstCapturedAt": payload["firstCapturedAt"],
            "lastCapturedAt": payload["lastCapturedAt"],
        }
        write_capture_summary(capture_dir, session_state)
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


def _load_module_credentials(module_id: str | None) -> tuple[str | None, str | None]:
    local_env = _load_local_env_values()
    if not module_id:
        return (
            os.getenv("WEB_API_BUILDER_USERNAME") or local_env.get("WEB_API_BUILDER_USERNAME"),
            os.getenv("WEB_API_BUILDER_PASSWORD") or local_env.get("WEB_API_BUILDER_PASSWORD"),
        )
    env_prefix = re.sub(r"[^A-Za-z0-9]+", "_", module_id).upper()
    username = (
        os.getenv(f"{env_prefix}_USERNAME")
        or local_env.get(f"{env_prefix}_USERNAME")
        or os.getenv("WEB_API_BUILDER_USERNAME")
        or local_env.get("WEB_API_BUILDER_USERNAME")
    )
    password = (
        os.getenv(f"{env_prefix}_PASSWORD")
        or local_env.get(f"{env_prefix}_PASSWORD")
        or os.getenv("WEB_API_BUILDER_PASSWORD")
        or local_env.get("WEB_API_BUILDER_PASSWORD")
    )
    if not (username and password):
        module_env_keys = MODULE_ENV_KEYS.get(module_id)
        if module_env_keys is not None:
            username_key, password_key = module_env_keys
            username = username or os.getenv(username_key) or local_env.get(username_key)
            password = password or os.getenv(password_key) or local_env.get(password_key)
    if username and password:
        return username, password

    if os.name == "nt":
        service_info = MODULE_KEYRING_MAP.get(module_id)
        if service_info is not None:
            service_name, username_key = service_info
            try:
                import keyring  # type: ignore
            except ImportError:
                keyring = None
            if keyring is not None:
                stored_username = keyring.get_password(service_name, username_key)
                if stored_username:
                    stored_password = keyring.get_password(service_name, stored_username)
                    if stored_password:
                        return stored_username, stored_password
    return username, password


def _load_client_instance(
    *,
    module_import: str | None,
    client_class: str | None,
    python_src_root: Path | None,
    base_url: str,
) -> Any | None:
    if not module_import or not client_class:
        return None
    if python_src_root is not None:
        src_text = str(python_src_root)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)
    module = importlib.import_module(module_import)
    client_type = getattr(module, client_class)
    return client_type(base_url=base_url)


def open_capture_browser(
    *,
    app_url: str,
    headless: bool = False,
    timeout_ms: int = 30000,
    capture_json: bool = False,
    capture_content_kinds: list[str] | None = None,
    capture_url_contains: list[str] | None = None,
    capture_domain_contains: list[str] | None = None,
    capture_mode: str = "last",
    capture_root: Path | None = None,
    start_capture_paused: bool = False,
    module_id: str | None = None,
    module_import: str | None = None,
    client_class: str | None = None,
    python_src_root: Path | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run `py -m pip install playwright` "
            "and `py -m playwright install chromium`."
        ) from exc

    capture_url_contains = capture_url_contains or []
    capture_content_kinds = capture_content_kinds or []
    capture_domain_contains = capture_domain_contains or []
    capture_root_path = capture_root or HAR_DIR

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(no_viewport=True)

        capture_state: dict[str, Any] | None = None
        if capture_json or capture_content_kinds or capture_url_contains or capture_domain_contains:
            capture_root_path.mkdir(parents=True, exist_ok=True)
            capture_state = install_response_capture(
                context,
                capture_root=capture_root_path,
                capture_json=capture_json,
                capture_content_kinds=capture_content_kinds,
                capture_url_contains=capture_url_contains,
                capture_domain_contains=capture_domain_contains,
                capture_mode=capture_mode,
            )

        prepared_context_with_client = False
        client = _load_client_instance(
            module_import=module_import,
            client_class=client_class,
            python_src_root=python_src_root,
            base_url=app_url,
        )
        username, password = _load_module_credentials(module_id)
        init_error: str | None = None
        if client is not None and hasattr(client, "initialize"):
            try:
                client.initialize(username=username, password=password)
                if hasattr(client, "export_playwright_cookies"):
                    cookies = client.export_playwright_cookies()
                    if cookies:
                        context.add_cookies(cookies)
                        prepared_context_with_client = True
            except TypeError:
                client.initialize()
            except Exception as exc:
                init_error = str(exc)
                if not hasattr(client, "initialize_browser_page"):
                    browser.close()
                    raise RuntimeError(
                        f"Module client initialization failed for '{module_id or module_import}': {exc}"
                    ) from exc

        page = context.new_page()
        handled_navigation = False
        if client is not None and hasattr(client, "initialize_browser_page") and not prepared_context_with_client:
            try:
                handled_navigation = bool(
                    client.initialize_browser_page(
                        page,
                        context=context,
                        target_url=app_url,
                        username=username,
                        password=password,
                    )
                )
            except Exception as exc:
                browser.close()
                raise RuntimeError(
                    f"Browser bootstrap failed for '{module_id or module_import}': {exc}"
                ) from exc
        try:
            if not handled_navigation:
                page.goto(app_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        result = {
            "url": page.url,
            "title": page.title(),
        }
        if prepared_context_with_client:
            result["session_bootstrap"] = "api_cookies"
        elif handled_navigation:
            result["session_bootstrap"] = "browser_flow"
        if init_error:
            result["initialize_warning"] = init_error
        active_dir = active_capture_session(capture_root_path)
        if active_dir:
            result["capture_dir"] = str(active_dir)
        if capture_state:
            result["capture_count"] = capture_state["count"] if capture_state else 0

        if headless:
            result["body_text_snippet"] = page.locator("body").first.inner_text()[:500]
            context.close()
            browser.close()
            return result

        print(json.dumps(result, indent=2, ensure_ascii=False))
        if active_dir:
            print(f"CAPTURE_DIR={active_dir}")
            print(f"Continuous capture active: {active_dir}")
            if capture_json:
                print("Filter: JSON responses only")
            if capture_content_kinds:
                print(f"Content kinds: {capture_content_kinds}")
            if capture_url_contains:
                print(f"URL filters: {capture_url_contains}")
            if capture_domain_contains:
                print(f"Domain filters: {capture_domain_contains}")
            print(f"Capture mode: {capture_mode}")
        print("Browser is open. Close it manually when finished.")
        page.wait_for_event("close", timeout=0)
        context.close()
        browser.close()
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True, help="Absolute URL to open in the browser.")
    parser.add_argument("--headless", action="store_true", help="Run headless and print a summary.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Navigation timeout in milliseconds.")
    parser.add_argument("--capture-json", action="store_true", help="Continuously capture JSON responses.")
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
    parser.add_argument("--capture-root", help="Optional directory under which to create the capture session.")
    parser.add_argument("--module-id", help="Optional module id used for credential lookup.")
    parser.add_argument("--module-import", help="Optional importable Python package name for the module client.")
    parser.add_argument("--client-class", help="Optional client class name to instantiate before opening the page.")
    parser.add_argument("--python-src-root", help="Optional python/src root to add to sys.path before importing the client.")
    parser.add_argument(
        "--start-capture-paused",
        action="store_true",
        help="Create the capture session immediately but leave it disabled until resumed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = open_capture_browser(
        app_url=args.app_url,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        capture_json=args.capture_json,
        capture_content_kinds=args.capture_content_kind,
        capture_url_contains=args.capture_url_contains,
        capture_domain_contains=args.capture_domain_contains,
        capture_mode=args.capture_mode,
        capture_root=Path(args.capture_root) if args.capture_root else None,
        start_capture_paused=args.start_capture_paused,
        module_id=args.module_id,
        module_import=args.module_import,
        client_class=args.client_class,
        python_src_root=Path(args.python_src_root) if args.python_src_root else None,
    )
    if args.headless:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
