from __future__ import annotations

import logging
import os
import threading
import time
import struct
import zlib
from typing import Any, Optional, Tuple

import mss
import numpy as np

from config import (
    BAR_RGB, LINE_RGB, CAST_RGB, RESULT_RGB, PINK_RGB, GOLD_RGB,
    BAR_TOL, LINE_TOL, CAST_TOL, RESULT_TOL, RESULT_REQUIRED,
    WHITE_THRESHOLD, WHITE_PERCENT, BAIT_COLOR_TOL, CURSOR_MIN_PIXELS,
    BAR_X_MIN, BAR_X_MAX, BAR_Y_MIN, BAR_Y_MAX,
    LINE_X_MIN, LINE_X_MAX, LINE_Y_MIN, LINE_Y_MAX,
    CAST_X_MIN, CAST_X_MAX, CAST_Y_MIN, CAST_Y_MAX,
    RESULT_X_MIN, RESULT_X_MAX, RESULT_Y_MIN, RESULT_Y_MAX,
    FISH_MODE_X_MIN, FISH_MODE_X_MAX, FISH_MODE_Y_MIN, FISH_MODE_Y_MAX,
    FISH_MODE_COLOR, FISH_MODE_TOL, FISH_MODE_MIN_PIXELS,
    FISH_MENU_X_MIN, FISH_MENU_X_MAX, FISH_MENU_Y_MIN, FISH_MENU_Y_MAX,
    FISH_MENU_TOL, FISH_MENU_GREEN_RGB, FISH_MENU_BLUE_RGB,
    FISH_MENU_PURPLE_RGB, FISH_MENU_ORANGE_RGB,
    BAIT_EMPTY_X_MIN, BAIT_EMPTY_X_MAX, BAIT_EMPTY_Y_MIN, BAIT_EMPTY_Y_MAX,
    BAIT_EMPTY_WHITE, BAIT_EMPTY_DARK, BAIT_EMPTY_TOL,
    BAIT_EMPTY_MIN_WHITE_RATIO, BAIT_EMPTY_MIN_DARK_RATIO,
    DEBUG_NO_BAIT_SCREENSHOT,
)
from win32_utils import print_window_to_rgb_array

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capture abstractions
# ---------------------------------------------------------------------------

class WindowCapture:
    def __init__(self, hwnd: int, ttl: float = 0.015) -> None:
        self.hwnd = hwnd
        self._frame: Optional[np.ndarray] = None
        self._frame_time = 0.0
        self._ttl = ttl
        self._lock = threading.Lock()

    def get_full_frame(self) -> Optional[np.ndarray]:
        now = time.perf_counter()

        with self._lock:
            if self._frame is not None and (now - self._frame_time) < self._ttl:
                return self._frame

        img = print_window_to_rgb_array(self.hwnd)

        if img is None:
            return None

        with self._lock:
            self._frame = img
            self._frame_time = time.perf_counter()

        return img


class MonitorCapture:
    def __init__(self, sct: "mss.MSS", monitor_index: int = 1) -> None:
        self.sct = sct

        if not (1 <= monitor_index < len(sct.monitors)):
            monitor_index = 1

        self.monitor_index = monitor_index
        self.monitor = dict(sct.monitors[monitor_index])

    def grab(self, region: dict) -> np.ndarray:
        raw = np.frombuffer(self.sct.grab(region).rgb, dtype=np.uint8)
        return raw.reshape((region["height"], region["width"], 3))


_MONITOR_LOCK = threading.Lock()
_MONITOR_CACHE: dict[int, dict] = {}


def _get_monitor(sct: "mss.MSS", monitor_index: int = 1) -> dict:
    global _MONITOR_CACHE

    with _MONITOR_LOCK:
        if monitor_index not in _MONITOR_CACHE:
            if not (1 <= monitor_index < len(sct.monitors)):
                monitor_index = 1

            _MONITOR_CACHE[monitor_index] = dict(sct.monitors[monitor_index])

        return _MONITOR_CACHE[monitor_index]


def reset_monitor_cache() -> None:
    global _MONITOR_CACHE

    with _MONITOR_LOCK:
        _MONITOR_CACHE.clear()


# ---------------------------------------------------------------------------
# Region helpers
# ---------------------------------------------------------------------------

