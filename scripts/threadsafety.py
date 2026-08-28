"""Marshall arbitrary callables onto the main Qt thread."""
from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

log = logging.getLogger(__name__)


class _MainDispatcher(QObject):
    """Singleton living on the main thread; executes queued lambdas."""

    _executeRequested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        # Always queued: even same-thread calls go through the event loop,
        # guaranteeing reentrancy-free execution.
        self._executeRequested.connect(
            self._execute, Qt.ConnectionType.QueuedConnection
        )

    @Slot(object)
    def _execute(self, fn) -> None:
        try:
            fn()
        except Exception:
            log.error("queued main-thread task failed\n%s",
                      traceback.format_exc())


_dispatcher: _MainDispatcher | None = None


def install_main_dispatcher() -> None:
    """Call once, on the main thread, during app boot."""
    global _dispatcher
    _dispatcher = _MainDispatcher()


def on_main_thread(fn) -> None:
    """Run *fn* on the main Qt thread. Safe to call from any thread."""
    assert _dispatcher is not None, (
        "on_main_thread() used before install_main_dispatcher()")
    if QThread.currentThread() is _dispatcher.thread():
        QTimer.singleShot(0, fn)
    else:
        _dispatcher._executeRequested.emit(fn)
