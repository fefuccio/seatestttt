# scripts/screen_detection.py
from __future__ import annotations

import logging
import os
import time
import struct
import zlib
from typing import Optional, Dict, Any

import numpy as np

from config import (
    BAR_RGB, LINE_RGB, CAST_RGB, RESULT_RGB, PINK_RGB, GOLD_RGB,
    BAR_TOL, LINE_TOL, CAST_TOL, RESULT_TOL, RESULT_REQUIRED,
    BAIT_COLOR_TOL, CURSOR_MIN_PIXELS,
    BAR_X_MIN, BAR_X_MAX, BAR_Y_MIN, BAR_Y_MAX,
    LINE_X_MIN, LINE_X_MAX, LINE_Y_MIN, LINE_Y_MAX,
    CAST_X_MIN, CAST_X_MAX, CAST_Y_MIN, CAST_Y_MAX,
    RESULT_X_MIN, RESULT_X_MAX, RESULT_Y_MIN, RESULT_Y_MAX,
    FISH_MODE_X_MIN, FISH_MODE_X_MAX, FISH_MODE_Y_MIN, FISH_MODE_Y_MAX,
    FISH_MODE_COLOR, FISH_MODE_TOL, FISH_MODE_MIN_PIXELS,
    FISH_MENU_X_MIN, FISH_MENU_X_MAX, FISH_MENU_Y_MIN, FISH_MENU_Y_MAX,
    FISH_MENU_TOL, FISH_MENU_GREEN_RGB,
    BAIT_EMPTY_X_MIN, BAIT_EMPTY_X_MAX, BAIT_EMPTY_Y_MIN, BAIT_EMPTY_Y_MAX,
    BAIT_EMPTY_WHITE, BAIT_EMPTY_DARK, BAIT_EMPTY_TOL,
    BAIT_EMPTY_MIN_WHITE_RATIO, BAIT_EMPTY_MIN_DARK_RATIO,
    DEBUG_NO_BAIT_SCREENSHOT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frame-based crop cache
# ---------------------------------------------------------------------------
_CROP_CACHE: Dict[int, Dict[str, np.ndarray]] = {}
_CACHE_MAX_SIZE = 3

def _get_cached_crops(frame: np.ndarray) -> Dict[str, np.ndarray]:
    if frame is None or frame.size == 0:
        return {}
    frame_id = id(frame)
    if frame_id in _CROP_CACHE:
        return _CROP_CACHE[frame_id]
    h, w = frame.shape[:2]
    regions = {
        "bar": _crop_region(frame, BAR_X_MIN, BAR_X_MAX, BAR_Y_MIN, BAR_Y_MAX),
        "line": _crop_region(frame, LINE_X_MIN, LINE_X_MAX, LINE_Y_MIN, LINE_Y_MAX),
        "cast": _crop_region(frame, CAST_X_MIN, CAST_X_MAX, CAST_Y_MIN, CAST_Y_MAX),
        "result": _crop_region(frame, RESULT_X_MIN, RESULT_X_MAX, RESULT_Y_MIN, RESULT_Y_MAX),
        "bait_empty": _crop_region(frame, BAIT_EMPTY_X_MIN, BAIT_EMPTY_X_MAX, BAIT_EMPTY_Y_MIN, BAIT_EMPTY_Y_MAX),
        "cursor": _crop_region(frame, 0.0, 1.0, 0.35, 0.55),
        "text": _crop_region(frame, 0.0, 1.0, 0.55, 0.57),
        "map": _crop_region(frame, FISH_MODE_X_MIN, FISH_MODE_X_MAX, FISH_MODE_Y_MIN, FISH_MODE_Y_MAX),
        "menu": _crop_region(frame, FISH_MENU_X_MIN, FISH_MENU_X_MAX, FISH_MENU_Y_MIN, FISH_MENU_Y_MAX),
    }
    if len(_CROP_CACHE) >= _CACHE_MAX_SIZE:
        oldest = next(iter(_CROP_CACHE))
        del _CROP_CACHE[oldest]
    _CROP_CACHE[frame_id] = regions
    return regions

def _crop_region(frame: np.ndarray, x_min: float, x_max: float, y_min: float, y_max: float) -> np.ndarray:
    if frame is None or frame.size == 0:
        return np.empty((0, 0, 3), dtype=np.uint8)
    h, w = frame.shape[:2]
    x0 = int(w * x_min)
    x1 = int(w * x_max)
    y0 = int(h * y_min)
    y1 = int(h * y_max)
    x0 = max(0, min(w, x0))
    x1 = max(0, min(w, x1))
    y0 = max(0, min(h, y0))
    y1 = max(0, min(h, y1))
    if x1 <= x0 or y1 <= y0:
        return np.empty((0, 0, 3), dtype=np.uint8)
    return frame[y0:y1, x0:x1]

# ---------------------------------------------------------------------------
# PNG Writer
# ---------------------------------------------------------------------------
def _write_png(filename: str, data: np.ndarray) -> None:
    height, width, channels = data.shape
    if channels != 3:
        raise ValueError("Only RGB images are supported")
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00' + data[y, :, :].tobytes()
    compressed_data = zlib.compress(raw_data)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type)
        crc = zlib.crc32(data, crc) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk_type + data + struct.pack('>I', crc)

    signature = b'\x89PNG\r\n\x1a\n'
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b'IHDR', header)
    idat = chunk(b'IDAT', compressed_data)
    iend = chunk(b'IEND', b'')
    with open(filename, 'wb') as f:
        f.write(signature + ihdr + idat + iend)

