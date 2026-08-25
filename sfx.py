"""
UI sound-effects helper for Sea Angler Assist.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path

import winsound

from paths import bundled_resource


_SOUNDS_DIR = bundled_resource(
    "sounds"
)

_FLAGS = (
    winsound.SND_FILENAME
    | winsound.SND_ASYNC
    | winsound.SND_NODEFAULT
)


def _sound_enabled() -> bool:
    try:
        from settings import get_settings

        settings = get_settings()

        return bool(
            settings.sound_effects.get()
        )

    except Exception:
        return True


def _close_after_playback(
    alias: str,
    length_ms: int,
) -> None:
    time.sleep(
        length_ms / 1000.0
        + 0.1
    )

    try:
        ctypes.windll.winmm.mciSendStringW(
            f"close {alias}",
            None,
            0,
            0,
        )

    except Exception:
        pass


def _play_mp3_async(
    path: str,
) -> None:
    alias = (
        f"sfx_"
        f"{int(time.time() * 1000)}"
    )

    safe_path = str(
        Path(path).resolve()
    )

    ctypes.windll.winmm.mciSendStringW(
        f'open "{safe_path}" '
        f'type mpegvideo alias {alias}',
        None,
        0,
        0,
    )

    buf = ctypes.create_unicode_buffer(
        256
    )

    ctypes.windll.winmm.mciSendStringW(
        f"status {alias} length",
        buf,
        256,
        0,
    )

    try:
        length_ms = int(
            buf.value
        )
    except ValueError:
        length_ms = 2000

    ctypes.windll.winmm.mciSendStringW(
        f"play {alias} from 0",
        None,
        0,
        0,
    )

    threading.Thread(
        target=_close_after_playback,
        args=(
            alias,
            length_ms,
        ),
        daemon=True,
    ).start()


def play_sfx(
    name: str,
) -> None:
    if not _sound_enabled():
        return

    try:
        wav_path = os.path.join(
            _SOUNDS_DIR,
            f"{name}.wav",
        )

        if os.path.isfile(
            wav_path
        ):
            winsound.PlaySound(
                wav_path,
                _FLAGS,
            )
            return

        mp3_path = os.path.join(
            _SOUNDS_DIR,
            f"{name}.mp3",
        )

        if os.path.isfile(
            mp3_path
        ):
            _play_mp3_async(
                mp3_path
            )

    except Exception:
        pass