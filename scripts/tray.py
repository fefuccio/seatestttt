from __future__ import annotations

from PySide6.QtCore import (
    QObject,
    QPoint,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QIcon,
    QPainter,
)
from PySide6.QtWidgets import (
    QMenu,
    QSystemTrayIcon,
)

from ui import ICON_PATH


class TrayManager(QObject):
    _BADGE_RUNNING = QColor(
        "#FA468E"
    )

    _BADGE_IDLE = QColor(
        "#64748B"
    )

    def __init__(
        self,
        main_window,
    ) -> None:
        super().__init__(
            main_window
        )

        self.window = main_window

        self._icon_idle = QIcon(
            ICON_PATH
        )

        self._icon_running = (
            self._build_badged_icon(
                self._icon_idle,
                self._BADGE_RUNNING,
            )
        )

        self.tray = QSystemTrayIcon(
            self._icon_idle,
            main_window,
        )

        self.tray.setObjectName(
            "TrayIcon"
        )

        self.tray.setToolTip(
            self._format_tooltip(
                False,
                "Idle",
                0,
            )
        )

        self._build_menu()

        self.tray.activated.connect(
            self._on_activated
        )

        self.tray.show()

    def _build_menu(
        self,
    ) -> None:
        menu = QMenu(
            self.window
        )

        menu.setObjectName(
            "TrayMenu"
        )

        menu.setStyleSheet(
            self.window.QSS
        )

        self.show_action = QAction(
            "Hide Window",
            menu,
        )

        self.show_action.triggered.connect(
            self.toggle_visibility
        )

        menu.addAction(
            self.show_action
        )

        self.toggle_action = QAction(
            "Start",
            menu,
        )

        self.toggle_action.triggered.connect(
            self.window.toggle
        )

        menu.addAction(
            self.toggle_action
        )

        menu.addSeparator()

        quit_action = QAction(
            "Quit",
            menu,
        )

        quit_action.triggered.connect(
            self.window.quit_application
        )

        menu.addAction(
            quit_action
        )

        self.tray.setContextMenu(
            menu
        )

    def _on_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if (
            reason
            == QSystemTrayIcon.ActivationReason.Trigger
        ):
            self.toggle_visibility()

    def toggle_visibility(
        self,
    ) -> None:
        win = self.window

        if win.isVisible():
            win.hide()

        else:
            win.show()

            win.setWindowState(
                win.windowState()
                & ~Qt.WindowState.WindowMinimized
            )

            win.raise_()
            win.activateWindow()

        self.refresh_visibility_label()

    def refresh_visibility_label(
        self,
    ) -> None:
        self.show_action.setText(
            "Hide Window"
            if self.window.isVisible()
            else "Show Window"
        )

    def update_state(
        self,
        running: bool,
        status: str,
        fish_count: int,
    ) -> None:
        self.tray.setIcon(
            self._icon_running
            if running
            else self._icon_idle
        )

        self.tray.setToolTip(
            self._format_tooltip(
                running,
                status,
                fish_count,
            )
        )

        self.toggle_action.setText(
            "Stop"
            if running
            else "Start"
        )

        self.refresh_visibility_label()

    @staticmethod
    def _format_tooltip(
        running: bool,
        status: str,
        fish_count: int,
    ) -> str:
        label = (
            "Running"
            if running
            else "Idle"
        )

        return (
            "Sea Angler Assist · "
            f"{label} | {status} | "
            f"Fish: {fish_count}"
        )

    @staticmethod
    def _build_badged_icon(
        base: QIcon,
        color: QColor,
    ) -> QIcon:
        sizes = base.availableSizes()

        if not sizes:
            return base

        size = max(
            sizes,
            key=lambda s:
                s.width()
                * s.height(),
        )

        pm = base.pixmap(
            size
        )

        if pm.isNull():
            return base

        painter = QPainter(pm)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        dot_r = max(
            5,
            min(
                size.width(),
                size.height(),
            )
            // 5,
        )

        margin = 2

        center = QPoint(
            size.width()
            - dot_r
            - margin,
            size.height()
            - dot_r
            - margin,
        )

        painter.setPen(
            QColor("#0B0E14")
        )

        painter.setBrush(
            QBrush(color)
        )

        painter.drawEllipse(
            center,
            dot_r,
            dot_r,
        )

        painter.end()

        return QIcon(pm)
