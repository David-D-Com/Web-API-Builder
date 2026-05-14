"""Smoke runner for the New Module 1 scaffold."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_src = repo_root / "python" / "src"
    sys.path.insert(0, str(package_src))
    from new_module_1 import NewModule1Client

    client = NewModule1Client(base_url="")
    print(client.healthcheck())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
