# scripts/fishing_bot.py
import sys
import threading
import time
import winsound
import logging

from contextlib import contextmanager
from typing import Optional, Any

import mss

from PySide6.QtCore import Signal, QTimer, QEvent, Qt, QPropertyAnimation, QEasingCurve, QEventLoop
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

# Direct import – controller.py is in the same directory
from controller import ControllerInput

from updater import check_for_updates, download_and_apply_update, UpdateResult

from config import (
    APP_VERSION, get_baits, BAR_RETRY_MAX, BAR_WAIT,
    BAIT_MENU_OPEN_SETTLE, BAIT_SWITCH_WAIT, BAIT_INPUT_WAIT,
    CAST_POLL, CAST_POLL_MAX, FOCUS_SETTLE,
    HOOK_GRACE_SECS, INPUT_WAIT, KEY_CANCEL, KEY_CAST, KEY_DPAD_L,
    KEY_DPAD_R, KEY_LEFT, KEY_MENU, KEY_RIGHT,
    POST_CAST_SETTLE, POST_MINIGAME_WAIT, RECOVER_WAIT,
    RESULT_DISMISS_WAIT, RESULT_POLL, RESULT_POLL_MAX,
    get_target_exe, REEL_SPEED_PX_PER_MS, REEL_CENTER_DEADZONE,
    REEL_COAST_ZONE, REEL_MAX_HOLD_TIME, REEL_MIN_HOLD_TIME,
    REEL_SAFETY_FACTOR, REEL_POLL_DELAY,
)

from capture import WindowCapture, MonitorCapture, ICapture
from engine import FishingEngine, EngineEvent
from bait_manager import BaitManager

from screen_detection import (
    detect_no_baits, detect_bar, detect_cast_button, detect_bait_menu_open,
    detect_line, detect_result, check_bait_availability,
    check_fishing_mode, FishingModeState,
)

from settings import get_settings
from sfx import play_sfx
from ui import FishingUI
from widgets import AdminWarningDialog, UpdatePromptDialog

from win32_utils import (
    find_hwnd_by_exe, focus_hwnd, is_running_as_admin,
    relaunch_as_admin, is_target_window_focused,
    GlobalHotkeyManager, get_vk_code, set_window_topmost,
)

logger = logging.getLogger(__name__)

TOGGLE_DEBOUNCE_SECS = 0.5

ACCENT = "#FA468E"
TEXT_MUTED = "#64748B"
DANGER = "#EF4444"
DEFAULT = "#E4E4E4"
WARNING = "#FFB610"


