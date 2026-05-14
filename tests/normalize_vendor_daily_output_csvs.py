"""Normalize vendor daily inverter CSV dumps to a shared schema."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Iterable

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "python" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from solar_data_normalization import NORMALIZED_DAILY_INVERTER_FIELDS, normalize_daily_inverter_row


def normalize_fronius_row(row: dict[str, str]) -> dict[str, str]:
    return normalize_daily_inverter_row("fronius", row)


def normalize_solis_row(row: dict[str, str]) -> dict[str, str]:
    return normalize_daily_inverter_row("solis", row)


def detect_provider(path: Path) -> str | None:
    name = path.name.lower()
    if name.startswith("fronius_"):
        return "fronius"
    if name.startswith("solis__"):
        return "solis"
    return None


def normalize_rows(provider: str, rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    normalizer = normalize_fronius_row if provider == "fronius" else normalize_solis_row
    normalized_rows = [normalizer(row) for row in rows]
    normalized_rows.sort(key=lambda item: (item.get("date", ""), item.get("site_id", ""), item.get("inverter_id", "")))
    return normalized_rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=NORMALIZED_DAILY_INVERTER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    dumps_dir = repo_root / "dumps"
    output_dir = dumps_dir / "normalized"

    written = 0
    for path in sorted(dumps_dir.glob("*.csv")):
        provider = detect_provider(path)
        if not provider:
            continue
        source_rows = read_csv_rows(path)
        normalized_rows = normalize_rows(provider, source_rows)
        output_path = output_dir / path.name
        write_csv_rows(output_path, normalized_rows)
        written += 1
        print(f"Normalized {path.name} -> {output_path.relative_to(repo_root)} ({len(normalized_rows)} rows)")

    print(f"Completed: {written} file(s) normalized into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
