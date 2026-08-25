"""Path resolution for bundled read-only vs writable APPDATA files."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import List

APP_NAME = "SeaAnglerAssist"

logger = logging.getLogger(__name__)


def is_frozen() -> bool:
    """
    Check for PyInstaller or Nuitka.
    """
    main_module = sys.modules.get("__main__")

    return bool(
        getattr(
            sys,
            "frozen",
            False,
        )
        or (
            main_module is not None
            and "__compiled__"
            in dir(main_module)
        )
    )


def bundled_root() -> str:
    """
    Resolve the root containing bundled resources.
    """
    meipass = getattr(
        sys,
        "_MEIPASS",
        None,
    )

    if meipass:
        return meipass

    return os.path.dirname(
        os.path.abspath(__file__)
    )


def bundled_resource(
    *parts: str,
) -> str:
    return os.path.join(
        bundled_root(),
        *parts,
    )


def writable_dir() -> str:
    candidates: List[str] = []

    appdata = os.environ.get(
        "APPDATA"
    )

    if appdata:
        candidates.append(
            os.path.join(
                appdata,
                APP_NAME,
            )
        )

    home = (
        os.environ.get("HOME")
        or os.path.expanduser("~")
    )

    if home:
        candidates.append(
            os.path.join(
                home,
                f".{APP_NAME.lower()}",
            )
        )

    candidates.append(
        bundled_root()
    )

    for path in candidates:
        parent = (
            os.path.dirname(path)
            or "."
        )

        if not os.path.isdir(parent):
            try:
                os.makedirs(
                    parent,
                    exist_ok=True,
                )
            except OSError:
                continue

        if not os.access(
            parent,
            os.W_OK,
        ):
            continue

        try:
            os.makedirs(
                path,
                exist_ok=True,
            )

            return path

        except OSError:
            continue

    return os.getcwd()


def writable_path(
    filename: str,
) -> str:
    return os.path.join(
        writable_dir(),
        filename,
    )


def ensure_writable_copy(
    filename: str,
) -> str:
    live = writable_path(
        filename
    )

    if not os.path.exists(live):
        bundled = bundled_resource(
            filename
        )

        if os.path.exists(bundled):
            try:
                shutil.copy2(
                    bundled,
                    live,
                )

                logger.info(
                    f"Seeded writable copy: {live}"
                )

            except OSError as exc:
                logger.warning(
                    f"Failed to copy "
                    f"{bundled} -> {live}: {exc}"
                )

    return live