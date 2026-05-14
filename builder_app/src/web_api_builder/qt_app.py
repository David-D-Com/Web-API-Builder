"""Qt6 desktop shell for managing API-builder modules."""

from __future__ import annotations

import ast
import difflib
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

import yaml
from PySide6.QtCore import QObject, QProcess, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .manifest import (
    APP_ROOT,
    ModuleManifest,
    capture_enabled,
    client_class_name,
    create_module_from_template,
    delete_module,
    infer_client_methods,
    is_blank_module,
    load_capture_sessions_for_manifest,
    load_manifests,
    load_prompt_library,
    load_raw_capture_entries,
    load_raw_capture_sessions,
    module_capture_root,
    next_module_id_for_name,
    next_blank_module_id,
    rename_module,
    save_prompt_library,
    set_capture_enabled,
    slugify_module_name,
)

DARK_STYLESHEET = """
QWidget {
    background-color: #1a1d23;
    color: #e8eaf0;
    font-size: 13px;
}

QMainWindow {
    background-color: #16191f;
}

QLabel {
    color: #d7dbe6;
    background-color: transparent;
}

QGroupBox {
    border: 1px solid #3a3f4b;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    background-color: #2b313b;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #9fc7ff;
}

QWidget[debugLimit="true"] {
    border: 2px solid #ff6b6b;
    border-radius: 6px;
}

QWidget[automationFlash="true"] {
    border: 2px solid #ffd54a;
    border-radius: 6px;
    background-color: rgba(255, 213, 74, 0.12);
}

QPushButton {
    background-color: #5b7cfa;
    border: 1px solid #6f8cff;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}

QPushButton:hover {
    background-color: #6c8aff;
}

QPushButton[compact="true"] {
    padding: 4px 8px;
}

QPushButton[danger="true"] {
    background-color: #c84b4b;
    border: 1px solid #dd6666;
}

QPushButton[danger="true"]:hover {
    background-color: #d85d5d;
}

QPushButton[danger="true"]:pressed {
    background-color: #b54141;
}

QPushButton[success="true"] {
    background-color: #2f8f53;
    border: 1px solid #55b978;
}

QPushButton[success="true"]:hover {
    background-color: #39a15f;
}

QPushButton[success="true"]:pressed {
    background-color: #267545;
}

QPushButton[filterToggle="true"] {
    background-color: #343c49;
    border: 1px solid #59667a;
    padding: 3px 8px;
}

QPushButton[filterToggle="true"]:checked {
    background-color: #4a5f84;
    border: 1px solid #78a9ff;
}

QPushButton[filterToggle="true"][allButton="true"]:checked {
    background-color: #2f8f53;
    border: 1px solid #55b978;
}

QPushButton:pressed {
    background-color: #4763d8;
}

QPushButton:disabled {
    background-color: #39404d;
    color: #7d8596;
    border-color: #353b46;
}

QLineEdit,
QComboBox,
QTextEdit,
QPlainTextEdit {
    background-color: #161a22;
    color: #f2f4f8;
    border: 1px solid #4b5563;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #2b6cb0;
}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border: 1px solid #78a9ff;
}

QLineEdit[invalid="true"] {
    border: 1px solid #ff6b6b;
    background-color: #2c1f24;
}

QComboBox::drop-down {
    background-color: #4b5c78;
    border-left: 1px solid #6f809d;
    width: 28px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

QComboBox::down-arrow {
    width: 0px;
    height: 0px;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid #ffffff;
}

QComboBox QAbstractItemView {
    background-color: #1f2530;
    color: #edf1f7;
    border: 1px solid #4b5563;
    selection-background-color: #2d4f7c;
}

QHeaderView::section {
    background-color: #425068;
    color: #eef3fb;
    padding: 6px;
    border: 1px solid #40485a;
    font-weight: 600;
}

QTableWidget {
    background-color: #dde6f3;
    alternate-background-color: #cfd9ea;
    gridline-color: #97a7c1;
    border: 1px solid #59667a;
    border-radius: 6px;
    selection-background-color: #7aa2ff;
    selection-color: #111318;
    color: #18202b;
}

QTableWidget::item {
    padding: 4px;
    background-color: transparent;
}

QTabWidget::pane {
    border: 1px solid #3f4656;
    border-radius: 8px;
    background-color: #2a3039;
    top: -1px;
}

QTabWidget[replyTabs="true"] {
    background-color: #232a34;
}

QTabWidget[replyTabs="true"]::pane {
    border: 1px solid #465062;
    border-radius: 8px;
    background-color: #232a34;
    top: -1px;
}

QTabBar::tab {
    background-color: #39414d;
    color: #d3d8e3;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background-color: #566277;
    color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background-color: #485364;
}

QTabWidget[replyTabs="true"] QTabBar::tab {
    background-color: #2f3948;
    color: #dbe4f1;
}

QTabWidget[replyTabs="true"] QTabBar::tab:selected {
    background-color: #4a5b73;
    color: #ffffff;
}

QTabWidget[replyTabs="true"] QTabBar::tab:hover:!selected {
    background-color: #3a4657;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

QCheckBox::indicator:unchecked {
    border: 1px solid #667085;
    background-color: #161a22;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    border: 1px solid #78a9ff;
    background-color: #5b7cfa;
    border-radius: 3px;
}

QSplitter::handle {
    background-color: #596477;
}

QSplitter::handle:hover {
    background-color: #7b879b;
}

QScrollBar:vertical {
    background-color: #2a3039;
    width: 14px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: #69778d;
    min-height: 24px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background-color: #8292ab;
}

QScrollBar:horizontal {
    background-color: #2a3039;
    height: 14px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background-color: #69778d;
    min-width: 24px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #8292ab;
}
"""

LIGHT_STYLESHEET = """
QWidget {
    background-color: #eef2f7;
    color: #1f2937;
    font-size: 13px;
}

QMainWindow {
    background-color: #e7ebf2;
}

QLabel {
    color: #243142;
    background-color: transparent;
}

QGroupBox {
    border: 1px solid #b8c3d4;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    background-color: #f7f9fc;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #2f5eb8;
}

QWidget[debugLimit="true"] {
    border: 2px solid #d64545;
    border-radius: 6px;
}

QWidget[automationFlash="true"] {
    border: 2px solid #d7a100;
    border-radius: 6px;
    background-color: rgba(255, 221, 87, 0.18);
}

QPushButton {
    background-color: #3f6fd9;
    border: 1px solid #355eb6;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}

QPushButton:hover {
    background-color: #4c7ce6;
}

QPushButton[compact="true"] {
    padding: 4px 8px;
}

QPushButton[danger="true"] {
    background-color: #d75252;
    border: 1px solid #be3f3f;
}

QPushButton[danger="true"]:hover {
    background-color: #e16060;
}

QPushButton[danger="true"]:pressed {
    background-color: #c44848;
}

QPushButton[success="true"] {
    background-color: #4ea96c;
    border: 1px solid #3d8b58;
}

QPushButton[success="true"]:hover {
    background-color: #5bb779;
}

QPushButton[success="true"]:pressed {
    background-color: #418d5b;
}

QPushButton[filterToggle="true"] {
    background-color: #dde7f5;
    border: 1px solid #a8b6c8;
    color: #223046;
    padding: 3px 8px;
}

QPushButton[filterToggle="true"]:checked {
    background-color: #bcd5ff;
    border: 1px solid #4f83e1;
    color: #142133;
}

QPushButton[filterToggle="true"][allButton="true"]:checked {
    background-color: #9ad3aa;
    border: 1px solid #40995a;
    color: #12311d;
}

QPushButton:pressed {
    background-color: #325cb8;
}

QPushButton:disabled {
    background-color: #cbd5e1;
    color: #667085;
    border-color: #bcc7d6;
}

QLineEdit,
QComboBox,
QTextEdit,
QPlainTextEdit {
    background-color: #ffffff;
    color: #111827;
    border: 1px solid #a9b6c8;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #9ec5ff;
}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border: 1px solid #4f83e1;
}

QLineEdit[invalid="true"] {
    border: 1px solid #d64545;
    background-color: #fff1f1;
}

QComboBox::drop-down {
    background-color: #d7e3f7;
    border-left: 1px solid #aabbd8;
    width: 28px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

QComboBox::down-arrow {
    width: 0px;
    height: 0px;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid #1f2937;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #111827;
    border: 1px solid #a9b6c8;
    selection-background-color: #dbeafe;
}

QHeaderView::section {
    background-color: #dbe6f5;
    color: #223046;
    padding: 6px;
    border: 1px solid #b7c5d8;
    font-weight: 600;
}

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #eef4fb;
    gridline-color: #c0cede;
    border: 1px solid #a8b6c8;
    border-radius: 6px;
    selection-background-color: #9fc2ff;
    selection-color: #111827;
    color: #162131;
}

QTableWidget::item {
    padding: 4px;
    background-color: transparent;
}

QTabWidget::pane {
    border: 1px solid #bcc7d8;
    border-radius: 8px;
    background-color: #f8fbff;
    top: -1px;
}

QTabWidget[replyTabs="true"] {
    background-color: #ffffff;
}

QTabWidget[replyTabs="true"]::pane {
    border: 1px solid #bcc7d8;
    border-radius: 8px;
    background-color: #ffffff;
    top: -1px;
}

QTabBar::tab {
    background-color: #d7e1ef;
    color: #3b4a5c;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #111827;
}

QTabBar::tab:hover:!selected {
    background-color: #e5edf8;
}

QTabWidget[replyTabs="true"] QTabBar::tab {
    background-color: #dbe5f2;
    color: #314155;
}

QTabWidget[replyTabs="true"] QTabBar::tab:selected {
    background-color: #ffffff;
    color: #111827;
}

QTabWidget[replyTabs="true"] QTabBar::tab:hover:!selected {
    background-color: #eaf0f8;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

QCheckBox::indicator:unchecked {
    border: 1px solid #93a4bb;
    background-color: #ffffff;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    border: 1px solid #4f83e1;
    background-color: #4f83e1;
    border-radius: 3px;
}

QSplitter::handle {
    background-color: #c5d0de;
}

QSplitter::handle:hover {
    background-color: #aebed2;
}

QScrollBar:vertical {
    background-color: #e9eef5;
    width: 14px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: #b0bfd2;
    min-height: 24px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background-color: #94abc5;
}

QScrollBar:horizontal {
    background-color: #e9eef5;
    height: 14px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background-color: #b0bfd2;
    min-width: 24px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #94abc5;
}
"""


# Shared layout sizing lives here so width/height tuning is independent from
# the visual theme stylesheets above.
UI_SIZES = {
    "window_default_width": 600,
    "window_default_height": 700,
    "module_combo_width": 200,
    "toolbar_button_width": 72,
    "toolbar_button_height": 28,
    "capture_session_combo_width": 200,
    "capture_button_width": 66,
    "capture_button_height": 28,
    "filter_button_height": 26,
    "filter_button_min_width": 56,
    "main_splitter_top_stretch": 4,
    "main_splitter_bottom_stretch": 1,
    "log_panel_margin": 0,
    "debug_near_min_slack": 24,
    "window_state_save_debounce_ms": 500,
    "base_url_normalize_debounce_ms": 900,
    "autosave_debounce_ms": 1500,
    "capture_refresh_interval_ms": 1000,
    "session_action_button_width": 56,
    "run_new_button_width": 84,
    "capture_tall_button_size": 64,
    "ollama_setting_width": 220,
    "prompt_toolbar_button_width": 64,
    "ollama_host_default": "192.168.66.11",
    "ollama_port_default": "11434",
    "control_poll_interval_ms": 350,
    "reply_diff_list_width": 220,
    "reply_many_files_threshold": 5,
    "llm_auto_cycle_max": 3,
    "ollama_stream_idle_timeout_sec": 20,
}

ACTIVE_CAPTURE_SESSION_FILE = "_active_capture_session.json"
CONTROL_ROOT = Path("C:/tmp") / "web_api_builder_control"


def parse_file_blocks(reply: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"<<<FILE:\s*(?P<path>[^>]+?)>>>\s*\n(?P<body>.*?)\n<<<END FILE>>>",
        re.DOTALL,
    )
    return [(match.group("path").strip(), match.group("body")) for match in pattern.finditer(reply)]


class OllamaRequestWorker(QObject):
    chunk = Signal(str, str, int, float)
    status = Signal(str, str)
    finished = Signal(str, str, str)
    error = Signal(str, str, str)

    def __init__(self, *, mode: str, model: str, base_url: str, prompt: str, repair_prompt: str | None = None, timeout: int = 120) -> None:
        super().__init__()
        self.mode = mode
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.prompt = prompt
        self.repair_prompt = repair_prompt
        self.timeout = timeout
        self.stream_timeout = int(UI_SIZES["ollama_stream_idle_timeout_sec"])

    def _send_generate_request(self, prompt: str, *, stream: bool, timeout_override: int | None = None) -> str:
        url = self.base_url + "/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": stream}
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        accumulated = ""
        started = time.monotonic()
        last_emit = started
        try:
            with urlopen(request, timeout=timeout_override or self.timeout) as response:
                if not stream:
                    result = json.loads(response.read().decode("utf-8"))
                    return str(result.get("response") or "")
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = str(item.get("response") or "")
                    if chunk:
                        accumulated += chunk
                        now = time.monotonic()
                        if (now - last_emit) >= 1.0:
                            token_count = len(re.findall(r"\S+", accumulated))
                            elapsed = max(now - started, 0.001)
                            rate = token_count / elapsed
                            self.chunk.emit(self.mode, accumulated, token_count, rate)
                            last_emit = now
                    if item.get("done"):
                        token_count = len(re.findall(r"\S+", accumulated))
                        elapsed = max(time.monotonic() - started, 0.001)
                        rate = token_count / elapsed
                        self.chunk.emit(self.mode, accumulated, token_count, rate)
                        break
        except Exception as exc:
            partial_message = f"{exc}"
            if accumulated:
                raise RuntimeError(f"{partial_message} (partial reply preserved)") from exc
            raise
        return accumulated

    def run(self) -> None:
        reply = ""
        try:
            self.status.emit(self.mode, "Sending request to Ollama...")
            try:
                reply = self._send_generate_request(
                    self.prompt,
                    stream=True,
                    timeout_override=self.stream_timeout,
                )
            except Exception as exc:
                if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                    self.status.emit(self.mode, "Stream timed out. Trying non-stream recovery...")
                    reply = self._send_generate_request(self.prompt, stream=False, timeout_override=self.timeout)
                else:
                    raise
            if not parse_file_blocks(reply) and self.repair_prompt:
                self.status.emit(self.mode, "No file blocks detected. Requesting format-only rewrite...")
                reply = self._send_generate_request(self.repair_prompt, stream=False)
            self.finished.emit(self.mode, self.prompt, reply)
        except Exception as exc:
            self.error.emit(self.mode, str(exc), reply)



