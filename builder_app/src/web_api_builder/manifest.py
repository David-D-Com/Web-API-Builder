"""Module manifest loading and lightweight repo introspection."""

from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


APP_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_ROOT = APP_ROOT / "settings"
HAR_ROOT = APP_ROOT / "har"
PROMPT_LIBRARY_PATH = SETTINGS_ROOT / "prompt_templates.yml"

DEFAULT_PROMPT_LIBRARY: list[dict[str, str]] = [
    {
        "name": "Implement Captures Into Module",
        "text": """You are helping extend a Python API module from captured browser/API traffic.

You have been given:
1. A ZIP of the current project or current module
2. A folder of captured requests
   - This may be raw HAR files, HAR-derived JSON files, or one-file-per-request captures
3. Optionally, notes describing what user actions produced the captures

Your mission:
Read the existing project, inspect the captures, determine which calls are already implemented, and then implement the missing useful API calls into the Python module cleanly and consistently.

Context about the project shape:
- This project may contain:
  - a reusable Python module under something like `python/src/<module_name>/`
  - tests and smoke scripts under `tests/`
  - helper/browser tooling under `scripts/`
  - builder/workbench config under `settings/`
- Your main target is the reusable Python module, not the builder GUI, unless builder-related metadata or test hooks must also be updated
- Do not treat raw captures as production assets to keep in the module/package
- Do not bake credentials into code

What I want you to do:

Phase 1: Understand the existing project
1. Inspect the ZIP contents
2. Identify:
   - the main reusable client/module
   - the current auth/session/signing flow
   - existing endpoint methods
   - any caching layer
   - existing tests/smoke tests
   - any docs or usage files
3. Summarize the current module shape before changing anything

Phase 2: Analyze captures
1. Read the captured requests
2. Group them by endpoint/path
3. Ignore obvious junk/noise where appropriate:
   - static assets
   - maps/telemetry
   - unrelated third-party calls
   - duplicate polling calls unless they reveal something important
4. Prefer JSON/API requests unless another type is clearly relevant
5. Deduplicate repeated calls:
   - keep the latest/final meaningful duplicate when the request shape is effectively the same
6. For each useful endpoint, determine:
   - HTTP method
   - path
   - required headers that actually matter
   - request body/query params
   - whether the endpoint is already implemented
   - what Python method name would make sense

Phase 3: Compare captures vs existing implementation
Build a gap analysis:
- already implemented endpoints
- partially implemented endpoints
- missing endpoints worth adding
- endpoints that are too noisy/irrelevant to add

Phase 4: Implement/update the module
If an existing Python module already exists:
- update it in place
- reuse its transport/auth/session/caching helpers
- do not create a parallel duplicate client

If no real module exists yet:
- create a proper importable Python package
- include:
  - client module
  - auth/session handling
  - basic README/usage notes
  - smoke test entry point

Implementation rules:
- Add clean, parameterized client methods
- Prefer semantic method names over raw endpoint names
- Keep low-level request logic centralized
- Reuse existing auth/signing/session code
- Add concise comments/docstrings where behavior is not obvious
- Keep code system-agnostic unless a file is explicitly platform-specific
- Avoid overengineering
- Make the smallest clean change set that adds the missing support

Caching rules:
- If caching already exists, integrate the new endpoints into it
- Historical/stable endpoints should be cached
- Live/current-state endpoints can remain uncached or use the project’s existing policy
- Do not repeatedly hit the API for identical historical requests if the project already has a cache pattern

Filtering/normalization rules:
- If the module already trims or normalizes payloads, integrate new endpoints consistently
- Do not introduce a totally separate output shape unless necessary

Phase 5: Tests
Update or add tests.
Prefer:
- extending existing smoke/integration tests
- adding focused tests for new endpoint methods
- verifying:
  - endpoint call succeeds
  - expected response shape is returned
  - parameters map correctly
  - no obvious regressions are introduced

If the project already has helper scripts for live validation, keep them working.

Phase 6: Documentation
Update the relevant docs so a human can use the new methods.
At minimum:
- mention the new methods/endpoints
- show brief usage if appropriate
- keep docs aligned with the actual code

Required final output:
Return all of the following:

1. Existing coverage summary
- Which captured endpoints were already implemented

2. New implementation summary
- Which new methods/endpoints you added
- Method name -> HTTP method + endpoint path

3. Ignored/filtered capture summary
- Which captures you intentionally ignored
- Why they were ignored

4. Code changes
- Explain what files were changed and why

5. Test changes
- Explain what tests were added or updated

6. Assumptions / uncertainties
- Mention anything ambiguous in the captures or implementation

7. Not implemented
- Any useful endpoints you chose not to implement, and why

8. Endpoint inventory
Provide a short mapping like:
- `list_sites` -> `POST /api/station/list`
- `inverter_detail` -> `POST /api/inverter/detail`

Important behavioral guidance:
- Repeated requests that only differ by date/page/id usually belong in one parameterized method
- Do not blindly mirror every raw endpoint name into Python
- Prefer maintainability over raw completeness
- If a capture clearly belongs to a browser-only UI concern and not the reusable API, mention it but do not force it into the core module

If builder/workbench files are present:
- only update them if needed to keep the module discoverable/testable in the existing project flow
- the reusable Python module remains the primary target

Deliverable expectation:
I want a result that feels like a real maintainable Python API module update, not just a quick reverse-engineering dump.""",
    },
    {
        "name": "Implement Captures Into Module (Short)",
        "text": """Given the attached ZIP of the current module/repo and the attached batch of captured API requests, inspect the existing Python client, determine which endpoints are already implemented, then add the missing useful endpoints into the existing reusable Python module.

Requirements:
- update the existing module in place
- reuse existing auth/session/signing/caching logic
- deduplicate noisy/repeated captures
- ignore irrelevant third-party/static noise
- add clean parameterized client methods
- extend existing tests/smoke tests
- update docs if needed
- preserve historical caching behavior
- do not embed credentials
- do not keep raw HAR files in the module

Return:
- existing endpoints already covered
- newly added endpoints
- ignored captures and why
- code/test/doc changes
- assumptions/uncertainties
- method name -> HTTP method + endpoint path inventory""",
    },
]


