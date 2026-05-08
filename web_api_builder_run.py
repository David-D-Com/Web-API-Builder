"""Run the Web API Builder GUI directly from the repo checkout.

This is a convenience launcher for local development on Windows so we can
start the Qt app from source without relying on an editable install first.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    builder_src = repo_root / "builder_app" / "src"
    sys.path.insert(0, str(builder_src))

    from web_api_builder.qt_app import main as qt_main

    return qt_main()


if __name__ == "__main__":
    raise SystemExit(main())
