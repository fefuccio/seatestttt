import json
import logging
import os
import shutil
from functools import lru_cache
from typing import List, Optional

import numpy as np

from paths import (
    bundled_resource,
    ensure_writable_copy,
    writable_path,
)

logger = logging.getLogger(__name__)

APP_VERSION = "0.0.1"

# ---------------------------------------------------------------------------
# Window / UI
# ---------------------------------------------------------------------------
WINDOW_W = 480
WINDOW_H = 420
DEBUG_WINDOW_H = 720
WINDOW_X_PCT = 0.01
WINDOW_Y_PCT = 0.99
SIDEBAR_WIDTH = 170
DROPDOWN_WIDTH = 220
GEAR_SIZE = 20
BAIT_LIST_MAX_H = 240
BAIT_LIST_EMPTY_H = 40
BAIT_LIST_FALLBACK_ITEM_H = 32
CONTAINER_PADDING = 10

# ---------------------------------------------------------------------------
# Game target
# ---------------------------------------------------------------------------
DEFAULT_GAME_EXE = ""

def get_target_exe() -> str:
    try:
        from settings import get_settings
        path = get_settings().game_exe_path.get()
        if path:
            return path
    except Exception:
        pass
    return DEFAULT_GAME_EXE

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
CAST_WAIT = 4
CAST_POLL = 0.5
CAST_POLL_MAX = 20
POST_MINIGAME_WAIT = 1
POST_RESULT_SETTLE = 0.5
RESULT_POLL = 0.5
RESULT_POLL_MAX = 20
RESULT_DISMISS_WAIT = 1
BAR_WAIT = 0.25
BAR_RETRY_MAX = 10
START_IGNORE_SECS = 0.2
TAP_DURATION = 0.1
INPUT_WAIT = 0.5
POST_CAST_SETTLE = 0.5
HOOK_GRACE_SECS = 3.5
RECOVER_WAIT = 2.0
FOCUS_SETTLE = 0.2

# ---------------------------------------------------------------------------
# Capture regions
# ---------------------------------------------------------------------------
DETECTION_PARAMS = {
    "bar": {"x_min": 0.30, "x_max": 0.70, "y_min": 0.05, "y_max": 0.10},
    "line": {"x_min": 0.30, "x_max": 0.70, "y_min": 0.05, "y_max": 0.10},
    "cast": {"x_min": 0.9, "x_max": 0.95, "y_min": 0.875, "y_max": 0.925},
    "result": {"x_min": 0.59, "x_max": 0.63, "y_min": 0.05, "y_max": 0.15},
    "bait_empty": {"x_min": 0.40, "x_max": 0.60, "y_min": 0.47, "y_max": 0.53},
    "fish_mode": {"x_min": 0.01, "x_max": 0.15, "y_min": 0.01, "y_max": 0.15},
    "fish_menu": {"x_min": 0.64, "x_max": 0.98, "y_min": 0.50, "y_max": 0.52},
}

BAR_X_MIN, BAR_X_MAX = DETECTION_PARAMS["bar"]["x_min"], DETECTION_PARAMS["bar"]["x_max"]
BAR_Y_MIN, BAR_Y_MAX = DETECTION_PARAMS["bar"]["y_min"], DETECTION_PARAMS["bar"]["y_max"]
LINE_X_MIN, LINE_X_MAX = DETECTION_PARAMS["line"]["x_min"], DETECTION_PARAMS["line"]["x_max"]
LINE_Y_MIN, LINE_Y_MAX = DETECTION_PARAMS["line"]["y_min"], DETECTION_PARAMS["line"]["y_max"]
CAST_X_MIN, CAST_X_MAX = DETECTION_PARAMS["cast"]["x_min"], DETECTION_PARAMS["cast"]["x_max"]
CAST_Y_MIN, CAST_Y_MAX = DETECTION_PARAMS["cast"]["y_min"], DETECTION_PARAMS["cast"]["y_max"]
RESULT_X_MIN, RESULT_X_MAX = DETECTION_PARAMS["result"]["x_min"], DETECTION_PARAMS["result"]["x_max"]
RESULT_Y_MIN, RESULT_Y_MAX = DETECTION_PARAMS["result"]["y_min"], DETECTION_PARAMS["result"]["y_max"]
BAIT_EMPTY_X_MIN, BAIT_EMPTY_X_MAX = DETECTION_PARAMS["bait_empty"]["x_min"], DETECTION_PARAMS["bait_empty"]["x_max"]
BAIT_EMPTY_Y_MIN, BAIT_EMPTY_Y_MAX = DETECTION_PARAMS["bait_empty"]["y_min"], DETECTION_PARAMS["bait_empty"]["y_max"]
FISH_MODE_X_MIN, FISH_MODE_X_MAX = DETECTION_PARAMS["fish_mode"]["x_min"], DETECTION_PARAMS["fish_mode"]["x_max"]
FISH_MODE_Y_MIN, FISH_MODE_Y_MAX = DETECTION_PARAMS["fish_mode"]["y_min"], DETECTION_PARAMS["fish_mode"]["y_max"]
FISH_MENU_X_MIN, FISH_MENU_X_MAX = DETECTION_PARAMS["fish_menu"]["x_min"], DETECTION_PARAMS["fish_menu"]["x_max"]
FISH_MENU_Y_MIN, FISH_MENU_Y_MAX = DETECTION_PARAMS["fish_menu"]["y_min"], DETECTION_PARAMS["fish_menu"]["y_max"]

