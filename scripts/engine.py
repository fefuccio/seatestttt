# scripts/engine.py
from __future__ import annotations

import time
import threading
from enum import Enum, auto
from typing import Optional, Callable, Any
from dataclasses import dataclass
import logging

import numpy as np

from config import (
    BAR_RETRY_MAX, BAR_WAIT, CAST_POLL, CAST_POLL_MAX,
    HOOK_GRACE_SECS, POST_CAST_SETTLE, POST_MINIGAME_WAIT,
    RECOVER_WAIT, RESULT_DISMISS_WAIT, RESULT_POLL, RESULT_POLL_MAX,
    REEL_CENTER_DEADZONE, REEL_COAST_ZONE,
    REEL_MAX_HOLD_TIME, REEL_MIN_HOLD_TIME, REEL_POLL_DELAY,
    BAR_X_MIN, BAR_X_MAX,
)

# Direct import – controller.py is in the same directory
from controller import ControllerInput

from capture import ICapture
from screen_detection import detect_bar, detect_line, detect_cast_button, detect_result, detect_no_baits
from settings import Settings
from bait_manager import BaitManager

logger = logging.getLogger(__name__)


class EngineState(Enum):
    IDLE = auto()
    CASTING = auto()
    WAITING_BITE = auto()
    HOOKING = auto()
    REELING = auto()
    RESULT_CHECK = auto()
    BAIT_SWITCHING = auto()
    ERROR = auto()


@dataclass
class EngineEvent:
    kind: str
    data: Any = None