def _build_region(mon: dict, x_min: float, x_max: float, y_min: float, y_max: float) -> dict:
    width = mon["width"]
    height = mon["height"]

    left = mon["left"] + int(width * x_min)
    top = mon["top"] + int(height * y_min)

    region_width = max(1, int(width * (x_max - x_min)))
    region_height = max(1, int(height * (y_max - y_min)))

    return {
        "left": left,
        "top": top,
        "width": region_width,
        "height": region_height,
    }


def _capture(
    sct: Any, x_min: float, x_max: float, y_min: float, y_max: float,
    region: Optional[dict] = None,
) -> Tuple[np.ndarray, dict]:
    if isinstance(sct, WindowCapture):
        frame = sct.get_full_frame()

        if frame is None:
            return (
                np.empty((0, 0, 3), dtype=np.uint8),
                {"left": 0, "top": 0, "width": 0, "height": 0},
            )

        height, width = frame.shape[:2]

        x0 = min(width - 1, max(0, int(width * x_min)))
        x1 = min(width, max(1, int(width * x_max)))
        y0 = min(height - 1, max(0, int(height * y_min)))
        y1 = min(height, max(1, int(height * y_max)))

        sub = frame[y0:y1, x0:x1]

        if region is None:
            region = {
                "left": x0, "top": y0,
                "width": x1 - x0, "height": y1 - y0,
            }

        return sub, region

    if isinstance(sct, MonitorCapture):
        mon = sct.monitor

        if region is None:
            region = _build_region(mon, x_min, x_max, y_min, y_max)

        return sct.grab(region), region

    monitor_index = getattr(sct, "monitor_index", 1)
    mon = _get_monitor(sct, monitor_index)

    if region is None:
        region = _build_region(mon, x_min, x_max, y_min, y_max)

    raw = np.frombuffer(sct.grab(region).rgb, dtype=np.uint8)

    return (
        raw.reshape((region["height"], region["width"], 3)),
        region,
    )


# ---------------------------------------------------------------------------
# PNG Writer Helper (No External Dependencies)
# ---------------------------------------------------------------------------

def _write_png(filename: str, data: np.ndarray) -> None:
    """Writes a 3-channel (RGB) numpy array to a PNG file using only stdlib."""
    height, width, channels = data.shape
    if channels != 3:
        raise ValueError("Only RGB images are supported")
    
    # Build raw data with filter type 0 (None) for each row
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00' + data[y, :, :].tobytes()
    
    # Compress the raw data
    compressed_data = zlib.compress(raw_data)
    
    # Construct PNG chunks
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type)
        crc = zlib.crc32(data, crc) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk_type + data + struct.pack('>I', crc)
    
    # Signature
    signature = b'\x89PNG\r\n\x1a\n'
    
    # IHDR (Header)
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0) # 8-bit, color type 2 (Truecolor)
    ihdr = chunk(b'IHDR', header)
    
    # IDAT (Image Data)
    idat = chunk(b'IDAT', compressed_data)
    
    # IEND (End)
    iend = chunk(b'IEND', b'')
    
    # Write to file
    with open(filename, 'wb') as f:
        f.write(signature + ihdr + idat + iend)


# ---------------------------------------------------------------------------
# Game detectors
# ---------------------------------------------------------------------------

