# scripts/capture.py
from __future__ import annotations

import abc
import logging
from typing import Optional

import numpy as np
import mss

from config import get_target_exe
from win32_utils import print_window_to_rgb_array, find_hwnd_by_exe

logger = logging.getLogger(__name__)


class ICapture(abc.ABC):
    """Abstract interface for screen capture providers."""

    @abc.abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        """Return an RGB image (H, W, 3) or None on failure."""
        pass


class WindowCapture(ICapture):
    """Captures a specific game window using PrintWindow (with fallback)."""

    def __init__(self, hwnd: Optional[int] = None) -> None:
        self.hwnd = hwnd or find_hwnd_by_exe(get_target_exe())
        self._fallback_used = False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self.hwnd:
            return None
        # First attempt with PrintWindow
        arr = print_window_to_rgb_array(self.hwnd)
        if arr is not None and arr.size > 0:
            self._fallback_used = False
            return arr
        # Fallback: BitBlt via mss on the window's screen? Actually we don't have BitBlt in win32_utils yet.
        # We'll implement a simple fallback using MonitorCapture on the monitor containing the window.
        # For now, log and return None.
        logger.warning("WindowCapture: PrintWindow returned empty/black frame, falling back to monitor capture.")
        # We'll use MonitorCapture but we need the monitor index. We'll get the monitor from window rect.
        # Simplified: use primary monitor.
        if not self._fallback_used:
            self._fallback_used = True
            mon_cap = MonitorCapture(1)
            return mon_cap.capture_frame()
        return None


class MonitorCapture(ICapture):
    """Captures an entire monitor using MSS."""

    def __init__(self, monitor_index: int = 1) -> None:
        self.sct = mss.mss()
        self.monitor_index = monitor_index
        if monitor_index < 1 or monitor_index >= len(self.sct.monitors):
            self.monitor_index = 1
        self.monitor = self.sct.monitors[self.monitor_index]

    def capture_frame(self) -> Optional[np.ndarray]:
        try:
            img = self.sct.grab(self.monitor)
            # MSS returns BGRA; we convert to RGB and ensure contiguous
            rgb = np.ascontiguousarray(np.array(img)[:, :, :3][:, :, ::-1])
            return rgb
        except Exception as e:
            logger.debug(f"MonitorCapture failed: {e}")
            return None