def slugify_module_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "new_module"


def client_class_name(slug: str) -> str:
    parts = [part for part in slug.split("_") if part]
    stem = "".join(part.capitalize() for part in parts) or "Module"
    return f"{stem}Client"


@dataclass
class ModuleManifest:
    """One module description loaded from `settings/<module>.yml`."""

    path: Path
    data: dict[str, Any]

    @property
    def module_id(self) -> str:
        return str(self.data.get("id") or self.path.stem)

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
    if not SETTINGS_ROOT.exists():
        return manifests
    for path in sorted(SETTINGS_ROOT.glob("*.yml")):
        if path.stem == "_template":
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        manifests.append(ModuleManifest(path=path, data=payload))
    return manifests


def _normalize_prompt_library(payload: Any) -> list[dict[str, str]]:
    prompts = payload.get("prompts") if isinstance(payload, dict) else payload
    if not isinstance(prompts, list):
        prompts = []
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(prompts):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"Prompt {index + 1}").strip()
        description = str(item.get("description") or "")
        text = str(item.get("text") or "")
        normalized.append({"name": name, "description": description, "text": text})
    return normalized


def load_prompt_library() -> list[dict[str, str]]:
    SETTINGS_ROOT.mkdir(parents=True, exist_ok=True)
    if not PROMPT_LIBRARY_PATH.exists():
        save_prompt_library(DEFAULT_PROMPT_LIBRARY)
        return copy.deepcopy(DEFAULT_PROMPT_LIBRARY)
    payload = yaml.safe_load(PROMPT_LIBRARY_PATH.read_text(encoding="utf-8")) or {}
    prompts = _normalize_prompt_library(payload)
    if not prompts:
        prompts = copy.deepcopy(DEFAULT_PROMPT_LIBRARY)
        save_prompt_library(prompts)
    return prompts


def save_prompt_library(prompts: list[dict[str, str]]) -> None:
    SETTINGS_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"prompts": _normalize_prompt_library(prompts)}
    PROMPT_LIBRARY_PATH.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def next_module_id_for_name(name: str) -> str:
    base = slugify_module_name(name)
    if not (SETTINGS_ROOT / f"{base}.yml").exists():
        return base
    index = 2
    while True:
        candidate = f"{base}_{index}"
        if not (SETTINGS_ROOT / f"{candidate}.yml").exists():
            return candidate
        index += 1


def create_module_from_template(module_id: str, name: str) -> ModuleManifest:
    template_path = SETTINGS_ROOT / "_template.yml"
    if not template_path.exists():
        raise FileNotFoundError(f"Template manifest not found: {template_path}")
    SETTINGS_ROOT.mkdir(parents=True, exist_ok=True)
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
    browser = payload["module"].setdefault("browser", {})
    browser["base_url"] = ""
    capture = payload["module"].setdefault("capture", {})
    capture["url_contains"] = []
    capture["domain_contains"] = []
    capture["content_kinds"] = ["json"]
    capture["mode"] = "last"
    payload.setdefault("commands", {})
    payload["commands"]["run_tests"] = f"python .\\tests\\{slug}_smoke.py"
    payload["commands"]["open_browser"] = ""
    payload["commands"]["process_captures"] = ""
    payload["pages"] = [{"name": "Base", "route": "/"}]
    payload["actions"] = {}
    target_path = SETTINGS_ROOT / f"{module_id}.yml"
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
                    f"    def initialize(self, *, username: str | None = None, password: str | None = None) -> \"{client_class}\":",
                    '        """Standard entrypoint for auth/session setup before endpoint calls."""',
                    "        _ = (username, password)",
                    "        return self",
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
                    '    client = ' + f'{client_class}(base_url="").initialize()',
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
    manifest.path.unlink(missing_ok=True)