# ---------------------------------------------------------------------------
# Helper to ensure color is ndarray
# ---------------------------------------------------------------------------
def _as_array(color):
    if isinstance(color, np.ndarray):
        return color
    return np.array(color, dtype=np.int16)

# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def detect_no_baits(frame: np.ndarray) -> bool:
    if frame is None or frame.size == 0:
        logger.debug("detect_no_baits: empty frame")
        return False
    crops = _get_cached_crops(frame)
    img = crops.get("bait_empty")
    if img is None or img.size == 0:
        logger.debug("detect_no_baits: empty region")
        return False

    white = _as_array(BAIT_EMPTY_WHITE)
    dark = _as_array(BAIT_EMPTY_DARK)
    mask_white = np.max(np.abs(img.astype(np.int16) - white), axis=2) <= BAIT_EMPTY_TOL
    white_ratio = float(np.mean(mask_white))
    mask_dark = np.max(np.abs(img.astype(np.int16) - dark), axis=2) <= BAIT_EMPTY_TOL
    dark_ratio = float(np.mean(mask_dark))

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

    result = bool(white_ratio >= BAIT_EMPTY_MIN_WHITE_RATIO and dark_ratio >= BAIT_EMPTY_MIN_DARK_RATIO)
    logger.debug(f"detect_no_baits: white={white_ratio:.2f}, dark={dark_ratio:.2f}, result={result}")
    return result

def detect_cast_button(frame: np.ndarray) -> bool:
    if frame is None or frame.size == 0:
        logger.debug("detect_cast_button: empty frame")
        return False
    crops = _get_cached_crops(frame)
    img = crops.get("cast")
    if img is None or img.size == 0:
        logger.debug("detect_cast_button: empty region")
        return False
    result = _find_color(img, _as_array(CAST_RGB), CAST_TOL) is not None
    logger.debug(f"detect_cast_button: {result}")
    return result

def detect_bar(frame: np.ndarray) -> Optional[int]:
    if frame is None or frame.size == 0:
        logger.debug("detect_bar: empty frame")
        return None
    crops = _get_cached_crops(frame)
    img = crops.get("bar")
    if img is None or img.size == 0:
        logger.debug("detect_bar: empty region")
        return None
    return _bar_center_x(img, BAR_TOL)