class MainWindow(QMainWindow):
    """Main desktop shell for module-oriented API builder workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("LocalRepo", "WebApiBuilder")
        self.setWindowTitle("Web API Builder")
        self.resize(UI_SIZES["window_default_width"], UI_SIZES["window_default_height"])
        self.restoreGeometry(self.settings.value("window/geometry", b""))

        self.manifests: list[ModuleManifest] = []
        self.current_manifest: ModuleManifest | None = None
        self.prompt_library: list[dict[str, str]] = load_prompt_library()
        self.current_llm_mode = "process"
        self.current_tab_index = 0
        self.last_loaded_module_name = ""
        self.suppress_name_change_prompt = False
        self.process: QProcess | None = None
        self.browser_process: QProcess | None = None
        self.browser_module_id: str | None = None
        self.current_capture_dir: Path | None = None
        self.browser_running = False
        self.last_capture_entry_count = 0
        self.window_state_timer = QTimer(self)
        self.window_state_timer.setSingleShot(True)
        self.window_state_timer.setInterval(UI_SIZES["window_state_save_debounce_ms"])
        self.window_state_timer.timeout.connect(self._save_window_state)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(UI_SIZES["autosave_debounce_ms"])
        self.autosave_timer.timeout.connect(self._autosave_manifest_if_possible)
        self.base_url_timer = QTimer(self)
        self.base_url_timer.setSingleShot(True)
        self.base_url_timer.setInterval(UI_SIZES["base_url_normalize_debounce_ms"])
        self.base_url_timer.timeout.connect(self._normalize_base_url_input)
        self.capture_refresh_timer = QTimer(self)
        self.capture_refresh_timer.setInterval(UI_SIZES["capture_refresh_interval_ms"])
        self.capture_refresh_timer.timeout.connect(self._refresh_current_capture_entries)
        self.control_timer = QTimer(self)
        self.control_timer.setInterval(UI_SIZES["control_poll_interval_ms"])
        self.control_timer.timeout.connect(self._poll_control_commands)
        self.record_blink_timer = QTimer(self)
        self.record_blink_timer.setInterval(650)
        self.record_blink_timer.timeout.connect(self._toggle_record_blink)
        self.record_blink_on = True
        self.ollama_threads: dict[str, QThread] = {}
        self.ollama_workers: dict[str, OllamaRequestWorker] = {}
        self.pending_ollama_requests: dict[str, dict[str, object]] = {}
        self.reply_apply_selection: dict[str, dict[str, bool]] = {"process": {}, "revise": {}}

        self.module_combo = QComboBox()
        self.module_combo.currentIndexChanged.connect(self._on_module_combo_changed)
        self.dark_mode_check = QCheckBox("Dark mode")
        self.dark_mode_check.setChecked(bool(self.settings.value("theme/dark_mode", True, type=bool)))
        self.dark_mode_check.toggled.connect(self._on_theme_toggled)
        self.debug_mode_check = QCheckBox("Debug mode")
        self.debug_mode_check.setChecked(bool(self.settings.value("debug/enabled", False, type=bool)))
        self.debug_mode_check.toggled.connect(self._on_debug_mode_toggled)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._on_module_name_edit_finished)
        self.description_edit = QLineEdit()
        self.description_edit.textChanged.connect(self._schedule_autosave)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.textChanged.connect(lambda _text: self.base_url_timer.start())
        self.base_url_edit.textChanged.connect(self._schedule_autosave)
        self.raw_capture_root_edit = QLineEdit()
        self.raw_capture_root_edit.textChanged.connect(self._schedule_autosave)
        self.processed_capture_root_edit = QLineEdit()
        self.processed_capture_root_edit.textChanged.connect(self._schedule_autosave)

        self.capture_url_filter_edit = QLineEdit()
        self.capture_url_filter_edit.textChanged.connect(self._schedule_autosave)
        self.capture_domain_filter_edit = QLineEdit()
        self.capture_domain_filter_edit.textChanged.connect(self._schedule_autosave)
        self.capture_mode_combo = QComboBox()
        self.capture_mode_combo.addItems(["Keep Last", "Keep All"])
        self.capture_mode_combo.setFixedWidth(110)
        self.capture_mode_combo.currentIndexChanged.connect(lambda _i: self._schedule_autosave())
        self.capture_content_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", "All"),
            ("json", "JSON"),
            ("html", "HTML"),
            ("js", "JS"),
            ("text", "Text"),
            ("other", "Other"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("filterToggle", True)
            button.setProperty("compact", True)
            if key == "all":
                button.setProperty("allButton", True)
            button.setMinimumWidth(UI_SIZES["filter_button_min_width"])
            button.setFixedHeight(UI_SIZES["filter_button_height"])
            button.clicked.connect(lambda _checked=False, kind=key: self._on_capture_content_button_clicked(kind))
            self.capture_content_buttons[key] = button

        self.test_command_edit = QLineEdit()
        self.test_command_edit.textChanged.connect(self._schedule_autosave)
        self.browser_command_edit = QLineEdit()
        self.browser_command_edit.textChanged.connect(self._schedule_autosave)
        self.process_capture_command_edit = QLineEdit()
        self.process_capture_command_edit.textChanged.connect(self._schedule_autosave)
        self.ollama_host_edit = QLineEdit()
        self.ollama_host_edit.setFixedWidth(UI_SIZES["ollama_setting_width"])
        self.ollama_host_edit.setText(str(self.settings.value("ollama/host", UI_SIZES["ollama_host_default"])))
        self.ollama_host_edit.textChanged.connect(self._schedule_autosave)
        self.ollama_port_edit = QLineEdit()
        self.ollama_port_edit.setFixedWidth(90)
        self.ollama_port_edit.setText(str(self.settings.value("ollama/port", UI_SIZES["ollama_port_default"])))
        self.ollama_port_edit.textChanged.connect(self._schedule_autosave)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setFixedWidth(UI_SIZES["ollama_setting_width"])
        self.ollama_model_combo.setEditable(True)
        self.ollama_model_combo.setCurrentText(str(self.settings.value("ollama/model", "") or ""))
        self.ollama_model_combo.currentIndexChanged.connect(lambda _i: self._schedule_autosave())
        self.actions_session_combo = QComboBox()
        self.actions_session_combo.setFixedWidth(UI_SIZES["capture_session_combo_width"])
        self.actions_session_combo.currentIndexChanged.connect(self._schedule_autosave)
        self.actions_session_combo.currentIndexChanged.connect(lambda _i: self._update_llm_action_buttons())
        self.actions_session_combo.currentIndexChanged.connect(lambda _i: self._on_shared_session_combo_changed("process"))
        self.actions_session_count_label = QLabel("")
        self.prompt_combo = QComboBox()
        self.prompt_combo.setEditable(True)
        self.prompt_combo.setToolTip(
            "Select a saved prompt preset. Use the prompt name to choose the workflow, then edit/save if needed."
        )
        self.prompt_combo.currentIndexChanged.connect(self._on_prompt_selected)
        self.prompt_description_edit = QLineEdit()
        self.prompt_description_edit.setPlaceholderText(
            "Short human-readable description of what this prompt is for"
        )
        self.prompt_description_edit.setToolTip(
            "Short saved description for the selected prompt preset. Edit it and click Save to update the prompt library."
        )
        self.prompt_editor = QTextEdit()
        self.prompt_editor.setToolTip(
            "The full prompt that will be sent to the selected Ollama model for this module/session."
        )
        self.prompt_editor.textChanged.connect(self._update_llm_action_buttons)
        self.ollama_reply_output = QTextEdit()
        self.ollama_reply_output.setReadOnly(True)
        self.ollama_reply_output.textChanged.connect(self._update_llm_action_buttons)
        self.process_reply_tabs = QTabWidget()
        self.process_reply_tabs.setProperty("replyTabs", True)
        self.process_diff_list = QListWidget()
        self.process_diff_stats_label = QLabel("")
        self.process_diff_apply_check = QCheckBox("Apply these changes")
        self.process_diff_view = QTextEdit()
        self.process_diff_view.setReadOnly(True)
        self.process_diff_list.currentItemChanged.connect(
            lambda current, _previous: self._on_diff_item_changed("process", current)
        )
        self.process_diff_apply_check.toggled.connect(
            lambda checked: self._on_review_apply_toggled("process", checked)
        )
        self.process_status_label = QLabel("")
        self.process_result_summary_label = QLabel("")
        self.process_result_summary_label.setWordWrap(True)
        self.process_result_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.revise_session_combo = QComboBox()
        self.revise_session_combo.setFixedWidth(UI_SIZES["capture_session_combo_width"])
        self.revise_session_combo.currentIndexChanged.connect(self._schedule_autosave)
        self.revise_session_combo.currentIndexChanged.connect(lambda _i: self._update_llm_action_buttons())
        self.revise_session_combo.currentIndexChanged.connect(lambda _i: self._on_shared_session_combo_changed("revise"))
        self.revise_session_count_label = QLabel("")
        self.revise_history_output = QTextEdit()
        self.revise_history_output.setReadOnly(True)
        self.revise_prompt_editor = QTextEdit()
        self.revise_prompt_editor.textChanged.connect(self._update_llm_action_buttons)
        self.revise_reply_output = QTextEdit()
        self.revise_reply_output.setReadOnly(True)
        self.revise_reply_output.textChanged.connect(self._update_llm_action_buttons)
        self.revise_reply_tabs = QTabWidget()
        self.revise_reply_tabs.setProperty("replyTabs", True)
        self.revise_diff_list = QListWidget()
        self.revise_diff_stats_label = QLabel("")
        self.revise_diff_apply_check = QCheckBox("Apply these changes")
        self.revise_diff_view = QTextEdit()
        self.revise_diff_view.setReadOnly(True)
        self.revise_diff_list.currentItemChanged.connect(
            lambda current, _previous: self._on_diff_item_changed("revise", current)
        )
        self.revise_diff_apply_check.toggled.connect(
            lambda checked: self._on_review_apply_toggled("revise", checked)
        )
        self.revise_status_label = QLabel("")
        self.revise_result_summary_label = QLabel("")
        self.revise_result_summary_label.setWordWrap(True)
        self.revise_result_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.endpoints_table = QTableWidget(0, 1)
        self.endpoints_table.setHorizontalHeaderLabels(["Implemented Client Methods"])
        self.endpoints_table.horizontalHeader().setStretchLastSection(True)

        self.pages_table = QTableWidget(0, 2)
        self.pages_table.setHorizontalHeaderLabels(["Page", "Route"])
        self.pages_table.horizontalHeader().setStretchLastSection(True)
        self.pages_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pages_table.itemDoubleClicked.connect(self.open_selected_page_route)

        self.raw_sessions_combo = QComboBox()
        self.raw_sessions_combo.setFixedWidth(UI_SIZES["capture_session_combo_width"])
        self.raw_sessions_combo.currentIndexChanged.connect(self._on_capture_session_changed)
        self.raw_requests_table = QTableWidget(0, 6)
        self.raw_requests_table.setHorizontalHeaderLabels(
            ["File", "Method", "URL", "Status", "Type", "Count"]
        )
        self.raw_requests_table.horizontalHeader().setStretchLastSection(True)
        self.raw_requests_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.raw_requests_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.raw_requests_table.itemDoubleClicked.connect(self.open_capture_request_details)

        self.open_session_folder_button = QPushButton("Open")
        self.open_session_folder_button.setProperty("compact", True)
        self.open_session_folder_button.clicked.connect(self.open_current_capture_folder)
        self.rename_session_button = QPushButton("Rename")
        self.rename_session_button.setProperty("compact", True)
        self.rename_session_button.clicked.connect(self.rename_current_session)
        self.run_new_button = QPushButton("Run New")
        self.run_new_button.setProperty("compact", True)
        self.run_new_button.setProperty("success", True)
        self.run_new_button.setText("New\nCapture")
        self.run_new_button.setStyleSheet("font-size: 9pt; padding: 1px 2px;")
        self.run_new_button.clicked.connect(self.open_new_capture_session)
        self.capture_toggle_button = QPushButton()
        self.capture_toggle_button.setProperty("compact", True)
        self.capture_toggle_button.setCheckable(True)
        self.capture_toggle_button.clicked.connect(self.toggle_capture_enabled)
        self.process_send_button = QPushButton("Send")
        self.process_send_button.setProperty("success", True)
        self.process_send_button.clicked.connect(lambda: self._send_prompt_to_ollama("process"))
        self.process_cycle_combo = QComboBox()
        self.process_cycle_combo.setToolTip("How many automatic LLM revise/retry cycles to allow for this send.")
        self.process_apply_button = QPushButton("Apply Reply")
        self.process_apply_button.clicked.connect(lambda: self._backup_and_apply_reply("process"))
        self.process_rename_session_button = QPushButton("Rename")
        self.process_rename_session_button.setProperty("compact", True)
        self.process_rename_session_button.clicked.connect(lambda: self._rename_session_from_combo("process"))
        self.process_delete_session_button = QPushButton("Delete")
        self.process_delete_session_button.setProperty("compact", True)
        self.process_delete_session_button.setProperty("danger", True)
        self.process_delete_session_button.clicked.connect(lambda: self._delete_session_from_combo("process"))
        self.revise_send_button = QPushButton("Send")
        self.revise_send_button.setProperty("success", True)
        self.revise_send_button.clicked.connect(lambda: self._send_prompt_to_ollama("revise"))
        self.revise_cycle_combo = QComboBox()
        self.revise_cycle_combo.setToolTip("How many automatic LLM revise/retry cycles to allow for this send.")
        self.revise_apply_button = QPushButton("Apply Reply")
        self.revise_apply_button.clicked.connect(lambda: self._backup_and_apply_reply("revise"))
        self.revise_rename_session_button = QPushButton("Rename")
        self.revise_rename_session_button.setProperty("compact", True)
        self.revise_rename_session_button.clicked.connect(lambda: self._rename_session_from_combo("revise"))
        self.revise_delete_session_button = QPushButton("Delete")
        self.revise_delete_session_button.setProperty("compact", True)
        self.revise_delete_session_button.setProperty("danger", True)
        self.revise_delete_session_button.clicked.connect(lambda: self._delete_session_from_combo("revise"))

        cycle_default = int(self.settings.value("llm/max_cycles", UI_SIZES["llm_auto_cycle_max"], type=int))
        cycle_default = min(5, max(1, cycle_default))
        for combo in (self.process_cycle_combo, self.revise_cycle_combo):
            combo.setFixedWidth(72)
            for value in range(1, 6):
                combo.addItem(str(value), value)
            combo.setCurrentIndex(cycle_default - 1)
        self.process_cycle_combo.currentIndexChanged.connect(
            lambda _index: self._on_llm_cycle_changed("process")
        )
        self.revise_cycle_combo.currentIndexChanged.connect(
            lambda _index: self._on_llm_cycle_changed("revise")
        )

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "QTextEdit { background-color: #000000; color: #ffffff; border: 1px solid #333333; }"
        )
        self.log_output.setAcceptRichText(True)

        self.clear_session_button = QPushButton("Clear")
        self.clear_session_button.setProperty("compact", True)
        self.clear_session_button.setProperty("danger", True)
        self.clear_session_button.clicked.connect(self.clear_current_session)
        self.delete_selected_requests_button = QPushButton("Delete")
        self.delete_selected_requests_button.setProperty("compact", True)
        self.delete_selected_requests_button.setProperty("danger", True)
        self.delete_selected_requests_button.clicked.connect(self.delete_selected_requests)

        self._build_ui()
        self._set_capture_content_kinds(["json"])
        self._rebuild_reply_tabs("process", "")
        self._rebuild_reply_tabs("revise", "")
        self._apply_theme()
        self.reload_modules()
        self._ensure_control_paths()
        self.control_timer.start()

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK_STYLESHEET if self.dark_mode_check.isChecked() else LIGHT_STYLESHEET)
        for table in (
            self.endpoints_table,
            self.pages_table,
            self.raw_requests_table,
        ):
            table.setAlternatingRowColors(True)
        if self.dark_mode_check.isChecked():
            self.log_output.setStyleSheet(
                "QTextEdit { background-color: #000000; color: #ffffff; border: 1px solid #333333; }"
            )
        else:
            self.log_output.setStyleSheet(
                "QTextEdit { background-color: #ffffff; color: #111827; border: 1px solid #b7c2d0; }"
            )
        self._update_debug_limit_highlight()

    def _set_enabled_reason(self, widget: QWidget, enabled: bool, reason: str = "") -> None:
        widget.setEnabled(enabled)
        widget.setToolTip("" if enabled else reason)

    def _control_commands_dir(self) -> Path:
        return CONTROL_ROOT / "commands"

    def _control_responses_dir(self) -> Path:
        return CONTROL_ROOT / "responses"

    def _ensure_control_paths(self) -> None:
        self._control_commands_dir().mkdir(parents=True, exist_ok=True)
        self._control_responses_dir().mkdir(parents=True, exist_ok=True)

    def _splitter_settings_key(self, tab_index: int) -> str:
        return f"window/main_splitter/tab_{tab_index}"

    def _save_splitter_state_for_tab(self, tab_index: int) -> None:
        if hasattr(self, "main_splitter"):
            self.settings.setValue(self._splitter_settings_key(tab_index), self.main_splitter.saveState())

    def _restore_splitter_state_for_tab(self, tab_index: int) -> None:
        if not hasattr(self, "main_splitter"):
            return
        splitter_state = self.settings.value(self._splitter_settings_key(tab_index), b"")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)

    def _on_tab_changed(self, index: int) -> None:
        self._save_splitter_state_for_tab(self.current_tab_index)
        self.current_tab_index = index
        self._restore_splitter_state_for_tab(index)
        self.refresh_capture_sessions()

    def _flash_widget(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        widget.setProperty("automationFlash", True)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
        QTimer.singleShot(1800, lambda: self._clear_automation_flash(widget))

    def _clear_automation_flash(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        widget.setProperty("automationFlash", False)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _on_theme_toggled(self, _checked: bool) -> None:
        self._apply_theme()

    def _on_debug_mode_toggled(self, _checked: bool) -> None:
        self._update_debug_limit_highlight()

    def _on_capture_content_button_clicked(self, kind: str) -> None:
        if kind == "all":
            if self.capture_content_buttons["all"].isChecked():
                for other_kind, button in self.capture_content_buttons.items():
                    if other_kind != "all":
                        button.setChecked(False)
            else:
                self.capture_content_buttons["all"].setChecked(True)
        else:
            if self.capture_content_buttons[kind].isChecked():
                self.capture_content_buttons["all"].setChecked(False)
            elif not any(
                button.isChecked()
                for key, button in self.capture_content_buttons.items()
                if key != "all"
            ):
                self.capture_content_buttons["all"].setChecked(True)
        self._schedule_autosave()

    def _selected_capture_content_kinds(self) -> list[str]:
        selected = [
            key for key, button in self.capture_content_buttons.items() if button.isChecked()
        ]
        if not selected:
            return ["all"]
        if "all" in selected:
            return ["all"]
        return selected

    def _set_capture_content_kinds(self, kinds: list[str]) -> None:
        normalized = [kind.lower() for kind in kinds if kind]
        if not normalized:
            normalized = ["all"]
        use_all = "all" in normalized
        for key, button in self.capture_content_buttons.items():
            button.setChecked(use_all if key == "all" else (not use_all and key in normalized))

    def _toggle_record_blink(self) -> None:
        self.record_blink_on = not self.record_blink_on
        self._update_capture_toggle_button()

    def _update_capture_toggle_button(self) -> None:
        button = self.capture_toggle_button
        if not self.browser_running:
            self.record_blink_timer.stop()
            self.record_blink_on = True
            button.setEnabled(False)
            button.setChecked(False)
            button.setText("")
            button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            button.setToolTip("No managed browser capture session is active.")
            return
        if self.current_capture_dir is None or not self.current_capture_dir.exists():
            self.record_blink_timer.stop()
            self.record_blink_on = True
            button.setEnabled(True)
            button.setChecked(False)
            button.setProperty("danger", False)
            button.setProperty("success", True)
            button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            button.setText("")
            button.setToolTip("Start recording. A new capture session will be created automatically.")
            style = button.style()
            style.unpolish(button)
            style.polish(button)
            button.update()
            return
        recording = capture_enabled(self.current_capture_dir)
        button.setEnabled(True)
        button.setChecked(recording)
        if recording:
            if not self.record_blink_timer.isActive():
                self.record_blink_on = True
                self.record_blink_timer.start()
            button.setProperty("danger", True)
            button.setProperty("success", False)
            button.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton if self.record_blink_on else QStyle.SP_BrowserStop))
            button.setText("●" if self.record_blink_on else "")
            button.setToolTip("Stop recording for the current capture session.")
        else:
            self.record_blink_timer.stop()
            self.record_blink_on = True
            button.setProperty("danger", False)
            button.setProperty("success", True)
            button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            button.setText("")
            button.setToolTip("Start recording for the current capture session.")
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()

    def _set_invalid_state(self, widget: QWidget, invalid: bool, tooltip: str = "") -> None:
        widget.setProperty("invalid", invalid)
        widget.setToolTip(tooltip)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _normalize_base_url_input(self) -> None:
        raw = self.base_url_edit.text().strip()
        if not raw:
            self._set_invalid_state(self.base_url_edit, False, "")
            return
        candidate = raw
        if "://" not in candidate and ("." in candidate or candidate.startswith("localhost")):
            candidate = "https://" + candidate
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._set_invalid_state(
                self.base_url_edit,
                True,
                "Base URL should look like https://example.com",
            )
            return
        normalized = f"{parsed.scheme}://{parsed.netloc}"
        self._set_invalid_state(self.base_url_edit, False, normalized)
        if normalized != raw:
            self.base_url_edit.blockSignals(True)
            self.base_url_edit.setText(normalized)
            self.base_url_edit.blockSignals(False)
        self._schedule_autosave()

    def _schedule_autosave(self, *_args) -> None:
        self.autosave_timer.start()

    def _autosave_manifest_if_possible(self) -> None:
        if self.current_manifest is None:
            return
        self.save_manifest(silent=True, refresh=False)

    def _global_path_setting(self, key: str, default_relative: str) -> Path:
        raw_value = str(self.settings.value(key, default_relative) or default_relative).strip()
        path = Path(raw_value)
        if path.is_absolute():
            return path
        return APP_ROOT / path

    def _raw_capture_root(self) -> Path:
        return self._global_path_setting("paths/raw_capture_root", "har")

    def _processed_capture_root(self) -> Path:
        return self._global_path_setting("paths/processed_capture_root", "captures_processed")

    def _module_code_slug(self) -> str:
        if self.current_manifest is not None:
            return slugify_module_name(self.name_edit.text() or self.current_manifest.module_id)
        return slugify_module_name(self.name_edit.text())

    def _derived_package_path(self) -> str:
        return f"python/src/{self._module_code_slug()}"

    def _derived_client_file(self) -> str:
        return f"{self._derived_package_path()}/client.py"

    def _derived_client_class(self) -> str:
        return client_class_name(self._module_code_slug())

    def _module_processed_capture_dir(self) -> Path:
        if self.current_manifest is None:
            return self._processed_capture_root()
        return self._processed_capture_root() / self.current_manifest.module_id

    def _active_capture_session_state_path(self) -> Path:
        if self.current_manifest is None:
            return self._raw_capture_root() / ACTIVE_CAPTURE_SESSION_FILE
        return module_capture_root(self.current_manifest.module_id, base_root=self._raw_capture_root()) / ACTIVE_CAPTURE_SESSION_FILE

    def _set_active_capture_session(self, session_dir: Path | None) -> None:
        state_path = self._active_capture_session_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active_session": str(session_dir) if session_dir else ""}
        state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _create_capture_session(self, *, recording: bool = False) -> Path | None:
        if self.current_manifest is None:
            return None
        root = module_capture_root(self.current_manifest.module_id, base_root=self._raw_capture_root())
        root.mkdir(parents=True, exist_ok=True)
        session_dir = root / datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = 2
        while session_dir.exists():
            session_dir = root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"
            suffix += 1
        session_dir.mkdir(parents=True, exist_ok=True)
        set_capture_enabled(session_dir, recording)
        self._set_active_capture_session(session_dir)
        self.current_capture_dir = session_dir
        self.refresh_capture_sessions()
        self.log(f"Created capture session: {session_dir}")
        return session_dir

    def _module_llm_state_path(self) -> Path:
        module_id = self.current_manifest.module_id if self.current_manifest else "global"
        return Path("C:/tmp") / "web_api_builder_state" / f"{module_id}.json"

    def _load_module_llm_state(self) -> dict[str, object]:
        path = self._module_llm_state_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_module_llm_state(self, state: dict[str, object]) -> None:
        path = self._module_llm_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _mode_state(self, mode: str) -> dict[str, object]:
        state = self._load_module_llm_state()
        mode_state = state.setdefault(mode, {})
        changed = False
        if not isinstance(mode_state, dict):
            mode_state = {}
            state[mode] = mode_state
            changed = True
        request_state = str(mode_state.get("request_state") or "")
        if request_state in {"running", "retrying"} and mode not in self.pending_ollama_requests:
            mode_state["request_state"] = "failed"
            mode_state.setdefault("last_error", "Previous request did not finish cleanly.")
            if not str(mode_state.get("last_status") or "").strip():
                mode_state["last_status"] = "Previous request was interrupted."
            changed = True
        if changed:
            self._save_module_llm_state(state)
        return mode_state

    def _update_mode_state(self, mode: str, mode_state: dict[str, object]) -> None:
        state = self._load_module_llm_state()
        state[mode] = mode_state
        self._save_module_llm_state(state)

    def _persist_mode_runtime(
        self,
        mode: str,
        *,
        reply: str | None = None,
        summary: str | None = None,
        status: str | None = None,
        request_state: str | None = None,
        error: str | None = None,
    ) -> None:
        mode_state = self._mode_state(mode)
        if reply is not None:
            mode_state["last_reply"] = reply
        if summary is not None:
            mode_state["last_summary"] = summary
        if status is not None:
            mode_state["last_status"] = status
        if request_state is not None:
            mode_state["request_state"] = request_state
        if error is not None:
            mode_state["last_error"] = error
        mode_state["updated_at"] = datetime.now().isoformat()
        self._update_mode_state(mode, mode_state)

    def _restore_mode_runtime(self, mode: str) -> None:
        mode_state = self._mode_state(mode)
        reply = str(mode_state.get("last_reply") or "")
        summary = str(mode_state.get("last_summary") or "")
        status = str(mode_state.get("last_status") or "")
        self._set_reply_text_for_mode(mode, reply, persist=False)
        self._set_result_summary_for_mode(mode, summary, persist=False)
        if status:
            self._set_llm_status_message(mode, status, persist=False)

    def _module_name_changed(self) -> bool:
        return bool(self.current_manifest) and self.name_edit.text().strip() != self.last_loaded_module_name

    def _on_module_name_edit_finished(self) -> None:
        if self.suppress_name_change_prompt or self.current_manifest is None:
            return
        new_name = self.name_edit.text().strip()
        if not new_name or new_name == self.last_loaded_module_name:
            self.name_edit.setText(self.last_loaded_module_name)
            return
        if QMessageBox.question(
            self,
            "Rename Module",
            (
                f"Rename module '{self.last_loaded_module_name}' to '{new_name}'?\n\n"
                "This will update derived fields, rename scaffold folders/files where possible, "
                "and replace references to the old module name."
            ),
        ) != QMessageBox.Yes:
            self.suppress_name_change_prompt = True
            self.name_edit.setText(self.last_loaded_module_name)
            self.suppress_name_change_prompt = False
            return
        try:
            renamed = rename_module(self.current_manifest, new_name)
        except Exception as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))
            self.suppress_name_change_prompt = True
            self.name_edit.setText(self.last_loaded_module_name)
            self.suppress_name_change_prompt = False
            self.log(f"Rename failed: {exc}")
            return
        self.log(f"Renamed module '{self.last_loaded_module_name}' -> '{new_name}'")
        self.last_loaded_module_name = renamed.name
        self.current_manifest = renamed
        self.reload_modules()

    def _conversation_age_text(self, mode: str) -> str:
        mode_state = self._mode_state(mode)
        if bool(mode_state.get("force_reprime")):
            return "Full re-prime queued for next send."
        primer_at = str(mode_state.get("primer_sent_at") or "")
        if not primer_at:
            return "No primer sent yet."
        try:
            sent_at = datetime.fromisoformat(primer_at)
        except ValueError:
            return "Primer timestamp invalid."
        delta = datetime.now() - sent_at
        minutes = int(delta.total_seconds() // 60)
        return f"Last primed {minutes} minute(s) ago."

    def _refresh_llm_status_labels(self) -> None:
        if "process" not in self.pending_ollama_requests:
            process_state = self._mode_state("process")
            saved = str(process_state.get("last_status") or "")
            self.process_status_label.setText(saved or self._conversation_age_text("process"))
        if "revise" not in self.pending_ollama_requests:
            revise_state = self._mode_state("revise")
            saved = str(revise_state.get("last_status") or "")
            self.revise_status_label.setText(saved or self._conversation_age_text("revise"))

    def _clear_llm_mode(self, mode: str) -> None:
        state = self._load_module_llm_state()
        state[mode] = {
            "history": [],
            "primer_sent_at": None,
            "force_reprime": False,
            "last_reply": "",
            "last_summary": "",
            "last_status": "",
            "request_state": "idle",
            "last_error": "",
        }
        self._save_module_llm_state(state)
        if mode == "process":
            self._set_reply_text_for_mode(mode, "")
            self._set_result_summary_for_mode(mode, "")
        else:
            self.revise_history_output.clear()
            self._set_reply_text_for_mode(mode, "")
            self._set_result_summary_for_mode(mode, "")
        self._refresh_llm_status_labels()
        self.log(f"Cleared {mode} LLM conversation state.")

    def _queue_llm_reprime(self, mode: str) -> None:
        mode_state = self._mode_state(mode)
        mode_state["force_reprime"] = True
        self._update_mode_state(mode, mode_state)
        self._refresh_llm_status_labels()
        self.log(f"Queued {mode} LLM re-prime for next send.")

    def _format_history(self, mode: str) -> str:
        mode_state = self._mode_state(mode)
        history = mode_state.get("history") or []
        if not isinstance(history, list):
            return ""
        lines: list[str] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "assistant").upper()
            content = str(item.get("content") or "")
            lines.append(f"[{role}]\n{content}")
        return "\n\n".join(lines)

    def _refresh_revise_history(self) -> None:
        self.revise_history_output.setPlainText(self._format_history("revise"))
        self._refresh_llm_status_labels()

    def _global_prompts(self) -> list[dict[str, str]]:
        return self.prompt_library

    def _reload_prompt_library(self) -> None:
        self.prompt_library = load_prompt_library()
        self._refresh_prompt_combo()
        self.log("Reloaded prompt library.")

    def _ollama_base_url(self) -> str:
        host = self.ollama_host_edit.text().strip() or UI_SIZES["ollama_host_default"]
        port = self.ollama_port_edit.text().strip() or UI_SIZES["ollama_port_default"]
        return f"http://{host}:{port}"

    def _load_ollama_models(self) -> None:
        url = self._ollama_base_url() + "/api/tags"
        self.log(f"Loading Ollama models from {url}")
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.log(f"Ollama model load failed: {exc}")
            return
        models = [str(item.get("name") or "") for item in payload.get("models", []) if item.get("name")]
        current = self.ollama_model_combo.currentText().strip()
        saved_model = str(self.settings.value("ollama/model", "") or "").strip()
        preferred_model = current or saved_model
        self.ollama_model_combo.blockSignals(True)
        self.ollama_model_combo.clear()
        self.ollama_model_combo.addItems(models)
        if preferred_model:
            self.ollama_model_combo.setCurrentText(preferred_model)
        self.ollama_model_combo.blockSignals(False)
        self.log(f"Loaded {len(models)} Ollama model(s).")

    def _refresh_actions_session_combo(self) -> None:
        shared_current = None
        if self.current_capture_dir is not None:
            shared_current = str(self.current_capture_dir)
        else:
            shared_current = self.actions_session_combo.currentData() or self.revise_session_combo.currentData()
        sessions = (
            load_capture_sessions_for_manifest(self.current_manifest, base_root=self._raw_capture_root())
            if self.current_manifest
            else load_raw_capture_sessions(base_root=self._raw_capture_root())
        )
        for combo in (self.actions_session_combo, self.revise_session_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(-1)
            combo.clear()
            for session in sessions:
                combo.addItem(session.name, str(session))
            combo.blockSignals(False)
            if shared_current:
                restored = False
                for index in range(combo.count()):
                    if combo.itemData(index) == shared_current:
                        combo.setCurrentIndex(index)
                        restored = True
                        break
                if restored:
                    continue
            if sessions:
                combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(-1)
        self._update_session_count_labels()
        self._update_llm_action_buttons()

    def _update_llm_action_buttons(self) -> None:
        process_session_ok = self._session_path_for_mode("process") is not None
        revise_session_ok = self._session_path_for_mode("revise") is not None
        process_prompt_ok = bool(self.prompt_combo.currentText().strip()) and bool(self.prompt_editor.toPlainText().strip())
        revise_prompt_ok = bool(self.revise_prompt_editor.toPlainText().strip())
        process_busy = "process" in self.pending_ollama_requests
        revise_busy = "revise" in self.pending_ollama_requests
        self._set_enabled_reason(
            self.process_send_button,
            (process_session_ok and process_prompt_ok and not process_busy),
            "Wait for the current LLM request to finish." if process_busy else "Session and prompt must be selected before sending to the LLM.",
        )
        self._set_enabled_reason(
            self.process_apply_button,
            bool(self.ollama_reply_output.toPlainText().strip()) and not process_busy,
            "Wait for the current LLM request to finish." if process_busy else "There is no LLM reply to apply yet.",
        )
        self._set_enabled_reason(
            self.process_rename_session_button,
            process_session_ok,
            "You need to select a session first.",
        )
        self._set_enabled_reason(
            self.process_delete_session_button,
            process_session_ok,
            "You need to select a session first.",
        )
        self._set_enabled_reason(
            self.revise_send_button,
            (revise_session_ok and revise_prompt_ok and not revise_busy),
            "Wait for the current LLM request to finish." if revise_busy else "Session and request text must be provided before sending to the LLM.",
        )
        self._set_enabled_reason(
            self.revise_apply_button,
            bool(self.revise_reply_output.toPlainText().strip()) and not revise_busy,
            "Wait for the current LLM request to finish." if revise_busy else "There is no LLM reply to apply yet.",
        )
        self._set_enabled_reason(
            self.revise_rename_session_button,
            revise_session_ok,
            "You need to select a session first.",
        )
        self._set_enabled_reason(
            self.revise_delete_session_button,
            revise_session_ok,
            "You need to select a session first.",
        )

    def _update_session_count_labels(self) -> None:
        for mode, label in (
            ("process", self.actions_session_count_label),
            ("revise", self.revise_session_count_label),
        ):
            session_path = self._session_path_for_mode(mode)
            if session_path is None or not session_path.exists():
                label.setText("")
                continue
            entry_count = len(load_raw_capture_entries(session_path))
            noun = "Entry" if entry_count == 1 else "Entries"
            label.setText(f"[{entry_count} {noun}]")

    def _refresh_prompt_combo(self) -> None:
        current = self.prompt_combo.currentData()
        prompts = self._global_prompts()
        self.prompt_combo.blockSignals(True)
        self.prompt_combo.clear()
        for index, prompt in enumerate(prompts):
            self.prompt_combo.addItem(str(prompt.get("name") or f"Prompt {index + 1}"), index)
        self.prompt_combo.blockSignals(False)
        if current is not None:
            for index in range(self.prompt_combo.count()):
                if self.prompt_combo.itemData(index) == current:
                    self.prompt_combo.setCurrentIndex(index)
                    self._on_prompt_selected(index)
                    return
        if prompts:
            self.prompt_combo.setCurrentIndex(0)
            self._on_prompt_selected(0)
        else:
            self.prompt_description_edit.clear()
            self.prompt_editor.clear()

    def _on_prompt_selected(self, index: int) -> None:
        prompts = self._global_prompts()
        if index < 0 or index >= len(prompts):
            self.prompt_description_edit.clear()
            self.prompt_editor.clear()
            self._update_llm_action_buttons()
            return
        self.prompt_description_edit.setText(str(prompts[index].get("description") or ""))
        self.prompt_editor.setPlainText(str(prompts[index].get("text") or ""))
        self._update_llm_action_buttons()

    def _new_prompt(self) -> None:
        name, ok = QInputDialog.getText(self, "New Prompt", "Prompt name:")
        if not ok or not name.strip():
            return
        self._global_prompts().append({"name": name.strip(), "description": "", "text": ""})
        save_prompt_library(self.prompt_library)
        self._refresh_prompt_combo()
        self.prompt_combo.setCurrentText(name.strip())
        self.prompt_description_edit.clear()
        self.log(f"Created prompt: {name.strip()}")

    def _save_prompt(self) -> None:
        prompts = self._global_prompts()
        index = self.prompt_combo.currentIndex()
        if index < 0:
            self._new_prompt()
            return
        prompts[index]["text"] = self.prompt_editor.toPlainText()
        prompts[index]["name"] = str(self.prompt_combo.currentText() or prompts[index].get("name") or "").strip()
        prompts[index]["description"] = self.prompt_description_edit.text().strip()
        save_prompt_library(self.prompt_library)
        self._refresh_prompt_combo()
        self.log(f"Saved prompt: {prompts[index]['name']}")

    def _delete_prompt(self) -> None:
        prompts = self._global_prompts()
        index = self.prompt_combo.currentIndex()
        if index < 0 or index >= len(prompts):
            return
        prompt_name = str(prompts[index].get("name") or "prompt")
        if QMessageBox.question(self, "Delete Prompt", f"Delete prompt '{prompt_name}'?") != QMessageBox.Yes:
            return
        prompts.pop(index)
        save_prompt_library(self.prompt_library)
        self._refresh_prompt_combo()
        self.log(f"Deleted prompt: {prompt_name}")

    def _selected_capture_paths_for_actions(self, session_path: Path) -> list[Path]:
        selected_paths: list[Path] = []
        if self.current_capture_dir is not None and self.current_capture_dir == session_path:
            for row in sorted({item.row() for item in self.raw_requests_table.selectedItems()}):
                item = self.raw_requests_table.item(row, 0)
                if item is None:
                    continue
                path_value = item.data(Qt.UserRole)
                if path_value:
                    selected_paths.append(Path(str(path_value)))
        if selected_paths:
            return [path for path in selected_paths if path.exists()]
        return [
            Path(str(entry.get("path")))
            for entry in load_raw_capture_entries(session_path)
            if entry.get("path")
        ]

    def _module_api_paths(self) -> list[Path]:
        if self.current_manifest is None:
            return []
        module_data = self.current_manifest.data.get("module", {})
        package_path_value = str(module_data.get("package_path") or self._derived_package_path())
        package_path = APP_ROOT / package_path_value
        paths: list[Path] = []
        if package_path.exists():
            paths.extend(sorted(path for path in package_path.rglob("*.py") if path.is_file()))
        client_file_value = str(module_data.get("client_file") or self._derived_client_file())
        client_file = APP_ROOT / client_file_value
        if client_file.exists() and client_file not in paths:
            paths.append(client_file)
        smoke_path = APP_ROOT / "tests" / f"{self._module_code_slug()}_smoke.py"
        if smoke_path.exists():
            paths.append(smoke_path)
        manifest_path = self.current_manifest.path
        if manifest_path.exists():
            paths.append(manifest_path)
        unique: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def _relative_repo_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(APP_ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return str(path)

    def _build_llm_bundle(self, *, session_path: Path, capture_paths: list[Path], prompt_text: str) -> tuple[Path, Path, str]:
        if self.current_manifest is None:
            raise RuntimeError("No module selected.")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bundle_root = Path("C:/tmp") / "web_api_builder_context" / self.current_manifest.module_id / timestamp
        files_dir = bundle_root / "files"
        captures_dir = bundle_root / "captures"
        files_dir.mkdir(parents=True, exist_ok=True)
        captures_dir.mkdir(parents=True, exist_ok=True)

        prompt_path = bundle_root / "prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        api_sections: list[str] = []
        for path in self._module_api_paths():
            rel = self._relative_repo_path(path)
            target = files_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.copy2(path, target)
                body = path.read_text(encoding="utf-8", errors="replace")
            else:
                body = ""
            api_sections.append(f"=== FILE: {rel} ===\n{body}\n=== END FILE ===")

        capture_sections: list[str] = []
        for path in capture_paths:
            rel = path.name
            target = captures_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.copy2(path, target)
                body = path.read_text(encoding="utf-8", errors="replace")
                capture_sections.append(f"=== CAPTURE: {rel} ===\n{body}\n=== END CAPTURE ===")

        zip_path = bundle_root.with_suffix(".zip")
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for item in bundle_root.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(bundle_root))

        inline_context = (
            f"Selected module: {self.current_manifest.module_id}\n"
            f"Selected capture session: {session_path}\n"
            f"Context bundle zip: {zip_path}\n\n"
            "Current API/module files:\n"
            + "\n\n".join(api_sections)
            + "\n\nSelected captures:\n"
            + "\n\n".join(capture_sections)
        )
        return bundle_root, zip_path, inline_context

    def _build_ollama_prompt(self, *, session_path: Path, capture_paths: list[Path], prompt_text: str) -> tuple[Path, Path, str]:
        bundle_root, zip_path, inline_context = self._build_llm_bundle(
            session_path=session_path,
            capture_paths=capture_paths,
            prompt_text=prompt_text,
        )
        wrapper = """You are editing files in an existing local repository.

