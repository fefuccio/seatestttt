# scripts/controller.py
from __future__ import annotations

import logging
import time
from typing import Any, Optional

try:
    import vgamepad as vg
except ImportError:
    vg = None

# Import from config; define fallback if missing
try:
    from config import TAP_DURATION, ALLOW_CONTROLLER_FALLBACK
except ImportError:
    # Fallback values if config is not fully loaded
    TAP_DURATION = 0.1
    ALLOW_CONTROLLER_FALLBACK = True

from win32_utils import (
    send_key_down,
    send_key_up,
    get_virtual_key_code,
)

logger = logging.getLogger(__name__)

BUTTON_NAME_MAP = {
    "CROSS": "DS4_BUTTON_CROSS",
    "CIRCLE": "DS4_BUTTON_CIRCLE",
    "TRIANGLE": "DS4_BUTTON_TRIANGLE",
    "L2": "DS4_BUTTON_TRIGGER_LEFT",
    "R2": "DS4_BUTTON_TRIGGER_RIGHT",
    "DPAD_LEFT": "DS4_BUTTON_DPAD_LEFT",
    "DPAD_RIGHT": "DS4_BUTTON_DPAD_RIGHT",
}

FALLBACK_BUTTON_MAP = {
    "CROSS": "f",
    "CIRCLE": None,
    "TRIANGLE": "e",
    "L2": "a",
    "R2": "d",
    "DPAD_LEFT": None,
    "DPAD_RIGHT": None,
}

class ControllerInput:
    def __init__(self) -> None:
        self.gamepad: Optional[Any] = None
        self.use_gamepad = False
        self.error: Optional[Exception] = None

        if vg is not None:
            try:
                self.gamepad = vg.VDS4Gamepad()
                self.gamepad.reset()
                self.gamepad.update()
                self.use_gamepad = True
            except Exception as exc:
                self.error = exc
                self.gamepad = None
                self.use_gamepad = False
        else:
            self.error = ImportError("vgamepad module not installed")

    @property
    def status(self) -> str:
        if self.use_gamepad:
            return "Gamepad"
        if self.error is not None:
            return f"Error: {self.error}"
        return "Keyboard fallback"

    @staticmethod
    def _normalize_button_name(name: str) -> str:
        return name.strip().upper()

    def _get_gamepad_button(self, name: str):
        if not self.use_gamepad:
            return None
        token = self._normalize_button_name(name)
        token = BUTTON_NAME_MAP.get(token, token)
        button_class = getattr(vg, "DS4_BUTTONS", None) or getattr(vg, "DS4_BUTTON", None)
        if button_class is None:
            return None
        return getattr(button_class, token, None)

    def _get_fallback_key(self, name: str) -> Optional[str]:
        token = self._normalize_button_name(name)
        return FALLBACK_BUTTON_MAP.get(token)

    def _use_analog_for_dpad(self, token: str, duration: float) -> bool:
        # Prefer digital DPAD if available
        if not (self.use_gamepad and self.gamepad is not None):
            return False
        if "DPAD" in token:
            button = self._get_gamepad_button(token)
            if button is not None:
                return False
            if "RIGHT" in token:
                x_value = 1.0
            elif "LEFT" in token:
                x_value = -1.0
            else:
                return False
            self.gamepad.left_joystick_float(x_value_float=x_value, y_value_float=0.0)
            self.gamepad.update()
            time.sleep(duration)
            self.gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
            self.gamepad.update()
            return True
        return False

    def press(self, name: str) -> None:
        if not ALLOW_CONTROLLER_FALLBACK and not self.use_gamepad:
            logger.warning("Controller fallback disabled and gamepad unavailable")
            return
        token = self._normalize_button_name(name)
        if self.use_gamepad and self.gamepad is not None:
            button = self._get_gamepad_button(token)
            if button is not None:
                self.gamepad.press_button(button=button)
                self.gamepad.update()
                return
        fallback = self._get_fallback_key(token)
        if fallback is None:
            return
        vk_code = get_virtual_key_code(fallback)
        if vk_code:
            send_key_down(vk_code)

    def release(self, name: str) -> None:
        if not ALLOW_CONTROLLER_FALLBACK and not self.use_gamepad:
            return
        token = self._normalize_button_name(name)
        if self.use_gamepad and self.gamepad is not None:
            button = self._get_gamepad_button(token)
            if button is not None:
                self.gamepad.release_button(button=button)
                self.gamepad.update()
                return
        fallback = self._get_fallback_key(token)
        if fallback is None:
            return
        vk_code = get_virtual_key_code(fallback)
        if vk_code:
            send_key_up(vk_code)

    def tap(self, name: str, duration: float = TAP_DURATION) -> None:
        if not ALLOW_CONTROLLER_FALLBACK and not self.use_gamepad:
            logger.warning("Controller fallback disabled and gamepad unavailable")
            return
        token = self._normalize_button_name(name)
        if self._use_analog_for_dpad(token, duration):
            return
        if self.use_gamepad and self.gamepad is not None:
            button = self._get_gamepad_button(token)
            if button is not None:
                self.gamepad.press_button(button=button)
                self.gamepad.update()
                time.sleep(duration)
                self.gamepad.release_button(button=button)
                self.gamepad.update()
                return
        fallback = self._get_fallback_key(token)
        if fallback is None:
            return
        vk_code = get_virtual_key_code(fallback)
        if not vk_code:
            return
        send_key_down(vk_code)
        time.sleep(duration)
        send_key_up(vk_code)

    def release_all(self) -> None:
        if self.use_gamepad and self.gamepad is not None:
            try:
                self.gamepad.reset()
                self.gamepad.update()
            except Exception:
                pass
        for name in ("L2", "R2", "CROSS", "CIRCLE", "TRIANGLE", "DPAD_LEFT", "DPAD_RIGHT"):
            try:
                self.release(name)
            except Exception:
                logger.exception("Failed to release %s", name)