def detect_line(frame: np.ndarray) -> Optional[int]:
    if frame is None or frame.size == 0:
        logger.debug("detect_line: empty frame")
        return None
    crops = _get_cached_crops(frame)
    img = crops.get("line")
    if img is None or img.size == 0:
        logger.debug("detect_line: empty region")
        return None
    return _line_col(img, LINE_TOL)

def detect_result(frame: np.ndarray) -> bool:
    if frame is None or frame.size == 0:
        logger.debug("detect_result: empty frame")
        return False
    crops = _get_cached_crops(frame)
    img = crops.get("result")
    if img is None or img.size == 0:
        logger.debug("detect_result: empty region")
        return False
    result = _find_color(img, _as_array(RESULT_RGB), RESULT_TOL, required=RESULT_REQUIRED) is not None
    logger.debug(f"detect_result: {result}")
    return result

# ---------------------------------------------------------------------------
# Internal helpers
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
    diff = np.max(np.abs(img.astype(np.int16) - _as_array(BAR_RGB)), axis=2)
    coords = np.argwhere(diff <= tol)
    if len(coords) == 0:
        return None
    cols = coords[:, 1]
    return int(np.mean(cols))

def _line_col(img: np.ndarray, tol: int):
    hit = _find_color(img, _as_array(LINE_RGB), tol)
    return hit[0] if hit is not None else None

# ---------------------------------------------------------------------------
# Bait-menu detectors
# ---------------------------------------------------------------------------
def _cursor_mask(img: np.ndarray) -> np.ndarray:
    pink = np.max(np.abs(img.astype(np.int16) - _as_array(PINK_RGB)), axis=2) <= BAIT_COLOR_TOL
    gold = np.max(np.abs(img.astype(np.int16) - _as_array(GOLD_RGB)), axis=2) <= BAIT_COLOR_TOL
    return pink | gold

def detect_bait_menu_open(frame: np.ndarray) -> bool:
    if frame is None or frame.size == 0:
        return False
    crops = _get_cached_crops(frame)
    cursor_img = crops.get("cursor")
    if cursor_img is None or cursor_img.size == 0:
        return False
    return bool(np.sum(_cursor_mask(cursor_img)) >= CURSOR_MIN_PIXELS)

def check_bait_availability(frame: np.ndarray) -> bool:
    if frame is None or frame.size == 0:
        return False
    crops = _get_cached_crops(frame)
    cursor_img = crops.get("cursor")
    if cursor_img is None or cursor_img.size == 0:
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
    cursor_cx = int(np.mean(cols))

    text_img = crops.get("text")
    if text_img is None or text_img.size == 0:
        return False
    rel_cx = cursor_cx
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
# Fishing-mode detector
# ---------------------------------------------------------------------------
class FishingModeState:
    NORMAL = 0
    MENU = 1
    MINIGAME = 2

def check_fishing_mode(frame: np.ndarray) -> int:
    if frame is None or frame.size == 0:
        return FishingModeState.NORMAL
    crops = _get_cached_crops(frame)
    img_map = crops.get("map")
    has_map = False
    if img_map is not None and img_map.size > 0:
        mask_map = np.max(np.abs(img_map.astype(np.int16) - _as_array(FISH_MODE_COLOR)), axis=2) <= FISH_MODE_TOL
        has_map = bool(np.sum(mask_map) >= FISH_MODE_MIN_PIXELS)

    img_menu = crops.get("menu")
    has_green = False
    if img_menu is not None and img_menu.size > 0:
        mask_green = np.max(np.abs(img_menu.astype(np.int16) - _as_array(FISH_MENU_GREEN_RGB)), axis=2) <= FISH_MENU_TOL
        has_green = bool(np.any(mask_green))

    if not has_map:
        if has_green:
            return FishingModeState.MENU
        else:
            return FishingModeState.MINIGAME
    else:
        return FishingModeState.NORMAL