# ---------------------------------------------------------------------------
# Detection colors and tolerances
# ---------------------------------------------------------------------------
BAR_RGB = np.array([0x34, 0xDA, 0xB3], dtype=np.int16)
LINE_RGB = np.array([0xFD, 0xF9, 0x92], dtype=np.int16)
CAST_RGB = np.array([0x20, 0x7C, 0xFF], dtype=np.int16)
RESULT_RGB = np.array([0xB9, 0xE7, 0x04], dtype=np.int16)
PINK_RGB = np.array([0xFA, 0x46, 0x8E], dtype=np.int16)
GOLD_RGB = np.array([0xF9, 0xC3, 0x20], dtype=np.int16)
FISH_MODE_COLOR = np.array([0xFF, 0xEF, 0xB8], dtype=np.int16)
FISH_MENU_GREEN_RGB = np.array([0x21, 0xA2, 0x8F], dtype=np.int16)

BAR_TOL = 25
LINE_TOL = 20
CAST_TOL = 15
RESULT_TOL = 15
RESULT_REQUIRED = 20
FISH_MODE_TOL = 3
FISH_MODE_MIN_PIXELS = 20
FISH_MENU_TOL = 5

BAIT_EMPTY_WHITE = np.array([0xFF, 0xFF, 0xFF], dtype=np.int16)
BAIT_EMPTY_DARK = np.array([0x00, 0x00, 0x00], dtype=np.int16)
BAIT_EMPTY_TOL = 40
BAIT_EMPTY_MIN_WHITE_RATIO = 0.15
BAIT_EMPTY_MIN_DARK_RATIO = 0.5

BAIT_COLOR_TOL = 30
CURSOR_MIN_PIXELS = 20
BAIT_MENU_OPEN_SETTLE = 0.6
BAIT_INPUT_WAIT = 0.1
BAIT_SWITCH_WAIT = 0.2
BAIT_MISS_CONFIRM_FRAMES = 3

# ---------------------------------------------------------------------------
# Reeling
# ---------------------------------------------------------------------------
REEL_SPEED_PX_PER_MS = 0.322
REEL_CENTER_DEADZONE = 8
REEL_COAST_ZONE = 16
REEL_MAX_HOLD_TIME = 0.080
REEL_MIN_HOLD_TIME = 0.030
REEL_SAFETY_FACTOR = 0.65
REEL_POLL_DELAY = 0.025

# ---------------------------------------------------------------------------
# Controller input
# ---------------------------------------------------------------------------
KEY_LEFT = "L2"
KEY_RIGHT = "R2"
KEY_CAST = "CROSS"
KEY_RESULT = "CROSS"
KEY_MENU = "TRIANGLE"
KEY_CANCEL = "CIRCLE"
KEY_DPAD_L = "DPAD_LEFT"
KEY_DPAD_R = "DPAD_RIGHT"

BOT_KEYS = {
    KEY_LEFT, KEY_RIGHT, KEY_CAST, KEY_RESULT,
    KEY_MENU, KEY_CANCEL, KEY_DPAD_L, KEY_DPAD_R,
}

# ---------------------------------------------------------------------------
# Rarity
# ---------------------------------------------------------------------------
RARITY_COLORS = {
    "green": "#21A28F",
    "blue": "#3C69FF",
    "purple": "#E741BD",
    "orange": "#FFB610",
}
RARITY_ORDER = ["green", "blue", "purple", "orange"]

# ---------------------------------------------------------------------------
# Baits (cached with lru_cache)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_baits() -> List[dict]:
    bundled_path = bundled_resource("baits.json")
    writable = writable_path("baits.json")
    try:
        with open(bundled_path, "r", encoding="utf-8") as f:
            bundled_data = json.load(f)
    except Exception:
        bundled_data = []

    needs_update = False
    try:
        with open(writable, "r", encoding="utf-8") as f:
            writable_data = json.load(f)
        if writable_data != bundled_data:
            needs_update = True
    except FileNotFoundError:
        needs_update = True
    except Exception:
        needs_update = True

    if needs_update and bundled_path != writable:
        try:
            os.makedirs(os.path.dirname(writable), exist_ok=True)
            shutil.copyfile(bundled_path, writable)
        except Exception as exc:
            logger.warning(f"Failed to update writable baits.json: {exc}")

    try:
        with open(writable, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list) and data:
            return data
    except Exception as exc:
        logger.warning(f"Failed to load baits from {writable}: {exc}")

    return [
        {"name": "Universal Bait", "rarity": "orange"},
        {"name": "Mixed Grain Bait", "rarity": "green"},
    ]

def get_baits() -> List[dict]:
    return _load_baits()

# ---------------------------------------------------------------------------
# Debug screenshots
# ---------------------------------------------------------------------------
DEBUG_NO_BAIT_SCREENSHOT = False

# ---------------------------------------------------------------------------
# Controller fallback setting
# ---------------------------------------------------------------------------
ALLOW_CONTROLLER_FALLBACK = True   # can be overridden by settings