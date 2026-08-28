from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Dict, Optional

import numpy as np
import psutil

from config import get_target_exe

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32

# ---------------------------------------------------------------------------
# Keyboard constants
# ---------------------------------------------------------------------------
VK_SPACE = 0x20
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_ALT = 0x12

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL

# ---------------------------------------------------------------------------
# Global hotkeys
# ---------------------------------------------------------------------------
class GlobalHotkeyManager:
    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.hotkeys: Dict[int, Callable[[], None]] = {}
        self.next_id = 1

    def register(self, vk_code: int, callback: Callable[[], None]) -> Optional[int]:
        if not vk_code:
            return None
        hotkey_id = self.next_id
        self.next_id += 1
        if user32.RegisterHotKey(self.hwnd, hotkey_id, MOD_NOREPEAT, vk_code):
            self.hotkeys[hotkey_id] = callback
            return hotkey_id
        return None

    def unregister(self, hotkey_id: int) -> None:
        if hotkey_id not in self.hotkeys:
            return
        user32.UnregisterHotKey(self.hwnd, hotkey_id)
        del self.hotkeys[hotkey_id]

    def unregister_all(self) -> None:
        for hotkey_id in list(self.hotkeys):
            self.unregister(hotkey_id)

def get_vk_code(key_str: str) -> int:
    if not key_str:
        return 0
    key_str = key_str.strip().upper()
    if key_str.startswith("F") and key_str[1:].isdigit():
        f_num = int(key_str[1:])
        if 1 <= f_num <= 24:
            return 0x6F + f_num
    if len(key_str) == 1 and key_str.isalpha():
        return ord(key_str)
    if len(key_str) == 1 and key_str.isdigit():
        return ord(key_str)
    return 0

# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------
def set_window_topmost(hwnd: int, topmost: bool) -> None:
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    flag = ctypes.c_void_p(-1) if topmost else ctypes.c_void_p(-2)
    user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

def is_running_as_admin() -> bool:
    try:
        return shell32.IsUserAnAdmin() != 0
    except AttributeError:
        return False

def relaunch_as_admin() -> bool:
    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    else:
        executable = sys.executable
        params = f'"{os.path.abspath(sys.argv[0])}" ' + " ".join(f'"{arg}"' for arg in sys.argv[1:])
    try:
        ret = shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(ret) > 32
    except Exception:
        logger.exception("Failed to relaunch as administrator")
        return False

def set_process_dpi_aware() -> None:
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass

# ---------------------------------------------------------------------------
# Process / window lookup
# ---------------------------------------------------------------------------
def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))

def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

_PID_CACHE: dict = {"exe": None, "pids": set(), "time": 0.0}
_PID_CACHE_LOCK = threading.Lock()
_PID_CACHE_TTL = 1.0

def _find_pids_for_exe(exe_path: str) -> set[int]:
    target = _norm_path(exe_path)
    now = time.monotonic()
    with _PID_CACHE_LOCK:
        if _PID_CACHE["exe"] == target and (now - _PID_CACHE["time"]) < _PID_CACHE_TTL:
            return set(_PID_CACHE["pids"])
    matching_pids = set()
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            exe = proc.info["exe"]
            if exe and _norm_path(exe) == target:
                matching_pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    with _PID_CACHE_LOCK:
        _PID_CACHE["exe"] = target
        _PID_CACHE["pids"] = set(matching_pids)
        _PID_CACHE["time"] = now
    return matching_pids

def invalidate_pid_cache() -> None:
    with _PID_CACHE_LOCK:
        _PID_CACHE["exe"] = None
        _PID_CACHE["pids"] = set()
        _PID_CACHE["time"] = 0.0

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

def find_hwnd_by_pid(pid: int):
    if not pid:
        return None
    found = {"hwnd": None}
    @EnumWindowsProc
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if _window_pid(hwnd) == pid:
            found["hwnd"] = hwnd
            return False
        return True
    user32.EnumWindows(enum_proc, 0)
    return found["hwnd"]

