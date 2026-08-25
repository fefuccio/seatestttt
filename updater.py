"""
GitHub-based Auto-Updater for Sea Angler Assist.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional, Tuple

try:
    import requests

    HAS_REQUESTS = True

except ImportError:
    requests = None
    HAS_REQUESTS = False

from config import APP_VERSION

logger = logging.getLogger(__name__)


GITHUB_REPO = "fefuccio/sea-angler-assist"
EXE_NAME = "Sea Angler Assist.exe"

API_URL = (
    f"https://api.github.com/repos/"
    f"{GITHUB_REPO}/releases/latest"
)


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


def _parse_version(
    v: str,
) -> Tuple[int, ...]:
    try:
        v = (
            v.lstrip("v")
            .strip()
        )

        parts = tuple(
            int(x)
            for x in v.split(".")
        )

        if len(parts) < 3:
            return (
                parts
                + (0,)
                * (
                    3 - len(parts)
                )
            )

        return parts

    except (
        ValueError,
        AttributeError,
    ):
        return (
            0,
            0,
            0,
        )


def check_for_updates() -> Optional[
    UpdateResult
]:
    """
    Check GitHub for a newer release.

    Returns None when running from source or
    when the network dependency isn't available.
    """
    if not getattr(
        sys,
        "frozen",
        False,
    ):
        return None

    if not HAS_REQUESTS:
        return None

    assert requests is not None

    try:
        response = requests.get(
            API_URL,
            timeout=5,
        )

        response.raise_for_status()

        data = response.json()

        latest_tag = data.get(
            "tag_name",
            "v0.0.0",
        )

        if (
            _parse_version(latest_tag)
            <= _parse_version(APP_VERSION)
        ):
            return UpdateResult(
                has_update=False
            )

        notes = data.get(
            "body",
            "No release notes provided.",
        )

        download_url = ""

        for asset in data.get(
            "assets",
            [],
        ):
            if (
                asset.get("name")
                == EXE_NAME
            ):
                download_url = (
                    asset.get(
                        "browser_download_url"
                    )
                    or ""
                )

                break

        if not download_url:
            return UpdateResult(
                has_update=False,
                error=(
                    f"'{EXE_NAME}' not found "
                    f"in the latest release assets."
                ),
            )

        return UpdateResult(
            has_update=True,
            latest_version=latest_tag,
            release_notes=notes,
            download_url=download_url,
        )

    except Exception as exc:
        logger.debug(
            f"Update check failed: {exc}"
        )

        return None


def download_and_apply_update(
    url: str,
    log_fn,
) -> bool:
    """
    Download the replacement executable and
    spawn a batch script to perform the swap.
    """
    if not HAS_REQUESTS:
        log_fn(
            "Update failed: requests is unavailable."
        )
        return False

    assert requests is not None

    if not url:
        log_fn(
            "Update failed: empty download URL."
        )
        return False

    try:
        log_fn(
            "Downloading update..."
        )

        current_exe = sys.executable

        update_exe = os.path.join(
            os.path.dirname(
                current_exe
            ),
            "SeaAnglerAssist_update.exe",
        )

        with requests.get(
            url,
            stream=True,
            timeout=30,
        ) as response:
            response.raise_for_status()

            with open(
                update_exe,
                "wb",
            ) as f:
                for chunk in response.iter_content(
                    chunk_size=8192
                ):
                    if chunk:
                        f.write(chunk)

        log_fn(
            "Update downloaded. "
            "Preparing to install..."
        )

        bat_path = os.path.join(
            os.path.dirname(
                current_exe
            ),
            "updater.bat",
        )

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

        with open(
            bat_path,
            "w",
            encoding="utf-8",
        ) as bat:
            bat.write(
                bat_content
            )

        subprocess.Popen(
            [
                "cmd",
                "/c",
                bat_path,
            ],
            creationflags=0x08000000,
        )

        return True

    except Exception as exc:
        log_fn(
            f"Update failed: {exc}"
        )

        logger.exception(
            "Update failed"
        )

        return False