# ---------------------------------------------------------------------------
# BotController – handles all bot logic
# ---------------------------------------------------------------------------
class BotController:
    def __init__(self, ui: FishingUI):
        self.ui = ui
        self.settings = get_settings()
        self.controller = ControllerInput()
        self.bait_manager = BaitManager()
        self.bait_manager.set_priority(self.settings.get_bait_priority())
        self.capture = self._create_capture()
        self.engine = FishingEngine(
            capture=self.capture,
            controller=self.controller,
            settings=self.settings,
            bait_manager=self.bait_manager,
            on_event=self._handle_engine_event,
            on_status=self.ui.set_status,
            on_log=self.ui.log,
            on_fish_count=self.ui.set_fish_count,
        )
        self.running = False
        self.stop_event = threading.Event()
        self.start_time = 0.0
        self.session_start = None

    def _create_capture(self) -> ICapture:
        mode = self.settings.capture_mode.get()
        if mode == "window":
            return WindowCapture()
        elif mode == "monitor":
            return MonitorCapture(self.settings.capture_monitor.get())
        else:  # auto
            hwnd = find_hwnd_by_exe(get_target_exe())
            if hwnd:
                return WindowCapture(hwnd)
            return MonitorCapture(self.settings.capture_monitor.get())

    def _handle_engine_event(self, event: EngineEvent) -> None:
        if event.kind == "fish_caught":
            self.ui.catch_burst.play()
        elif event.kind == "bait_exhausted":
            self._play_alert()
            self.ui.BaitExhausted.emit(-1)
        elif event.kind == "bait_switched":
            self.ui.BaitEquipped.emit(event.data)
        elif event.kind == "error":
            self.ui.log(f"Engine error: {event.data}", DANGER)
            self.stop(manual=False)
        elif event.kind == "missed_fish":
            self.ui.log("Fish missed", WARNING)

    def _play_alert(self) -> None:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self.start_time = time.monotonic()
        self.session_start = self.start_time
        self.ui.set_mode_colors(True)
        self.ui.set_status("Focusing...")
        if not self.focus_game_window():
            self.ui.set_status("Idle")
            self.ui.log("Could not focus game window.", DANGER)
            self.running = False
            self.ui.set_mode_colors(False)
            return
        self.ui.timer_var.set("00:00:00")
        self.ui.set_status("Starting...")
        self.ui.log("[Session started]", TEXT_MUTED)
        play_sfx("start")
        self.engine.start()
        QTimer.singleShot(100, self.focus_game_window)

    def stop(self, manual: bool = False) -> None:
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        self.engine.stop()
        self.ui.set_status("Idle")
        self.ui.set_mode_colors(False)
        self.ui.log("[Session stopped]", TEXT_MUTED)
        if manual:
            play_sfx("stop")

    def toggle(self) -> None:
        now = time.monotonic()
        if now - getattr(self, '_last_toggle', 0) < TOGGLE_DEBOUNCE_SECS:
            return
        setattr(self, '_last_toggle', now)
        if self.running:
            self.stop(manual=True)
        else:
            self.start()

    def focus_game_window(self) -> bool:
        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd:
            return focus_hwnd(hwnd)
        return False

    def auto_detect_baits(self) -> bool:
        self.stop_event.clear()
        self.ui.set_status("Detecting Baits")
        self.ui.log("Auto-detecting available baits...", ACCENT)
        self.ui.log("Opening bait menu...", DEFAULT)

        if not self.focus_game_window():
            self.ui.log("Could not focus game window. Aborting bait detection.", DANGER)
            self.ui.set_status("Idle")
            return False

        if not self.sleep(FOCUS_SETTLE):
            return False

        sct = self.capture

        if not self._check_and_enter_fishing_mode(sct):
            self.ui.set_status("Idle")
            return False

        self.controller.tap(KEY_MENU)
        if not self.sleep(INPUT_WAIT):
            return False
        if not self.sleep(BAIT_MENU_OPEN_SETTLE):
            return False

        for _ in range(5):
            self.controller.tap(KEY_DPAD_L)
            if not self.sleep(BAIT_INPUT_WAIT):
                return False

        if not self.sleep(BAIT_SWITCH_WAIT):
            return False

        found_any = False
        for idx, bait in enumerate(get_baits()):
            if self.stop_event.is_set():
                return False

            if not self.ui.abort_behavior_var.get():
                if not is_target_window_focused():
                    self.ui.log("Game window lost focus. Re-focusing...", WARNING)
                    if not self.focus_game_window():
                        self.ui.log("Aborting bait detection.", DANGER)
                        self.ui.set_status("Idle")
                        return False
                    if not self.sleep(0.5):
                        return False

            frame = sct.capture_frame()
            if frame is None:
                self.ui.log("Capture failed during bait detection.", DANGER)
                self.ui.set_status("Idle")
                return False

            if not detect_bait_menu_open(frame):
                self.ui.log("Bait menu closed. Aborting bait detection.", DANGER)
                self.ui.set_status("Idle")
                return False

            is_avail = check_bait_availability(frame)
            if is_avail:
                self.ui.bait_vars[idx].set(True)
                self.ui.log(f" -> {idx + 1}. {bait['name']}: Available", TEXT_MUTED)
                found_any = True
            else:
                if self.ui.bait_vars[idx].get():
                    self.ui.log(f" -> {idx + 1}. {bait['name']}: Unavailable (deselected)", TEXT_MUTED)
                else:
                    self.ui.log(f" -> {idx + 1}. {bait['name']}: Unavailable", TEXT_MUTED)
                self.ui.bait_vars[idx].set(False)

            if idx < len(get_baits()) - 1:
                self.controller.tap(KEY_DPAD_R)
                if not self.sleep(BAIT_INPUT_WAIT):
                    return False
                if not self.sleep(BAIT_SWITCH_WAIT):
                    return False

        frame = sct.capture_frame()
        if frame is not None and not detect_bait_menu_open(frame):
            self.ui.log("Bait menu not detected or already closed — not pressing Circle.", WARNING)
            self.ui.set_status("Idle")
            return False

        self.controller.tap(KEY_CANCEL)
        play_sfx("detect")

        if not self.sleep(INPUT_WAIT):
            return False

        self.ui.set_status("Idle")
        if found_any:
            self.ui.log("Auto-detection complete. Baits updated.", ACCENT)
        else:
            self.ui.log("No available baits found.", WARNING)

        self.ui.BaitListUpdated.emit()
        return True

    def _check_and_enter_fishing_mode(self, sct: ICapture) -> bool:
        frame = sct.capture_frame()
        if frame is None:
            return False
        state = check_fishing_mode(frame)
        if state in (FishingModeState.MENU, FishingModeState.MINIGAME):
            # Only attempt gamepad wake-up if gamepad is available
            if self.controller.gamepad is not None:
                try:
                    self.controller.gamepad.left_joystick_float(x_value_float=1.0, y_value_float=0.0)
                    self.controller.gamepad.update()
                    time.sleep(0.1)
                    self.controller.gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
                    self.controller.gamepad.update()
                    time.sleep(0.1)
                except Exception:
                    pass
        if state == FishingModeState.MINIGAME:
            return True
        if state == FishingModeState.MENU:
            self.controller.tap(KEY_MENU)
            if not self.sleep(0.5):
                return False
            self.controller.tap(KEY_CAST)
            if not self.sleep(2.0):
                return False
            frame = sct.capture_frame()
            if frame is not None and check_fishing_mode(frame) == FishingModeState.MINIGAME:
                return True
        self.ui.log("Equip bait before fishing.", DANGER)
        return False

    def equip_next_bait(self) -> bool:
        if not self.settings.auto_bait.get():
            return False

        current_idx = self.ui.current_bait_idx.get()
        if current_idx < 0:
            current_idx = -1

        priority = self.settings.get_bait_priority()
        available = [
            i for i in priority
            if 0 <= i < len(self.ui.bait_vars)
            and self.ui.bait_vars[i].get()
            and i != current_idx
        ]

        if not available:
            self.ui.log("No baits left to switch to.", DANGER)
            self._play_alert()
            self.ui.BaitExhausted.emit(current_idx)
            return False

        next_idx = available[0]
        target_name = get_baits()[next_idx]["name"]

        self.ui.set_status("Switching Bait")
        self.ui.log(f"Equipping bait #{next_idx + 1}: {target_name}", ACCENT)

        if not self.focus_game_window():
            self.ui.set_status("Idle")
            return False

        if not self.sleep(FOCUS_SETTLE):
            return False

        self.controller.tap(KEY_MENU)
        if not self.sleep(INPUT_WAIT):
            return False
        if not self.sleep(BAIT_MENU_OPEN_SETTLE):
            return False

        self.controller.tap(KEY_DPAD_L)
        if not self.sleep(INPUT_WAIT):
            return False

        for _ in range(next_idx):
            if self.stop_event.is_set():
                return False
            self.controller.tap(KEY_DPAD_R)
            if not self.sleep(INPUT_WAIT):
                return False

        self.controller.tap(KEY_CANCEL)

        if not self.sleep(INPUT_WAIT + POST_CAST_SETTLE):
            return False

        self.ui.BaitEquipped.emit(next_idx)
        return True

    def sleep(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_event.is_set():
                return False
            time.sleep(0.01)
        return True

    def release_all(self) -> None:
        self.controller.release_all()


# ---------------------------------------------------------------------------
# FishingUI – presentation only, delegates to BotController
# ---------------------------------------------------------------------------
class FishingBot(FishingUI):
    LogRequest = Signal(str, str, bool, bool)
    StopRequested = Signal()
    BaitExhausted = Signal(int)
    BaitEquipped = Signal(int)
    StatusChanged = Signal(str)
    FishCountChanged = Signal(int)
    TimerChanged = Signal(str)
    ControllerChanged = Signal(str)
    BaitListUpdated = Signal()
    OpacityChangeRequested = Signal(float, int, object)

    def __init__(self) -> None:
        self._last_toggle = 0.0
        self.start_time = 0.0
        self.fish_count = 0
        self.session_start = None

        self.build_ui()

        self._active_anims = []
        self.OpacityChangeRequested.connect(self._on_opacity_change_requested)

        self.fish_count_var.set(0)
        self.set_controller_status("")

        self.program_hwnd = self._get_program_hwnd()

        self._settings_open = False

        self._hotkey_manager = GlobalHotkeyManager(int(self.winId()))

        self._local_shortcuts = []

        self._is_topmost = None

        self._start_update_check()

        self.LogRequest.connect(self._handle_log_request)
        self.StopRequested.connect(self._handle_stop_request)
        self.BaitExhausted.connect(self._handle_bait_exhausted)
        self.BaitEquipped.connect(self._handle_bait_equipped)
        self.StatusChanged.connect(self._handle_status_changed)
        self.FishCountChanged.connect(self._handle_fish_count_changed)
        self.TimerChanged.connect(self._handle_timer_changed)
        self.ControllerChanged.connect(self._handle_controller_changed)
        self.BaitListUpdated.connect(self._update_bait_select_text)
        self.UpdateCheckReady.connect(self._handle_update_result)

        self._setup_tray()

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_timer)
        self._clock.start()

        self._check_admin_status()

        # ---- Create controller BEFORE applying hotkeys ----
        self.controller = BotController(self)

        self._apply_hotkeys()

    # ------------------------------------------------------------------
    # UI helper methods
    # ------------------------------------------------------------------

    def _on_opacity_change_requested(self, end_opacity: float, duration: int, event: Optional[threading.Event]) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(end_opacity)
        self._active_anims.append(anim)
        if event is not None:
            def on_finished():
                event.set()
                try:
                    self._active_anims.remove(anim)
                except ValueError:
                    pass
            anim.finished.connect(on_finished)
        else:
            anim.finished.connect(lambda: self._active_anims.remove(anim))
        anim.start()

    def _animate_and_wait(self, start_opacity: float, end_opacity: float, duration: int) -> None:
        if threading.current_thread() is threading.main_thread():
            loop = QEventLoop()
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(duration)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(start_opacity)
            anim.setEndValue(end_opacity)
            self._active_anims.append(anim)
            anim.finished.connect(loop.quit)
            anim.finished.connect(lambda: self._active_anims.remove(anim))
            anim.start()
            loop.exec_()
        else:
            event = threading.Event()
            self.OpacityChangeRequested.emit(end_opacity, duration, event)
            event.wait(duration / 1000.0 + 0.5)

    def _start_update_check(self) -> None:
        def _check_and_emit():
            result = check_for_updates()
            if result:
                self.UpdateCheckReady.emit(result)
        threading.Thread(target=_check_and_emit, daemon=True).start()

    def _handle_update_result(self, result: UpdateResult) -> None:
        if not result.has_update:
            if result.error:
                self.log(f"Update check failed: {result.error}", WARNING)
            else:
                self.log(f"App is up to date (v{APP_VERSION})", ACCENT)
            return
        self.log(f"Updates available: {result.latest_version}", ACCENT)
        dialog = UpdatePromptDialog(result.release_notes, self.C, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.log("Applying updates...", ACCENT)
            def download_thread():
                success = download_and_apply_update(result.download_url, self.log)
                if success:
                    self.log("Restarting to apply update...", ACCENT)
                    QApplication.quit()
                else:
                    self.log("Update failed.", WARNING)
            threading.Thread(target=download_thread, daemon=True).start()
        else:
            self.log("Update skipped by user", TEXT_MUTED)

    def _apply_hotkeys(self) -> None:
        self._hotkey_manager.unregister_all()
        for shortcut in self._local_shortcuts:
            shortcut.deleteLater()
        self._local_shortcuts = []

        is_admin = is_running_as_admin()

        def register(key_str, callback, bypass_settings=False):
            if is_admin:
                vk = get_vk_code(key_str)
                if vk:
                    def wrapped() -> None:
                        if not bypass_settings and self._settings_open:
                            return
                        if self.settings.hotkey_game_only.get():
                            app = QApplication.instance()
                            qt_focused = (isinstance(app, QApplication) and app.activeWindow() is not None)
                            if not (is_target_window_focused() or qt_focused):
                                return
                        QTimer.singleShot(0, callback)
                    self._hotkey_manager.register(vk, wrapped)
            else:
                if not key_str:
                    return
                seq = QKeySequence(key_str)
                if seq.isEmpty():
                    return
                def wrapped():
                    if not bypass_settings and self._settings_open:
                        return
                    QTimer.singleShot(0, callback)
                shortcut = QShortcut(seq, self)
                shortcut.activated.connect(wrapped)
                self._local_shortcuts.append(shortcut)

        register(self.settings.hotkey_start.get(), self.controller.start)
        register(self.settings.hotkey_stop.get(), lambda: self.controller.stop(manual=True))
        register(self.settings.hotkey_auto_switch.get(), lambda: self.settings.auto_bait.set(not self.settings.auto_bait.get()))
        def detect_baits_cb() -> None:
            if not self.settings.auto_bait.get():
                return
            self._on_auto_detect_baits()
        register(self.settings.hotkey_detect_baits.get(), detect_baits_cb)
        register(self.settings.hotkey_settings.get(), self._open_settings, bypass_settings=True)
        register(self.settings.hotkey_debug.get(), lambda: self.debug_console_active.set(not self.debug_console_active.get()))

    # ------------------------------------------------------------------
    # Delegate bot actions
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.controller.start()

    def stop(self, manual: bool = False) -> None:
        self.controller.stop(manual=manual)

    def toggle(self) -> None:
        self.controller.toggle()

    def focus_game_window(self) -> bool:
        return self.controller.focus_game_window()

    def equip_next_bait(self) -> bool:
        return self.controller.equip_next_bait()

    def auto_detect_baits(self) -> bool:
        return self.controller.auto_detect_baits()

    def _on_auto_detect_baits(self) -> None:
        if self.running:
            self.log("Stop the bot before detecting baits.")
            return
        self.log("Auto-detecting available baits...")
        def run_detect():
            if self.focus_game_window():
                self.controller.auto_detect_baits()
        threading.Thread(target=run_detect, daemon=True).start()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------
    def _handle_log_request(self, msg: str, color: str, clear: bool, replace_last: bool) -> None:
        if clear:
            self.log_box.clear_log()
        if msg:
            ts = time.strftime("%H:%M:%S")
            text = f"[{ts}] {msg}\n"
            if replace_last:
                self.log_box.replace_last_line(text, color)
            else:
                self.log_box.append(text, color)

    def _handle_stop_request(self) -> None:
        self.stop()

    def _handle_bait_exhausted(self, current_idx: int) -> None:
        if 0 <= current_idx < len(self.bait_vars):
            self.bait_vars[current_idx].set(False)
        self.stop()

    def _handle_bait_equipped(self, next_idx: int) -> None:
        for var in self.bait_vars:
            var.set(False)
        if 0 <= next_idx < len(self.bait_vars):
            self.bait_vars[next_idx].set(True)
        self.current_bait_idx.set(next_idx)

    def _handle_status_changed(self, text: str) -> None:
        self.status_var.set(text)

    def _handle_fish_count_changed(self, count: int) -> None:
        self.fish_count = count
        self.fish_count_var.set(count)

    def _handle_timer_changed(self, text: str) -> None:
        self.timer_var.set(text)

    def _handle_controller_changed(self, text: str) -> None:
        self.controller_status_var.set(text)

    def _get_program_hwnd(self) -> Optional[int]:
        try:
            return int(self.winId())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Tray and UI helpers
    # ------------------------------------------------------------------
    def _setup_tray(self) -> None:
        from tray import TrayManager
        QApplication.setQuitOnLastWindowClosed(False)
        self._tray_manager = TrayManager(self)
        self._update_tray_state()
        self.StatusChanged.connect(lambda *_: self._update_tray_state())
        self.FishCountChanged.connect(lambda *_: self._update_tray_state())

    def _update_tray_state(self, *_args) -> None:
        if self._tray_manager:
            self._tray_manager.update_state(
                self.running, self.status_var.get(), self.fish_count_var.get()
            )

    def _check_admin_status(self) -> None:
        if not is_running_as_admin():
            msg = "Not running as Administrator:\nSome functions are not expected to work correctly."
            self.log(msg, WARNING)
            dlg = AdminWarningDialog(self.C, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if relaunch_as_admin():
                    sys.exit(0)
                self.log("Failed to relaunch as Administrator.", DANGER)

    def _tick_timer(self) -> None:
        if self.running and self.session_start is not None:
            elapsed = int(time.monotonic() - self.session_start)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            self.timer_var.set(f"{hrs:02}:{mins:02}:{secs:02}")
        self._update_topmost_state()

    def _update_topmost_state(self) -> None:
        if not self.isVisible():
            return
        if QApplication.activeModalWidget():
            return
        try:
            game_focused = is_target_window_focused()
            bot_focused = self.isActiveWindow()
            desired = game_focused or bot_focused
            if desired != self._is_topmost:
                set_window_topmost(int(self.winId()), desired)
                self._is_topmost = desired
        except Exception:
            logger.debug("Failed to update topmost state", exc_info=True)

    # ------------------------------------------------------------------
    # Close / quit
    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.controller.stop()
        finally:
            try:
                self.controller.release_all()
            except Exception:
                pass
            if self._hotkey_manager:
                self._hotkey_manager.unregister_all()
            self.root.destroy()
            if self._tray_manager is not None:
                self._tray_manager.tray.hide()
            QApplication.quit()

    def quit_application(self) -> None:
        self._force_quit = True
        try:
            self.settings.flush()
        except Exception:
            pass
        try:
            self.controller.stop()
        except Exception:
            logger.debug("Failed to stop on quit", exc_info=True)
        if self._hotkey_manager:
            self._hotkey_manager.unregister_all()
        if self._tray_manager is not None:
            self._tray_manager.tray.hide()
        self.app.quit()