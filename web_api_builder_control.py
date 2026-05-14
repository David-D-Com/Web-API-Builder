"""Send simple JSON control commands to the running Web API Builder app.

This talks to the real Qt app through a small file-based control channel in
``C:/tmp/web_api_builder_control`` so we can drive the actual UI workflow from
the command line during testing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path


CONTROL_ROOT = Path("C:/tmp") / "web_api_builder_control"
COMMANDS_DIR = CONTROL_ROOT / "commands"
RESPONSES_DIR = CONTROL_ROOT / "responses"


def send_command(command: str, args: dict[str, object], timeout: float) -> dict[str, object]:
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    command_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex}"
    command_path = COMMANDS_DIR / f"{command_id}.json"
    response_path = RESPONSES_DIR / f"{command_id}.json"
    payload = {"command": command, "args": args}
    command_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if response_path.exists():
            try:
                response = json.loads(response_path.read_text(encoding="utf-8"))
            finally:
                response_path.unlink(missing_ok=True)
            return response
        time.sleep(0.15)
    raise TimeoutError(f"Timed out waiting for response to command '{command}'.")


def print_json(data: dict[str, object]) -> int:
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the running Web API Builder GUI.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Seconds to wait for a response")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("get-state")

    p = sub.add_parser("switch-tab")
    p.add_argument("name")

    p = sub.add_parser("select-module")
    p.add_argument("module_id")

    p = sub.add_parser("select-process-session")
    p.add_argument("session")

    p = sub.add_parser("select-revise-session")
    p.add_argument("session")

    p = sub.add_parser("select-prompt")
    p.add_argument("name")

    p = sub.add_parser("set-model")
    p.add_argument("model")

    p = sub.add_parser("open-page-route")
    p.add_argument("page")

    p = sub.add_parser("press-button")
    p.add_argument("button_id")

    args = parser.parse_args()
    if args.cmd == "get-state":
        response = send_command("get_state", {}, args.timeout)
    elif args.cmd == "switch-tab":
        response = send_command("switch_tab", {"name": args.name}, args.timeout)
    elif args.cmd == "select-module":
        response = send_command("select_module", {"module_id": args.module_id}, args.timeout)
    elif args.cmd == "select-process-session":
        response = send_command("select_process_session", {"session": args.session}, args.timeout)
    elif args.cmd == "select-revise-session":
        response = send_command("select_revise_session", {"session": args.session}, args.timeout)
    elif args.cmd == "select-prompt":
        response = send_command("select_prompt", {"name": args.name}, args.timeout)
    elif args.cmd == "set-model":
        response = send_command("set_model", {"model": args.model}, args.timeout)
    elif args.cmd == "open-page-route":
        response = send_command("open_page_route", {"page": args.page}, args.timeout)
    elif args.cmd == "press-button":
        response = send_command("press_button", {"button_id": args.button_id}, args.timeout)
    else:
        raise SystemExit(f"Unknown command: {args.cmd}")
    return print_json(response)


if __name__ == "__main__":
    raise SystemExit(main())
