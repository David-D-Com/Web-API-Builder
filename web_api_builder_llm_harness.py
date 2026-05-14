"""CLI harness for testing the Web API Builder -> Ollama workflow.

This lets us exercise the same high-level LLM loop outside the GUI:
- choose a module
- choose a capture session
- choose a saved prompt or provide ad-hoc text
- bundle the current API files plus selected captures
- send to Ollama
- validate whether the reply contains applyable file blocks
- optionally apply the result with a backup
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile


REPO_ROOT = Path(__file__).resolve().parent
BUILDER_SRC = REPO_ROOT / "builder_app" / "src"
if str(BUILDER_SRC) not in sys.path:
    sys.path.insert(0, str(BUILDER_SRC))

from web_api_builder.manifest import (  # noqa: E402
    APP_ROOT,
    ModuleManifest,
    load_capture_sessions_for_manifest,
    load_manifests,
    load_prompt_library,
    load_raw_capture_entries,
)


FILE_BLOCK_PREFIX = "<<<FILE:"
FILE_BLOCK_SUFFIX = "<<<END FILE>>>"


@dataclass
class HarnessContext:
    module: ModuleManifest
    session_path: Path
    capture_paths: list[Path]
    prompt_name: str
    prompt_text: str
    host: str
    port: str
    api_file_limit: int | None = None


def module_api_paths(manifest: ModuleManifest) -> list[Path]:
    module_data = manifest.data.get("module", {})
    package_path = APP_ROOT / str(module_data.get("package_path") or "")
    client_file = APP_ROOT / str(module_data.get("client_file") or "")
    paths: list[Path] = []
    if package_path.exists():
        paths.extend(sorted(path for path in package_path.rglob("*.py") if path.is_file()))
    if client_file.exists() and client_file not in paths:
        paths.append(client_file)
    slug = package_path.name if package_path.name else manifest.module_id
    smoke_test = APP_ROOT / "tests" / f"{slug}_smoke.py"
    if smoke_test.exists():
        paths.append(smoke_test)
    if manifest.path.exists():
        paths.append(manifest.path)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def relative_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(APP_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def parse_reply_file_blocks(reply: str) -> list[tuple[str, str]]:
    import re

    pattern = re.compile(
        r"<<<FILE:\s*(?P<path>[^>]+?)>>>\s*\n(?P<body>.*?)\n<<<END FILE>>>",
        re.DOTALL,
    )
    return [(match.group("path").strip(), match.group("body")) for match in pattern.finditer(reply)]


def summarize_capture_endpoints(capture_paths: list[Path]) -> dict[str, object]:
    summary: dict[str, dict[str, object]] = {}
    for path in capture_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        request = payload.get("request", {})
        method = str(request.get("method") or "")
        url = str(request.get("url") or "")
        if not method or not url:
            continue
        parts = urlsplit(url)
        endpoint_key = f"{method} {parts.scheme}://{parts.netloc}{parts.path}"
        bucket = summary.setdefault(
            endpoint_key,
            {
                "method": method,
                "url": f"{parts.scheme}://{parts.netloc}{parts.path}",
                "count": 0,
                "query_param_keys": set(),
                "files": [],
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["files"].append(path.name)
        for key, _value in parse_qsl(parts.query, keep_blank_values=True):
            bucket["query_param_keys"].add(key)

    normalized: list[dict[str, object]] = []
    for item in summary.values():
        normalized.append(
            {
                "method": item["method"],
                "url": item["url"],
                "count": item["count"],
                "query_param_keys": sorted(item["query_param_keys"]),
                "files": item["files"],
            }
        )
    normalized.sort(key=lambda item: (str(item["url"]), str(item["method"])))

    recommended: list[str] = []
    ignored: list[str] = []
    for item in normalized:
        url = str(item["url"])
        if any(token in url for token in ("/ActualData/", "/Chart/", "/PvSystems/")):
            recommended.append(f"{item['method']} {url}")
        elif any(token in url for token in ("/Messages/", "/PvSystemImages/", "consentcdn.cookiebot.com", "/logincontext", "/dist/")):
            ignored.append(f"{item['method']} {url}")
    return {
        "endpoints": normalized,
        "recommended_endpoints": recommended,
        "likely_noise": ignored,
    }


def choose_module(module_id: str) -> ModuleManifest:
    manifests = load_manifests()
    for manifest in manifests:
        if manifest.module_id == module_id:
            return manifest
    known = ", ".join(manifest.module_id for manifest in manifests)
    raise SystemExit(f"Unknown module '{module_id}'. Known modules: {known}")


def choose_session(manifest: ModuleManifest, session_name: str | None) -> Path:
    sessions = load_capture_sessions_for_manifest(manifest)
    if not sessions:
        raise SystemExit(f"No capture sessions found for module '{manifest.module_id}'.")
    if not session_name or session_name == "latest":
        return sessions[0]
    for session in sessions:
        if session.name == session_name or str(session) == session_name:
            return session
    known = ", ".join(session.name for session in sessions)
    raise SystemExit(f"Unknown session '{session_name}'. Known sessions: {known}")


def choose_capture_paths(session_path: Path, limit: int | None = None) -> list[Path]:
    entries = load_raw_capture_entries(session_path)
    paths = [Path(str(entry.get("path"))) for entry in entries if entry.get("path")]
    if limit is not None:
        paths = paths[:limit]
    return [path for path in paths if path.exists()]


def choose_prompt(prompt_name: str | None, prompt_text: str | None) -> tuple[str, str]:
    if prompt_text:
        return ("Ad Hoc Prompt", prompt_text)
    prompts = load_prompt_library()
    if prompt_name:
        for prompt in prompts:
            if str(prompt.get("name") or "") == prompt_name:
                return (str(prompt.get("name")), str(prompt.get("text") or ""))
        known = ", ".join(str(prompt.get("name") or "") for prompt in prompts)
        raise SystemExit(f"Unknown prompt '{prompt_name}'. Known prompts: {known}")
    if not prompts:
        raise SystemExit("Prompt library is empty.")
    first = prompts[0]
    return (str(first.get("name") or "Prompt 1"), str(first.get("text") or ""))


def build_bundle(context: HarnessContext) -> tuple[Path, Path, str]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_root = Path("C:/tmp") / "web_api_builder_context" / context.module.module_id / timestamp
    files_dir = bundle_root / "files"
    captures_dir = bundle_root / "captures"
    files_dir.mkdir(parents=True, exist_ok=True)
    captures_dir.mkdir(parents=True, exist_ok=True)

    (bundle_root / "prompt.txt").write_text(context.prompt_text, encoding="utf-8")
    endpoint_summary = summarize_capture_endpoints(context.capture_paths)
    (bundle_root / "endpoint_summary.json").write_text(
        json.dumps(endpoint_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    api_sections: list[str] = []
    api_paths = module_api_paths(context.module)
    if context.api_file_limit is not None:
        api_paths = api_paths[: context.api_file_limit]
    for path in api_paths:
        rel = relative_repo_path(path)
        target = files_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        body = path.read_text(encoding="utf-8", errors="replace")
        api_sections.append(f"=== FILE: {rel} ===\n{body}\n=== END FILE ===")

    capture_sections: list[str] = []
    for path in context.capture_paths:
        target = captures_dir / path.name
        shutil.copy2(path, target)
        body = path.read_text(encoding="utf-8", errors="replace")
        capture_sections.append(f"=== CAPTURE: {path.name} ===\n{body}\n=== END CAPTURE ===")

    zip_path = bundle_root.with_suffix(".zip")
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for item in bundle_root.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(bundle_root))

    full_prompt = (
        "You are editing files in an existing local repository.\n\n"
        "Use the provided project files and captured requests to update the Python API module.\n\n"
        "The target output must be a real importable Python module/package for communicating with the target web application.\n"
        "The target is NOT:\n"
        "- a Flask app\n"
        "- a FastAPI app\n"
        "- a demo web server\n"
        "- mocked endpoint handlers\n"
        "- hard-coded fake response data\n"
        "- browser automation unless the task explicitly asks for helper tooling\n\n"
        "Repository shape requirements:\n"
        "- Implement or update reusable client code under the existing module package path.\n"
        "- Preserve the repo's package-oriented structure.\n"
        "- Prefer client classes, request helpers, and smoke tests.\n"
        "- If tests are returned, they should test the module/client, not stand up a server.\n\n"
        "Response format requirements:\n"
        "- Return only changed files.\n"
        "- For each changed file, use this exact format:\n"
        "<<<FILE: relative/path/from/repo/root>>>\n"
        "<full replacement file contents>\n"
        "<<<END FILE>>>\n"
        "- You may optionally include one summary block first:\n"
        "<<<SUMMARY>>>\n"
        "<brief summary>\n"
        "<<<END SUMMARY>>>\n"
        "- Do not use markdown fences around file contents.\n"
        "- Do not omit unchanged imports or context if a file is returned; each file block must contain the full final file contents.\n\n"
        f"Selected module: {context.module.module_id}\n"
        f"Selected prompt: {context.prompt_name}\n"
        f"Selected capture session: {context.session_path}\n"
        f"Context bundle zip: {zip_path}\n\n"
        "Captured endpoint summary:\n"
        + json.dumps(endpoint_summary, indent=2, ensure_ascii=False)
        + "\n\n"
        "User task:\n"
        f"{context.prompt_text}\n\n"
        "Current API/module files:\n"
        + "\n\n".join(api_sections)
        + "\n\nSelected captures:\n"
        + "\n\n".join(capture_sections)
        + "\n\nImplementation guidance:\n"
        + "- Use the endpoint summary to maximize useful functional coverage from this capture.\n"
        + "- Treat the entries in recommended_endpoints as the default implementation target list.\n"
        + "- If you skip a recommended endpoint, explicitly justify it by omission from the returned files and keep coverage as high as possible for the rest.\n"
        + "- Prefer implementing production/data endpoints before message, image, consent, or login noise.\n"
        + "- If chart endpoints have many variants, implement a reusable parameterized helper plus small convenience wrappers where appropriate.\n"
        + "- If a smoke test file is present in the provided module files, update it so the new API surface has a basic verification path.\n"
    )
    return bundle_root, zip_path, full_prompt


def send_to_ollama(host: str, port: str, model: str, prompt: str, timeout: int) -> str:
    url = f"http://{host}:{port}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return str(result.get("response") or "")


def reformat_reply_to_file_blocks(
    *,
    host: str,
    port: str,
    model: str,
    timeout: int,
    prior_reply: str,
    candidate_files: list[str],
) -> str:
    prompt = (
        "Rewrite the prior answer into valid file blocks only.\n\n"
        "Rules:\n"
        "- Return only changed files.\n"
        "- Use only paths from this allowed list:\n"
        + "\n".join(f"  - {path}" for path in candidate_files)
        + "\n"
        "- For each changed file, use this exact format:\n"
        "<<<FILE: relative/path/from/repo/root>>>\n"
        "<full replacement file contents>\n"
        "<<<END FILE>>>\n"
        "- You may omit any file you do not want to change.\n"
        "- Do not include markdown fences.\n"
        "- Do not include prose, explanations, or headings.\n\n"
        "Prior answer to rewrite:\n"
        + prior_reply
    )
    return send_to_ollama(host, port, model, prompt, timeout)


def list_ollama_models(host: str, port: str, timeout: int) -> list[str]:
    url = f"http://{host}:{port}/api/tags"
    request = Request(url, method="GET")
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [str(item.get("name") or "") for item in payload.get("models", []) if item.get("name")]


def apply_reply(manifest: ModuleManifest, reply: str) -> tuple[int, Path]:
    file_blocks = parse_reply_file_blocks(reply)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = Path("C:/tmp") / "web_api_builder_backups" / manifest.module_id / timestamp
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "ollama_reply.txt").write_text(reply, encoding="utf-8")
    applied = 0
    for relative_path, content in file_blocks:
        candidate = (APP_ROOT / relative_path).resolve()
        try:
            candidate.relative_to(APP_ROOT.resolve())
        except ValueError:
            continue
        if candidate.exists():
            backup_path = backup_root / candidate.relative_to(APP_ROOT)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, backup_path)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content.rstrip() + "\n", encoding="utf-8")
        applied += 1
    return applied, backup_root


def list_sessions(manifest: ModuleManifest) -> int:
    sessions = load_capture_sessions_for_manifest(manifest)
    if not sessions:
        print("No sessions found.")
        return 0
    for session in sessions:
        print(session)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the Web API Builder -> Ollama workflow from the CLI.")
    parser.add_argument("--module", required=True, help="Module id from settings/<module>.yml")
    parser.add_argument("--session", default="latest", help="Session folder name or full path, or 'latest'")
    parser.add_argument("--list-sessions", action="store_true", help="List available sessions for the module and exit")
    parser.add_argument("--prompt-name", help="Prompt name from settings/prompt_templates.yml")
    parser.add_argument("--prompt-text", help="Ad hoc prompt text; overrides --prompt-name")
    parser.add_argument("--model", required=False, default="", help="Ollama model name")
    parser.add_argument("--host", default="192.168.66.11", help="Ollama host")
    parser.add_argument("--port", default="11434", help="Ollama port")
    parser.add_argument("--timeout", type=int, default=180, help="Ollama request timeout in seconds")
    parser.add_argument("--capture-limit", type=int, default=None, help="Limit number of capture files sent")
    parser.add_argument("--api-file-limit", type=int, default=None, help="Limit number of API/module files sent")
    parser.add_argument("--list-models", action="store_true", help="Query /api/tags and print available Ollama models")
    parser.add_argument("--retry-format", action="store_true", help="If the first reply has no FILE blocks, ask the model to rewrite it into valid FILE blocks.")
    parser.add_argument("--show-reply", action="store_true", help="Print the full reply")
    parser.add_argument("--apply", action="store_true", help="Apply valid file blocks to the repo with a backup")
    args = parser.parse_args()

    manifest = choose_module(args.module)
    if args.list_sessions:
        return list_sessions(manifest)
    if args.list_models:
        models = list_ollama_models(args.host, args.port, args.timeout)
        if not models:
            print("No models returned.")
            return 0
        for model in models:
            print(model)
        return 0
    if not args.model:
        raise SystemExit("--model is required unless using --list-sessions")

    session_path = choose_session(manifest, args.session)
    capture_paths = choose_capture_paths(session_path, args.capture_limit)
    prompt_name, prompt_text = choose_prompt(args.prompt_name, args.prompt_text)
    context = HarnessContext(
        module=manifest,
        session_path=session_path,
        capture_paths=capture_paths,
        prompt_name=prompt_name,
        prompt_text=prompt_text,
        host=args.host,
        port=args.port,
        api_file_limit=args.api_file_limit,
    )
    bundle_root, zip_path, full_prompt = build_bundle(context)
    print(f"Module: {manifest.module_id}")
    print(f"Session: {session_path}")
    print(f"Prompt: {prompt_name}")
    print(f"Capture files: {len(capture_paths)}")
    print(f"Bundle dir: {bundle_root}")
    print(f"Bundle zip: {zip_path}")
    reply = send_to_ollama(args.host, args.port, args.model, full_prompt, args.timeout)
    file_blocks = parse_reply_file_blocks(reply)
    if not file_blocks and args.retry_format:
        candidate_files = [relative_repo_path(path) for path in module_api_paths(manifest)]
        retry_reply = reformat_reply_to_file_blocks(
            host=args.host,
            port=args.port,
            model=args.model,
            timeout=args.timeout,
            prior_reply=reply,
            candidate_files=candidate_files,
        )
        if retry_reply.strip():
            reply = retry_reply
            file_blocks = parse_reply_file_blocks(reply)

    reply_dir = Path("C:/tmp") / "web_api_builder_replies" / manifest.module_id
    reply_dir.mkdir(parents=True, exist_ok=True)
    reply_path = reply_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    reply_path.write_text(reply, encoding="utf-8")
    print(f"Reply saved: {reply_path}")
    print(f"Reply length: {len(reply)} chars")
    print(f"File blocks detected: {len(file_blocks)}")
    if file_blocks:
        print("Detected file targets:")
        for relative_path, _body in file_blocks:
            print(f"  - {relative_path}")
    else:
        print("No applyable file blocks were found in the reply.")

    if args.show_reply:
        print("\n===== OLLAMA REPLY =====\n")
        print(reply)

    if args.apply:
        applied, backup_root = apply_reply(manifest, reply)
        print(f"Applied files: {applied}")
        print(f"Backup dir: {backup_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
