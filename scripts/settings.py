# scripts/settings.py
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Any

from PySide6.QtCore import QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import QApplication

from observables import (
    ObservableBool, ObservableInt, ObservableList, ObservableStr,
)
from paths import writable_path
from config import get_baits, DEFAULT_GAME_EXE

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "game_exe_path": DEFAULT_GAME_EXE,
    "minimize_to_tray": False,
    "start_minimized": False,
    "debug_console": False,
    "ignore_abort": False,
    "alert_sound": "default",
    "bait_priority": [],
    "capture_mode": "auto",
    "capture_monitor": 1,
    "sound_effects": True,
    "auto_bait": False,
    "hotkey_start": "F5",
    "hotkey_stop": "F6",
    "hotkey_auto_switch": "F7",
    "hotkey_detect_baits": "F8",
    "hotkey_settings": "F1",
    "hotkey_debug": "F2",
    "hotkey_game_only": True,
    "allow_controller_fallback": True,
}

def _settings_path() -> str:
    return writable_path("settings.json")

def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return default

def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _as_str(value: Any, default: str) -> str:
    return str(value) if value is not None else default

class Settings(QObject):
    SAVE_DEBOUNCE_MS = 400
    save_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        data = self._load()

        self.game_exe_path = ObservableStr(_as_str(data.get("game_exe_path"), DEFAULTS["game_exe_path"]))
        self.minimize_to_tray = ObservableBool(_as_bool(data.get("minimize_to_tray"), DEFAULTS["minimize_to_tray"]))
        self.start_minimized = ObservableBool(_as_bool(data.get("start_minimized"), DEFAULTS["start_minimized"]))
        self.debug_console = ObservableBool(_as_bool(data.get("debug_console"), DEFAULTS["debug_console"]))
        self.ignore_abort = ObservableBool(_as_bool(data.get("ignore_abort"), DEFAULTS["ignore_abort"]))
        self.sound_effects = ObservableBool(_as_bool(data.get("sound_effects"), DEFAULTS["sound_effects"]))
        self.alert_sound = ObservableStr(_as_str(data.get("alert_sound"), DEFAULTS["alert_sound"]))

        raw_priority = data.get("bait_priority", DEFAULTS["bait_priority"])
        self.bait_priority = ObservableList(self._normalize_priority(raw_priority))

        self.capture_mode = ObservableStr(_as_str(data.get("capture_mode"), DEFAULTS["capture_mode"]))
        self.capture_monitor = ObservableInt(_as_int(data.get("capture_monitor"), DEFAULTS["capture_monitor"]))

        self.auto_bait = ObservableBool(_as_bool(data.get("auto_bait"), DEFAULTS["auto_bait"]))

        self.hotkey_start = ObservableStr(_as_str(data.get("hotkey_start"), DEFAULTS["hotkey_start"]))
        self.hotkey_stop = ObservableStr(_as_str(data.get("hotkey_stop"), DEFAULTS["hotkey_stop"]))
        self.hotkey_auto_switch = ObservableStr(_as_str(data.get("hotkey_auto_switch"), DEFAULTS["hotkey_auto_switch"]))
        self.hotkey_detect_baits = ObservableStr(_as_str(data.get("hotkey_detect_baits"), DEFAULTS["hotkey_detect_baits"]))
        self.hotkey_settings = ObservableStr(_as_str(data.get("hotkey_settings"), DEFAULTS["hotkey_settings"]))
        self.hotkey_debug = ObservableStr(_as_str(data.get("hotkey_debug"), DEFAULTS["hotkey_debug"]))
        self.hotkey_game_only = ObservableBool(_as_bool(data.get("hotkey_game_only"), DEFAULTS["hotkey_game_only"]))
        self.allow_controller_fallback = ObservableBool(_as_bool(data.get("allow_controller_fallback"), DEFAULTS["allow_controller_fallback"]))

        self._save_timer: QTimer | None = None
        self._save_lock = threading.Lock()

        for observable in self._observables():
            observable.changed.connect(self._schedule_save)

    def _observables(self):
        return [
            self.game_exe_path, self.minimize_to_tray, self.start_minimized,
            self.debug_console, self.ignore_abort, self.sound_effects,
            self.alert_sound, self.bait_priority, self.capture_mode,
            self.capture_monitor, self.auto_bait,
            self.hotkey_start, self.hotkey_stop,
            self.hotkey_auto_switch, self.hotkey_detect_baits,
            self.hotkey_settings, self.hotkey_debug, self.hotkey_game_only,
            self.allow_controller_fallback,
        ]

    @staticmethod
    def _normalize_priority(raw: Any) -> list[int]:
        if not isinstance(raw, list):
            return list(range(len(get_baits())))
        seen: set[int] = set()
        out: list[int] = []
        for value in raw:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(get_baits()) and idx not in seen:
                seen.add(idx)
                out.append(idx)
        for idx in range(len(get_baits())):
            if idx not in seen:
                out.append(idx)
        return out

    def get_bait_priority(self) -> list[int]:
        return self.bait_priority.get()

    def set_bait_priority(self, order: list[int]) -> None:
        self.bait_priority.set(self._normalize_priority(order))

    @staticmethod
    def _load() -> dict[str, Any]:
        path = _settings_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            logger.debug(f"Could not load settings from {path}: {exc}")
            return dict(DEFAULTS)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        merged = dict(DEFAULTS)
        for key in DEFAULTS:
            if key in data:
                merged[key] = data[key]
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_exe_path": self.game_exe_path.get(),
            "minimize_to_tray": self.minimize_to_tray.get(),
            "start_minimized": self.start_minimized.get(),
            "debug_console": self.debug_console.get(),
            "ignore_abort": self.ignore_abort.get(),
            "sound_effects": self.sound_effects.get(),
            "alert_sound": self.alert_sound.get(),
            "bait_priority": self.bait_priority.get(),
            "capture_mode": self.capture_mode.get(),
            "capture_monitor": self.capture_monitor.get(),
            "auto_bait": self.auto_bait.get(),
            "hotkey_start": self.hotkey_start.get(),
            "hotkey_stop": self.hotkey_stop.get(),
            "hotkey_auto_switch": self.hotkey_auto_switch.get(),
            "hotkey_detect_baits": self.hotkey_detect_baits.get(),
            "hotkey_settings": self.hotkey_settings.get(),
            "hotkey_debug": self.hotkey_debug.get(),
            "hotkey_game_only": self.hotkey_game_only.get(),
            "allow_controller_fallback": self.allow_controller_fallback.get(),
        }

    def save(self) -> bool:
        with self._save_lock:
            data = self.to_dict()
            path = _settings_path()
            directory = os.path.dirname(path) or "."
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError:
                return False
            try:
                fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2, ensure_ascii=False)
                    os.replace(tmp, path)
                except Exception:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise
            except OSError:
                return False
            return True

    def _schedule_save(self) -> None:
        app = QApplication.instance()
        if app is None:
            self.save()
            return
        if QThread.currentThread() != app.thread():
            # Force on main thread
            QTimer.singleShot(0, self._do_save)
            return
        if self._save_timer is None:
            timer = QTimer(app)
            timer.setSingleShot(True)
            timer.setInterval(self.SAVE_DEBOUNCE_MS)
            timer.timeout.connect(self.save)
            self._save_timer = timer
        self._save_timer.start()

    def _do_save(self) -> None:
        self.save()

    def flush(self) -> None:
        if self._save_timer is not None and self._save_timer.isActive():
            self._save_timer.stop()
        self.save()

_settings_instance: Settings | None = None
_settings_lock = threading.Lock()

def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        with _settings_lock:
            if _settings_instance is None:
                _settings_instance = Settings()
    return _settings_instance