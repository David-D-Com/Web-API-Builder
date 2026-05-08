"""Qt6 desktop shell for managing API-builder modules."""

from __future__ import annotations

import re
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
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
    create_module_scaffold,
    delete_module,
    infer_client_methods,
    is_blank_module,
    load_manifests,
    load_raw_capture_entries,
    load_raw_capture_sessions,
    module_capture_root,
    next_blank_module_id,
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
    "capture_session_combo_width": 240,
    "capture_button_width": 68,
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
    "capture_button_width": 78,
    "capture_session_combo_width": 180,
    "session_action_button_width": 60,
    "run_new_button_width": 84,
    "ollama_setting_width": 220,
    "prompt_toolbar_button_width": 64,
    "ollama_host_default": "192.168.66.11",
    "ollama_port_default": "11434",
}



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
        self.process: QProcess | None = None
        self.browser_process: QProcess | None = None
        self.current_capture_dir: Path | None = None
        self.browser_running = False
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

        self.module_combo = QComboBox()
        self.module_combo.currentIndexChanged.connect(self._on_module_combo_changed)
        self.dark_mode_check = QCheckBox("Dark mode")
        self.dark_mode_check.setChecked(bool(self.settings.value("theme/dark_mode", True, type=bool)))
        self.dark_mode_check.toggled.connect(self._on_theme_toggled)
        self.debug_mode_check = QCheckBox("Debug mode")
        self.debug_mode_check.setChecked(bool(self.settings.value("debug/enabled", False, type=bool)))
        self.debug_mode_check.toggled.connect(self._on_debug_mode_toggled)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _index: self.refresh_capture_sessions())

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._schedule_autosave)
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
        self.ollama_model_combo.currentIndexChanged.connect(lambda _i: self._schedule_autosave())
        self.actions_session_combo = QComboBox()
        self.actions_session_combo.setFixedWidth(UI_SIZES["capture_session_combo_width"])
        self.prompt_combo = QComboBox()
        self.prompt_combo.setFixedWidth(220)
        self.prompt_combo.currentIndexChanged.connect(self._on_prompt_selected)
        self.prompt_editor = QTextEdit()
        self.ollama_reply_output = QTextEdit()
        self.ollama_reply_output.setReadOnly(True)

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

        self.run_new_button = QPushButton("Run New")
        self.run_new_button.setProperty("compact", True)
        self.run_new_button.setProperty("success", True)
        self.run_new_button.clicked.connect(self.open_default_browser_session)
        self.capture_start_button = QPushButton("▶")
        self.capture_start_button.setProperty("compact", True)
        self.capture_start_button.clicked.connect(self.start_capture_for_active_session)
        self.capture_stop_button = QPushButton("■")
        self.capture_stop_button.setProperty("compact", True)
        self.capture_stop_button.clicked.connect(self.stop_capture_for_active_session)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "QTextEdit { background-color: #000000; color: #ffffff; border: 1px solid #333333; }"
        )
        self.log_output.setAcceptRichText(True)

        self.play_pause_button = QPushButton("Pause")
        self.play_pause_button.setProperty("compact", True)
        self.play_pause_button.clicked.connect(self.toggle_capture_enabled)
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
        self._apply_theme()
        self.reload_modules()

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

    def _module_prompts(self) -> list[dict[str, str]]:
        if self.current_manifest is None:
            return []
        actions = self.current_manifest.data.setdefault("actions", {})
        prompts = actions.setdefault("prompts", [])
        if not isinstance(prompts, list):
            actions["prompts"] = []
            return actions["prompts"]
        return prompts

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
        current = self.ollama_model_combo.currentText()
        self.ollama_model_combo.blockSignals(True)
        self.ollama_model_combo.clear()
        self.ollama_model_combo.addItems(models)
        if current and current in models:
            self.ollama_model_combo.setCurrentText(current)
        self.ollama_model_combo.blockSignals(False)
        self.log(f"Loaded {len(models)} Ollama model(s).")

    def _refresh_actions_session_combo(self) -> None:
        current = self.actions_session_combo.currentData()
        sessions = load_raw_capture_sessions(
            self.current_manifest.module_id if self.current_manifest else None,
            base_root=self._raw_capture_root(),
        )
        self.actions_session_combo.blockSignals(True)
        self.actions_session_combo.clear()
        for session in sessions:
            self.actions_session_combo.addItem(session.name, str(session))
        self.actions_session_combo.blockSignals(False)
        if current:
            for index in range(self.actions_session_combo.count()):
                if self.actions_session_combo.itemData(index) == current:
                    self.actions_session_combo.setCurrentIndex(index)
                    return
        if sessions:
            self.actions_session_combo.setCurrentIndex(0)

    def _refresh_prompt_combo(self) -> None:
        current = self.prompt_combo.currentData()
        prompts = self._module_prompts()
        self.prompt_combo.blockSignals(True)
        self.prompt_combo.clear()
        for index, prompt in enumerate(prompts):
            self.prompt_combo.addItem(str(prompt.get("name") or f"Prompt {index + 1}"), index)
        self.prompt_combo.blockSignals(False)
        if current is not None:
            for index in range(self.prompt_combo.count()):
                if self.prompt_combo.itemData(index) == current:
                    self.prompt_combo.setCurrentIndex(index)
                    return
        if prompts:
            self.prompt_combo.setCurrentIndex(0)
        else:
            self.prompt_editor.clear()

    def _on_prompt_selected(self, index: int) -> None:
        prompts = self._module_prompts()
        if index < 0 or index >= len(prompts):
            return
        self.prompt_editor.setPlainText(str(prompts[index].get("text") or ""))

    def _new_prompt(self) -> None:
        if self.current_manifest is None:
            return
        name, ok = QInputDialog.getText(self, "New Prompt", "Prompt name:")
        if not ok or not name.strip():
            return
        self._module_prompts().append({"name": name.strip(), "text": ""})
        self._refresh_prompt_combo()
        self.prompt_combo.setCurrentText(name.strip())
        self._schedule_autosave()

    def _save_prompt(self) -> None:
        if self.current_manifest is None:
            return
        prompts = self._module_prompts()
        index = self.prompt_combo.currentIndex()
        if index < 0:
            self._new_prompt()
            return
        prompts[index]["text"] = self.prompt_editor.toPlainText()
        prompts[index]["name"] = self.prompt_combo.currentText()
        self.save_manifest(silent=True)
        self.log(f"Saved prompt: {prompts[index]['name']}")

    def _delete_prompt(self) -> None:
        if self.current_manifest is None:
            return
        prompts = self._module_prompts()
        index = self.prompt_combo.currentIndex()
        if index < 0 or index >= len(prompts):
            return
        prompt_name = str(prompts[index].get("name") or "prompt")
        if QMessageBox.question(self, "Delete Prompt", f"Delete prompt '{prompt_name}'?") != QMessageBox.Yes:
            return
        prompts.pop(index)
        self._refresh_prompt_combo()
        self.save_manifest(silent=True)

    def _send_prompt_to_ollama(self) -> None:
        model = self.ollama_model_combo.currentText().strip()
        session_path_value = self.actions_session_combo.currentData()
        if not model:
            self.log("No Ollama model selected.")
            return
        if not session_path_value:
            self.log("No capture session selected for analysis.")
            return
        session_path = Path(str(session_path_value))
        context_lines = []
        for entry in load_raw_capture_entries(session_path)[:50]:
            context_lines.append(
                f"{entry.get('method','')} {entry.get('url','')} status={entry.get('status','')} type={entry.get('content_type','')}"
            )
        prompt_text = self.prompt_editor.toPlainText().strip()
        if not prompt_text:
            self.log("Prompt editor is empty.")
            return
        full_prompt = (
            "You are analyzing captured web API traffic.\n\n"
            f"Session folder: {session_path}\n"
            "Captured requests:\n"
            + "\n".join(context_lines)
            + "\n\nUser prompt:\n"
            + prompt_text
        )
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        url = self._ollama_base_url() + "/api/generate"
        self.log(f"Sending prompt to Ollama model '{model}' using {session_path.name}")
        try:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.log(f"Ollama request failed: {exc}")
            self.ollama_reply_output.setPlainText(str(exc))
            return
        reply = str(result.get("response") or "")
        self.ollama_reply_output.setPlainText(reply)
        self.log("Ollama reply received.")

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

        self.setCentralWidget(central)

    def _build_details_panel(self) -> QWidget:
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        self.tabs.addTab(self._build_captures_tab(), "Captures")
        self.tabs.addTab(self._build_actions_tab(), "Actions")
        self.tabs.addTab(self._build_endpoints_tab(), "Endpoints")
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

        workspace_group = QGroupBox("Workspace Settings")
        workspace_form = QFormLayout(workspace_group)
        workspace_form.addRow("Raw Capture Root", self.raw_capture_root_edit)
        workspace_form.addRow("Processed Capture Root", self.processed_capture_root_edit)
        layout.addWidget(workspace_group)

        page_group = QGroupBox("Discovered Routes")
        page_layout = QVBoxLayout(page_group)
        page_layout.addWidget(QLabel("Double-click a route to open a logged-in browser at that context."))
        page_layout.addWidget(self.pages_table)
        layout.addWidget(page_group)
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
        controls.addWidget(self.play_pause_button)
        controls.addWidget(self.clear_session_button)
        controls.addWidget(self.delete_selected_requests_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.setProperty("compact", True)
        refresh_button.setFixedWidth(UI_SIZES["capture_button_width"])
        refresh_button.setFixedHeight(UI_SIZES["capture_button_height"])
        refresh_button.clicked.connect(self.refresh_capture_sessions)
        controls.addWidget(refresh_button)
        self.run_new_button.setFixedWidth(UI_SIZES["run_new_button_width"])
        self.run_new_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.run_new_button)
        self.capture_start_button.setFixedWidth(UI_SIZES["session_action_button_width"])
        self.capture_start_button.setFixedHeight(UI_SIZES["capture_button_height"])
        self.capture_stop_button.setFixedWidth(UI_SIZES["session_action_button_width"])
        self.capture_stop_button.setFixedHeight(UI_SIZES["capture_button_height"])
        controls.addWidget(self.capture_start_button)
        controls.addWidget(self.capture_stop_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        for button in (
            self.play_pause_button,
            self.clear_session_button,
            self.delete_selected_requests_button,
        ):
            button.setFixedWidth(UI_SIZES["capture_button_width"])
            button.setFixedHeight(UI_SIZES["capture_button_height"])

        layout.addWidget(self.raw_requests_table, stretch=1)
        return widget

    def _build_actions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        command_group = QGroupBox("Commands")
        form = QFormLayout(command_group)
        form.addRow("Test Command", self.test_command_edit)
        form.addRow("Browser Command", self.browser_command_edit)
        form.addRow("Process Capture Command", self.process_capture_command_edit)
        layout.addWidget(command_group)

        command_buttons = QHBoxLayout()
        run_test = QPushButton("Run Tests")
        run_test.clicked.connect(lambda: self.run_manifest_command(self.test_command_edit.text()))
        open_browser = QPushButton("Open Browser Session")
        open_browser.clicked.connect(self.open_default_browser_session)
        process_capture = QPushButton("Process Captures")
        process_capture.clicked.connect(lambda: self.run_manifest_command(self.process_capture_command_edit.text()))
        command_buttons.addWidget(run_test)
        command_buttons.addWidget(open_browser)
        command_buttons.addWidget(process_capture)
        command_buttons.addStretch(1)
        layout.addLayout(command_buttons)

        ollama_group = QGroupBox("Ollama")
        ollama_layout = QVBoxLayout(ollama_group)
        ollama_settings = QHBoxLayout()
        ollama_settings.addWidget(QLabel("Host"))
        ollama_settings.addWidget(self.ollama_host_edit)
        ollama_settings.addWidget(QLabel("Port"))
        ollama_settings.addWidget(self.ollama_port_edit)
        ollama_settings.addWidget(QLabel("Model"))
        ollama_settings.addWidget(self.ollama_model_combo)
        refresh_models = QPushButton("Refresh Models")
        refresh_models.clicked.connect(self._load_ollama_models)
        ollama_settings.addWidget(refresh_models)
        ollama_settings.addStretch(1)
        ollama_layout.addLayout(ollama_settings)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("Session"))
        session_row.addWidget(self.actions_session_combo)
        session_row.addStretch(1)
        ollama_layout.addLayout(session_row)

        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt"))
        prompt_row.addWidget(self.prompt_combo)
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
        prompt_row.addWidget(prompt_new)
        prompt_row.addWidget(prompt_save)
        prompt_row.addWidget(prompt_delete)
        prompt_row.addStretch(1)
        ollama_layout.addLayout(prompt_row)

        ollama_layout.addWidget(QLabel("Prompt"))
        ollama_layout.addWidget(self.prompt_editor)
        send_button = QPushButton("Send")
        send_button.setProperty("success", True)
        send_button.clicked.connect(self._send_prompt_to_ollama)
        ollama_layout.addWidget(send_button, alignment=Qt.AlignLeft)
        ollama_layout.addWidget(QLabel("Reply"))
        ollama_layout.addWidget(self.ollama_reply_output)
        layout.addWidget(ollama_group)

        note = QLabel(
            "Browser launches inherit the current capture settings from the Capture tab. "
            "When a browser session starts successfully, the app switches to the Capture tab."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
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
        blank = next((manifest for manifest in self.manifests if is_blank_module(manifest)), None)
        if blank is None:
            module_id = next_blank_module_id()
            blank = create_module_from_template(module_id, f"New Module {module_id.split('_')[-1]}")
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
        if not commands["run_tests"]:
            commands["run_tests"] = default_test_command
        commands["open_browser"] = self.browser_command_edit.text().strip()
        commands["process_captures"] = self.process_capture_command_edit.text().strip()
        create_module_scaffold(
            module_id=self.current_manifest.module_id,
            module_name=data["name"],
            payload=data,
        )
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
        self.current_manifest = manifest
        self.refresh_current_views()

    def refresh_current_views(self) -> None:
        if self.current_manifest is None:
            self._clear_fields()
            return
        data = self.current_manifest.data
        module_data = data.get("module", {})
        commands = data.get("commands", {})
        capture = module_data.get("capture", {})

        self.name_edit.setText(str(data.get("name") or ""))
        self.description_edit.setText(str(data.get("description") or ""))
        self.base_url_edit.setText(str((module_data.get("browser") or {}).get("base_url") or ""))
        self.raw_capture_root_edit.setText(str(self._raw_capture_root()))
        self.processed_capture_root_edit.setText(str(self._processed_capture_root()))
        self.capture_url_filter_edit.setText(", ".join(capture.get("url_contains") or []))
        self.capture_domain_filter_edit.setText(", ".join(capture.get("domain_contains") or []))
        content_kinds = capture.get("content_kinds")
        if not content_kinds:
            content_kinds = ["json"] if bool(capture.get("include_json_only", True)) else ["all"]
        self._set_capture_content_kinds(list(content_kinds))
        self.capture_mode_combo.setCurrentText("Keep All" if str(capture.get("mode") or "last") == "all" else "Keep Last")
        self.test_command_edit.setText(str(commands.get("run_tests") or ""))
        self.browser_command_edit.setText(str(commands.get("open_browser") or ""))
        self.process_capture_command_edit.setText(str(commands.get("process_captures") or ""))
        saved_model = str(self.settings.value("ollama/model", "") or "")
        if saved_model and self.ollama_model_combo.findText(saved_model) >= 0:
            self.ollama_model_combo.setCurrentText(saved_model)
        self._refresh_actions_session_combo()
        self._refresh_prompt_combo()

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

    def refresh_capture_sessions(self) -> None:
        sessions = load_raw_capture_sessions(
            self.current_manifest.module_id if self.current_manifest else None,
            base_root=self._raw_capture_root(),
        )
        selected = self.raw_sessions_combo.currentData()
        self.raw_sessions_combo.blockSignals(True)
        self.raw_sessions_combo.clear()
        for session in sessions:
            self.raw_sessions_combo.addItem(session.name, str(session))
        self.raw_sessions_combo.blockSignals(False)
        if self.current_capture_dir and self.current_capture_dir.exists():
            self._select_session_in_combo(self.current_capture_dir)
        elif selected:
            self._select_session_in_combo(Path(str(selected)))
        elif sessions:
            self.raw_sessions_combo.setCurrentIndex(0)
            self._on_capture_session_changed(0)
        else:
            self.current_capture_dir = None
            self._populate_raw_requests([])
            self._update_capture_buttons()

    def _select_session_in_combo(self, session_dir: Path) -> None:
        for index in range(self.raw_sessions_combo.count()):
            if self.raw_sessions_combo.itemData(index) == str(session_dir):
                self.raw_sessions_combo.setCurrentIndex(index)
                self._on_capture_session_changed(index)
                return

    def _on_capture_session_changed(self, index: int) -> None:
        if index < 0:
            self.current_capture_dir = None
            self._populate_raw_requests([])
            self._update_capture_buttons()
            return
        session_value = self.raw_sessions_combo.itemData(index)
        self.current_capture_dir = Path(str(session_value))
        self._populate_raw_requests(load_raw_capture_entries(self.current_capture_dir))
        self._update_capture_buttons()

    def _populate_raw_requests(self, entries: list[dict[str, object]]) -> None:
        self.raw_requests_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.raw_requests_table.setItem(row, 0, QTableWidgetItem(str(entry.get("name") or "")))
            self.raw_requests_table.setItem(row, 1, QTableWidgetItem(str(entry.get("method") or "")))
            self.raw_requests_table.setItem(row, 2, QTableWidgetItem(str(entry.get("url") or "")))
            self.raw_requests_table.setItem(row, 3, QTableWidgetItem(str(entry.get("status") or "")))
            self.raw_requests_table.setItem(row, 4, QTableWidgetItem(str(entry.get("content_type") or "")))
            self.raw_requests_table.setItem(row, 5, QTableWidgetItem(str(entry.get("occurrence_count") or "")))
            self.raw_requests_table.item(row, 0).setData(Qt.UserRole, entry.get("path"))
        self._refresh_actions_session_combo()

    def _update_capture_buttons(self) -> None:
        enabled = self.current_capture_dir is not None and self.current_capture_dir.exists()
        self.play_pause_button.setEnabled(enabled)
        self.clear_session_button.setEnabled(enabled)
        self.delete_selected_requests_button.setEnabled(enabled)
        browser_enabled = self.browser_running
        self.capture_start_button.setEnabled(browser_enabled and enabled)
        self.capture_stop_button.setEnabled(browser_enabled and enabled)
        self.run_new_button.setEnabled(not browser_enabled)
        if enabled and self.current_capture_dir is not None:
            if capture_enabled(self.current_capture_dir):
                self.play_pause_button.setText("Pause")
                self.capture_start_button.setEnabled(False)
                self.capture_stop_button.setEnabled(browser_enabled)
            else:
                self.play_pause_button.setText("Resume")
                self.capture_start_button.setEnabled(browser_enabled)
                self.capture_stop_button.setEnabled(False)
        else:
            self.play_pause_button.setText("Pause")
            self.capture_start_button.setEnabled(False)
            self.capture_stop_button.setEnabled(False)

    def toggle_capture_enabled(self) -> None:
        if self.current_capture_dir is None:
            return
        new_state = not capture_enabled(self.current_capture_dir)
        set_capture_enabled(self.current_capture_dir, new_state)
        self.log(f"Capture {'enabled' if new_state else 'paused'}: {self.current_capture_dir}")
        self._update_capture_buttons()

    def start_capture_for_active_session(self) -> None:
        if self.current_capture_dir is None:
            return
        set_capture_enabled(self.current_capture_dir, True)
        self.log(f"Capture enabled: {self.current_capture_dir}")
        self._update_capture_buttons()

    def stop_capture_for_active_session(self) -> None:
        if self.current_capture_dir is None:
            return
        set_capture_enabled(self.current_capture_dir, False)
        self.log(f"Capture paused: {self.current_capture_dir}")
        self._update_capture_buttons()

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

    def delete_selected_requests(self) -> None:
        if self.current_capture_dir is None:
            return
        selected_rows = sorted({item.row() for item in self.raw_requests_table.selectedItems()})
        if not selected_rows:
            return
        if QMessageBox.question(
            self,
            "Delete Requests",
            f"Delete {len(selected_rows)} selected capture file(s)?",
        ) != QMessageBox.Yes:
            return
        for row in selected_rows:
            item = self.raw_requests_table.item(row, 0)
            if item is None:
                continue
            path_value = item.data(Qt.UserRole)
            if path_value:
                Path(str(path_value)).unlink(missing_ok=True)
        self.refresh_capture_sessions()

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

    def open_default_browser_session(self) -> None:
        self.log("Open browser session requested.")
        if self.run_browser_command(None):
            self.tabs.setCurrentIndex(2)

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
            command = "python .\\scripts\\open_solis_browser_session.py"
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
        capture_args.append("--start-capture-paused")
        if app_url:
            capture_args.append(f'--app-url "{app_url}"')
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
        self.prompt_editor.clear()
        self.ollama_reply_output.clear()
        self.prompt_combo.clear()
        self.actions_session_combo.clear()
        self.endpoints_table.setRowCount(0)
        self.pages_table.setRowCount(0)
        self.raw_sessions_combo.clear()
        self.raw_requests_table.setRowCount(0)


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
