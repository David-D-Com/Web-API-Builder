"""Normalize a raw Solis JSON capture folder into cleaner JSON/CSV artifacts.

This script reads the per-request JSON files written by the browser capture
helper, extracts the useful request/response payloads, groups them by endpoint,
and optionally deletes the raw capture folder afterward.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
HAR_ROOT = ROOT / "har"
PROCESSED_ROOT = ROOT / "captures_processed"


def find_latest_capture_dir() -> Path:
    candidates = sorted(HAR_ROOT.glob("solis-json-capture-*"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError("No capture folders found under har/.")
    return candidates[-1]


def safe_slug(text: str) -> str:
    slug = []
    for char in text:
        if char.isalnum():
            slug.append(char.lower())
        else:
            slug.append("_")
    return "".join(slug).strip("_") or "root"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json_maybe(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def endpoint_name(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return path.replace("/api/", "", 1).strip("/") or "root"


def process_capture_dir(capture_dir: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    endpoints_dir = output_root / "endpoints"
    endpoints_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in sorted(capture_dir.glob("*.json")):
        if path.name == "_capture_summary.json":
            continue
        payload = load_json(path)
        normalized_request = payload.get("normalizedRequest", {})
        request = payload.get("request", {})
        response = payload.get("response", {})
        url = str(normalized_request.get("url") or request.get("url") or "")
        endpoint = endpoint_name(url)
        request_body = parse_json_maybe(request.get("postData"))
        response_body = parse_json_maybe(response.get("text"))

        record = {
            "source_file": path.name,
            "endpoint": endpoint,
            "method": normalized_request.get("method") or request.get("method"),
            "url": url,
            "captured_at": payload.get("capturedAt"),
            "occurrence_count": payload.get("occurrenceCount", 1),
            "request_fingerprint": payload.get("requestFingerprint"),
            "request_body": request_body,
            "response_status": response.get("status"),
            "response_content_type": response.get("contentType"),
            "response_body": response_body,
        }
        rows.append(record)
        grouped[endpoint].append(record)

    for endpoint, records in grouped.items():
        endpoint_path = endpoints_dir / f"{safe_slug(endpoint)}.json"
        endpoint_path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    summary = {
        "capture_dir": str(capture_dir),
        "processed_dir": str(output_root),
        "file_count": len(rows),
        "endpoint_count": len(grouped),
        "endpoints": [
            {
                "endpoint": endpoint,
                "request_count": len(records),
                "methods": sorted({str(record["method"]) for record in records}),
                "files": [record["source_file"] for record in records],
            }
            for endpoint, records in sorted(grouped.items())
        ],
    }
    (output_root / "capture_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with (output_root / "endpoint_index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_file",
                "endpoint",
                "method",
                "url",
                "captured_at",
                "occurrence_count",
                "request_fingerprint",
                "response_status",
                "response_content_type",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source_file": row["source_file"],
                    "endpoint": row["endpoint"],
                    "method": row["method"],
                    "url": row["url"],
                    "captured_at": row["captured_at"],
                    "occurrence_count": row["occurrence_count"],
                    "request_fingerprint": row["request_fingerprint"],
                    "response_status": row["response_status"],
                    "response_content_type": row["response_content_type"],
                }
            )

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process a raw Solis capture folder.")
    parser.add_argument(
        "--capture-dir",
        help="Raw capture directory under har/. Defaults to the newest solis-json-capture-* folder.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to captures_processed/<capture-dir-name>.",
    )
    parser.add_argument(
        "--delete-raw",
        action="store_true",
        help="Delete the raw capture directory after successful processing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    capture_dir = Path(args.capture_dir) if args.capture_dir else find_latest_capture_dir()
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else PROCESSED_ROOT / capture_dir.name
    )

    summary = process_capture_dir(capture_dir, output_dir)
    if args.delete_raw:
        shutil.rmtree(capture_dir)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