def rename_module(manifest: ModuleManifest, new_name: str) -> ModuleManifest:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Module name cannot be empty.")

    old_name = manifest.name
    old_id = manifest.module_id
    old_slug = slugify_module_name(old_name)
    new_slug = slugify_module_name(new_name)
    new_id = next_module_id_for_name(new_name) if slugify_module_name(old_id) != new_slug else old_id

    data = copy.deepcopy(manifest.data)
    data["name"] = new_name
    data["id"] = new_id
    module_data = data.setdefault("module", {})

    old_package_rel = str(module_data.get("package_path") or f"python/src/{old_slug}")
    old_client_rel = str(module_data.get("client_file") or f"python/src/{old_slug}/client.py")
    old_class = str(module_data.get("client_class") or client_class_name(old_slug))

    new_package_rel = f"python/src/{new_slug}"
    new_client_rel = f"{new_package_rel}/client.py"
    new_class = client_class_name(new_slug)

    old_package_path = APP_ROOT / old_package_rel
    new_package_path = APP_ROOT / new_package_rel
    old_test_path = APP_ROOT / "tests" / f"{old_slug}_smoke.py"
    new_test_path = APP_ROOT / "tests" / f"{new_slug}_smoke.py"
    old_processed_path = APP_ROOT / str(module_data.get("processed_capture_dir") or f"captures_processed/{old_id}")
    new_processed_rel = f"captures_processed/{new_id}"
    new_processed_path = APP_ROOT / new_processed_rel
    old_capture_path = HAR_ROOT / old_id
    new_capture_path = HAR_ROOT / new_id

    if old_package_path.exists() and old_package_path != new_package_path and not new_package_path.exists():
        new_package_path.parent.mkdir(parents=True, exist_ok=True)
        old_package_path.rename(new_package_path)
    if old_test_path.exists() and old_test_path != new_test_path and not new_test_path.exists():
        new_test_path.parent.mkdir(parents=True, exist_ok=True)
        old_test_path.rename(new_test_path)
    if old_processed_path.exists() and old_processed_path != new_processed_path and not new_processed_path.exists():
        new_processed_path.parent.mkdir(parents=True, exist_ok=True)
        old_processed_path.rename(new_processed_path)
    if old_capture_path.exists() and old_capture_path != new_capture_path and not new_capture_path.exists():
        new_capture_path.parent.mkdir(parents=True, exist_ok=True)
        old_capture_path.rename(new_capture_path)

    module_data["package_path"] = new_package_rel
    module_data["client_file"] = new_client_rel
    module_data["client_class"] = new_class
    module_data["processed_capture_dir"] = new_processed_rel

    commands = data.setdefault("commands", {})
    old_default_test = f"python .\\tests\\{old_slug}_smoke.py"
    if str(commands.get("run_tests") or "").strip() == old_default_test or not str(commands.get("run_tests") or "").strip():
        commands["run_tests"] = f"python .\\tests\\{new_slug}_smoke.py"

    replacement_targets = []
    if new_package_path.exists():
        replacement_targets.extend(path for path in new_package_path.rglob("*.py") if path.is_file())
    if new_test_path.exists():
        replacement_targets.append(new_test_path)

    replacements = {
        old_class: new_class,
        f"from {old_slug} import {old_class}": f"from {new_slug} import {new_class}",
        f"import {old_slug}": f"import {new_slug}",
        f"class {old_class}": f"class {new_class}",
        f"Client package for {old_name}": f"Client package for {new_name}",
        f"Starter client for {old_name}": f"Starter client for {new_name}",
        f"Smoke runner for the {old_name} scaffold.": f"Smoke runner for the {new_name} scaffold.",
    }
    for path in replacement_targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        updated = text
        for before, after in replacements.items():
            updated = updated.replace(before, after)
        if old_slug != new_slug:
            updated = updated.replace(f"from {old_slug} import", f"from {new_slug} import")
        if updated != text:
            path.write_text(updated, encoding="utf-8")

    new_manifest_path = SETTINGS_ROOT / f"{new_id}.yml"
    if manifest.path.exists() and manifest.path != new_manifest_path:
        new_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest.path.rename(new_manifest_path)

    renamed = ModuleManifest(path=new_manifest_path, data=data)
    renamed.save()
    return renamed


def next_blank_module_id() -> str:
    index = 1
    while True:
        module_id = f"new_module_{index}"
        if not (SETTINGS_ROOT / f"{module_id}.yml").exists():
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
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)


def load_capture_sessions_for_manifest(manifest: ModuleManifest, base_root: Path | None = None) -> list[Path]:
    return load_raw_capture_sessions(manifest.module_id, base_root=base_root)


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
