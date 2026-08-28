from __future__ import annotations

import logging
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Signal

from config import (
    BAIT_INPUT_WAIT,
    BAIT_MENU_OPEN_SETTLE,
    BAIT_SWITCH_WAIT,
    FOCUS_SETTLE,
    GAME_DISPLAY_NAME,
    INPUT_WAIT,
    get_target_exe,
)
from capture import ICapture, MonitorCapture, WindowCapture
from controller import ControllerBase
from bait_manager import BaitManager
from engine import FishingEngine
from screen_detection import (
    FishingModeState,
    check_bait_availability,
    check_fishing_mode,
    detect_bait_menu_open,
)
from settings import Settings
from win32_utils import find_hwnd_by_exe, focus_hwnd, is_target_window_focused

logger = logging.getLogger(__name__)


class BotController(QObject):
    """Owns engine lifecycle, capture chain, input backend, bait manager."""

    stateChanged = Signal(str)
    logLine = Signal(str, int)                 # (message, log_level)
    notificationRaised = Signal(str, str)      # (title, body)
    fishCountChanged = Signal(int)

    def __init__(
        self,
        settings: Settings,
        controller: ControllerBase | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self.bait_manager = BaitManager(parent=self)
        self.bait_manager.auto_switch_enabled = settings.auto_bait.get()
        self.bait_manager.ignore_abort = settings.ignore_abort.get()

        self.capture = self._build_capture()
        self.engine: FishingEngine | None = None

        # Connect settings changes to bait_manager
        settings.auto_bait.changed.connect(self._on_auto_bait_changed)
        settings.ignore_abort.changed.connect(self._on_ignore_abort_changed)

    @property
    def is_running(self) -> bool:
        """True while the engine thread lives — includes 'paused'."""
        return self.engine is not None and self.engine.is_alive

    def _build_capture(self) -> ICapture:
        mode = self.settings.capture_mode.get()
        if mode == "window":
            return WindowCapture()
        if mode == "monitor":
            return MonitorCapture(self.settings.capture_monitor.get())
        # auto
        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd:
            return WindowCapture(hwnd)
        return MonitorCapture(self.settings.capture_monitor.get())

    def _on_auto_bait_changed(self, value: bool) -> None:
        self.bait_manager.auto_switch_enabled = value

    def _on_ignore_abort_changed(self, value: bool) -> None:
        self.bait_manager.ignore_abort = value

    def start(self) -> None:
        """Preflight, then start. On refusal: stay 'idle' and say why."""
        if self.is_running:
            return

        if self.controller is None:
            self.notificationRaised.emit(
                "No controller", "Input backend failed to initialize."
            )
            self.logLine.emit("start aborted: no input backend", logging.ERROR)
            return

        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd is None:
            self.logLine.emit(
                "start aborted: game window not found", logging.WARNING
            )
            self.notificationRaised.emit(
                "Game not running",
                f"Launch {GAME_DISPLAY_NAME} and go to a fishing spot.",
            )
            self.stateChanged.emit("idle")
            return

        focus_hwnd(hwnd)

        if self.engine is None:
            self.engine = FishingEngine(
                capture=self.capture,
                controller=self.controller,
                bait_manager=self.bait_manager,
                on_event=self._on_engine_event,
                on_status=self.stateChanged.emit,
                on_log=self.logLine.emit,
                on_fish_count=self.fishCountChanged.emit,
            )
        self.engine.start()

    def stop(self) -> None:
        """Idempotent; safe even if the engine never started."""
        if self.engine is not None:
            self.engine.request_stop_and_join()
        self.stateChanged.emit("idle")

    def shutdown(self, timeout: float = 3.0) -> None:
        self.stop()
        if self.engine is not None:
            self.engine.request_stop_and_join(timeout)
        if self.controller is not None:
            self.controller.release_all()

    def focus_game_window(self) -> bool:
        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd:
            return focus_hwnd(hwnd)
        return False

    def auto_detect_baits(self) -> bool:
        if self.controller is None:
            self.logLine.emit("no input backend — cannot detect baits", logging.ERROR)
            return False

        if not self.focus_game_window():
            self.logLine.emit(
                "could not focus game window — aborting bait detection", logging.WARNING
            )
            return False

        time.sleep(FOCUS_SETTLE)

        frame, _ = self.capture.grab_with_id()
        if frame is None:
            self.logLine.emit("capture failed during bait detection", logging.ERROR)
            return False

        state = check_fishing_mode(frame)
        if state not in (FishingModeState.MENU, FishingModeState.MINIGAME):
            self.logLine.emit("enter fishing mode before detecting baits", logging.WARNING)
            return False

        self.controller.tap("TRIANGLE")
        time.sleep(INPUT_WAIT + BAIT_MENU_OPEN_SETTLE)

        for _ in range(5):
            self.controller.tap("DPAD_LEFT")
            time.sleep(BAIT_INPUT_WAIT)

        time.sleep(BAIT_SWITCH_WAIT)

        from config import load_baits

        bait_list = load_baits()
        for idx, _bait in enumerate(bait_list):
            if not is_target_window_focused():
                if not self.focus_game_window():
                    self.logLine.emit("game window lost focus — aborting", logging.WARNING)
                    return False
                time.sleep(0.5)

            frame, _ = self.capture.grab_with_id()
            if frame is None:
                self.logLine.emit("capture failed during detection", logging.ERROR)
                return False

            if not detect_bait_menu_open(frame):
                self.logLine.emit("bait menu closed unexpectedly", logging.WARNING)
                return False

            avail = check_bait_availability(frame)
            if avail:
                self.logLine.emit(f"bait #{idx + 1} available", logging.INFO)
            else:
                self.logLine.emit(f"bait #{idx + 1} unavailable", logging.DEBUG)

            if idx < len(bait_list) - 1:
                self.controller.tap("DPAD_RIGHT")
                time.sleep(BAIT_INPUT_WAIT + BAIT_SWITCH_WAIT)

        self.controller.tap("CIRCLE")
        time.sleep(INPUT_WAIT)
        self.logLine.emit("bait detection complete", logging.INFO)
        return True

    def equip_next_bait(self) -> bool:
        if self.controller is None:
            self.logLine.emit("no input backend — cannot switch bait", logging.ERROR)
            return False

        if not self.bait_manager.auto_switch_enabled:
            return False

        current = self.bait_manager.current_index
        next_idx = self.bait_manager.get_next_available(current)
        if next_idx is None:
            self.logLine.emit("no next bait available", logging.WARNING)
            return False

        self.controller.tap("TRIANGLE")
        time.sleep(BAIT_MENU_OPEN_SETTLE)
        self.controller.tap("DPAD_LEFT")
        time.sleep(BAIT_INPUT_WAIT)
        for _ in range(next_idx):
            self.controller.tap("DPAD_RIGHT")
            time.sleep(BAIT_INPUT_WAIT)
        self.controller.tap("CIRCLE")
        time.sleep(INPUT_WAIT)
        self.bait_manager.select(next_idx)
        self.logLine.emit(f"equipped bait #{next_idx + 1}", logging.INFO)
        return True

    def _on_engine_event(self, kind: str, data: Any) -> None:
        if kind == "fish_caught":
            self.fishCountChanged.emit(data)
        elif kind == "bait_exhausted":
            self.logLine.emit("baits exhausted — refill required", logging.WARNING)
            self.notificationRaised.emit(
                "Bait exhausted", "Switch to a different bait or refill."
            )
        elif kind == "error":
            self.logLine.emit(f"engine error: {data}", logging.ERROR)
            self.stop()
        elif kind == "window_lost":
            self.logLine.emit("game window lost — bot paused", logging.WARNING)
            self.notificationRaised.emit("Game lost", "Bot paused – reopen the game.")