class FishingEngine:
    """State machine that drives the fishing process."""

    def __init__(
        self,
        capture: ICapture,
        controller: ControllerInput,
        settings: Settings,
        bait_manager: BaitManager,
        on_event: Callable[[EngineEvent], None],
        on_status: Callable[[str], None],
        on_log: Callable[[str, str], None],
        on_fish_count: Callable[[int], None],
    ):
        self.capture = capture
        self.controller = controller
        self.settings = settings
        self.bait_manager = bait_manager
        self.on_event = on_event
        self.on_status = on_status
        self.on_log = on_log
        self.on_fish_count = on_fish_count

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.state = EngineState.IDLE
        self.fish_count = 0
        self.line_cast = False

        # Performance monitoring
        self._loop_count = 0
        self._capture_time_accum = 0.0
        self._consecutive_capture_failures = 0
        self._max_capture_failures = 10
        self._use_monitor_fallback = False
        self._monitor_capture = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        with self._lock:
            self.state = EngineState.IDLE
            self.fish_count = 0
            self.line_cast = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.controller.release_all()

    def _run(self) -> None:
        try:
            self._main_loop()
        except Exception as e:
            self.on_log(f"Engine crashed: {e}", "#EF4444")
            self.on_event(EngineEvent("error", str(e)))
        finally:
            self.controller.release_all()
            with self._lock:
                self.state = EngineState.IDLE
            self.on_status("Idle")

    def _main_loop(self) -> None:
        self._loop_count = 0
        self._capture_time_accum = 0.0
        self._consecutive_capture_failures = 0
        self._use_monitor_fallback = False

        last_frame = None
        last_detections = {}
        frame_cache_ttl = 0.1
        last_frame_time = 0.0

        while not self._stop_event.is_set():
            # Capture frame
            frame = None
            if not self._use_monitor_fallback:
                frame = self.capture.capture_frame()
            if frame is None:
                if not self._use_monitor_fallback:
                    self.on_log("Capture failed, switching to monitor fallback", "#FFB610")
                    self._use_monitor_fallback = True
                    if self._monitor_capture is None:
                        from capture import MonitorCapture
                        self._monitor_capture = MonitorCapture(1)
                    frame = self._monitor_capture.capture_frame()
                if frame is None:
                    self._consecutive_capture_failures += 1
                    if self._consecutive_capture_failures >= self._max_capture_failures:
                        self.on_log("Capture failed repeatedly, pausing bot", "#EF4444")
                        self.on_event(EngineEvent("error", "Capture failure"))
                        self._stop_event.set()
                        break
                    self._sleep(0.2)
                    continue
                else:
                    self._consecutive_capture_failures = 0
            else:
                self._consecutive_capture_failures = 0

            # Performance logging
            capture_start = time.perf_counter()
            capture_duration_ms = (time.perf_counter() - capture_start) * 1000.0
            self._loop_count += 1
            self._capture_time_accum += capture_duration_ms
            if self._loop_count >= 50 and self.settings.debug_console.get():
                avg_ms = self._capture_time_accum / self._loop_count
                self.on_log(f"[Perf] Avg capture time: {avg_ms:.2f} ms  (frames: {self._loop_count})", "#94A3B8")
                self._loop_count = 0
                self._capture_time_accum = 0.0

            # Frame-based detection caching
            now = time.monotonic()
            if last_frame is not None and np.array_equal(frame, last_frame) and (now - last_frame_time) < frame_cache_ttl:
                bar_x = last_detections.get("bar")
                line_x = last_detections.get("line")
                cast_button = last_detections.get("cast_button")
                result = last_detections.get("result")
                no_bait = last_detections.get("no_bait")
            else:
                bar_x = detect_bar(frame)
                line_x = detect_line(frame)
                cast_button = detect_cast_button(frame)
                result = detect_result(frame)
                no_bait = detect_no_baits(frame)
                last_frame = frame.copy()
                last_frame_time = now
                last_detections = {
                    "bar": bar_x,
                    "line": line_x,
                    "cast_button": cast_button,
                    "result": result,
                    "no_bait": no_bait,
                }

            # Ensure booleans
            cast_button = bool(cast_button) if cast_button is not None else False
            result = bool(result) if result is not None else False
            no_bait = bool(no_bait) if no_bait is not None else False

            # Ensure bait
            if self.settings.auto_bait.get():
                if not self._ensure_bait(frame, no_bait):
                    continue

            # Check minigame
            if bar_x is not None or line_x is not None:
                self.line_cast = False
                self._run_reeling(frame, bar_x, line_x)
            else:
                if not self.line_cast:
                    self._do_cast_and_hook(frame, cast_button)
                else:
                    self._wait_for_bite()

            # After minigame or failed cast, handle result
            self._handle_result(frame, result)

            # Adaptive sleep
            if self.state == EngineState.IDLE:
                self._sleep(0.1)
            elif self.state == EngineState.WAITING_BITE:
                self._sleep(0.2)
            else:
                self._sleep(0.02)

    def _ensure_bait(self, frame: np.ndarray, no_bait: bool) -> bool:
        if no_bait:
            self.on_log("No bait detected", "#EF4444")
            if self.settings.auto_bait.get():
                self.on_log("Switching bait...", "#FA468E")
                success = self._switch_to_next_bait()
                if not success:
                    self.on_event(EngineEvent("bait_exhausted"))
                    self._stop_event.set()
                return success
            else:
                self.on_event(EngineEvent("bait_exhausted"))
                self._stop_event.set()
                return False
        return True

    def _switch_to_next_bait(self) -> bool:
        current = self.bait_manager.current_index
        next_idx = self.bait_manager.get_next_available()
        if next_idx is None:
            return False
        self.controller.tap("TRIANGLE")
        self._sleep(0.6)
        self.controller.tap("DPAD_LEFT")
        self._sleep(0.1)
        for _ in range(next_idx):
            self.controller.tap("DPAD_RIGHT")
            self._sleep(0.1)
        self.controller.tap("CIRCLE")
        self._sleep(0.3)
        frame = self.capture.capture_frame()
        if frame is not None and not detect_no_baits(frame):
            with self._lock:
                self.bait_manager.current_index = next_idx
            self.on_event(EngineEvent("bait_switched", next_idx))
            return True
        return False

    def _do_cast_and_hook(self, frame: np.ndarray, cast_button: bool) -> None:
        with self._lock:
            self.state = EngineState.CASTING
        self.on_status("Casting")
        self.on_log("Casting hook...", "#E4E4E4")
        self.controller.tap("CROSS")
        self._sleep(POST_CAST_SETTLE)

        if detect_no_baits(frame):
            if not self._ensure_bait(frame, True):
                return

        with self._lock:
            self.line_cast = True
            self.state = EngineState.WAITING_BITE
        self.on_status("Waiting for bite...")
        self._sleep(HOOK_GRACE_SECS)

        for attempt in range(1, CAST_POLL_MAX + 1):
            if self._stop_event.is_set():
                return
            fresh_frame = self.capture.capture_frame()
            if fresh_frame is None:
                continue
            bar_x = detect_bar(fresh_frame)
            line_x = detect_line(fresh_frame)
            if bar_x is not None or line_x is not None:
                with self._lock:
                    self.state = EngineState.REELING
                self._run_reeling(fresh_frame, bar_x, line_x)
                return
            if detect_cast_button(fresh_frame):
                self.controller.tap("CROSS")
                self._sleep(0.2)
                for _ in range(BAR_RETRY_MAX):
                    if self._stop_event.is_set():
                        return
                    fresh_frame = self.capture.capture_frame()
                    if fresh_frame is not None and detect_bar(fresh_frame) is not None:
                        with self._lock:
                            self.state = EngineState.REELING
                        self._run_reeling(fresh_frame, detect_bar(fresh_frame), detect_line(fresh_frame))
                        return
                    self._sleep(BAR_WAIT)
                self.on_log("Hook failed – no bar appeared", "#EF4444")
                with self._lock:
                    self.line_cast = False
                if self.settings.ignore_abort.get():
                    self.on_log("Recovering...", "#FA468E")
                    self._sleep(RECOVER_WAIT)
                    return
                self.on_event(EngineEvent("error", "Hook timeout"))
                self._stop_event.set()
                return
            self._sleep(CAST_POLL)

        self.on_log("No hook detected", "#EF4444")
        with self._lock:
            self.line_cast = False
        if self.settings.ignore_abort.get():
            self.on_log("Recovering...", "#FA468E")
            self._sleep(RECOVER_WAIT)
            return
        self.on_event(EngineEvent("error", "Cast timeout"))
        self._stop_event.set()

    def _wait_for_bite(self) -> None:
        self._sleep(0.2)

    def _run_reeling(self, frame: np.ndarray, bar_x: Optional[int], line_x: Optional[int]) -> None:
        with self._lock:
            self.state = EngineState.REELING
        self.on_status("Reeling")

        if frame is not None:
            h, w = frame.shape[:2]
            region_w = int(w * (BAR_X_MAX - BAR_X_MIN))
        else:
            region_w = 1920

        current_held_key = None

        def release_current():
            nonlocal current_held_key
            if current_held_key is not None:
                self.controller.release(current_held_key)
                current_held_key = None

        while not self._stop_event.is_set():
            fresh_frame = self.capture.capture_frame()
            if fresh_frame is None:
                continue
            bar_x = detect_bar(fresh_frame)
            if bar_x is None:
                release_current()
                self.on_log("Bar disappeared – fish lost", "#EF4444")
                return
            line_x = detect_line(fresh_frame)
            if line_x is None:
                release_current()
                self._sleep(0.025)
                continue

            delta = bar_x - line_x
            rel_error = abs(delta) / region_w
            deadzone = REEL_CENTER_DEADZONE / region_w
            coast_zone = REEL_COAST_ZONE / region_w

            if rel_error <= deadzone:
                release_current()
                self._sleep(0.025)
                continue
            if rel_error <= coast_zone:
                release_current()
                self._sleep(0.05)
                continue

            desired_key = "R2" if delta > 0 else "L2"
            if current_held_key is not None and current_held_key != desired_key:
                release_current()
                continue

            hold_time = min(REEL_MAX_HOLD_TIME, max(REEL_MIN_HOLD_TIME, rel_error * REEL_MAX_HOLD_TIME))
            if current_held_key is None:
                self.controller.press(desired_key)
                current_held_key = desired_key
            self._sleep(hold_time)
            release_current()
            self._sleep(REEL_POLL_DELAY)

        with self._lock:
            self.state = EngineState.RESULT_CHECK
        self._sleep(POST_MINIGAME_WAIT)

    def _handle_result(self, frame: np.ndarray, result: bool) -> None:
        if self._stop_event.is_set():
            return
        with self._lock:
            self.state = EngineState.RESULT_CHECK
        self.on_status("Check")
        self.on_log("Checking result...", "#E4E4E4")

        self._sleep(RESULT_POLL)
        found = result
        if not found:
            for _ in range(RESULT_POLL_MAX):
                if self._stop_event.is_set():
                    return
                fresh_frame = self.capture.capture_frame()
                if fresh_frame is not None and detect_result(fresh_frame):
                    found = True
                    break
                self._sleep(RESULT_POLL)

        with self._lock:
            self.line_cast = False
        if found:
            with self._lock:
                self.fish_count += 1
            self.on_fish_count(self.fish_count)
            self.on_log(f"Caught fish #{self.fish_count}!", "#FA468E")
            self.on_event(EngineEvent("fish_caught", self.fish_count))
            self.on_status("Caught!")
            self._sleep(RESULT_DISMISS_WAIT)
        else:
            self.on_log("Fish missed or result timed out.", "#EF4444")
            self.on_event(EngineEvent("missed_fish"))

        self._sleep(POST_CAST_SETTLE)
        with self._lock:
            self.state = EngineState.IDLE
        self.on_status("Idle")

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stop_event.is_set():
            time.sleep(0.01)