def find_hwnd_by_exe(exe_path: str):
    pids = _find_pids_for_exe(exe_path)
    if not pids:
        return None
    for pid in pids:
        # Check if process still exists
        if not psutil.pid_exists(pid):
            continue
        hwnd = find_hwnd_by_pid(pid)
        if hwnd:
            return hwnd
    # Cache might be stale; invalidate and retry
    invalidate_pid_cache()
    pids = _find_pids_for_exe(exe_path)
    for pid in pids:
        if not psutil.pid_exists(pid):
            continue
        hwnd = find_hwnd_by_pid(pid)
        if hwnd:
            return hwnd
    return None

def focus_hwnd(hwnd) -> bool:
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached = []
    try:
        if user32.AttachThreadInput(current_thread, fg_thread, True):
            attached.append((current_thread, fg_thread))
        if user32.AttachThreadInput(current_thread, target_thread, True):
            attached.append((current_thread, target_thread))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        return True
    finally:
        for current, target in reversed(attached):
            user32.AttachThreadInput(current, target, False)

def is_target_window_focused() -> bool:
    hwnd = find_hwnd_by_exe(get_target_exe())
    if not hwnd:
        return False
    return user32.GetForegroundWindow() == hwnd

# ---------------------------------------------------------------------------
# Window capture (with BitBlt fallback)
# ---------------------------------------------------------------------------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]

def print_window_to_rgb_array(hwnd):
    if not hwnd:
        return None
    if user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    hwnd_dc = user32.GetDC(hwnd)
    if not hwnd_dc:
        return None
    mfc_dc = None
    bitmap = None
    try:
        mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mfc_dc:
            return None
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        if not bitmap:
            return None
        previous = gdi32.SelectObject(mfc_dc, bitmap)
        try:
            # Try PrintWindow first
            result = user32.PrintWindow(hwnd, mfc_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
            if result != 1:
                result = user32.PrintWindow(hwnd, mfc_dc, 0)
            if result != 1:
                # Fallback: BitBlt with CAPTUREBLT
                result = gdi32.BitBlt(mfc_dc, 0, 0, width, height, hwnd_dc, 0, 0, 0x40000000)  # CAPTUREBLT
                if not result:
                    return None
            bmpinfo = BITMAPINFO()
            bmpinfo.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmpinfo.bmiHeader.biWidth = width
            bmpinfo.bmiHeader.biHeight = -height
            bmpinfo.bmiHeader.biPlanes = 1
            bmpinfo.bmiHeader.biBitCount = 32
            bmpinfo.bmiHeader.biCompression = 0
            buffer_size = width * height * 4
            buffer = ctypes.create_string_buffer(buffer_size)
            lines = gdi32.GetDIBits(mfc_dc, bitmap, 0, height, buffer, ctypes.byref(bmpinfo), 0)
            if lines != height:
                return None
            img = np.frombuffer(buffer.raw, dtype=np.uint8).reshape((height, width, 4))
            img_rgb = img[:, :, :3][:, :, ::-1]
            return np.ascontiguousarray(img_rgb)
        finally:
            if previous:
                gdi32.SelectObject(mfc_dc, previous)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mfc_dc:
            gdi32.DeleteDC(mfc_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

# ---------------------------------------------------------------------------
# Keyboard injection
# ---------------------------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ki", KEYBDINPUT),
    ]

VK_CODE_MAP = {
    "space": VK_SPACE,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "escape": VK_ESCAPE,
    "esc": VK_ESCAPE,
    "tab": VK_TAB,
    "shift": VK_SHIFT,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "alt": VK_ALT,
}

def send_key_down(vk_code: int) -> bool:
    if not vk_code:
        return False
    ki = KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
    inp = INPUT(type=INPUT_KEYBOARD, ki=ki)
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

def send_key_up(vk_code: int) -> bool:
    if not vk_code:
        return False
    ki = KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
    inp = INPUT(type=INPUT_KEYBOARD, ki=ki)
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

def get_virtual_key_code(key_name: str) -> int:
    key_name = key_name.strip().lower()
    if key_name in VK_CODE_MAP:
        return VK_CODE_MAP[key_name]
    if len(key_name) == 1:
        return ord(key_name.upper())
    return 0