Use the provided project files and captured requests to update the Python API module.

The target output must be a real importable Python module/package for communicating with the target web application.
The target is NOT:
- a Flask app
- a FastAPI app
- a demo web server
- mocked endpoint handlers
- hard-coded fake response data
- browser automation unless the task explicitly asks for helper tooling

Repository shape requirements:
- Implement or update reusable client code under the existing module package path.
- Preserve the repo's package-oriented structure.
- Prefer client classes, request helpers, and smoke tests.
- If tests are returned, they should test the module/client, not stand up a server.

Response format requirements:
- Return only changed files.
- For each changed file, use this exact format:
<<<FILE: relative/path/from/repo/root>>>
<full replacement file contents>
<<<END FILE>>>
- You may optionally include one summary block first:
<<<SUMMARY>>>
<brief summary>
<<<END SUMMARY>>>
- Do not use markdown fences around file contents.
- Do not omit unchanged imports or context if a file is returned; each file block must contain the full final file contents.
"""
        full_prompt = (
            wrapper
            + "\nUser task:\n"
            + prompt_text
            + "\n\nRepository and capture context:\n"
            + inline_context
        )
        return bundle_root, zip_path, full_prompt

    def _send_generate_request(self, *, model: str, prompt: str, timeout: int = 120) -> str:
        url = self._ollama_base_url() + "/api/generate"
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

    def _build_reformat_prompt(self, *, prior_reply: str) -> str:
        if self.current_manifest is None:
            return prior_reply
        module_data = self.current_manifest.data.get("module", {})
        candidate_files = [
            str(module_data.get("client_file") or self._derived_client_file()).replace("\\", "/"),
            f"tests/{self._module_code_slug()}_smoke.py",
            str(self.current_manifest.path.relative_to(APP_ROOT)).replace("\\", "/"),
        ]
        return (
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
            "- The output must remain a real importable Python module/package, not a Flask/FastAPI server or mocked web app.\n"
            "- Do not include markdown fences.\n"
            "- Do not include prose, explanations, or headings.\n\n"
            "Prior answer to rewrite:\n"
            + prior_reply
        )

    def _reformat_reply_to_file_blocks(self, *, model: str, prior_reply: str) -> str:
        prompt = self._build_reformat_prompt(prior_reply=prior_reply)
        return self._send_generate_request(model=model, prompt=prompt, timeout=120)

    def _detect_wrong_shape_reply(self, reply: str) -> list[str]:
        findings: list[str] = []
        lowered = reply.lower()
        if "from flask import" in lowered or "flask(" in lowered or "@app.route" in lowered:
            findings.append("looks like a Flask app/server, not a reusable client module")
        if "from fastapi import" in lowered or "fastapi(" in lowered:
            findings.append("looks like a FastAPI/server app, not a reusable client module")
        if "mock data" in lowered or "hard-coded fake" in lowered:
            findings.append("contains mocked or fake data language")
        return findings

    def _validate_reply_for_module(self, reply: str) -> dict[str, object]:
        file_blocks = self._parse_reply_file_blocks(reply)
        issues: list[str] = []
        warnings: list[str] = []
        issues.extend(self._detect_wrong_shape_reply(reply))
        if self.current_manifest is None:
            return {
                "rating": "Needs revision",
                "retry": False,
                "issues": ["No module is selected."],
                "warnings": [],
                "file_count": len(file_blocks),
                "public_method_count": 0,
            }
        if not file_blocks:
            issues.append("No valid <<<FILE>>> blocks were returned.")
            return {
                "rating": "Needs revision",
                "retry": True,
                "issues": issues,
                "warnings": warnings,
                "file_count": 0,
                "public_method_count": 0,
            }
        file_map = {path.replace("\\", "/"): content for path, content in file_blocks}
        module_data = self.current_manifest.data.get("module", {})
        client_file = str(module_data.get("client_file") or self._derived_client_file()).replace("\\", "/")
        smoke_file = f"tests/{self._module_code_slug()}_smoke.py"
        client_class = str(module_data.get("client_class") or self._derived_client_class())
        public_method_count = 0
        existing_public_methods = self._current_client_public_methods(client_file, client_class)

        for relative_path, content in file_map.items():
            if relative_path.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    issues.append(f"{relative_path} has a Python syntax error: {exc.msg} (line {exc.lineno})")

        client_content = file_map.get(client_file)
        if not client_content:
            issues.append(f"Expected updated client module '{client_file}' was not returned.")
        else:
            try:
                tree = ast.parse(client_content)
            except SyntaxError:
                pass
            else:
                class_node: ast.ClassDef | None = None
                for node in tree.body:
                    if isinstance(node, ast.ClassDef) and node.name == client_class:
                        class_node = node
                        break
                if class_node is None:
                    issues.append(f"Client class '{client_class}' was not found in {client_file}.")
                else:
                    returned_public_methods = {
                        item.name
                        for item in class_node.body
                        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
                    }
                    public_method_count = sum(
                        1
                        for item in class_node.body
                        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
                    )
                    if public_method_count == 0:
                        issues.append(f"Client class '{client_class}' does not expose any public methods yet.")
                    missing_methods = sorted(existing_public_methods - returned_public_methods)
                    if missing_methods:
                        issues.append(
                            f"Client reply removed existing public method(s): {', '.join(missing_methods)}."
                        )

        smoke_content = file_map.get(smoke_file)
        if not smoke_content:
            warnings.append(f"Smoke test '{smoke_file}' was not returned.")
        else:
            import_markers = (
                f"from {self._module_code_slug()} import {client_class}",
                f"from {self._module_code_slug()}.client import {client_class}",
            )
            if not any(marker in smoke_content for marker in import_markers):
                issues.append(f"Smoke test '{smoke_file}' does not appear to import {client_class} correctly.")
            if client_content:
                available_methods = self._public_methods_from_source(client_content, client_class)
                smoke_calls = self._smoke_test_method_calls(smoke_content)
                missing_called_methods = sorted(name for name in smoke_calls if name not in available_methods)
                if missing_called_methods:
                    issues.append(
                        f"Smoke test '{smoke_file}' calls method(s) not present in {client_file}: "
                        + ", ".join(missing_called_methods)
                        + "."
                    )

        if issues:
            rating = "Needs revision"
            retry = True
        elif warnings:
            rating = "Structurally valid"
            retry = True
        else:
            rating = "Likely usable"
            retry = False
        return {
            "rating": rating,
            "retry": retry,
            "issues": issues,
            "warnings": warnings,
            "file_count": len(file_blocks),
            "public_method_count": public_method_count,
        }

    def _public_methods_from_source(self, source: str, client_class: str) -> set[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == client_class:
                return {
                    item.name
                    for item in node.body
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
                }
        return set()

    def _current_client_public_methods(self, relative_path: str, client_class: str) -> set[str]:
        path = APP_ROOT / relative_path
        if not path.exists():
            return set()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        return self._public_methods_from_source(source, client_class)

    def _smoke_test_method_calls(self, smoke_source: str) -> set[str]:
        return set(re.findall(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", smoke_source))

    def _build_retry_followup_prompt(self, *, request_context: dict[str, object], reply: str, validation: dict[str, object]) -> str:
        issues = [str(item) for item in (validation.get("issues") or [])]
        warnings = [str(item) for item in (validation.get("warnings") or [])]
        problem_lines = [f"- {item}" for item in issues + warnings]
        return (
            str(request_context.get("full_prompt") or "")
            + "\n\nAutomatic validation feedback from the previous attempt:\n"
            + ("\n".join(problem_lines) if problem_lines else "- The previous attempt was incomplete.")
            + "\n\nPlease revise the returned files so they satisfy the repository constraints and fix every issue above."
            "\nReturn only full replacement file blocks in the required <<<FILE>>> format."
            "\nKeep the result as a real importable Python client module package, not a server app."
            "\n\nPrevious attempt to revise:\n"
            + reply
        )

    def _parse_reply_file_blocks(self, reply: str) -> list[tuple[str, str]]:
        pattern = re.compile(
            r"<<<FILE:\s*(?P<path>[^>]+?)>>>\s*\n(?P<body>.*?)\n<<<END FILE>>>",
            re.DOTALL,
        )
        return [(match.group("path").strip(), match.group("body")) for match in pattern.finditer(reply)]

    def _reply_widgets_for_mode(self, mode: str) -> tuple[QTextEdit, QTabWidget]:
        if mode == "revise":
            return self.revise_reply_output, self.revise_reply_tabs
        return self.ollama_reply_output, self.process_reply_tabs

    def _build_diff_text(self, relative_path: str, new_content: str) -> str:
        candidate = (APP_ROOT / relative_path).resolve()
        old_content = ""
        try:
            candidate.relative_to(APP_ROOT.resolve())
        except ValueError:
            old_lines = []
        else:
            if candidate.exists():
                old_content = candidate.read_text(encoding="utf-8", errors="replace")
            old_lines = old_content.splitlines()
        new_lines = new_content.rstrip().splitlines()
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        return "\n".join(diff_lines) if diff_lines else f"No textual diff for {relative_path}."

    @staticmethod
    def _diff_to_html(diff_text: str) -> str:
        escaped_lines: list[str] = []
        for line in diff_text.splitlines():
            safe = (
                line.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            if line.startswith("+++") or line.startswith("---"):
                escaped_lines.append(f"<span style='color:#7fb3ff;'>{safe}</span>")
            elif line.startswith("@@"):
                escaped_lines.append(f"<span style='color:#e2c672;'>{safe}</span>")
            elif line.startswith("+"):
                escaped_lines.append(f"<span style='color:#7ad97a;'>{safe}</span>")
            elif line.startswith("-"):
                escaped_lines.append(f"<span style='color:#ff8a8a;'>{safe}</span>")
            else:
                escaped_lines.append(safe)
        return (
            "<html><body style=\"font-family:'Consolas','Courier New',monospace; white-space:pre;\">"
            + "<br/>".join(escaped_lines)
            + "</body></html>"
        )

    def _reply_review_widgets(self, mode: str) -> tuple[QListWidget, QTextEdit]:
        if mode == "revise":
            return self.revise_diff_list, self.revise_diff_view
        return self.process_diff_list, self.process_diff_view

    def _reply_review_header_widgets(self, mode: str) -> tuple[QLabel, QCheckBox]:
        if mode == "revise":
            return self.revise_diff_stats_label, self.revise_diff_apply_check
        return self.process_diff_stats_label, self.process_diff_apply_check

    @staticmethod
    def _diff_add_remove_counts(diff_text: str) -> tuple[int, int]:
        additions = 0
        removals = 0
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                removals += 1
        return additions, removals

    def _selected_reply_file_blocks(self, mode: str) -> list[tuple[str, str]]:
        selections = self.reply_apply_selection.get(mode) or {}
        file_blocks = self._parse_reply_file_blocks(self._reply_text_for_mode(mode))
        return [(path, content) for path, content in file_blocks if selections.get(path.replace("\\", "/"), True)]

    def _update_apply_tab_tooltip(self, mode: str) -> None:
        selected_count = len(self._selected_reply_file_blocks(mode))
        button = self.revise_apply_button if mode == "revise" else self.process_apply_button
        button.setToolTip(f"Apply the currently checked file changes from the latest LLM reply. [{selected_count} selected]")

    def _build_single_file_diff_tab(self, mode: str, relative_path: str, content: str) -> QWidget:
        normalized = relative_path.replace("\\", "/")
        diff_text = self._build_diff_text(relative_path, content)
        additions, removals = self._diff_add_remove_counts(diff_text)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        stats_label = QLabel(f"[+{additions} / -{removals}]")
        apply_check = QCheckBox("Apply these changes")
        apply_check.setChecked(self.reply_apply_selection.get(mode, {}).get(normalized, True))
        apply_check.toggled.connect(lambda checked, m=mode, p=normalized: self._on_inline_apply_toggled(m, p, checked))
        header.addWidget(stats_label)
        header.addStretch(1)
        header.addWidget(apply_check)
        layout.addLayout(header)
        diff_view = QTextEdit()
        diff_view.setReadOnly(True)
        diff_view.setHtml(self._diff_to_html(diff_text))
        diff_view.moveCursor(QTextCursor.Start)
        layout.addWidget(diff_view, stretch=1)
        return container

    def _build_review_tab(self, mode: str, file_blocks: list[tuple[str, str]]) -> QWidget:
        diff_list, diff_view = self._reply_review_widgets(mode)
        stats_label, apply_check = self._reply_review_header_widgets(mode)
        diff_list.clear()
        diff_view.clear()
        diff_list.setFixedWidth(UI_SIZES["reply_diff_list_width"])
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(stats_label)
        header.addStretch(1)
        header.addWidget(apply_check)
        right_layout.addLayout(header)
        right_layout.addWidget(diff_view, stretch=1)
        layout.addWidget(diff_list)
        layout.addWidget(right, stretch=1)
        stats_label.clear()
        apply_check.blockSignals(True)
        apply_check.setChecked(True)
        apply_check.blockSignals(False)
        for relative_path, content in file_blocks:
            normalized = relative_path.replace("\\", "/")
            diff_text = self._build_diff_text(relative_path, content)
            additions, removals = self._diff_add_remove_counts(diff_text)
            item = QListWidgetItem(Path(relative_path).name or relative_path)
            item.setToolTip(relative_path)
            item.setData(
                Qt.UserRole,
                {
                    "path": normalized,
                    "diff_text": diff_text,
                    "additions": additions,
                    "removals": removals,
                },
            )
            diff_list.addItem(item)
        if diff_list.count() > 0:
            diff_list.setCurrentRow(0)
        return container

    def _on_inline_apply_toggled(self, mode: str, relative_path: str, checked: bool) -> None:
        self.reply_apply_selection.setdefault(mode, {})[relative_path] = checked
        self._update_apply_tab_tooltip(mode)

    def _on_review_apply_toggled(self, mode: str, checked: bool) -> None:
        diff_list, _diff_view = self._reply_review_widgets(mode)
        current = diff_list.currentItem()
        if current is None:
            return
        data = current.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        relative_path = str(data.get("path") or "")
        if not relative_path:
            return
        self.reply_apply_selection.setdefault(mode, {})[relative_path] = checked
        self._update_apply_tab_tooltip(mode)

    def _on_diff_item_changed(self, mode: str, current: QListWidgetItem | None) -> None:
        _diff_list, diff_view = self._reply_review_widgets(mode)
        stats_label, apply_check = self._reply_review_header_widgets(mode)
        if current is None:
            diff_view.clear()
            stats_label.clear()
            return
        data = current.data(Qt.UserRole)
        if not isinstance(data, dict):
            diff_view.clear()
            stats_label.clear()
            return
        relative_path = str(data.get("path") or "")
        diff_text = str(data.get("diff_text") or "")
        additions = int(data.get("additions") or 0)
        removals = int(data.get("removals") or 0)
        diff_view.setHtml(self._diff_to_html(str(diff_text)))
        diff_view.moveCursor(QTextCursor.Start)
        stats_label.setText(f"[+{additions} / -{removals}]")
        apply_check.blockSignals(True)
        apply_check.setChecked(self.reply_apply_selection.get(mode, {}).get(relative_path, True))
        apply_check.blockSignals(False)

    def _rebuild_reply_tabs(self, mode: str, text: str) -> None:
        reply_output, reply_tabs = self._reply_widgets_for_mode(mode)
        file_blocks = self._parse_reply_file_blocks(text)
        self.reply_apply_selection[mode] = {
            path.replace("\\", "/"): self.reply_apply_selection.get(mode, {}).get(path.replace("\\", "/"), True)
            for path, _content in file_blocks
        }
        reply_tabs.blockSignals(True)
        reply_tabs.clear()
        reply_tabs.addTab(reply_output, "Chat")
        if file_blocks:
            if len(file_blocks) > UI_SIZES["reply_many_files_threshold"]:
                review_tab = self._build_review_tab(mode, file_blocks)
                reply_tabs.addTab(review_tab, "Changes")
                reply_tabs.setTabToolTip(reply_tabs.count() - 1, f"{len(file_blocks)} changed files")
            else:
                for relative_path, content in file_blocks:
                    diff_view = self._build_single_file_diff_tab(mode, relative_path, content)
                    tab_name = Path(relative_path).name or relative_path
                    reply_tabs.addTab(diff_view, tab_name)
                    reply_tabs.setTabToolTip(reply_tabs.count() - 1, relative_path)
        reply_tabs.setCurrentIndex(0)
        reply_tabs.blockSignals(False)
        self._update_apply_tab_tooltip(mode)

    def _reply_text_for_mode(self, mode: str) -> str:
        reply_output, _reply_tabs = self._reply_widgets_for_mode(mode)
        return reply_output.toPlainText().strip()

    def _set_reply_text_for_mode(self, mode: str, text: str, *, persist: bool = True) -> None:
        reply_output, reply_tabs = self._reply_widgets_for_mode(mode)
        reply_output.setPlainText(text)
        reply_output.moveCursor(QTextCursor.End)
        reply_output.ensureCursorVisible()
        self._rebuild_reply_tabs(mode, text)
        reply_tabs.setCurrentIndex(0)
        if persist:
            self._persist_mode_runtime(mode, reply=text)

    def _append_reply_chunk_for_mode(self, mode: str, text: str) -> None:
        reply_output, reply_tabs = self._reply_widgets_for_mode(mode)
        reply_output.blockSignals(True)
        reply_output.setPlainText(text)
        reply_output.blockSignals(False)
        reply_output.moveCursor(QTextCursor.End)
        reply_output.ensureCursorVisible()
        reply_tabs.setCurrentIndex(0)
        self._persist_mode_runtime(mode, reply=text)

    def _set_result_summary_for_mode(self, mode: str, text: str, *, persist: bool = True) -> None:
        if mode == "revise":
            self.revise_result_summary_label.setText(text)
        else:
            self.process_result_summary_label.setText(text)
        if persist:
            self._persist_mode_runtime(mode, summary=text)

    def _set_llm_busy(self, mode: str, busy: bool) -> None:
        if mode == "revise":
            button = self.revise_send_button
            status = self.revise_status_label
        else:
            button = self.process_send_button
            status = self.process_status_label
        if busy:
            button.setEnabled(False)
            button.setText("Sending...")
            status.setText("Working...")
        else:
            button.setText("Send")
            self._refresh_llm_status_labels()

    def _set_llm_status_message(self, mode: str, text: str, *, persist: bool = True) -> None:
        if mode == "revise":
            self.revise_status_label.setText(text)
        else:
            self.process_status_label.setText(text)
        if persist:
            self._persist_mode_runtime(mode, status=text)

    def _current_llm_cycle_count(self, mode: str) -> int:
        combo = self.revise_cycle_combo if mode == "revise" else self.process_cycle_combo
        value = combo.currentData()
        try:
            return min(5, max(1, int(value or combo.currentText() or UI_SIZES["llm_auto_cycle_max"])))
        except ValueError:
            return int(UI_SIZES["llm_auto_cycle_max"])

    def _on_llm_cycle_changed(self, source_mode: str) -> None:
        value = self._current_llm_cycle_count(source_mode)
        other = self.process_cycle_combo if source_mode == "revise" else self.revise_cycle_combo
        if other.currentData() != value:
            other.blockSignals(True)
            for index in range(other.count()):
                if int(other.itemData(index) or 0) == value:
                    other.setCurrentIndex(index)
                    break
            other.blockSignals(False)
        self.settings.setValue("llm/max_cycles", value)

    def _editor_text_for_mode(self, mode: str) -> str:
        if mode == "revise":
            return self.revise_prompt_editor.toPlainText().strip()
        return self.prompt_editor.toPlainText().strip()

    def _session_path_for_mode(self, mode: str) -> Path | None:
        combo = self.revise_session_combo if mode == "revise" else self.actions_session_combo
        value = combo.currentData()
        if not value:
            return None
        return Path(str(value))

    def _tab_names(self) -> list[str]:
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def _tab_index_by_name(self, name: str) -> int:
        lowered = name.strip().lower()
        for index, label in enumerate(self._tab_names()):
            if label.lower() == lowered:
                return index
        raise ValueError(f"Unknown tab '{name}'. Known tabs: {', '.join(self._tab_names())}")

    def _set_combo_to_text(self, combo: QComboBox, value: str) -> bool:
        for index in range(combo.count()):
            if combo.itemText(index) == value or str(combo.itemData(index) or "") == value:
                combo.setCurrentIndex(index)
                return True
        return False

    def _get_control_state(self) -> dict[str, object]:
        process_mode_state = self._mode_state("process")
        revise_mode_state = self._mode_state("revise")
        pages = []
        for row in range(self.pages_table.rowCount()):
            name_item = self.pages_table.item(row, 0)
            route_item = self.pages_table.item(row, 1)
            pages.append(
                {
                    "name": name_item.text() if name_item is not None else "",
                    "route": route_item.text() if route_item is not None else "",
                }
            )
        return {
            "module_id": self.current_manifest.module_id if self.current_manifest else "",
            "tab": self.tabs.tabText(self.tabs.currentIndex()),
            "process_session": self.actions_session_combo.currentText(),
            "process_prompt": self.prompt_combo.currentText(),
            "process_summary": self.process_result_summary_label.text(),
            "process_reply_length": len(self.ollama_reply_output.toPlainText()),
            "process_file_blocks": len(self._parse_reply_file_blocks(self.ollama_reply_output.toPlainText())),
            "process_request_state": str(process_mode_state.get("request_state") or ("running" if "process" in self.pending_ollama_requests else "idle")),
            "process_status": self.process_status_label.text(),
            "process_last_error": str(process_mode_state.get("last_error") or ""),
            "revise_session": self.revise_session_combo.currentText(),
            "revise_summary": self.revise_result_summary_label.text(),
            "revise_reply_length": len(self.revise_reply_output.toPlainText()),
            "revise_file_blocks": len(self._parse_reply_file_blocks(self.revise_reply_output.toPlainText())),
            "revise_request_state": str(revise_mode_state.get("request_state") or ("running" if "revise" in self.pending_ollama_requests else "idle")),
            "revise_status": self.revise_status_label.text(),
            "revise_last_error": str(revise_mode_state.get("last_error") or ""),
            "endpoint_count": self.endpoints_table.rowCount(),
            "route_count": self.pages_table.rowCount(),
            "pages": pages,
            "browser_running": self.browser_running,
        }

    def _press_button_by_id(self, button_id: str) -> None:
        mapping: dict[str, tuple[QPushButton, callable]] = {
            "process_send": (self.process_send_button, lambda: self._send_prompt_to_ollama("process")),
            "process_apply": (
                self.process_apply_button,
                lambda: self._backup_and_apply_reply("process", confirm=False, apply_all_if_none_selected=True),
            ),
            "revise_send": (self.revise_send_button, lambda: self._send_prompt_to_ollama("revise")),
            "revise_apply": (
                self.revise_apply_button,
                lambda: self._backup_and_apply_reply("revise", confirm=False, apply_all_if_none_selected=True),
            ),
            "process_reprime": (None, lambda: self._queue_llm_reprime("process")),
            "revise_reprime": (None, lambda: self._queue_llm_reprime("revise")),
            "new_capture": (self.run_new_button, self.open_new_capture_session),
            "capture_toggle": (self.capture_toggle_button, self.toggle_capture_enabled),
        }
        if button_id not in mapping:
            raise ValueError(f"Unknown button id '{button_id}'")
        widget, callback = mapping[button_id]
        if widget is not None:
            if not widget.isEnabled():
                raise ValueError(f"Button '{button_id}' is disabled.")
            self._flash_widget(widget)
        callback()

    def _handle_control_command(self, payload: dict[str, object]) -> dict[str, object]:
        command = str(payload.get("command") or "").strip()
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if command == "get_state":
            return self._get_control_state()
        if command == "switch_tab":
            tab_name = str(args.get("name") or "")
            index = self._tab_index_by_name(tab_name)
            self.tabs.setCurrentIndex(index)
            self._flash_widget(self.tabs)
            return self._get_control_state()
        if command == "select_module":
            module_id = str(args.get("module_id") or "")
            if not self._set_combo_to_text(self.module_combo, module_id):
                raise ValueError(f"Unknown module '{module_id}'")
            self._flash_widget(self.module_combo)
            return self._get_control_state()
        if command == "select_process_session":
            session = str(args.get("session") or "")
            if not self._set_combo_to_text(self.actions_session_combo, session):
                raise ValueError(f"Unknown process session '{session}'")
            self._flash_widget(self.actions_session_combo)
            return self._get_control_state()
        if command == "select_revise_session":
            session = str(args.get("session") or "")
            if not self._set_combo_to_text(self.revise_session_combo, session):
                raise ValueError(f"Unknown revise session '{session}'")
            self._flash_widget(self.revise_session_combo)
            return self._get_control_state()
        if command == "select_prompt":
            prompt = str(args.get("name") or "")
            if not self._set_combo_to_text(self.prompt_combo, prompt):
                raise ValueError(f"Unknown prompt '{prompt}'")
            self._flash_widget(self.prompt_combo)
            return self._get_control_state()
        if command == "set_model":
            model = str(args.get("model") or "")
            self.ollama_model_combo.setCurrentText(model)
            self._flash_widget(self.ollama_model_combo)
            self._schedule_autosave()
            return self._get_control_state()
        if command == "open_page_route":
            page_name = str(args.get("page") or "")
            if not self._open_page_route_by_name(page_name):
                raise ValueError(f"Unknown page '{page_name}'")
            return self._get_control_state()
        if command == "press_button":
            button_id = str(args.get("button_id") or "")
            self._press_button_by_id(button_id)
            return self._get_control_state()
        raise ValueError(f"Unknown command '{command}'")

    def _poll_control_commands(self) -> None:
        commands_dir = self._control_commands_dir()
        responses_dir = self._control_responses_dir()
        for command_path in sorted(commands_dir.glob("*.json")):
            try:
                payload = json.loads(command_path.read_text(encoding="utf-8"))
            except Exception as exc:
                response = {"ok": False, "error": f"Invalid command payload: {exc}"}
            else:
                try:
                    result = self._handle_control_command(payload)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc), "state": self._get_control_state()}
                else:
                    response = {"ok": True, "result": result}
            response_path = responses_dir / command_path.name
            response_path.write_text(json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8")
            command_path.unlink(missing_ok=True)

    def _rename_session_path(self, session_path: Path) -> Path | None:
        if not session_path.exists():
            return None
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Capture Session",
            "New session folder name:",
            text=session_path.name,
        )
        if not ok:
            return None
        new_name = new_name.strip()
        if not new_name or new_name == session_path.name:
            return None
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(
                self,
                "Invalid Session Name",
                "Session folder names cannot contain path separator or reserved filename characters.",
            )
            return None
        target = session_path.parent / new_name
        if target.exists():
            QMessageBox.warning(self, "Rename Failed", f"A capture session named '{new_name}' already exists.")
            return None
        try:
            session_path.rename(target)
        except OSError as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))
            return None
        if self.browser_running:
            active_path = self._active_capture_session_state_path()
            try:
                payload = json.loads(active_path.read_text(encoding="utf-8")) if active_path.exists() else {}
            except (OSError, json.JSONDecodeError):
                payload = {}
            if str(payload.get("active_session") or "") == str(session_path):
                self._set_active_capture_session(target)
        if self.current_capture_dir == session_path:
            self.current_capture_dir = target
        self.log(f"Renamed capture session: {session_path.name} -> {target.name}")
        self.refresh_capture_sessions()
        self._refresh_actions_session_combo()
        return target

    def _rename_session_from_combo(self, mode: str) -> None:
        session_path = self._session_path_for_mode(mode)
        if session_path is None:
            return
        renamed = self._rename_session_path(session_path)
        if renamed is None:
            return
        combo = self.revise_session_combo if mode == "revise" else self.actions_session_combo
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == str(renamed):
                combo.setCurrentIndex(index)
                break

    def _delete_session_path(self, session_path: Path) -> bool:
        if not session_path.exists():
            return False
        if QMessageBox.question(
            self,
            "Delete Session",
            f"Delete the entire capture session folder '{session_path.name}'?",
        ) != QMessageBox.Yes:
            return False
        if self.browser_running:
            set_capture_enabled(session_path, False)
            active_path = self._active_capture_session_state_path()
            try:
                payload = json.loads(active_path.read_text(encoding="utf-8")) if active_path.exists() else {}
            except (OSError, json.JSONDecodeError):
                payload = {}
            if str(payload.get("active_session") or "") == str(session_path):
                self._set_active_capture_session(None)
        if self.current_capture_dir == session_path:
            self.current_capture_dir = None
        shutil.rmtree(session_path, ignore_errors=True)
        self.log(f"Deleted capture session: {session_path}")
        self.refresh_capture_sessions()
        self._refresh_actions_session_combo()
        return True

    def _delete_session_from_combo(self, mode: str) -> None:
        session_path = self._session_path_for_mode(mode)
        if session_path is None:
            return
        self._delete_session_path(session_path)

    def _build_conversation_prompt(
        self,
        *,
        mode: str,
        prompt_text: str,
        session_path: Path,
        capture_paths: list[Path],
    ) -> tuple[Path, Path, str]:
        bundle_root, zip_path, full_prompt = self._build_ollama_prompt(
            session_path=session_path,
            capture_paths=capture_paths,
            prompt_text=prompt_text,
        )
        mode_state = self._mode_state(mode)
        history = mode_state.get("history") or []
        if not isinstance(history, list):
            history = []
        primer_at_raw = str(mode_state.get("primer_sent_at") or "")
        force_reprime = bool(mode_state.get("force_reprime"))
        primer_stale = True
        if primer_at_raw:
            try:
                primer_stale = (datetime.now() - datetime.fromisoformat(primer_at_raw)).total_seconds() > 3600
            except ValueError:
                primer_stale = True
        base_wrapper = "Conversation history:\n"
        if history:
            history_lines = []
            for item in history[-8:]:
                if not isinstance(item, dict):
                    continue
                history_lines.append(f"{str(item.get('role') or 'assistant').upper()}: {str(item.get('content') or '')}")
            base_wrapper += "\n\n".join(history_lines) + "\n\n"
        if force_reprime or primer_stale or not history:
            compiled = (
                "This is the primary task definition for this module conversation. Re-prime yourself with it.\n\n"
                + full_prompt
                + "\n\n"
                + base_wrapper
            )
        else:
            compiled = (
                "Continue the existing module conversation. The primary task was already established recently. "
                "Use the prior conversation plus the latest request below.\n\n"
                + base_wrapper
                + "Latest request:\n"
                + prompt_text
                + "\n\nLatest repository/capture context:\n"
                + f"Context bundle zip: {zip_path}\n"
            )
        mode_state["history"] = history
        mode_state["last_bundle_zip"] = str(zip_path)
        mode_state["last_bundle_root"] = str(bundle_root)
        if force_reprime or primer_stale or not history:
            mode_state["primer_sent_at"] = datetime.now().isoformat()
            mode_state["force_reprime"] = False
        self._update_mode_state(mode, mode_state)
        self._refresh_llm_status_labels()
        return bundle_root, zip_path, compiled

    def _backup_and_apply_reply(
        self,
        mode: str = "process",
        *,
        confirm: bool = True,
        apply_all_if_none_selected: bool = False,
    ) -> None:
        if self.current_manifest is None:
            return
        reply = self._reply_text_for_mode(mode)
        if not reply:
            self.log("No Ollama reply to apply.")
            return
        file_blocks = self._parse_reply_file_blocks(reply)
        if not file_blocks:
            QMessageBox.information(
                self,
                "No File Blocks",
                "The Ollama reply did not contain any <<<FILE: ...>>> blocks to apply.",
            )
            return
        selected_file_blocks = self._selected_reply_file_blocks(mode)
        if not selected_file_blocks:
            if apply_all_if_none_selected:
                self.reply_apply_selection[mode] = {
                    path.replace("\\", "/"): True for path, _content in file_blocks
                }
                self._set_reply_text_for_mode(mode, reply)
                selected_file_blocks = self._selected_reply_file_blocks(mode)
            else:
                message = QMessageBox(self)
                message.setWindowTitle("No Changes Selected")
                message.setText("You need to select changes to apply first, or select Apply All.")
                _ok_button = message.addButton("OK", QMessageBox.RejectRole)
                apply_all_button = message.addButton("Apply All", QMessageBox.AcceptRole)
                message.setIcon(QMessageBox.Information)
                message.exec()
                if message.clickedButton() is apply_all_button:
                    self.reply_apply_selection[mode] = {
                        path.replace("\\", "/"): True for path, _content in file_blocks
                    }
                    self._set_reply_text_for_mode(mode, reply)
                    selected_file_blocks = self._selected_reply_file_blocks(mode)
                else:
                    return
        if confirm and QMessageBox.question(
            self,
            "Apply Ollama Reply",
            f"Apply {len(selected_file_blocks)} selected file update(s)? Existing files will be backed up first.",
        ) != QMessageBox.Yes:
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_root = Path("C:/tmp") / "web_api_builder_backups" / self.current_manifest.module_id / timestamp
        backup_root.mkdir(parents=True, exist_ok=True)
        (backup_root / "ollama_reply.txt").write_text(reply, encoding="utf-8")
        applied = 0
        for relative_path, content in selected_file_blocks:
            candidate = (APP_ROOT / relative_path).resolve()
            try:
                candidate.relative_to(APP_ROOT.resolve())
            except ValueError:
                self.log(f"Skipped unsafe path from reply: {relative_path}")
                continue
            if candidate.exists():
                backup_path = backup_root / candidate.relative_to(APP_ROOT)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, backup_path)
            else:
                backup_path = backup_root / "created_files.txt"
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                existing = backup_path.read_text(encoding="utf-8") if backup_path.exists() else ""
                backup_path.write_text(existing + relative_path + "\n", encoding="utf-8")
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(content.rstrip() + "\n", encoding="utf-8")
            self.log(f"Applied file from Ollama reply: {relative_path}")
            applied += 1
        self.log(f"Backed up prior files to: {backup_root}")
        self.log(f"Applied {applied} file(s) from Ollama reply.")
        self.refresh_current_views()

    def _cleanup_ollama_request(self, mode: str) -> None:
        worker = self.ollama_workers.pop(mode, None)
        thread = self.ollama_threads.pop(mode, None)
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.quit()
            thread.wait(1000)
            thread.deleteLater()

    def _is_active_run(self, mode: str, run_id: str) -> bool:
        request_context = self.pending_ollama_requests.get(mode) or {}
        return str(request_context.get("run_id") or "") == run_id

    def _start_ollama_request(
        self,
        *,
        mode: str,
        model: str,
        prompt_text: str,
        full_prompt: str,
        bundle_root: Path,
        zip_path: Path,
        session_path: Path,
        capture_paths: list[Path],
        cycle_index: int,
        max_cycles: int,
    ) -> None:
        if mode in self.ollama_threads:
            self.log(f"An Ollama request is already running for {mode}.")
            return
        run_id = uuid.uuid4().hex
        request_context = {
            "mode": mode,
            "run_id": run_id,
            "model": model,
            "prompt_text": prompt_text,
            "full_prompt": full_prompt,
            "bundle_root": str(bundle_root),
            "zip_path": str(zip_path),
            "session_path": str(session_path),
            "capture_paths": [str(path) for path in capture_paths],
            "cycle_index": cycle_index,
            "max_cycles": max_cycles,
        }
        self.pending_ollama_requests[mode] = request_context
        self._persist_mode_runtime(mode, request_state="retrying" if cycle_index > 1 else "running", error="")
        self._set_llm_busy(mode, True)
        self._set_llm_status_message(mode, f"Cycle {cycle_index}/{max_cycles}: sending to Ollama...")
        self._set_result_summary_for_mode(mode, f"Working... cycle {cycle_index}/{max_cycles}.")
        self._update_llm_action_buttons()
        self.log(
            f"[{mode}] Starting Ollama cycle {cycle_index}/{max_cycles} with model '{model}' "
            f"for session '{session_path.name}'."
        )

        worker = OllamaRequestWorker(
            mode=mode,
            model=model,
            base_url=self._ollama_base_url(),
            prompt=full_prompt,
            repair_prompt=None,
            timeout=120,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(lambda worker_mode, text, rid=run_id: self._on_ollama_worker_status(worker_mode, text, rid))
        worker.chunk.connect(
            lambda worker_mode, text, token_count, rate, rid=run_id: self._on_ollama_worker_chunk(
                worker_mode,
                text,
                token_count,
                rate,
                rid,
            )
        )
        worker.finished.connect(
            lambda worker_mode, sent_prompt, reply, rid=run_id: self._on_ollama_worker_finished(
                worker_mode,
                sent_prompt,
                reply,
                rid,
            )
        )
        worker.error.connect(
            lambda worker_mode, error_text, partial_reply, rid=run_id: self._on_ollama_worker_error(
                worker_mode,
                error_text,
                partial_reply,
                rid,
            )
        )
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        self.ollama_workers[mode] = worker
        self.ollama_threads[mode] = thread
        thread.start()

    def _on_ollama_worker_status(self, mode: str, text: str, run_id: str) -> None:
        if not self._is_active_run(mode, run_id):
            self.log(f"[{mode}] Ignoring stale status from run {run_id[:8]}.")
            return
        request_context = self.pending_ollama_requests.get(mode) or {}
        cycle_index = int(request_context.get("cycle_index") or 1)
        max_cycles = int(request_context.get("max_cycles") or UI_SIZES["llm_auto_cycle_max"])
        self._set_llm_status_message(mode, f"Cycle {cycle_index}/{max_cycles}: {text}")
        self._set_result_summary_for_mode(mode, f"Working... cycle {cycle_index}/{max_cycles}.")
        self.log(f"[{mode}] {text}")

    def _on_ollama_worker_chunk(self, mode: str, text: str, token_count: int, rate: float, run_id: str) -> None:
        if not self._is_active_run(mode, run_id):
            self.log(f"[{mode}] Ignoring stale chunk from run {run_id[:8]}.")
            return
        request_context = self.pending_ollama_requests.get(mode) or {}
        cycle_index = int(request_context.get("cycle_index") or 1)
        max_cycles = int(request_context.get("max_cycles") or UI_SIZES["llm_auto_cycle_max"])
        self._append_reply_chunk_for_mode(mode, text)
        self._set_llm_status_message(mode, f"Cycle {cycle_index}/{max_cycles}: receiving reply...")
        self._set_result_summary_for_mode(mode, f"Cycle {cycle_index}/{max_cycles}: {token_count} tokens @ {rate:.1f} tokens/s")
        self._persist_mode_runtime(mode, request_state="running")

    def _on_ollama_worker_error(self, mode: str, error_text: str, partial_reply: str, run_id: str) -> None:
        if not self._is_active_run(mode, run_id):
            self.log(f"[{mode}] Ignoring stale error from run {run_id[:8]}.")
            return
        self._cleanup_ollama_request(mode)
        self.pending_ollama_requests.pop(mode, None)
        self.log(f"Ollama request failed: {error_text}")
        if partial_reply.strip():
            self._set_reply_text_for_mode(mode, partial_reply)
            self.log(f"[{mode}] Preserved partial reply after failure.")
        else:
            self._set_reply_text_for_mode(mode, error_text)
        if "timed out" in error_text.lower() or "timeout" in error_text.lower():
            self._set_result_summary_for_mode(mode, "Request timed out. Partial reply preserved.")
            self._set_llm_status_message(mode, "Timed out while waiting for more reply data.")
        else:
            self._set_result_summary_for_mode(mode, f"Request failed: {error_text}")
            self._set_llm_status_message(mode, "Request failed.")
        self._persist_mode_runtime(mode, request_state="failed", error=error_text)
        self._set_llm_busy(mode, False)
        self._update_llm_action_buttons()

    def _on_ollama_worker_finished(self, mode: str, _sent_prompt: str, reply: str, run_id: str) -> None:
        if not self._is_active_run(mode, run_id):
            self.log(f"[{mode}] Ignoring stale completion from run {run_id[:8]}.")
            return
        request_context = self.pending_ollama_requests.get(mode) or {}
        self._cleanup_ollama_request(mode)
        validation = self._validate_reply_for_module(reply)
        cycle_index = int(request_context.get("cycle_index") or 1)
        max_cycles = int(request_context.get("max_cycles") or UI_SIZES["llm_auto_cycle_max"])
        self.log(
            f"[{mode}] Ollama cycle {cycle_index}/{max_cycles} finished with "
            f"{len(reply)} characters and {len(self._parse_reply_file_blocks(reply))} file block(s)."
        )
        should_retry = bool(validation.get("retry")) and cycle_index < max_cycles
        if should_retry:
            if not self._parse_reply_file_blocks(reply):
                followup_prompt = self._build_reformat_prompt(prior_reply=reply)
            else:
                followup_prompt = self._build_retry_followup_prompt(
                    request_context=request_context,
                    reply=reply,
                    validation=validation,
                )
            self.log(
                f"Ollama {mode} cycle {cycle_index}/{max_cycles} needs revision. "
                f"Starting cycle {cycle_index + 1}/{max_cycles}."
            )
            self._set_reply_text_for_mode(mode, reply)
            self._set_result_summary_for_mode(
                mode,
                f"Revising... cycle {cycle_index + 1}/{max_cycles}",
            )
            self._persist_mode_runtime(mode, request_state="retrying")
            self._start_ollama_request(
                mode=mode,
                model=str(request_context.get("model") or ""),
                prompt_text=str(request_context.get("prompt_text") or ""),
                full_prompt=followup_prompt,
                bundle_root=Path(str(request_context.get("bundle_root") or "")),
                zip_path=Path(str(request_context.get("zip_path") or "")),
                session_path=Path(str(request_context.get("session_path") or "")),
                capture_paths=[Path(str(path)) for path in (request_context.get("capture_paths") or [])],
                cycle_index=cycle_index + 1,
                max_cycles=max_cycles,
            )
            return

        self.pending_ollama_requests.pop(mode, None)
        self._set_reply_text_for_mode(mode, reply)
        preview = self._preview_reply_changes(reply)
        mode_state = self._mode_state(mode)
        history = mode_state.get("history") or []
        if not isinstance(history, list):
            history = []
        history.append({"role": "user", "content": str(request_context.get("prompt_text") or "")})
        history.append({"role": "assistant", "content": reply})
        mode_state["history"] = history[-20:]
        self._update_mode_state(mode, mode_state)
        if mode == "revise":
            self._refresh_revise_history()
        self._refresh_llm_status_labels()

        files = preview.get("files") or []
        file_count = int(preview.get("file_count") or 0)
        endpoint_delta = int(preview.get("endpoint_delta") or 0)
        route_delta = int(preview.get("route_delta") or 0)
        summary_parts = [f"{validation.get('rating')}. {file_count} files after {cycle_index} cycle(s)."]
        if endpoint_delta > 0:
            summary_parts.append(f"+{endpoint_delta} endpoint method(s) previewed.")
        elif endpoint_delta < 0:
            summary_parts.append(f"{endpoint_delta} endpoint method(s) vs current preview.")
        if route_delta > 0:
            summary_parts.append(f"+{route_delta} route(s) previewed.")
        elif route_delta < 0:
            summary_parts.append(f"{route_delta} route(s) vs current preview.")
        issues = [str(item) for item in (validation.get("issues") or [])]
        warnings = [str(item) for item in (validation.get("warnings") or [])]
        self._set_result_summary_for_mode(mode, " ".join(summary_parts))
        for item in issues:
            self.log(f"[{mode} validator] {item}")
        for item in warnings:
            self.log(f"[{mode} validator warning] {item}")
        if files:
            self.log(
                f"[{mode}] Returned files: "
                + ", ".join(str(path) for path in files[:8])
                + (" ..." if len(files) > 8 else "")
            )
        self._set_llm_status_message(mode, f"Completed after {cycle_index} cycle(s).")
        self._persist_mode_runtime(mode, request_state="completed", error="")
        self._set_llm_busy(mode, False)
        self._update_llm_action_buttons()
        self.log(f"Ollama {mode} reply received.")

    def _send_prompt_to_ollama(self, mode: str = "process") -> None:
        model = self.ollama_model_combo.currentText().strip()
        if not model:
            self.log("No Ollama model selected.")
            return
        session_path = self._session_path_for_mode(mode)
        if session_path is None:
            self.log("No capture session selected for analysis.")
            return
        prompt_text = self._editor_text_for_mode(mode)
        if not prompt_text:
            self.log("Prompt editor is empty.")
            return
        capture_paths = self._selected_capture_paths_for_actions(session_path)
        if not capture_paths:
            self.log("No capture files available for the selected session.")
            return
        bundle_root, zip_path, full_prompt = self._build_conversation_prompt(
            mode=mode,
            session_path=session_path,
            capture_paths=capture_paths,
            prompt_text=prompt_text,
        )
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        self.log(
            f"Sending {mode} prompt to Ollama model '{model}' using {session_path.name} "
            f"with {len(capture_paths)} capture file(s)."
        )
        self.log(f"Created LLM context bundle: {bundle_root}")
        self.log(f"Created LLM context zip: {zip_path}")
        self._start_ollama_request(
            mode=mode,
            model=model,
            prompt_text=prompt_text,
            full_prompt=full_prompt,
            bundle_root=bundle_root,
            zip_path=zip_path,
            session_path=session_path,
            capture_paths=capture_paths,
            cycle_index=1,
            max_cycles=self._current_llm_cycle_count(mode),
        )

    def _set_debug_limit_widget(self, widget: QWidget | None, *, enabled: bool) -> None:
        if widget is None:
            return
        widget.setProperty("debugLimit", enabled)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _clear_debug_limit_highlights(self) -> None:
        for widget in self.findChildren(QWidget):
            if widget.property("debugLimit"):
                self._set_debug_limit_widget(widget, enabled=False)

    @staticmethod
    def _widget_debug_name(widget: QWidget) -> str:
        if isinstance(widget, QGroupBox) and widget.title():
            return f"QGroupBox({widget.title()})"
        if isinstance(widget, QTabWidget):
            return "QTabWidget(Main Tabs)"
        if isinstance(widget, QTableWidget):
            headers = []
            for column in range(min(widget.columnCount(), 2)):
                item = widget.horizontalHeaderItem(column)
                if item is not None and item.text():
                    headers.append(item.text())
            if headers:
                return f"QTableWidget({', '.join(headers)})"
        if isinstance(widget, QTextEdit):
            return "QTextEdit(Console)"
        name = widget.objectName().strip()
        if name:
            return f"{widget.__class__.__name__}({name})"
        return widget.__class__.__name__

    def _find_limit_widgets(self) -> tuple[QWidget | None, QWidget | None]:
        candidates: list[QWidget] = []
        for widget in self.findChildren(QWidget):
            if not widget.isVisible():
                continue
            if widget is self or widget is self.centralWidget():
                continue
            hint = widget.minimumSizeHint()
            if hint.width() <= 0 and hint.height() <= 0:
                continue
            candidates.append(widget)
        if not candidates:
            return None, None

        def container_score(widget: QWidget) -> int:
            score = 0
            if isinstance(widget, (QGroupBox, QTabWidget, QTableWidget, QTextEdit, QSplitter, QComboBox)):
                score += 1000
            if widget.layout() is not None:
                score += 500
            score += len(widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)) * 10
            return score

        width_widget = max(
            candidates,
            key=lambda w: (w.minimumSizeHint().width(), container_score(w)),
        )
        height_widget = max(
            candidates,
            key=lambda w: (w.minimumSizeHint().height(), container_score(w)),
        )
        return width_widget, height_widget

    def _update_debug_limit_highlight(self) -> None:
        self._clear_debug_limit_highlights()
        if not self.debug_mode_check.isChecked():
            self.setToolTip("")
            return
        min_size = self.minimumSizeHint()
        near_min_width = self.width() <= max(
            min_size.width() + UI_SIZES["debug_near_min_slack"], min_size.width()
        )
        near_min_height = self.height() <= max(
            min_size.height() + UI_SIZES["debug_near_min_slack"], min_size.height()
        )
        if not near_min_width and not near_min_height:
            self.setToolTip("")
            return
        width_widget, height_widget = self._find_limit_widgets()
        lines: list[str] = []
        if near_min_width and width_widget is not None:
            self._set_debug_limit_widget(width_widget, enabled=True)
            lines.append(
                f"Width limiter: {self._widget_debug_name(width_widget)} minimumSizeHint="
                f"{width_widget.minimumSizeHint().width()}x{width_widget.minimumSizeHint().height()}"
            )
        if near_min_height and height_widget is not None and height_widget is not width_widget:
            self._set_debug_limit_widget(height_widget, enabled=True)
            lines.append(
                f"Height limiter: {self._widget_debug_name(height_widget)} minimumSizeHint="
                f"{height_widget.minimumSizeHint().width()}x{height_widget.minimumSizeHint().height()}"
            )
        elif near_min_height and height_widget is not None:
            lines.append(
                f"Height limiter: {self._widget_debug_name(height_widget)} minimumSizeHint="
                f"{height_widget.minimumSizeHint().width()}x{height_widget.minimumSizeHint().height()}"
            )
        self.setToolTip("\n".join(lines))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_window_state()
        super().closeEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        super().moveEvent(event)
        self._schedule_window_state_save()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_window_state_save()
        self._update_debug_limit_highlight()

    def _schedule_window_state_save(self) -> None:
        self.window_state_timer.start()

    def _save_window_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        if hasattr(self, "main_splitter"):
            self.settings.setValue("window/main_splitter", self.main_splitter.saveState())
            self._save_splitter_state_for_tab(self.current_tab_index)
        self.settings.setValue("theme/dark_mode", self.dark_mode_check.isChecked())
        self.settings.setValue("debug/enabled", self.debug_mode_check.isChecked())

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Module"))
        self.module_combo.setFixedWidth(UI_SIZES["module_combo_width"])
        header_layout.addWidget(self.module_combo)
        add_button = QPushButton("Add")
        add_button.setProperty("compact", True)
        add_button.setProperty("success", True)
        add_button.clicked.connect(self.create_or_select_blank_module)
        delete_button = QPushButton("Delete")
        delete_button.setProperty("compact", True)
        delete_button.setProperty("danger", True)
        delete_button.clicked.connect(self.delete_selected_module)
        reload_button = QPushButton("Reload")
        reload_button.setProperty("compact", True)
        reload_button.clicked.connect(self.reload_modules)
        save_button = QPushButton("Save")
        save_button.setProperty("compact", True)
        save_button.clicked.connect(self.save_manifest)
        for button in (add_button, delete_button, reload_button, save_button):
            button.setFixedSize(UI_SIZES["toolbar_button_width"], UI_SIZES["toolbar_button_height"])
        header_layout.addWidget(add_button)
        header_layout.addWidget(reload_button)
        header_layout.addWidget(save_button)
        header_layout.addWidget(delete_button)
        header_layout.addStretch(1)
        header_layout.addWidget(self.dark_mode_check)
        header_layout.addWidget(self.debug_mode_check)
        root_layout.addLayout(header_layout)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self._build_details_panel())
        self.main_splitter.addWidget(self._build_log_panel())
        self.main_splitter.setStretchFactor(0, UI_SIZES["main_splitter_top_stretch"])
        self.main_splitter.setStretchFactor(1, UI_SIZES["main_splitter_bottom_stretch"])
        self.main_splitter.splitterMoved.connect(lambda _pos, _index: self._schedule_window_state_save())
        root_layout.addWidget(self.main_splitter, stretch=1)
        splitter_state = self.settings.value("window/main_splitter", b"")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)
        self._restore_splitter_state_for_tab(self.current_tab_index)

        self.setCentralWidget(central)

    def _build_details_panel(self) -> QWidget:
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        self.tabs.addTab(self._build_captures_tab(), "Captures")
        self.tabs.addTab(self._build_actions_tab(), "Process")
        self.tabs.addTab(self._build_revise_tab(), "Revise")
        self.tabs.addTab(self._build_endpoints_tab(), "Endpoints")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        return self.tabs

    def _build_log_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        margin = UI_SIZES["log_panel_margin"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.addWidget(self.log_output)
        return panel

    def _build_overview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        form.addRow("Module Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Base URL", self.base_url_edit)
        layout.addLayout(form)

        page_group = QGroupBox("Discovered Routes")
        page_layout = QVBoxLayout(page_group)
        page_layout.addWidget(QLabel("Double-click a route to open a logged-in browser at that context."))
        page_layout.addWidget(self.pages_table)
        layout.addWidget(page_group)
        return widget

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        general_form.addRow("Raw Capture Root", self.raw_capture_root_edit)
        general_form.addRow("Processed Capture Root", self.processed_capture_root_edit)
        layout.addWidget(general_group)

        ollama_group = QGroupBox("Ollama")
        ollama_layout = QHBoxLayout(ollama_group)
        ollama_layout.addWidget(QLabel("Host"))
        ollama_layout.addWidget(self.ollama_host_edit)
        ollama_layout.addWidget(QLabel("Port"))
        ollama_layout.addWidget(self.ollama_port_edit)
        ollama_layout.addWidget(QLabel("Model"))
        ollama_layout.addWidget(self.ollama_model_combo)
        refresh_models = QPushButton("Refresh Models")
        refresh_models.clicked.connect(self._load_ollama_models)
        refresh_models.setToolTip("Reload available Ollama models from the configured host and port.")
        ollama_layout.addWidget(refresh_models)
        ollama_layout.addStretch(1)
        layout.addWidget(ollama_group)

        layout.addStretch(1)
        return widget

    def _build_endpoints_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Methods are inferred from the configured client class."))
        layout.addWidget(self.endpoints_table)
        return widget

    def _build_captures_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        filter_group = QGroupBox("Capture Settings")
        filter_layout = QVBoxLayout(filter_group)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Domain Contains"))
        filter_row.addWidget(self.capture_domain_filter_edit, stretch=2)
        filter_row.addWidget(QLabel("URL Contains"))
        filter_row.addWidget(self.capture_url_filter_edit, stretch=2)
        filter_row.addWidget(QLabel("Duplicates"))
        filter_row.addWidget(self.capture_mode_combo)
        filter_layout.addLayout(filter_row)

        content_row = QHBoxLayout()
        content_row.addWidget(QLabel("Capture Types"))
        for key in ("all", "json", "html", "js", "text", "other"):
            content_row.addWidget(self.capture_content_buttons[key])
        content_row.addStretch(1)
        filter_layout.addLayout(content_row)
        layout.addWidget(filter_group)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Session"))
        controls.addWidget(self.raw_sessions_combo)
        self.open_session_folder_button.setFixedWidth(UI_SIZES["capture_button_width"])
        self.open_session_folder_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.open_session_folder_button)
        self.rename_session_button.setFixedWidth(UI_SIZES["capture_button_width"])
        self.rename_session_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.rename_session_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.setProperty("compact", True)
        refresh_button.setFixedWidth(UI_SIZES["capture_button_width"])
        refresh_button.setFixedHeight(UI_SIZES["capture_button_height"])
        refresh_button.clicked.connect(self.refresh_capture_sessions)
        controls.addWidget(refresh_button)
        self.clear_session_button.setFixedWidth(UI_SIZES["capture_button_width"])
        self.clear_session_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.clear_session_button)
        self.delete_selected_requests_button.setFixedWidth(UI_SIZES["capture_button_width"])
        self.delete_selected_requests_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.delete_selected_requests_button)
        controls.addStretch(1)

        right_controls = QHBoxLayout()
        right_controls.setContentsMargins(0, 0, 0, 0)
        right_controls.setSpacing(8)
        self.run_new_button.setFixedSize(UI_SIZES["capture_tall_button_size"], UI_SIZES["capture_tall_button_size"])
        self.capture_toggle_button.setFixedSize(UI_SIZES["capture_tall_button_size"], UI_SIZES["capture_tall_button_size"])
        right_controls.addWidget(self.run_new_button, alignment=Qt.AlignRight)
        right_controls.addWidget(self.capture_toggle_button, alignment=Qt.AlignRight)
        controls.addLayout(right_controls)
        layout.addLayout(controls)

        layout.addWidget(self.raw_requests_table, stretch=1)
        return widget

    def _build_actions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        command_group = QGroupBox("Commands")
        form = QFormLayout(command_group)
        run_test = QPushButton("Run")
        run_test.setProperty("compact", True)
        run_test.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        run_test.clicked.connect(lambda: self.run_manifest_command(self.test_command_edit.text()))
        open_browser = QPushButton("Open")
        open_browser.setProperty("compact", True)
        open_browser.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        open_browser.clicked.connect(self.open_default_browser_session)
        process_capture = QPushButton("Run")
        process_capture.setProperty("compact", True)
        process_capture.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        process_capture.clicked.connect(lambda: self.run_manifest_command(self.process_capture_command_edit.text()))

        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.addWidget(self.test_command_edit, stretch=1)
        test_layout.addWidget(run_test)
        browser_row = QWidget()
        browser_layout = QHBoxLayout(browser_row)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.browser_command_edit, stretch=1)
        browser_layout.addWidget(open_browser)
        process_row = QWidget()
        process_layout = QHBoxLayout(process_row)
        process_layout.setContentsMargins(0, 0, 0, 0)
        process_layout.addWidget(self.process_capture_command_edit, stretch=1)
        process_layout.addWidget(process_capture)

        form.addRow("Test Command", test_row)
        form.addRow("Browser Command", browser_row)
        form.addRow("Process Capture Command", process_row)
        layout.addWidget(command_group)

        ollama_group = QGroupBox("Processing Prompts")
        ollama_layout = QVBoxLayout(ollama_group)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("Session"))
        session_row.addWidget(self.actions_session_combo)
        self.process_rename_session_button.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        self.process_delete_session_button.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        session_row.addWidget(self.process_rename_session_button)
        session_row.addWidget(self.process_delete_session_button)
        session_row.addWidget(self.actions_session_count_label)
        session_row.addStretch(1)
        ollama_layout.addLayout(session_row)

        process_status_row = QHBoxLayout()
        process_status_row.addWidget(self.process_status_label)
        process_status_row.addStretch(1)
        process_reprime = QPushButton("Re-prime Next Send")
        process_reprime.setToolTip(
            "Keep the current conversation history, but force the next send to include the full "
            "module task/context again so you can steer the model back on track."
        )
        process_reprime.clicked.connect(lambda: self._queue_llm_reprime("process"))
        process_status_row.addWidget(process_reprime)
        process_reset = QPushButton("Reset LLM")
        process_reset.setProperty("danger", True)
        process_reset.setToolTip(
            "Clear the saved conversation state for this module's Process tab and start fresh."
        )
        process_reset.clicked.connect(lambda: self._clear_llm_mode("process"))
        process_status_row.addWidget(process_reset)
        ollama_layout.addLayout(process_status_row)

        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt"))
        prompt_row.addWidget(self.prompt_combo, stretch=1)
        prompt_new = QPushButton("New")
        prompt_new.setProperty("compact", True)
        prompt_new.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        prompt_new.clicked.connect(self._new_prompt)
        prompt_save = QPushButton("Save")
        prompt_save.setProperty("compact", True)
        prompt_save.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        prompt_save.clicked.connect(self._save_prompt)
        prompt_delete = QPushButton("Delete")
        prompt_delete.setProperty("compact", True)
        prompt_delete.setProperty("danger", True)
        prompt_delete.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        prompt_delete.clicked.connect(self._delete_prompt)
        prompt_reload = QPushButton("Reload")
        prompt_reload.setProperty("compact", True)
        prompt_reload.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        prompt_reload.clicked.connect(self._reload_prompt_library)
        prompt_row.addWidget(prompt_new)
        prompt_row.addWidget(prompt_save)
        prompt_row.addWidget(prompt_delete)
        prompt_row.addWidget(prompt_reload)
        prompt_row.addStretch(1)
        ollama_layout.addLayout(prompt_row)
        ollama_layout.addWidget(QLabel("Prompt Description"))
        ollama_layout.addWidget(self.prompt_description_edit)

        ollama_layout.addWidget(QLabel("Prompt"))
        ollama_layout.addWidget(self.prompt_editor)
        send_row = QHBoxLayout()
        self.process_send_button.setToolTip(
            "Send the selected prompt, current module files, and selected capture session to the configured Ollama model."
        )
        self.process_apply_button.setToolTip(
            "Apply valid <<<FILE: ...>>> blocks from the latest LLM reply after creating a backup."
        )
        self.process_apply_button.setText("Apply Changes")
        send_row.addWidget(self.process_send_button, alignment=Qt.AlignLeft)
        send_row.addWidget(QLabel("Cycles"))
        send_row.addWidget(self.process_cycle_combo, alignment=Qt.AlignLeft)
        send_row.addWidget(self.process_result_summary_label, stretch=1)
        send_row.addWidget(self.process_apply_button, alignment=Qt.AlignRight)
        ollama_layout.addLayout(send_row)
        ollama_layout.addWidget(self.process_reply_tabs, stretch=1)
        layout.addWidget(ollama_group, stretch=1)
        scroll.setWidget(container)
        return scroll

    def _build_revise_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        note = QLabel(
            "Use Revise for follow-up questions about the current module and recent captures. "
            "This keeps a separate per-module conversation thread from Process."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("Session"))
        session_row.addWidget(self.revise_session_combo)
        self.revise_rename_session_button.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        self.revise_delete_session_button.setFixedWidth(UI_SIZES["prompt_toolbar_button_width"])
        session_row.addWidget(self.revise_rename_session_button)
        session_row.addWidget(self.revise_delete_session_button)
        session_row.addWidget(self.revise_session_count_label)
        session_row.addStretch(1)
        layout.addLayout(session_row)

        status_row = QHBoxLayout()
        status_row.addWidget(self.revise_status_label)
        status_row.addStretch(1)
        revise_reprime = QPushButton("Re-prime Next Send")
        revise_reprime.setToolTip(
            "Keep the current conversation history, but force the next send to include the full "
            "module task/context again so you can steer the model back on track."
        )
        revise_reprime.clicked.connect(lambda: self._queue_llm_reprime("revise"))
        status_row.addWidget(revise_reprime)
        revise_reset = QPushButton("Reset LLM")
        revise_reset.setProperty("danger", True)
        revise_reset.setToolTip(
            "Clear the saved conversation state for this module's Revise tab and start fresh."
        )
        revise_reset.clicked.connect(lambda: self._clear_llm_mode("revise"))
        status_row.addWidget(revise_reset)
        layout.addLayout(status_row)

        revise_reprime_note = QLabel(
            "Re-prime Next Send keeps this module's Revise thread but re-sends the full context on the "
            "next message. Reset LLM wipes the saved Revise conversation for this module."
        )
        revise_reprime_note.setWordWrap(True)
        layout.addWidget(revise_reprime_note)

        layout.addWidget(QLabel("Conversation"))
        layout.addWidget(self.revise_history_output, stretch=1)
        layout.addWidget(QLabel("Question / Revision Request"))
        layout.addWidget(self.revise_prompt_editor)

        controls = QHBoxLayout()
        self.revise_apply_button.setText("Apply Changes")
        controls.addWidget(self.revise_send_button)
        controls.addWidget(QLabel("Cycles"))
        controls.addWidget(self.revise_cycle_combo, alignment=Qt.AlignLeft)
        controls.addWidget(self.revise_result_summary_label, stretch=1)
        controls.addWidget(self.revise_apply_button, alignment=Qt.AlignRight)
        layout.addLayout(controls)

        layout.addWidget(self.revise_reply_tabs, stretch=2)
        scroll.setWidget(container)
        return scroll

    def reload_modules(self) -> None:
        selected_id = self.current_manifest.module_id if self.current_manifest else None
        self.manifests = load_manifests()
        self.module_combo.blockSignals(True)
        self.module_combo.clear()
        for manifest in self.manifests:
            self.module_combo.addItem(manifest.name, manifest.module_id)
        self.module_combo.blockSignals(False)

        if self.manifests:
            index = 0
            if selected_id:
                for i, manifest in enumerate(self.manifests):
                    if manifest.module_id == selected_id:
                        index = i
                        break
            self.module_combo.setCurrentIndex(index)
            self._select_manifest(self.manifests[index])
        else:
            self.current_manifest = None
            self._clear_fields()

    def create_or_select_blank_module(self) -> None:
        name, ok = QInputDialog.getText(self, "New Module", "Module name:")
        if not ok or not name.strip():
            return
        module_id = next_module_id_for_name(name.strip())
        blank = create_module_from_template(module_id, name.strip())
        self.reload_modules()
        for index, manifest in enumerate(self.manifests):
            if manifest.module_id == blank.module_id:
                self.module_combo.setCurrentIndex(index)
                self.tabs.setCurrentIndex(0)
                break

    def delete_selected_module(self) -> None:
        if self.current_manifest is None:
            return
        if QMessageBox.question(
            self,
            "Delete Module",
            f"Delete module '{self.current_manifest.name}'?\n\nThis removes the manifest directory from the repo.",
        ) != QMessageBox.Yes:
            return
        if QMessageBox.question(
            self,
            "Delete Module",
            "Are you super duper sure?",
        ) != QMessageBox.Yes:
            return
        delete_module(self.current_manifest)
        self.current_manifest = None
        self.reload_modules()

    def save_manifest(self, silent: bool = False, refresh: bool = True) -> None:
        if self.current_manifest is None:
            return
        if not silent and self._module_name_changed():
            self._on_module_name_edit_finished()
            if self.current_manifest is None:
                return
        self.settings.setValue("paths/raw_capture_root", self.raw_capture_root_edit.text().strip() or "har")
        self.settings.setValue(
            "paths/processed_capture_root",
            self.processed_capture_root_edit.text().strip() or "captures_processed",
        )
        self.settings.setValue("ollama/host", self.ollama_host_edit.text().strip() or UI_SIZES["ollama_host_default"])
        self.settings.setValue("ollama/port", self.ollama_port_edit.text().strip() or UI_SIZES["ollama_port_default"])
        self.settings.setValue("ollama/model", self.ollama_model_combo.currentText().strip())
        data = self.current_manifest.data
        data["name"] = self.name_edit.text().strip()
        data["description"] = self.description_edit.text().strip()
        module_data = data.setdefault("module", {})
        module_data["package_path"] = self._derived_package_path()
        module_data["client_file"] = self._derived_client_file()
        module_data["client_class"] = str(module_data.get("client_class") or self._derived_client_class()).strip()
        browser = module_data.setdefault("browser", {})
        browser["base_url"] = self.base_url_edit.text().strip()
        try:
            module_data["processed_capture_dir"] = str(
                self._module_processed_capture_dir().resolve().relative_to(APP_ROOT.resolve())
            )
        except ValueError:
            module_data["processed_capture_dir"] = str(self._module_processed_capture_dir())
        capture = module_data.setdefault("capture", {})
        capture["url_contains"] = [token.strip() for token in self.capture_url_filter_edit.text().split(",") if token.strip()]
        capture["domain_contains"] = [token.strip() for token in self.capture_domain_filter_edit.text().split(",") if token.strip()]
        capture["content_kinds"] = self._selected_capture_content_kinds()
        capture["mode"] = "last" if self.capture_mode_combo.currentText() == "Keep Last" else "all"
        commands = data.setdefault("commands", {})
        default_test_command = f"python .\\tests\\{self._module_code_slug()}_smoke.py"
        commands["run_tests"] = self.test_command_edit.text().strip()
        if not commands["run_tests"] or commands["run_tests"] == "python .\\tests\\template_module_smoke.py":
            commands["run_tests"] = default_test_command
        commands["open_browser"] = self.browser_command_edit.text().strip()
        commands["process_captures"] = self.process_capture_command_edit.text().strip()
        self.current_manifest.save()
        if not silent:
            self.log("Saved manifest: " + str(self.current_manifest.path))
        if refresh:
            self.refresh_current_views()

    def _on_module_combo_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.manifests):
            self.current_manifest = None
            self._clear_fields()
            return
        self._select_manifest(self.manifests[index])

    def _select_manifest(self, manifest: ModuleManifest) -> None:
        self._activate_module_context(manifest)
        self.current_manifest = manifest
        self.refresh_current_views()

    def _stop_managed_browser_for_context_switch(self) -> None:
        if self.browser_process is None or self.browser_process.state() == QProcess.NotRunning:
            self.browser_running = False
            self.browser_module_id = None
            return
        try:
            self.browser_process.kill()
            self.browser_process.waitForFinished(2000)
        except Exception:
            pass
        self.browser_running = False
        self.browser_module_id = None
        self.log("Stopped managed browser because module context changed.")

    def _reset_module_runtime_context(self) -> None:
        self.current_capture_dir = None
        self.last_capture_entry_count = 0
        self.capture_refresh_timer.stop()
        self._populate_raw_requests([])
        self._refresh_actions_session_combo()
        self._refresh_revise_history()
        self._update_capture_buttons()

    def _activate_module_context(self, manifest: ModuleManifest) -> None:
        new_module_id = manifest.module_id
        if self.browser_running and self.browser_module_id and self.browser_module_id != new_module_id:
            self._stop_managed_browser_for_context_switch()
        self._reset_module_runtime_context()
        self.log(f"Switched module context to: {new_module_id}")

    def _set_widget_text_safely(self, widget: QLineEdit | QTextEdit, value: str) -> None:
        widget.blockSignals(True)
        if isinstance(widget, QTextEdit):
            widget.setPlainText(value)
        else:
            widget.setText(value)
        widget.blockSignals(False)

    def _reset_module_scoped_fields(self) -> None:
        for widget in (
            self.name_edit,
            self.description_edit,
            self.base_url_edit,
            self.capture_url_filter_edit,
            self.capture_domain_filter_edit,
            self.test_command_edit,
            self.browser_command_edit,
            self.process_capture_command_edit,
            self.prompt_editor,
            self.ollama_reply_output,
            self.revise_prompt_editor,
            self.revise_reply_output,
        ):
            self._set_widget_text_safely(widget, "")
        self.actions_session_combo.blockSignals(True)
        self.actions_session_combo.clear()
        self.actions_session_combo.blockSignals(False)
        self.revise_session_combo.blockSignals(True)
        self.revise_session_combo.clear()
        self.revise_session_combo.blockSignals(False)
        self.prompt_combo.blockSignals(True)
        self.prompt_combo.clear()
        self.prompt_combo.blockSignals(False)
        self.raw_sessions_combo.blockSignals(True)
        self.raw_sessions_combo.clear()
        self.raw_sessions_combo.blockSignals(False)
        self.pages_table.setRowCount(0)
        self.endpoints_table.setRowCount(0)
        self.raw_requests_table.setRowCount(0)
        self._set_capture_content_kinds(["json"])
        self.capture_mode_combo.setCurrentText("Keep Last")

    def refresh_current_views(self) -> None:
        if self.current_manifest is None:
            self._clear_fields()
            return
        self._reset_module_scoped_fields()
        data = self.current_manifest.data
        module_data = data.get("module", {})
        commands = data.get("commands", {})
        capture = module_data.get("capture", {})

        self._set_widget_text_safely(self.name_edit, str(data.get("name") or ""))
        self.last_loaded_module_name = self.name_edit.text().strip()
        self._set_widget_text_safely(self.description_edit, str(data.get("description") or ""))
        self._set_widget_text_safely(self.base_url_edit, str((module_data.get("browser") or {}).get("base_url") or ""))
        self._set_widget_text_safely(self.raw_capture_root_edit, str(self._raw_capture_root()))
        self._set_widget_text_safely(self.processed_capture_root_edit, str(self._processed_capture_root()))
        self._set_widget_text_safely(self.capture_url_filter_edit, ", ".join(capture.get("url_contains") or []))
        self._set_widget_text_safely(self.capture_domain_filter_edit, ", ".join(capture.get("domain_contains") or []))
        content_kinds = capture.get("content_kinds")
        if not content_kinds:
            content_kinds = ["json"] if bool(capture.get("include_json_only", True)) else ["all"]
        self._set_capture_content_kinds(list(content_kinds))
        self.capture_mode_combo.setCurrentText("Keep All" if str(capture.get("mode") or "last") == "all" else "Keep Last")
        default_test_command = f"python .\\tests\\{self._module_code_slug()}_smoke.py"
        run_tests_value = str(commands.get("run_tests") or "").strip()
        if not run_tests_value or run_tests_value == "python .\\tests\\template_module_smoke.py":
            run_tests_value = default_test_command
        self._set_widget_text_safely(self.test_command_edit, run_tests_value)
        self._set_widget_text_safely(self.browser_command_edit, str(commands.get("open_browser") or ""))
        self._set_widget_text_safely(self.process_capture_command_edit, str(commands.get("process_captures") or ""))
        saved_model = str(self.settings.value("ollama/model", "") or "").strip()
        if saved_model:
            self.ollama_model_combo.setCurrentText(saved_model)
        self._refresh_actions_session_combo()
        self._refresh_prompt_combo()
        if self.prompt_combo.currentIndex() >= 0:
            self._on_prompt_selected(self.prompt_combo.currentIndex())
        self._refresh_revise_history()
        self._restore_mode_runtime("process")
        self._restore_mode_runtime("revise")
        self._refresh_llm_status_labels()
        self._update_session_count_labels()
        self._update_llm_action_buttons()

        self._populate_endpoints()
        self._populate_captures()
        self._populate_pages()
        if self.current_capture_dir is not None:
            expected_root = module_capture_root(
                self.current_manifest.module_id,
                base_root=self._raw_capture_root(),
            )
            try:
                self.current_capture_dir.relative_to(expected_root)
            except ValueError:
                self.current_capture_dir = None
        self.refresh_capture_sessions()

    def _populate_endpoints(self) -> None:
        self.endpoints_table.setRowCount(0)
        if self.current_manifest is None:
            return
        module_data = self.current_manifest.data.get("module", {})
        client_file_value = module_data.get("client_file") or self._derived_client_file()
        client_class = str(module_data.get("client_class") or "WebApiClient")
        if not client_file_value or not client_class:
            return
        client_file = Path(str(client_file_value))
        if not client_file.is_absolute():
            client_file = APP_ROOT / client_file
        methods = infer_client_methods(client_file, client_class)
        self._populate_endpoint_rows(methods)

    def _populate_endpoint_rows(self, methods: list[str]) -> None:
        self.endpoints_table.setRowCount(len(methods))
        for row, method in enumerate(methods):
            self.endpoints_table.setItem(row, 0, QTableWidgetItem(method))

    def _populate_captures(self) -> None:
        return

    def _populate_pages(self) -> None:
        self.pages_table.setRowCount(0)
        if self.current_manifest is None:
            return
        pages = self.current_manifest.data.get("pages") or []
        self._populate_page_rows(pages)

    def _populate_page_rows(self, pages: list[object]) -> None:
        if not isinstance(pages, list):
            return
        self.pages_table.setRowCount(len(pages))
        for row, page in enumerate(pages):
            if isinstance(page, dict):
                route = str(page.get("route") or "")
                name = str(page.get("name") or "")
                if route == "/" and name.lower() == "overview":
                    name = "Base"
                self.pages_table.setItem(row, 0, QTableWidgetItem(name))
                self.pages_table.setItem(row, 1, QTableWidgetItem(route))

    def _preview_reply_changes(self, reply: str) -> dict[str, object]:
        if self.current_manifest is None:
            return {"file_count": 0, "endpoint_delta": 0, "route_delta": 0, "files": []}
        file_blocks = self._parse_reply_file_blocks(reply)
        if not file_blocks:
            return {"file_count": 0, "endpoint_delta": 0, "route_delta": 0, "files": []}
        module_data = self.current_manifest.data.get("module", {})
        client_file_value = str(module_data.get("client_file") or self._derived_client_file())
        manifest_file_value = str(self.current_manifest.path.relative_to(APP_ROOT))
        previewed_endpoints = False
        previewed_pages = False
        endpoint_delta = 0
        route_delta = 0
        current_endpoint_count = self.endpoints_table.rowCount()
        current_route_count = self.pages_table.rowCount()
        for relative_path, content in file_blocks:
            normalized = relative_path.replace("\\", "/")
            if not previewed_endpoints and normalized == client_file_value.replace("\\", "/"):
                try:
                    tree = ast.parse(content)
                except SyntaxError:
                    pass
                else:
                    client_class = str(module_data.get("client_class") or self._derived_client_class())
                    methods: list[str] = []
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef) and node.name == client_class:
                            for item in node.body:
                                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                                    methods.append(item.name)
                            break
                    if methods:
                        endpoint_delta = len(methods) - current_endpoint_count
                        self._populate_endpoint_rows(methods)
                        previewed_endpoints = True
            if not previewed_pages and normalized == manifest_file_value.replace("\\", "/"):
                try:
                    payload = yaml.safe_load(content) or {}
                except Exception:
                    pass
                else:
                    pages = payload.get("pages") or []
                    if isinstance(pages, list):
                        route_delta = len(pages) - current_route_count
                        self._populate_page_rows(pages)
                        previewed_pages = True
        if previewed_endpoints:
            self.log("Previewed endpoint updates from pending LLM reply.")
        if previewed_pages:
            self.log("Previewed route updates from pending LLM reply.")
        return {
            "file_count": len(file_blocks),
            "endpoint_delta": endpoint_delta,
            "route_delta": route_delta,
            "files": [path for path, _content in file_blocks],
        }

    def refresh_capture_sessions(self) -> None:
        sessions = (
            load_capture_sessions_for_manifest(self.current_manifest, base_root=self._raw_capture_root())
            if self.current_manifest
            else load_raw_capture_sessions(base_root=self._raw_capture_root())
        )
        selected = self.raw_sessions_combo.currentData()
        self.raw_sessions_combo.blockSignals(True)
        self.raw_sessions_combo.setCurrentIndex(-1)
        self.raw_sessions_combo.clear()
        for session in sessions:
            self.raw_sessions_combo.addItem(session.name, str(session))
        self.raw_sessions_combo.blockSignals(False)
        if self.current_capture_dir and self.current_capture_dir.exists():
            if self._select_session_in_combo(self.current_capture_dir):
                return
        elif selected:
            if self._select_session_in_combo(Path(str(selected))):
                return
        if sessions:
            self.raw_sessions_combo.setCurrentIndex(0)
            self._on_capture_session_changed(0)
            return
        self.current_capture_dir = None
        self.last_capture_entry_count = 0
        self.capture_refresh_timer.stop()
        self._populate_raw_requests([])
        self._update_capture_buttons()

    def _select_session_in_combo(self, session_dir: Path) -> bool:
        for index in range(self.raw_sessions_combo.count()):
            if self.raw_sessions_combo.itemData(index) == str(session_dir):
                self.raw_sessions_combo.setCurrentIndex(index)
                self._on_capture_session_changed(index)
                return True
        return False

    def _set_shared_session_selection(self, session_path: Path | None, *, source: str) -> None:
        target_value = str(session_path) if session_path is not None else None
        combos = (
            ("capture", self.raw_sessions_combo),
            ("process", self.actions_session_combo),
            ("revise", self.revise_session_combo),
        )
        for name, combo in combos:
            if name == source:
                continue
            combo.blockSignals(True)
            if target_value is None:
                combo.setCurrentIndex(-1)
            else:
                for index in range(combo.count()):
                    if str(combo.itemData(index) or "") == target_value:
                        combo.setCurrentIndex(index)
                        break
                else:
                    combo.setCurrentIndex(-1)
            combo.blockSignals(False)
        self._update_session_count_labels()
        self._update_llm_action_buttons()

    def _on_shared_session_combo_changed(self, mode: str) -> None:
        combo = self.revise_session_combo if mode == "revise" else self.actions_session_combo
        session_value = combo.currentData()
        target = Path(str(session_value)) if session_value else None
        if target is None:
            self._set_shared_session_selection(None, source=mode)
            return
        if self.current_capture_dir is None or str(self.current_capture_dir) != str(target):
            self.current_capture_dir = target
            self._populate_raw_requests(load_raw_capture_entries(self.current_capture_dir))
            if self.browser_running:
                self._set_active_capture_session(self.current_capture_dir)
        self._set_shared_session_selection(target, source=mode)

    def _on_capture_session_changed(self, index: int) -> None:
        if index < 0:
            if self.browser_running:
                self._set_active_capture_session(None)
            self.current_capture_dir = None
            self.last_capture_entry_count = 0
            self.capture_refresh_timer.stop()
            self._populate_raw_requests([])
            self._set_shared_session_selection(None, source="capture")
            self._update_capture_buttons()
            return
        session_value = self.raw_sessions_combo.itemData(index)
        self.current_capture_dir = Path(str(session_value))
        if self.browser_running:
            self._set_active_capture_session(self.current_capture_dir)
        self._populate_raw_requests(load_raw_capture_entries(self.current_capture_dir))
        self._set_shared_session_selection(self.current_capture_dir, source="capture")
        if self.browser_running:
            self.capture_refresh_timer.start()
        self._update_capture_buttons()

    def _populate_raw_requests(self, entries: list[dict[str, object]]) -> None:
        previous_count = self.raw_requests_table.rowCount()
        should_scroll_to_bottom = len(entries) > previous_count
        self.raw_requests_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.raw_requests_table.setItem(row, 0, QTableWidgetItem(str(entry.get("name") or "")))
            self.raw_requests_table.setItem(row, 1, QTableWidgetItem(str(entry.get("method") or "")))
            self.raw_requests_table.setItem(row, 2, QTableWidgetItem(str(entry.get("url") or "")))
            self.raw_requests_table.setItem(row, 3, QTableWidgetItem(str(entry.get("status") or "")))
            self.raw_requests_table.setItem(row, 4, QTableWidgetItem(str(entry.get("content_type") or "")))
            self.raw_requests_table.setItem(row, 5, QTableWidgetItem(str(entry.get("occurrence_count") or "")))
            self.raw_requests_table.item(row, 0).setData(Qt.UserRole, entry.get("path"))
        self.last_capture_entry_count = len(entries)
        if should_scroll_to_bottom and entries:
            self.raw_requests_table.scrollToBottom()
        self._refresh_actions_session_combo()

    def _refresh_current_capture_entries(self) -> None:
        if self.current_capture_dir is None or not self.current_capture_dir.exists():
            self.capture_refresh_timer.stop()
            return
        entries = load_raw_capture_entries(self.current_capture_dir)
        if len(entries) != self.last_capture_entry_count:
            self._populate_raw_requests(entries)

    def _update_capture_buttons(self) -> None:
        enabled = self.current_capture_dir is not None and self.current_capture_dir.exists()
        self.open_session_folder_button.setEnabled(True)
        self.rename_session_button.setEnabled(enabled)
        self.clear_session_button.setEnabled(enabled)
        self.delete_selected_requests_button.setEnabled(enabled)
        self.run_new_button.setEnabled(self.current_manifest is not None)
        self._update_capture_toggle_button()

    def toggle_capture_enabled(self) -> None:
        if not self.browser_running:
            return
        if self.current_capture_dir is None or not self.current_capture_dir.exists():
            created = self._create_capture_session(recording=False)
            if created is None:
                return
        new_state = not capture_enabled(self.current_capture_dir)
        self._set_active_capture_session(self.current_capture_dir)
        set_capture_enabled(self.current_capture_dir, new_state)
        self.log(f"Capture {'enabled' if new_state else 'paused'}: {self.current_capture_dir}")
        self._update_capture_buttons()

    def open_current_capture_folder(self) -> None:
        if self.current_capture_dir is not None and self.current_capture_dir.exists():
            target = self.current_capture_dir
        elif self.current_manifest is not None:
            target = module_capture_root(self.current_manifest.module_id, base_root=self._raw_capture_root())
            target.mkdir(parents=True, exist_ok=True)
        else:
            target = self._raw_capture_root()
            target.mkdir(parents=True, exist_ok=True)
        self.log(f"Open capture folder: {target}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def clear_current_session(self) -> None:
        if self.current_capture_dir is None:
            return
        if QMessageBox.question(
            self,
            "Clear Session",
            f"Delete all captured request files in '{self.current_capture_dir.name}'?",
        ) != QMessageBox.Yes:
            return
        for path in self.current_capture_dir.glob("*.json"):
            path.unlink(missing_ok=True)
        self.refresh_capture_sessions()

    def rename_current_session(self) -> None:
        if self.current_capture_dir is None or not self.current_capture_dir.exists():
            return
        self._rename_session_path(self.current_capture_dir)

    def delete_selected_requests(self) -> None:
        if self.current_capture_dir is None:
            return
        self._delete_session_path(self.current_capture_dir)

    def open_capture_request_details(self) -> None:
        row = self.raw_requests_table.currentRow()
        if row < 0:
            return
        item = self.raw_requests_table.item(row, 0)
        if item is None:
            return
        path_value = item.data(Qt.UserRole)
        if not path_value:
            return
        capture_path = Path(str(path_value))
        if not capture_path.exists():
            QMessageBox.warning(self, "Missing Capture File", f"Capture file not found:\n{capture_path}")
            return
        try:
            payload = json.loads(capture_path.read_text(encoding="utf-8"))
            pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Capture Read Failed", f"Could not load capture file:\n{exc}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Capture Details - {capture_path.name}")
        dialog.resize(980, 720)
        layout = QVBoxLayout(dialog)

        path_label = QLabel(str(capture_path))
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(pretty)
        layout.addWidget(details, stretch=1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        dialog.exec()

    def open_selected_page_route(self) -> None:
        row = self.pages_table.currentRow()
        if row < 0 or self.current_manifest is None:
            return
        route_item = self.pages_table.item(row, 1)
        if route_item is None:
            return
        route = route_item.text().strip()
        if not route:
            return
        self.log(f"Open route requested: {route}")
        if QMessageBox.question(
            self,
            "Open Browser",
            f"Open a logged-in browser at route:\n{route}",
        ) != QMessageBox.Yes:
            return
        app_url = self._resolve_route_to_url(route)
        if app_url is None:
            self.log("Open route cancelled or base URL invalid.")
            return
        if self.run_browser_command(app_url):
            self.tabs.setCurrentIndex(2)

    def _open_page_route_by_name(self, page_name: str) -> bool:
        if self.current_manifest is None:
            return False
        target = page_name.strip().lower()
        for row in range(self.pages_table.rowCount()):
            item = self.pages_table.item(row, 0)
            route_item = self.pages_table.item(row, 1)
            if item is None or route_item is None:
                continue
            if item.text().strip().lower() != target:
                continue
            self.pages_table.setCurrentCell(row, 0)
            self._flash_widget(self.pages_table)
            route = route_item.text().strip()
            self.log(f"Open route requested: {route}")
            app_url = self._resolve_route_to_url(route)
            if app_url is None:
                self.log("Open route cancelled or base URL invalid.")
                return False
            if self.run_browser_command(app_url):
                self.tabs.setCurrentIndex(2)
                return True
            return False
        return False

    def open_default_browser_session(self) -> None:
        self.log("Open browser session requested.")
        app_url: str | None = None
        if self.current_manifest is not None:
            browser = self.current_manifest.data.get("module", {}).get("browser", {})
            app_url = str(browser.get("base_url") or "").strip() or None
        if self.run_browser_command(app_url):
            self.tabs.setCurrentIndex(2)

    def open_new_capture_session(self) -> None:
        self.log("New capture session requested.")
        was_recording = False
        if self.current_capture_dir is not None and self.current_capture_dir.exists():
            was_recording = capture_enabled(self.current_capture_dir)
        created = self._create_capture_session(recording=was_recording if self.browser_running else False)
        if created is None:
            return
        app_url: str | None = None
        if self.current_manifest is not None:
            browser = self.current_manifest.data.get("module", {}).get("browser", {})
            app_url = str(browser.get("base_url") or "").strip() or None
        if not self.browser_running:
            if self.run_browser_command(app_url):
                self.tabs.setCurrentIndex(1)
        elif self.browser_running:
            self.tabs.setCurrentIndex(1)
            self._update_capture_buttons()

    def _resolve_route_to_url(self, route: str) -> str | None:
        if self.current_manifest is None:
            return None
        placeholders = re.findall(r"{([^}]+)}", route)
        resolved = route
        for placeholder in placeholders:
            value, ok = QInputDialog.getText(self, "Route Placeholder", f"Value for {placeholder}:")
            if not ok or not value.strip():
                return None
            resolved = resolved.replace("{" + placeholder + "}", value.strip())
        if resolved.startswith("http://") or resolved.startswith("https://"):
            return resolved
        browser = self.current_manifest.data.get("module", {}).get("browser", {})
        base_url = str(browser.get("base_url") or "").rstrip("/")
        if not base_url:
            QMessageBox.warning(self, "Missing Base URL", "This module does not define module.browser.base_url.")
            return None
        return base_url + resolved

    def run_browser_command(self, app_url: str | None) -> bool:
        command = self.browser_command_edit.text().strip()
        if not command:
            command = "python .\\scripts\\open_capture_browser.py"
        capture_args = []
        for kind in self._selected_capture_content_kinds():
            capture_args.append(f"--capture-content-kind {kind}")
        capture_args.append(f'--capture-mode {"last" if self.capture_mode_combo.currentText() == "Keep Last" else "all"}')
        for token in [item.strip() for item in self.capture_url_filter_edit.text().split(",") if item.strip()]:
            capture_args.append(f'--capture-url-contains "{token}"')
        for token in [item.strip() for item in self.capture_domain_filter_edit.text().split(",") if item.strip()]:
            capture_args.append(f'--capture-domain-contains "{token}"')
        if self.current_manifest is not None:
            capture_args.append(
                f'--capture-root "{module_capture_root(self.current_manifest.module_id, base_root=self._raw_capture_root())}"'
            )
            module_data = self.current_manifest.data.get("module", {})
            package_path = str(module_data.get("package_path") or "").replace("\\", "/").strip("/")
            module_import = package_path.split("/")[-1] if package_path else ""
            client_class = str(module_data.get("client_class") or "").strip()
            if self.current_manifest.module_id:
                capture_args.append(f'--module-id "{self.current_manifest.module_id}"')
            if module_import:
                capture_args.append(f'--module-import "{module_import}"')
            if client_class:
                capture_args.append(f'--client-class "{client_class}"')
            capture_args.append(f'--python-src-root "{APP_ROOT / "python" / "src"}"')
        capture_args.append("--start-capture-paused")
        if app_url:
            capture_args.append(f'--app-url "{app_url}"')
        else:
            QMessageBox.warning(self, "Missing Base URL", "This module does not define a base URL for launching a browser.")
            return False
        full_command = " ".join([command, *capture_args]).strip()
        self.run_browser_process(full_command)
        return True

    def run_browser_process(self, command: str) -> None:
        if self.browser_process is not None and self.browser_process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Browser Running", "A managed browser session is already running.")
            return
        self.browser_process = QProcess(self)
        self.browser_process.setWorkingDirectory(str(APP_ROOT))
        self.browser_process.readyReadStandardOutput.connect(self._append_browser_stdout)
        self.browser_process.readyReadStandardError.connect(self._append_browser_stderr)
        self.browser_process.finished.connect(self._browser_process_finished)
        self.browser_running = True
        self.browser_module_id = self.current_manifest.module_id if self.current_manifest else None
        self.capture_refresh_timer.start()
        self._update_capture_buttons()
        self.log(f"> powershell -NoProfile -Command {command}")
        self.browser_process.start("powershell", ["-NoProfile", "-Command", command])

    def run_manifest_command(self, command: str) -> None:
        if not command.strip():
            QMessageBox.information(self, "No Command", "This action is not configured for the current module.")
            return
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Busy", "A command is already running.")
            return
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(APP_ROOT))
        self.process.readyReadStandardOutput.connect(self._append_stdout)
        self.process.readyReadStandardError.connect(self._append_stderr)
        self.process.finished.connect(self._process_finished)
        self.log(f"> powershell -NoProfile -Command {command}")
        self.process.start("powershell", ["-NoProfile", "-Command", command])

    def _append_stdout(self) -> None:
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self._handle_process_output_line(line)

    def _append_stderr(self) -> None:
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self.log(line)

    def _append_browser_stdout(self) -> None:
        if self.browser_process is None:
            return
        text = bytes(self.browser_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self._handle_process_output_line(line)

    def _append_browser_stderr(self) -> None:
        if self.browser_process is None:
            return
        text = bytes(self.browser_process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self.log(line)

    def _handle_process_output_line(self, line: str) -> None:
        self.log(line)
        if line.startswith("CAPTURE_DIR="):
            capture_dir = Path(line.split("=", 1)[1].strip())
            self.current_capture_dir = capture_dir
            self.tabs.setCurrentIndex(1)
            self.refresh_capture_sessions()

    def _process_finished(self) -> None:
        if self.process is None:
            return
        self.log(f"Command exited with code {self.process.exitCode()}")
        self.refresh_current_views()

    def _browser_process_finished(self) -> None:
        if self.browser_process is None:
            return
        self.log(f"Browser command exited with code {self.browser_process.exitCode()}")
        self.browser_running = False
        self.browser_module_id = None
        self.capture_refresh_timer.stop()
        self.refresh_capture_sessions()
        self._update_capture_buttons()

    def log(self, message: str) -> None:
        self.log_output.append(self._ansi_to_html(message))

    @staticmethod
    def _ansi_to_html(text: str) -> str:
        """Render a small subset of ANSI terminal colors into HTML."""
        ansi_colors = {
            "30": "#000000",
            "31": "#ff5f56",
            "32": "#27c93f",
            "33": "#ffbd2e",
            "34": "#1e90ff",
            "35": "#ff6ac1",
            "36": "#5ac8fa",
            "37": "#f8f8f2",
            "90": "#7f8c8d",
            "91": "#ff6b6b",
            "92": "#7bed9f",
            "93": "#f9ca24",
            "94": "#70a1ff",
            "95": "#e056fd",
            "96": "#7ed6df",
            "97": "#ffffff",
        }

        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        pattern = re.compile(r"\x1b\[([0-9;]+)m")
        result: list[str] = []
        open_span = False
        last = 0
        for match in pattern.finditer(escaped):
            result.append(escaped[last:match.start()])
            codes = match.group(1).split(";")
            if "0" in codes:
                if open_span:
                    result.append("</span>")
                    open_span = False
            else:
                color = next((ansi_colors.get(code) for code in reversed(codes) if code in ansi_colors), None)
                if color:
                    if open_span:
                        result.append("</span>")
                    result.append(f'<span style="color: {color};">')
                    open_span = True
            last = match.end()
        result.append(escaped[last:])
        if open_span:
            result.append("</span>")
        return "".join(result)

    def _clear_fields(self) -> None:
        for widget in (
            self.name_edit,
            self.description_edit,
            self.base_url_edit,
            self.raw_capture_root_edit,
            self.processed_capture_root_edit,
            self.capture_url_filter_edit,
            self.capture_domain_filter_edit,
            self.test_command_edit,
            self.browser_command_edit,
            self.process_capture_command_edit,
        ):
            widget.clear()
        self._set_capture_content_kinds(["all"])
        self.capture_mode_combo.setCurrentText("Keep Last")
        self.prompt_description_edit.clear()
        self.prompt_editor.clear()
        self.ollama_reply_output.clear()
        self.process_result_summary_label.clear()
        self.process_status_label.clear()
        self.prompt_combo.clear()
        self.actions_session_combo.clear()
        self.actions_session_count_label.clear()
        self.revise_session_combo.clear()
        self.revise_session_count_label.clear()
        self.revise_history_output.clear()
        self.revise_prompt_editor.clear()
        self.revise_reply_output.clear()
        self.revise_result_summary_label.clear()
        self.revise_status_label.clear()
        self.endpoints_table.setRowCount(0)
        self.pages_table.setRowCount(0)
        self.raw_sessions_combo.clear()
        self._rebuild_reply_tabs("process", "")
        self._rebuild_reply_tabs("revise", "")
        self._update_llm_action_buttons()
        self.raw_requests_table.setRowCount(0)


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