def detect_no_baits(sct: Any) -> bool:
    """
    Returns True if the screen displays the 'no baits left' UI.
    Checks if the middle of the screen has a dark box with pure white text.
    """
    img, _ = _capture(sct, BAIT_EMPTY_X_MIN, BAIT_EMPTY_X_MAX, BAIT_EMPTY_Y_MIN, BAIT_EMPTY_Y_MAX)

    if img.size == 0:
        return False

    # Strict white check
    mask_white = np.max(np.abs(img.astype(np.int16) - BAIT_EMPTY_WHITE), axis=2) <= BAIT_EMPTY_TOL
    white_ratio = float(np.mean(mask_white))

    # Strict dark background check
    mask_dark = np.max(np.abs(img.astype(np.int16) - BAIT_EMPTY_DARK), axis=2) <= BAIT_EMPTY_TOL
    dark_ratio = float(np.mean(mask_dark))

    # ------------------------- DEBUG START -------------------------
    if DEBUG_NO_BAIT_SCREENSHOT and img.size > 0:
        debug_dir = os.path.join(os.getcwd(), "debug")
        try:
            os.makedirs(debug_dir, exist_ok=True)
            filename = os.path.join(debug_dir, f"no_bait_debug_{int(time.time())}.png")
            _write_png(filename, img)
            logger.warning(
                f"[DEBUG No-Bait] Region saved: {filename} | "
                f"White: {white_ratio:.2f} (min {BAIT_EMPTY_MIN_WHITE_RATIO}) | "
                f"Dark: {dark_ratio:.2f} (min {BAIT_EMPTY_MIN_DARK_RATIO}) | "
                f"Detected: {bool(white_ratio >= BAIT_EMPTY_MIN_WHITE_RATIO and dark_ratio >= BAIT_EMPTY_MIN_DARK_RATIO)}"
            )
        except Exception as e:
            logger.warning(f"[DEBUG No-Bait] Failed to save screenshot: {e}")
    # ------------------------- DEBUG END -------------------------

    return bool(white_ratio >= BAIT_EMPTY_MIN_WHITE_RATIO and dark_ratio >= BAIT_EMPTY_MIN_DARK_RATIO)


def detect_cast_button(sct: Any) -> bool:
    img, _ = _capture(sct, CAST_X_MIN, CAST_X_MAX, CAST_Y_MIN, CAST_Y_MAX)

    if img.size == 0:
        return False

    return _find_color(img, CAST_RGB, CAST_TOL) is not None


def detect_bar(sct: Any) -> Optional[int]:
    img, region = _capture(sct, BAR_X_MIN, BAR_X_MAX, BAR_Y_MIN, BAR_Y_MAX)

    if img.size == 0:
        return None

    cx = _bar_center_x(img, BAR_TOL)

    if cx is None:
        return None

    return region["left"] + cx


def detect_line(sct: Any) -> Optional[int]:
    img, region = _capture(sct, LINE_X_MIN, LINE_X_MAX, LINE_Y_MIN, LINE_Y_MAX)

    if img.size == 0:
        return None

    lx = _line_col(img, LINE_TOL)

    if lx is None:
        return None

    return region["left"] + lx


def detect_result(sct: Any) -> bool:
    img, _ = _capture(sct, RESULT_X_MIN, RESULT_X_MAX, RESULT_Y_MIN, RESULT_Y_MAX)

    if img.size == 0:
        return False

    return _find_color(img, RESULT_RGB, RESULT_TOL, required=RESULT_REQUIRED) is not None


# ---------------------------------------------------------------------------
# Generic pixel detection
# ---------------------------------------------------------------------------

def _find_color(img: np.ndarray, target: np.ndarray, tol: int, required: int = 1):
    if img.size == 0:
        return None

    diff = np.max(np.abs(img.astype(np.int16) - target), axis=2)
    coords = np.argwhere(diff <= tol)

    if required == 1 and len(coords) >= 1:
        return (int(coords[0, 1]), int(coords[0, 0]))

    if len(coords) >= required:
        cols = coords[:, 1]
        rows = coords[:, 0]
        return (int(np.median(cols)), int(np.median(rows)))

    return None


def _bar_center_x(img: np.ndarray, tol: int):
    if img.size == 0:
        return None

    diff = np.max(np.abs(img.astype(np.int16) - BAR_RGB), axis=2)
    coords = np.argwhere(diff <= tol)

    if len(coords) == 0:
        return None

    cols = coords[:, 1]
    return int(np.mean(cols))


def _line_col(img: np.ndarray, tol: int):
    hit = _find_color(img, LINE_RGB, tol)
    return hit[0] if hit is not None else None


# ---------------------------------------------------------------------------
# Bait-menu detectors
# ---------------------------------------------------------------------------

def _cursor_mask(img: np.ndarray) -> np.ndarray:
    pink = np.max(np.abs(img.astype(np.int16) - PINK_RGB), axis=2) <= BAIT_COLOR_TOL
    gold = np.max(np.abs(img.astype(np.int16) - GOLD_RGB), axis=2) <= BAIT_COLOR_TOL

    return pink | gold


