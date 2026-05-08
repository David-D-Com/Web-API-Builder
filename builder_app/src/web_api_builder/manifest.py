"""Module manifest loading and lightweight repo introspection."""

from __future__ import annotations

import ast
import copy
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


APP_ROOT = Path(__file__).resolve().parents[3]
MODULES_ROOT = APP_ROOT / "modules"
HAR_ROOT = APP_ROOT / "har"


def slugify_module_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "new_module"


def client_class_name(slug: str) -> str:
    parts = [part for part in slug.split("_") if part]
    stem = "".join(part.capitalize() for part in parts) or "Module"
    return f"{stem}Client"


@dataclass
class ModuleManifest:
    """One module description loaded from `modules/*/module.yml`."""

    path: Path
    data: dict[str, Any]

    @property
    def module_id(self) -> str:
        return str(self.data.get("id") or self.path.parent.name)

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.module_id)

    @property
    def description(self) -> str:
        return str(self.data.get("description") or "")

    def resolve_path(self, relative_key: str) -> Path | None:
        value = self.data.get(relative_key)
        if not value:
            return None
        path = Path(str(value))
        if path.is_absolute():
            return path
        return APP_ROOT / path

    def save(self) -> None:
        self.path.write_text(
            yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


def load_manifests() -> list[ModuleManifest]:
    manifests: list[ModuleManifest] = []
    if not MODULES_ROOT.exists():
        return manifests
    for path in sorted(MODULES_ROOT.glob("*/module.yml")):
        if path.parent.name == "_template":
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        manifests.append(ModuleManifest(path=path, data=payload))
    return manifests


def create_module_from_template(module_id: str, name: str) -> ModuleManifest:
    template_path = MODULES_ROOT / "_template" / "module.yml"
    if not template_path.exists():
        raise FileNotFoundError(f"Template manifest not found: {template_path}")
    target_dir = MODULES_ROOT / module_id
    target_dir.mkdir(parents=True, exist_ok=False)
    payload = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        payload = {}
    payload = copy.deepcopy(payload)
    payload["id"] = module_id
    payload["name"] = name
    payload.setdefault("module", {})
    payload["module"]["manifest_version"] = 1
    slug = slugify_module_name(name)
    payload["module"]["package_path"] = f"python/src/{slug}"
    payload["module"]["client_file"] = f"python/src/{slug}/client.py"
    payload["module"]["client_class"] = client_class_name(slug)
    payload["module"]["processed_capture_dir"] = f"captures_processed/{module_id}"
    payload.setdefault("commands", {})
    payload["commands"]["run_tests"] = payload["commands"].get("run_tests") or f"python .\\tests\\{slug}_smoke.py"
    target_path = target_dir / "module.yml"
    target_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    create_module_scaffold(module_id=module_id, module_name=name, payload=payload)
    return ModuleManifest(path=target_path, data=payload)


def create_module_scaffold(*, module_id: str, module_name: str, payload: dict[str, Any]) -> None:
    module_data = payload.setdefault("module", {})
    slug = slugify_module_name(module_name)
    package_path = APP_ROOT / str(module_data.get("package_path") or f"python/src/{slug}")
    client_file = APP_ROOT / str(module_data.get("client_file") or f"python/src/{slug}/client.py")
    client_class = str(module_data.get("client_class") or client_class_name(slug))
    tests_dir = APP_ROOT / "tests"
    test_file = tests_dir / f"{slug}_smoke.py"

    package_path.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    init_path = package_path / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            f'"""Client package for {module_name}."""\n\nfrom .client import {client_class}\n\n__all__ = ["{client_class}"]\n',
            encoding="utf-8",
        )

    if not client_file.exists():
        client_file.write_text(
            "\n".join(
                [
                    f'"""Starter client for {module_name}."""',
                    "",
                    "from __future__ import annotations",
                    "",
                    "",
                    f"class {client_class}:",
                    '    """Placeholder browser-derived API client."""',
                    "",
                    "    def __init__(self, base_url: str = \"\") -> None:",
                    "        self.base_url = base_url.rstrip(\"/\")",
                    "",
                    "    def healthcheck(self) -> dict[str, str]:",
                    '        """Simple placeholder so endpoint discovery has something to show."""',
                    '        return {"status": "ok", "base_url": self.base_url}',
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    if not test_file.exists():
        test_file.write_text(
            "\n".join(
                [
                    f'"""Smoke runner for the {module_name} scaffold."""',
                    "",
                    "from __future__ import annotations",
                    "",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "",
                    "def main() -> int:",
                    "    repo_root = Path(__file__).resolve().parents[1]",
                    '    package_src = repo_root / "python" / "src"',
                    "    sys.path.insert(0, str(package_src))",
                    f'    from {slug} import {client_class}',
                    "",
                    '    client = ' + f'{client_class}(base_url="")',
                    "    print(client.healthcheck())",
                    "    return 0",
                    "",
                    "",
                    'if __name__ == "__main__":',
                    "    raise SystemExit(main())",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def delete_module(manifest: ModuleManifest) -> None:
    shutil.rmtree(manifest.path.parent)


def next_blank_module_id() -> str:
    index = 1
    while True:
        module_id = f"new_module_{index}"
        if not (MODULES_ROOT / module_id).exists():
            return module_id
        index += 1


def is_blank_module(manifest: ModuleManifest) -> bool:
    return manifest.module_id.startswith("new_module_")


def infer_client_methods(client_file: Path, client_class: str) -> list[str]:
    """Return public method names from the configured client class."""
    if not client_file.exists():
        return []
    try:
        tree = ast.parse(client_file.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    methods: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == client_class:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    methods.append(item.name)
            break
    return methods


def load_capture_summary(processed_capture_dir: Path) -> list[dict[str, Any]]:
    """Load processed capture summaries for one module."""
    if not processed_capture_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for summary_path in sorted(processed_capture_dir.glob("*/capture_summary.json")):
        try:
            payload = yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(payload, dict):
            payload["_summary_path"] = str(summary_path)
            summaries.append(payload)
    return summaries


def module_capture_root(module_id: str, base_root: Path | None = None) -> Path:
    return (base_root or HAR_ROOT) / module_id


def load_raw_capture_sessions(module_id: str | None = None, base_root: Path | None = None) -> list[Path]:
    root = module_capture_root(module_id, base_root=base_root) if module_id else (base_root or HAR_ROOT)
    if not root.exists():
        return []
    return sorted(root.glob("solis-json-capture-*"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_raw_capture_entries(session_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not session_dir.exists():
        return entries
    for path in sorted(session_dir.glob("*.json")):
        if path.name.startswith("_capture_"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        normalized_request = payload.get("normalizedRequest", {})
        response = payload.get("response", {})
        entries.append(
            {
                "path": str(path),
                "name": path.name,
                "method": normalized_request.get("method") or payload.get("request", {}).get("method", ""),
                "url": normalized_request.get("url") or payload.get("request", {}).get("url", ""),
                "status": response.get("status", ""),
                "content_type": response.get("contentType", ""),
                "occurrence_count": payload.get("occurrenceCount", 1),
            }
        )
    return entries


def set_capture_enabled(session_dir: Path, enabled: bool) -> None:
    control_path = session_dir / "_capture_control.json"
    control_path.write_text(
        json.dumps({"enabled": enabled}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def capture_enabled(session_dir: Path) -> bool:
    control_path = session_dir / "_capture_control.json"
    if not control_path.exists():
        return True
    try:
        payload = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(payload.get("enabled", True))
