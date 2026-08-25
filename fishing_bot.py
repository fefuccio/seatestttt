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

from screen_detection import (
    detect_no_baits, detect_bar, detect_cast_button, detect_bait_menu_open,
    detect_line, detect_result, check_bait_availability,
    WindowCapture, MonitorCapture, check_fishing_mode, FishingModeState,
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

# Color constants for log messages
ACCENT = "#FA468E"
TEXT_MUTED = "#64748B"
DANGER = "#EF4444"
DEFAULT = "#E4E4E4"
WARNING = "#FFB610"


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
    UpdateCheckReady = Signal(object)
    
    # Signal to request opacity change on the main thread
    OpacityChangeRequested = Signal(float, int, object)

    def __init__(self) -> None:
        self.running = False
        self.stop_event = threading.Event()

        self.last_toggle = 0.0
        self.start_time = 0.0
        self.fish_count = 0
        self.session_start = None

        self.controller = ControllerInput()

        self.build_ui()

        # Initialize animation handler
        self._active_anims = []
        self.OpacityChangeRequested.connect(self._on_opacity_change_requested)

        self.fish_count_var.set(0)
        self.set_controller_status(self.controller.status)

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
        self._apply_hotkeys()

    def _on_opacity_change_requested(self, end_opacity: float, duration: int, event: Optional[threading.Event]) -> None:
        """Main thread handler for safe opacity animations."""
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(end_opacity)
        
        # Keep a reference to prevent garbage collection
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
            # Clean up if no event is passed
            anim.finished.connect(lambda: self._active_anims.remove(anim))
            
        anim.start()

    def _animate_and_wait(self, start_opacity: float, end_opacity: float, duration: int) -> None:
        """Thread-safe animation that waits for completion without freezing the UI."""
        if threading.current_thread() is threading.main_thread():
            # On main thread, use a local event loop to pump events
            loop = QEventLoop()
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(duration)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(start_opacity)
            anim.setEndValue(end_opacity)
            
            # Keep a reference
            self._active_anims.append(anim)
            
            anim.finished.connect(loop.quit)
            anim.finished.connect(lambda: self._active_anims.remove(anim))
            
            anim.start()
            loop.exec_()
        else:
            # On background thread, signal main thread to animate and wait
            event = threading.Event()
            self.OpacityChangeRequested.emit(end_opacity, duration, event)
            # Wait for the event with a safety timeout
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

                            qt_focused = (
                                isinstance(app, QApplication)
                                and app.activeWindow() is not None
                            )

                            if not (is_target_window_focused() or qt_focused):
                                return

                        callback()

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
                    callback()

                shortcut = QShortcut(seq, self)
                shortcut.activated.connect(wrapped)
                self._local_shortcuts.append(shortcut)

        register(self.settings.hotkey_start.get(), self.start)
        register(
            self.settings.hotkey_stop.get(),
            lambda: self.stop(manual=True)
        )
        register(
            self.settings.hotkey_auto_switch.get(),
            lambda: self.auto_bait_var.set(not self.auto_bait_var.get()),
        )

        def detect_baits_cb() -> None:
            if not self.auto_bait_var.get():
                return
            self._on_auto_detect_baits()

        register(self.settings.hotkey_detect_baits.get(), detect_baits_cb)
        register(self.settings.hotkey_settings.get(), self._open_settings, bypass_settings=True)
        register(
            self.settings.hotkey_debug.get(),
            lambda: self.debug_console_active.set(not self.debug_console_active.get()),
        )

    @contextmanager
    def make_capture_context(self):
        mode = self.settings.capture_mode.get()

        if mode in ("auto", "window"):
            hwnd = find_hwnd_by_exe(get_target_exe())

            if hwnd:
                cap = WindowCapture(hwnd)
                test_frame = cap.get_full_frame()

                if test_frame is not None and test_frame.size > 0:
                    self.log(f"Capture mode: Window (HWND {hwnd})", TEXT_MUTED)
                    yield cap
                    return

                if mode == "window":
                    yield None
                    return

        monitor_index = self.settings.capture_monitor.get()

        if mode == "auto":
            self.log("Capture mode: Auto (Falling back to Monitor)", TEXT_MUTED)
        else:
            self.log(f"Capture mode: Monitor {monitor_index}", TEXT_MUTED)

        with mss.mss() as sct:
            yield MonitorCapture(sct, monitor_index)

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
                self.running, self.status_var.get(), self.fish_count_var.get(),
            )

    def _check_admin_status(self) -> None:
        if not is_running_as_admin():
            msg = (
                "Not running as Administrator:\n"
                "Some functions are not expected to work correctly."
            )
            self.log(msg, WARNING)

            dlg = AdminWarningDialog(self.C, self)

            if dlg.exec() == QDialog.DialogCode.Accepted:
                if relaunch_as_admin():
                    sys.exit(0)

                self.log("Failed to relaunch as Administrator.", DANGER)

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
            return int(self.root.winfo_id())
        except Exception:
            return None

    def log(self, msg: str, color: str = DEFAULT, clear: bool = False, replace_last: bool = False) -> None:
        self.LogRequest.emit(msg, color, clear, replace_last)

        if color == DANGER:
            play_sfx("stop")

    def set_status(self, text: str) -> None:
        self.StatusChanged.emit(text)

    def set_controller_status(self, text: str) -> None:
        self.ControllerChanged.emit(text)

    def update_fish(self) -> None:
        self.FishCountChanged.emit(self.fish_count)

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

    def play_alert(self) -> None:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

    def _refocus_game(self) -> None:
        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd:
            focus_hwnd(hwnd)

    def _perform_gamepad_wake_up(self) -> None:
        """Performs the left stick check only when in a fishing menu or minigame."""
        if self.controller.use_gamepad and self.controller.gamepad is not None:
            try:
                self.controller.gamepad.left_joystick_float(x_value_float=1.0, y_value_float=0.0)
                self.controller.gamepad.update()
                time.sleep(0.1)

                self.controller.gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
                self.controller.gamepad.update()
                time.sleep(0.1)
            except Exception:
                pass

    def focus_game_window(self) -> bool:
        # Fade out before focusing game
        self._animate_and_wait(self.windowOpacity(), 0.0, 150)

        found = False
        for _ in range(30):
            hwnd = find_hwnd_by_exe(get_target_exe())

            if hwnd and focus_hwnd(hwnd):
                found = True
                break

            time.sleep(0.1)

        # Fade back in after focusing
        self._animate_and_wait(self.windowOpacity(), 1.0, 250)

        # Ensure the game window has focus AFTER the fade-in so controller inputs hit the game
        hwnd = find_hwnd_by_exe(get_target_exe())
        if hwnd:
            focus_hwnd(hwnd)

        if not found:
            self.log("Could not find the game window.", WARNING)
        return found

    def _check_and_enter_fishing_mode(self, sct: Any) -> bool:
        state = check_fishing_mode(sct)

        if state in (FishingModeState.MENU, FishingModeState.MINIGAME):
            self._perform_gamepad_wake_up()

        if state == FishingModeState.MINIGAME:
            return True

        if state == FishingModeState.MENU:
            self.controller.tap(KEY_MENU)

            if not self.sleep(0.5):
                return False

            self.controller.tap(KEY_CAST)

            if not self.sleep(2.0):
                return False

            if check_fishing_mode(sct) == FishingModeState.MINIGAME:
                self._perform_gamepad_wake_up()
                return True

        self.log("Equip bait before fishing.", DANGER)
        self.set_status("Idle")
        self.StopRequested.emit()
        return False

    # ------------------------------------------------------------------
    # The remainder of the bot loop
    # ------------------------------------------------------------------

    def auto_detect_baits(self) -> bool:
        self.stop_event.clear()
        self.set_status("Detecting Baits")
        self.log("Auto-detecting available baits...", ACCENT)
        self.log("Opening bait menu...", DEFAULT)

        if not self.focus_game_window():
            self.log("Could not focus game window. Aborting bait detection.", DANGER)
            self.set_status("Idle")
            return False

        if not self.sleep(FOCUS_SETTLE):
            return False

        found_any = False

        with self.make_capture_context() as sct:
            if sct is None:
                self.set_status("Idle")
                return False

            if not self._check_and_enter_fishing_mode(sct):
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

            for idx, bait in enumerate(get_baits()):
                if self.stop_event.is_set():
                    return False

                if not self.abort_behavior_var.get():
                    if not is_target_window_focused():
                        self.log("Game window lost focus. Re-focusing...", WARNING)

                        if not self.focus_game_window():
                            self.log("Aborting bait detection.", DANGER)
                            self.set_status("Idle")
                            return False

                        if not self.sleep(0.5):
                            return False

                if not detect_bait_menu_open(sct):
                    self.log("Bait menu closed. Aborting bait detection.", DANGER)
                    self.set_status("Idle")
                    return False

                is_avail = check_bait_availability(sct)

                if is_avail:
                    self.bait_vars[idx].set(True)
                    self.log(f" -> {idx + 1}. {bait['name']}: Available", TEXT_MUTED)
                    found_any = True
                else:
                    if self.bait_vars[idx].get():
                        self.log(f" -> {idx + 1}. {bait['name']}: Unavailable (deselected)", TEXT_MUTED)
                    else:
                        self.log(f" -> {idx + 1}. {bait['name']}: Unavailable", TEXT_MUTED)

                    self.bait_vars[idx].set(False)

                if idx < len(get_baits()) - 1:
                    self.controller.tap(KEY_DPAD_R)
                    if not self.sleep(BAIT_INPUT_WAIT):
                        return False
                    if not self.sleep(BAIT_SWITCH_WAIT):
                        return False

            if not detect_bait_menu_open(sct):
                self.log("Bait menu not detected or already closed — not pressing Circle.", WARNING)
                self.set_status("Idle")
                return False

        self.controller.tap(KEY_CANCEL)
        play_sfx("detect")

        if not self.sleep(INPUT_WAIT):
            return False

        self.set_status("Idle")

        if found_any:
            self.log("Auto-detection complete. Baits updated.", ACCENT)
        else:
            self.log("No available baits found.", WARNING)

        self.BaitListUpdated.emit()
        return True

    def equip_next_bait(self) -> bool:
        if not self.auto_bait_var.get():
            return False

        current_idx = self.current_bait_idx.get()
        if current_idx < 0:
            current_idx = -1

        priority = self.settings.get_bait_priority()

        available = [
            i for i in priority
            if 0 <= i < len(self.bait_vars)
            and self.bait_vars[i].get()
            and i != current_idx
        ]

        if not available:
            self.log("No baits left to switch to.", DANGER)
            self.play_alert()
            self.BaitExhausted.emit(current_idx)
            return False

        next_idx = available[0]
        target_name = get_baits()[next_idx]["name"]

        self.set_status("Switching Bait")
        self.log(f"Equipping bait #{next_idx + 1}: {target_name}", ACCENT)

        if not self.focus_game_window():
            self.set_status("Idle")
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

        self.BaitEquipped.emit(next_idx)

        # Reset so the next loop iteration knows to cast (no line cast yet after a switch).
        self.line_cast = False
        return True

    def toggle(self) -> None:
        now = time.monotonic()

        if now - self.last_toggle < TOGGLE_DEBOUNCE_SECS:
            return

        self.last_toggle = now

        if self.running:
            self.stop(manual=True)
        else:
            self.start()

    def start(self) -> None:
        if self.running:
            return

        self.running = True
        self.set_mode_colors(True)
        self.set_status("Focusing...")

        if not self.focus_game_window():
            self.set_status("Idle")
            self.log("Could not focus game window.", DANGER)
            self.running = False
            self.set_mode_colors(False)
            return

        # Force a topmost refresh on the next tick.
        self._is_topmost = None
        self.stop_event.clear()

        if not self.sleep(FOCUS_SETTLE):
            self.running = False
            self.set_mode_colors(False)
            return

        with self.make_capture_context() as sct:
            if sct is None:
                self.log("Capture failed. Cannot start.", DANGER)
                self.set_status("Idle")
                self.running = False
                self.set_mode_colors(False)
                return

            if not self._check_and_enter_fishing_mode(sct):
                return

        self.start_time = time.monotonic()
        self.session_start = self.start_time
        self.timer_var.set("00:00:00")
        self.update_fish()
        self.set_status("Starting...")
        self.log("[Session started]", TEXT_MUTED)
        play_sfx("start")

        self._worker_thread = threading.Thread(target=self.loop, daemon=True)
        self._worker_thread.start()

        QTimer.singleShot(100, self._refocus_game)

    def stop(self, manual: bool = False) -> None:
        if not self.running:
            return

        self.running = False
        self.stop_event.set()

        try:
            self.controller.release_all()
        except Exception:
            pass

        worker = getattr(self, "_worker_thread", None)

        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=3.0)

        self.set_status("Idle")
        self.set_mode_colors(False)
        self.log("[Session stopped]", TEXT_MUTED)

        if manual:
            play_sfx("stop")

    def close(self) -> None:
        try:
            self.stop()
        finally:
            try:
                self.controller.release_all()
            except Exception:
                pass

            self.root.destroy()

            if self._tray_manager is not None:
                self._tray_manager.tray.hide()

            QApplication.quit()

    def sleep(self, seconds: float) -> bool:
        end = time.monotonic() + seconds

        while time.monotonic() < end:
            if self.stop_event.is_set():
                return False
            time.sleep(0.01)

        return True

    def play_minigame(self, sct: Any) -> bool:
        # FIX: Focus the game immediately before starting the reeling state
        if not self.focus_game_window():
            self.log("Could not focus game window.", DANGER)
            return False

        capture_width = 1920

        if isinstance(sct, WindowCapture):
            frame = sct.get_full_frame()
            if frame is not None:
                capture_width = frame.shape[1]
        elif hasattr(sct, "monitors"):
            capture_width = sct.monitors[1]["width"]

        effective_speed_px_ms = (REEL_SPEED_PX_PER_MS * capture_width) / 1920.0

        current_held_key: Optional[str] = None

        def release_current() -> None:
            nonlocal current_held_key
            if current_held_key is not None:
                try:
                    self.controller.release(current_held_key)
                except Exception:
                    pass
                current_held_key = None

        while not self.stop_event.is_set():
            # Ensure game keeps focus during the minigame
            hwnd = find_hwnd_by_exe(get_target_exe())
            if hwnd and not is_target_window_focused():
                focus_hwnd(hwnd)

            bar_x = detect_bar(sct)
            if bar_x is None:
                release_current()
                return True

            line_x = detect_line(sct)
            if line_x is None:
                release_current()
                time.sleep(REEL_POLL_DELAY)
                continue

            delta = bar_x - line_x
            error = abs(delta)

            if error <= REEL_CENTER_DEADZONE:
                release_current()
                time.sleep(REEL_POLL_DELAY)
                continue

            if error <= REEL_COAST_ZONE:
                release_current()
                time.sleep(REEL_POLL_DELAY * 2)
                continue

            desired_key = KEY_RIGHT if delta > 0 else KEY_LEFT

            if current_held_key is not None and current_held_key != desired_key:
                release_current()
                time.sleep(REEL_POLL_DELAY)
                continue

            time_needed_ms = error / effective_speed_px_ms

            hold_time_sec = max(
                REEL_MIN_HOLD_TIME,
                min(
                    REEL_MAX_HOLD_TIME,
                    (time_needed_ms / 1000.0) * REEL_SAFETY_FACTOR,
                ),
            )

            try:
                if current_held_key is None:
                    self.controller.press(desired_key)
                    current_held_key = desired_key
            except Exception:
                pass

            if not self.sleep(hold_time_sec):
                release_current()
                return False

            release_current()

            if not self.sleep(REEL_POLL_DELAY):
                return False

        release_current()
        return False

    def loop(self) -> None:
        self.line_cast = False
        try:
            with self.make_capture_context() as sct:
                if sct is None:
                    self.StopRequested.emit()
                    return

                while not self.stop_event.is_set():
                    if not self._ensure_bait(sct):
                        return

                    bar_x = detect_bar(sct)
                    line_x = detect_line(sct)

                    if bar_x is not None or line_x is not None:
                        self.line_cast = False
                        self.set_status("Reeling")
                        if not self.play_minigame(sct):
                            return
                    else:
                        if not self._do_cast_and_hook(sct):
                            return

                    if not self._do_result(sct):
                        return
        finally:
            try:
                self.controller.release_all()
            except Exception:
                logger.debug("Failed to release controller", exc_info=True)

    def _ensure_bait(self, sct: Any) -> bool:
        return True

    def _handle_no_baits(self) -> bool:
        self.log("No bait detected", DANGER)
        if self.auto_bait_var.get():
            self.log("Swapping bait...", ACCENT)
            return self.equip_next_bait()
        else:
            self.play_alert()
            self.StopRequested.emit()
            return False

    def _do_cast_and_hook(self, sct: Any) -> bool:
        if not self.line_cast:
            self.set_status("Casting")
            self.log("Casting hook...", DEFAULT)
            self._perform_gamepad_wake_up()
            self.controller.tap(KEY_CAST)

            if not self.sleep(POST_CAST_SETTLE):
                return False

            if detect_no_baits(sct):
                if not self._handle_no_baits():
                    return False

            self.line_cast = True
        else:
            self.set_status("Waiting for bite...")

        if not self.sleep(HOOK_GRACE_SECS):
            return False

        self.set_status("Hooking")

        cast_found = False
        game_started = False

        for attempt in range(1, CAST_POLL_MAX + 1):
            if self.stop_event.is_set():
                return False

            if detect_bar(sct) is not None or detect_line(sct) is not None:
                game_started = True
                cast_found = True
                break

            if detect_cast_button(sct):
                cast_found = True
                break

            self.log(
                f"Waiting for hook... (Attempt {attempt}/{CAST_POLL_MAX})",
                TEXT_MUTED,
                replace_last=(attempt > 1),
            )

            if not self.sleep(CAST_POLL):
                return False

        if not cast_found:
            self.log("No hook detected", DANGER)
            self.line_cast = False

            if self.abort_behavior_var.get():
                self.log("Recovering... continuing session.", ACCENT)
                if not self.sleep(RECOVER_WAIT):
                    return False
                return True

            self.StopRequested.emit()
            return False

        if not game_started:
            self.log("Hook detected!", DEFAULT)
            self._perform_gamepad_wake_up()
            self.controller.tap(KEY_CAST)

        bar_found = False

        for attempt in range(1, BAR_RETRY_MAX + 1):
            if self.stop_event.is_set():
                return False

            if detect_bar(sct) is not None:
                bar_found = True
                break

            self.log(
                f"Waiting for bar... (Attempt {attempt}/{BAR_RETRY_MAX})",
                TEXT_MUTED,
                replace_last=(attempt > 1),
            )

            if not self.sleep(BAR_WAIT):
                return False

        if not bar_found:
            self.log("No bar detected", DANGER)
            self.line_cast = False

            if self.abort_behavior_var.get():
                self.log("Recovering... continuing session.", ACCENT)
                if not self.sleep(RECOVER_WAIT):
                    return True

            self.StopRequested.emit()
            return False

        self.set_status("Reeling")
        self.log("Reeling in fish...", DEFAULT)
        self._perform_gamepad_wake_up()
        return self.play_minigame(sct)

    def _do_result(self, sct: Any) -> bool:
        if self.stop_event.is_set():
            return False

        self.set_status("Check")
        self.log("Checking result...", DEFAULT)

        if not self.sleep(POST_MINIGAME_WAIT):
            return False

        result_found = False

        for attempt in range(1, RESULT_POLL_MAX + 1):
            if self.stop_event.is_set():
                return False

            if detect_result(sct):
                result_found = True
                break

            self.log(
                f"Waiting for result... (Attempt {attempt}/{RESULT_POLL_MAX})",
                TEXT_MUTED,
                replace_last=True,
            )

            if not self.sleep(RESULT_POLL):
                return False

        self.line_cast = False

        if result_found:
            self.fish_count += 1
            self.update_fish()
            self.log(f"Caught fish #{self.fish_count}!", ACCENT)
            self.set_status("Caught!")
            # Move stick on result
            self._perform_gamepad_wake_up()

            if not self.sleep(RESULT_DISMISS_WAIT):
                return False
        else:
            self.log("Fish missed or result timed out.", DANGER)

        if not self.sleep(POST_CAST_SETTLE):
            return False

        return True

    def _should_minimize_to_tray(self) -> bool:
        if getattr(self, "_force_quit", False):
            return False

        settings = getattr(self, "settings", None)

        if settings is None:
            return False

        try:
            return bool(settings.minimize_to_tray.get())
        except Exception:
            return False

    def _minimize_to_tray(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.hide()

        if self._tray_manager is not None:
            self._tray_manager.refresh_visibility_label()

    def _restore_from_tray(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

        if self._tray_manager is not None:
            self._tray_manager.refresh_visibility_label()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)

        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.windowState() & Qt.WindowState.WindowMinimized
            and self._should_minimize_to_tray()
        ):
            QTimer.singleShot(0, self._minimize_to_tray)

    def closeEvent(self, event) -> None:
        if self._should_minimize_to_tray():
            event.ignore()
            self._minimize_to_tray()
            return

        handler = getattr(self, "_close_handler", None)

        if handler is not None:
            handler()

        event.accept()

    def quit_application(self) -> None:
        self._force_quit = True

        try:
            self.settings.flush()  # Ensure settings are saved on quit
        except Exception:
            pass

        handler = getattr(self, "_close_handler", None)

        if handler is not None:
            handler()
        else:
            try:
                self.stop()
            except Exception:
                logger.debug("Failed to stop on quit", exc_info=True)

        if self._tray_manager is not None:
            self._tray_manager.tray.hide()

        self.app.quit()

    def destroy(self) -> None:
        self.hide()

    def mainloop(self) -> None:
        if self.settings.start_minimized.get():
            self._minimize_to_tray()
        else:
            self.show()

        sys.exit(self.app.exec())