def detect_bait_menu_open(sct: Any) -> bool:
    cursor_img, _ = _capture(sct, 0.0, 1.0, 0.35, 0.55)

    if cursor_img.size == 0:
        return False

    return bool(np.sum(_cursor_mask(cursor_img)) >= CURSOR_MIN_PIXELS)


def check_bait_availability(sct: Any) -> bool:
    cursor_img, cursor_region = _capture(sct, 0.0, 1.0, 0.35, 0.55)

    if cursor_img.size == 0:
        return False

    cursor_mask = _cursor_mask(cursor_img)

    if np.sum(cursor_mask) < CURSOR_MIN_PIXELS:
        return False

    cols = np.where(cursor_mask.any(axis=0))[0]

    if len(cols) == 0:
        return False

    diffs = np.diff(cols)
    split_indices = np.where(diffs > 5)[0]

    if len(split_indices) > 0:
        blobs = np.split(cols, split_indices + 1)
        largest_blob = max(blobs, key=len)
        cols = largest_blob

    cursor_cx = cursor_region["left"] + int(np.mean(cols))

    text_img, text_region = _capture(sct, 0.0, 1.0, 0.55, 0.57)

    if text_img.size == 0:
        return False

    rel_cx = cursor_cx - text_region["left"]
    slice_w = 120

    start_x = max(0, rel_cx - slice_w // 2)
    end_x = min(text_img.shape[1], rel_cx + slice_w // 2)

    if start_x >= end_x:
        return False

    text_slice = text_img[:, start_x:end_x]

    r = text_slice[:, :, 0].astype(np.int16)
    g = text_slice[:, :, 1].astype(np.int16)
    b = text_slice[:, :, 2].astype(np.int16)

    reddish_mask = (r > 150) & (g < 100) & (b < 100)
    reddish_count = int(np.sum(reddish_mask))

    return bool(reddish_count < 5)


# ---------------------------------------------------------------------------
# Fishing-mode detector (Map + Green menu - unchanged)
# ---------------------------------------------------------------------------

class FishingModeState:
    NORMAL = 0
    MENU = 1
    MINIGAME = 2


def check_fishing_mode(sct: Any) -> int:
    """
    Returns the current fishing mode state based on the 4-state logic:
    1. Map yes -> NORMAL
    2. Map no + Menu (Green is required, others are optional) -> MENU
    3. Map no + No Menu -> MINIGAME
    """
    img_map, _ = _capture(
        sct, FISH_MODE_X_MIN, FISH_MODE_X_MAX, FISH_MODE_Y_MIN, FISH_MODE_Y_MAX,
    )
    has_map = False
    if img_map.size > 0:
        mask_map = np.max(np.abs(img_map.astype(np.int16) - FISH_MODE_COLOR), axis=2) <= FISH_MODE_TOL
        has_map = bool(np.sum(mask_map) >= FISH_MODE_MIN_PIXELS)

    # Check menu region
    img_menu, _ = _capture(
        sct, FISH_MENU_X_MIN, FISH_MENU_X_MAX, FISH_MENU_Y_MIN, FISH_MENU_Y_MAX,
    )
    
    has_green = False
    has_blue = False
    has_purple = False
    has_orange = False
    
    if img_menu.size > 0:
        mask_green = np.max(np.abs(img_menu.astype(np.int16) - FISH_MENU_GREEN_RGB), axis=2) <= FISH_MENU_TOL
        mask_blue = np.max(np.abs(img_menu.astype(np.int16) - FISH_MENU_BLUE_RGB), axis=2) <= FISH_MENU_TOL
        mask_purple = np.max(np.abs(img_menu.astype(np.int16) - FISH_MENU_PURPLE_RGB), axis=2) <= FISH_MENU_TOL
        mask_orange = np.max(np.abs(img_menu.astype(np.int16) - FISH_MENU_ORANGE_RGB), axis=2) <= FISH_MENU_TOL
        
        has_green = bool(np.any(mask_green))
        has_blue = bool(np.any(mask_blue))
        has_purple = bool(np.any(mask_purple))
        has_orange = bool(np.any(mask_orange))

    # Green is the only must-have
    has_menu = has_green

    if not has_map:
        if has_menu:
            return FishingModeState.MENU
        else:
            return FishingModeState.MINIGAME
    else:
        return FishingModeState.NORMAL