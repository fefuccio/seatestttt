# scripts/updater.py
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional, Tuple

# Import requests directly; handle import error
try:
    import requests
except ImportError:
    requests = None

from config import APP_VERSION

logger = logging.getLogger(__name__)

GITHUB_REPO = "fefuccio/sea-angler-assist"
EXE_NAME = "Sea Angler Assist.exe"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

class UpdateResult:
    def __init__(
        self,
        has_update: bool,
        latest_version: str = "",
        release_notes: str = "",
        download_url: str = "",
        error: str = "",
    ):
        self.has_update = has_update
        self.latest_version = latest_version
        self.release_notes = release_notes
        self.download_url = download_url
        self.error = error

def _parse_version(v: str) -> Tuple[int, ...]:
    try:
        v = v.lstrip("v").strip()
        parts = tuple(int(x) for x in v.split("."))
        if len(parts) < 3:
            return parts + (0,) * (3 - len(parts))
        return parts
    except (ValueError, AttributeError):
        return (0, 0, 0)

def check_for_updates() -> UpdateResult:
    """Always returns an UpdateResult; error field set on failure."""
    if not getattr(sys, "frozen", False):
        return UpdateResult(has_update=False, error="Running from source, update check skipped")
    if requests is None:
        return UpdateResult(has_update=False, error="requests module not available")
    try:
        response = requests.get(API_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        latest_tag = data.get("tag_name", "v0.0.0")
        if _parse_version(latest_tag) <= _parse_version(APP_VERSION):
            return UpdateResult(has_update=False)
        notes = data.get("body", "No release notes provided.")
        download_url = ""
        for asset in data.get("assets", []):
            if asset.get("name") == EXE_NAME:
                download_url = asset.get("browser_download_url") or ""
                break
        if not download_url:
            return UpdateResult(
                has_update=False,
                error=f"'{EXE_NAME}' not found in latest release assets."
            )
        return UpdateResult(
            has_update=True,
            latest_version=latest_tag,
            release_notes=notes,
            download_url=download_url,
        )
    except Exception as exc:
        logger.debug(f"Update check failed: {exc}")
        return UpdateResult(has_update=False, error=str(exc))

def download_and_apply_update(url: str, log_fn) -> bool:
    if requests is None:
        log_fn("Update failed: requests is unavailable.")
        return False
    if not url:
        log_fn("Update failed: empty download URL.")
        return False
    try:
        log_fn("Downloading update...")
        current_exe = sys.executable
        update_exe = os.path.join(os.path.dirname(current_exe), "SeaAnglerAssist_update.exe")
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with open(update_exe, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        log_fn("Update downloaded. Preparing to install...")
        bat_path = os.path.join(os.path.dirname(current_exe), "updater.bat")
        bat_content = f"""@echo off
setlocal
timeout /t 1 /nobreak >nul
:wait
del /f /q "{current_exe}" >nul 2>&1
if exist "{current_exe}" goto wait
move /y "{update_exe}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
        with open(bat_path, "w", encoding="utf-8") as bat:
            bat.write(bat_content)
        subprocess.Popen(["cmd", "/c", bat_path], creationflags=0x08000000)
        return True
    except Exception as exc:
        log_fn(f"Update failed: {exc}")
        logger.exception("Update failed")
        return False