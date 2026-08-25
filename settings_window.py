from __future__ import annotations

import math
import os
import re
from typing import List, Optional

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation,
    QRectF, QModelIndex, QSize, QRect, QPointF, QAbstractAnimation, QByteArray,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QBrush, QPainter, QPen, QPainterPath,
    QLinearGradient, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QListView, QRadioButton,
    QStackedWidget, QVBoxLayout, QWidget, QGraphicsOpacityEffect,
    QStyledItemDelegate, QStyleOptionViewItem,
)
import mss

from config import (
    get_baits, RARITY_COLORS, WINDOW_H, WINDOW_W, SIDEBAR_WIDTH,
    BAIT_LIST_MAX_H, BAIT_LIST_EMPTY_H, BAIT_LIST_FALLBACK_ITEM_H,
    CONTAINER_PADDING,
)
from paths import bundled_resource
from settings import Settings
import ui
from widgets import (
    CHECK_URL as _CHECK_URL,
    HotkeyButton, PolishedButton, FadeInDialog,
    SwitchButton, FONT_FAMILY,
    AnimatedCheckBox,
)
from win32_utils import is_running_as_admin


# ---------------------------------------------------------------------------
# Sidebar constants
# ---------------------------------------------------------------------------
SIDEBAR_ROW_H = 44
SIDEBAR_ICON_LEFT = 16
SIDEBAR_LABEL_LEFT = 46
SIDEBAR_TEXT_Y_OFFSET = -2
SIDEBAR_PILL_MARGIN_X = 8
SIDEBAR_PILL_MARGIN_Y = 6
SIDEBAR_ICON_SIZE = 18

_SVG_FILES = {
    "General": "general.svg",
    "Alerts": "alerts.svg",
    "Bait": "baits.svg",
    "Capture": "capture.svg",
    "Hotkeys": "hotkeys.svg",
}
_SVG_CACHE: dict = {}


def _load_svg_silhouette(name: str, size: int):
    """Load an SVG icon as a tightly cropped white silhouette, cached."""
    size = max(1, int(size))
    key = f"{name}_{size}"
    if key in _SVG_CACHE:
        return _SVG_CACHE[key]

    filename = _SVG_FILES.get(name)
    if filename is None:
        _SVG_CACHE[key] = None
        return None

    filepath = os.path.join(bundled_resource("ui"), filename)
    if not os.path.exists(filepath):
        _SVG_CACHE[key] = None
        return None

    try:
        from PySide6.QtSvg import QSvgRenderer
        if QSvgRenderer is None:
            _SVG_CACHE[key] = None
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            svg_data = f.read()

        svg_data = re.sub(
            r'fill="(?!none)[^"]*"', 'fill="#FFFFFF"',
            svg_data, flags=re.IGNORECASE,
        )
        svg_data = re.sub(
            r'fill:\s*(?!none)#?[0-9a-fA-F]+', 'fill:#FFFFFF',
            svg_data, flags=re.IGNORECASE,
        )

        renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
        if not renderer.isValid():
            _SVG_CACHE[key] = None
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        bounds = QRectF(0, 0, size, size)
        renderer.render(painter, bounds)
        painter.end()

        image = pixmap.toImage()
        x_min = image.width()
        y_min = image.height()
        x_max = -1
        y_max = -1
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    x_min = min(x_min, x)
                    y_min = min(y_min, y)
                    x_max = max(x_max, x)
                    y_max = max(y_max, y)

        if x_max >= 0:
            cropped = pixmap.copy(
                x_min, y_min,
                x_max - x_min + 1, y_max - y_min + 1,
            )
            _SVG_CACHE[key] = cropped
            return cropped

        # SVG rendered no visible content — cache None
        # so _draw_sidebar_glyph falls back to _draw_painted_glyph
        _SVG_CACHE[key] = None
        return None

    except Exception:
        _SVG_CACHE[key] = None
        return None


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _draw_painted_glyph(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Draw a tiny fallback line icon."""
    painter.save()
    pen = QPen(color)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx = rect.center().x()
    cy = rect.center().y()
    s = rect.width() / 2.0

    if name == "General":
        r = s * 0.55
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawEllipse(QPointF(cx, cy), r * 0.35, r * 0.35)
        for i in range(6):
            angle = math.radians(i * 60)
            x1 = cx + math.cos(angle) * (r + 1.5)
            y1 = cy + math.sin(angle) * (r + 1.5)
            x2 = cx + math.cos(angle) * (r + 4.0)
            y2 = cy + math.sin(angle) * (r + 4.0)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    elif name == "Alerts":
        path = QPainterPath()
        path.moveTo(cx - s * 0.55, cy + s * 0.35)
        path.lineTo(cx - s * 0.55, cy)
        path.arcTo(
            QRectF(cx - s * 0.55, cy - s * 0.85, s * 1.1, s * 1.1),
            180, -180,
        )
        path.lineTo(cx + s * 0.55, cy + s * 0.35)
        path.lineTo(cx - s * 0.55, cy + s * 0.35)
        painter.drawPath(path)
        painter.drawLine(
            QPointF(cx - s * 0.28, cy + s * 0.62),
            QPointF(cx + s * 0.28, cy + s * 0.62),
        )

    elif name == "Bait":
        path = QPainterPath()
        path.moveTo(cx - s * 0.7, cy)
        path.cubicTo(
            cx - s * 0.3, cy - s * 0.65,
            cx + s * 0.35, cy - s * 0.5,
            cx + s * 0.65, cy,
        )
        path.cubicTo(
            cx + s * 0.35, cy + s * 0.5,
            cx - s * 0.3, cy + s * 0.65,
            cx - s * 0.7, cy,
        )
        painter.drawPath(path)

        tail = QPainterPath()
        tail.moveTo(cx + s * 0.55, cy - s * 0.05)
        tail.lineTo(cx + s * 0.95, cy - s * 0.35)
        tail.moveTo(cx + s * 0.55, cy + s * 0.05)
        tail.lineTo(cx + s * 0.95, cy + s * 0.35)
        painter.drawPath(tail)

        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(cx - s * 0.42, cy - s * 0.05), 1.0, 1.0)

    elif name == "Capture":
        painter.drawRoundedRect(
            QRectF(cx - s * 0.8, cy - s * 0.55, s * 1.6, s * 1.1),
            2.0, 2.0,
        )
        painter.drawEllipse(QPointF(cx, cy), s * 0.32, s * 0.32)
        painter.drawLine(
            QPointF(cx - s * 0.28, cy - s * 0.55),
            QPointF(cx - s * 0.1, cy - s * 0.55),
        )

    elif name == "Hotkeys":
        painter.drawRoundedRect(
            QRectF(cx - s * 0.8, cy - s * 0.6, s * 1.6, s * 1.2),
            2.5, 2.5,
        )
        painter.drawLine(QPointF(cx - s * 0.35, cy), QPointF(cx + s * 0.35, cy))
        painter.drawLine(QPointF(cx, cy - s * 0.28), QPointF(cx, cy + s * 0.28))

    painter.restore()


def _draw_sidebar_glyph(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    pixmap = _load_svg_silhouette(name, int(rect.width()))
    if pixmap is not None and not pixmap.isNull():
        painter.save()
        result = QPixmap(pixmap.size())
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.drawPixmap(0, 0, pixmap)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(result.rect(), color)
        p.end()
        x = int(rect.center().x() - result.width() / 2)
        y = int(rect.center().y() - result.height() / 2)
        painter.drawPixmap(x, y, result)
        painter.restore()
        return

    _draw_painted_glyph(painter, name, rect, color)


class SidebarItemDelegate(QStyledItemDelegate):
    """Paint left-aligned sidebar rows with vertically-centered contents."""

    def __init__(self, sidebar: "SidebarListWidget", parent=None) -> None:
        super().__init__(parent)
        self.sidebar = sidebar

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        C = ui.FishingUI.C
        row = index.row()
        rect = option.rect
        is_current = row == self.sidebar.currentRow()
        progress = self.sidebar.row_progress(row)

        # Paint selection highlight behind the icon and text.
        pill_rect = self.sidebar.current_pill_rect()
        if not pill_rect.isNull() and rect.intersects(pill_rect):
            painter.save()
            painter.setClipRect(rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            accent = QColor(C["accent"])
            fill = QColor(accent)
            fill.setAlpha(36)
            border = QColor(accent)
            border.setAlpha(180)
            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.2))
            painter.drawRoundedRect(pill_rect, 8, 8)
            painter.restore()

        muted = QColor(C["text_muted"])
        subtle = QColor(C["text_subtle"])
        active = QColor("#FFFFFF")
        accent = QColor(C["accent"])

        base_text = (
            subtle
            if (row == self.sidebar._hover_row and progress < 0.01)
            else muted
        )
        text_color = _lerp_color(base_text, active, progress)
        icon_color = _lerp_color(base_text, active, progress)

        font = QFont(FONT_FAMILY)
        font.setPixelSize(14)
        font.setWeight(
            QFont.Weight.Bold
            if (is_current or progress > 0.5)
            else QFont.Weight.Normal
        )
        painter.setFont(font)
        painter.setPen(QPen(text_color))

        # Icons are centered on the row.
        icon_y = rect.center().y() - SIDEBAR_ICON_SIZE / 2.0
        icon_rect = QRectF(
            rect.left() + SIDEBAR_ICON_LEFT, icon_y,
            SIDEBAR_ICON_SIZE, SIDEBAR_ICON_SIZE,
        )

        scale = 0.92 + 0.08 * progress
        painter.save()
        painter.translate(icon_rect.center())
        painter.scale(scale, scale)
        painter.translate(-icon_rect.center())
        _draw_sidebar_glyph(
            painter,
            str(index.data(Qt.ItemDataRole.DisplayRole)),
            icon_rect,
            icon_color,
        )
        painter.restore()

        # Text is vertically centered with an optical offset.
        text_rect = QRect(
            rect.left() + SIDEBAR_LABEL_LEFT,
            rect.top() + SIDEBAR_TEXT_Y_OFFSET,
            rect.width() - SIDEBAR_LABEL_LEFT - 8,
            rect.height() - SIDEBAR_TEXT_Y_OFFSET,
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(index.data(Qt.ItemDataRole.DisplayRole)),
        )
        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(SIDEBAR_WIDTH, SIDEBAR_ROW_H)


class WrappingLabel(QLabel):
    _MIN_SANE_WIDTH = 40

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.width() < self._MIN_SANE_WIDTH:
            return
        h = self.heightForWidth(self.width())
        if h > 0 and self.minimumHeight() != h:
            self.setMinimumHeight(h)


class SidebarListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(SidebarItemDelegate(self, self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContentsMargins(0, 0, 0, 0)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._pill_rect = QRect()
        self._slider_anim = QVariantAnimation(self)
        self._slider_anim.setDuration(260)
        self._slider_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slider_anim.valueChanged.connect(self._on_slide_value)
        self._from_row = -1
        self._to_row = -1
        self._hover_row = -1
        self.setMouseTracking(True)
        self.currentRowChanged.connect(self._on_row_changed)

    def row_progress(self, row: int) -> float:
        if self._slider_anim.state() == QAbstractAnimation.State.Running:
            t = self._slider_anim.currentValue()
            t = 0.0 if t is None else float(t)
            if row == self._to_row:
                return t
            if row == self._from_row:
                return 1.0 - t
            return 0.0
        return 1.0 if row == self.currentRow() else 0.0

    def current_pill_rect(self) -> QRect:
        return self._pill_rect

    def _target_rect(self, row: int) -> QRect:
        rect = self.visualRect(self.model().index(row, 0))
        return rect.adjusted(
            SIDEBAR_PILL_MARGIN_X, SIDEBAR_PILL_MARGIN_Y,
            -SIDEBAR_PILL_MARGIN_X, -SIDEBAR_PILL_MARGIN_Y,
        )

    def _on_slide_value(self, t: float) -> None:
        start = (
            self._target_rect(self._from_row)
            if self._from_row >= 0
            else self._target_rect(self._to_row)
        )
        end = self._target_rect(self._to_row)
        x = start.x() + (end.x() - start.x()) * t
        y = start.y() + (end.y() - start.y()) * t
        w = start.width() + (end.width() - start.width()) * t
        h = start.height() + (end.height() - start.height()) * t
        self._pill_rect = QRect(int(x), int(y), int(w), int(h))
        self.viewport().update()

    def _on_row_changed(self, row):
        if row < 0:
            self._pill_rect = QRect()
            self.viewport().update()
            return

        target_rect = self._target_rect(row)
        if not self._pill_rect.isValid():
            self._pill_rect = target_rect
            self._from_row = row
            self._to_row = row
        else:
            self._from_row = self._to_row if self._to_row >= 0 else row
            self._to_row = row
            self._slider_anim.stop()
            self._slider_anim.setStartValue(0.0)
            self._slider_anim.setEndValue(1.0)
            self._slider_anim.start()

        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.currentRow() >= 0:
            self._pill_rect = self._target_rect(self.currentRow())
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        idx = self.indexAt(event.pos())
        row = idx.row() if idx.isValid() else -1
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()


class BaitPriorityList(QListWidget):
    def dropEvent(self, event):
        if (
            self.dropIndicatorPosition()
            == QAbstractItemView.DropIndicatorPosition.OnViewport
        ):
            event.ignore()
            return
        super().dropEvent(event)


class SettingsDialog(FadeInDialog):
    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setFont(QFont(FONT_FAMILY))
        self.setWindowTitle("Sea Angler Assist (Settings)")
        self.setModal(True)
        self._init_animations()
        self._build_ui()
        self._apply_style()
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.ensurePolished()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.finished.connect(lambda _r: self.settings.flush())

    def _init_animations(self) -> None:
        self._bait_height_anim = QVariantAnimation(self)
        self._bait_height_anim.setDuration(200)
        self._bait_height_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._bait_height_anim.valueChanged.connect(
            lambda h: self.bait_list.setFixedHeight(int(h))
            if hasattr(self, "bait_list")
            else None
        )

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = SidebarListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sidebar.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sidebar.setSpacing(0)
        self.sidebar.setUniformItemSizes(True)

        for name in ("General", "Alerts", "Bait", "Capture", "Hotkeys"):
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(SIDEBAR_WIDTH, SIDEBAR_ROW_H))
            self.sidebar.addItem(item)

        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._on_section_change)
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        self._stack_fx = QGraphicsOpacityEffect(self.stack)
        self._stack_fx.setOpacity(1.0)
        self.stack.setGraphicsEffect(self._stack_fx)
        self._stack_fade = QPropertyAnimation(self._stack_fx, b"opacity", self)

        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_alerts_page())
        self.stack.addWidget(self._build_bait_page())
        self.stack.addWidget(self._build_capture_page())
        self.stack.addWidget(self._build_hotkeys_page())
        root.addWidget(self.stack, stretch=1)

    def _on_section_change(self, idx: int) -> None:
        if self.stack.currentIndex() == idx:
            return
        self._stack_fade.stop()
        self._stack_fade.setDuration(120)
        self._stack_fade.setStartValue(1.0)
        self._stack_fade.setEndValue(0.0)
        self._stack_fade.start()

        def _swap() -> None:
            self.stack.setCurrentIndex(idx)
            self._stack_fade.stop()
            self._stack_fade.setDuration(220)
            self._stack_fade.setStartValue(0.0)
            self._stack_fade.setEndValue(1.0)
            self._stack_fade.start()

        QTimer.singleShot(120, _swap)

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)

        v.addWidget(self._section_title("GENERAL"))
        v.addWidget(self._section_subtitle("Application and game integration"))
        v.addWidget(self._divider())
        v.addSpacing(6)
        v.addWidget(self._field_label("GAME EXECUTABLE"))

        row = QHBoxLayout()
        row.setSpacing(8)
        edit = QLineEdit(self.settings.game_exe_path.get())
        edit.setObjectName("PathEdit")
        edit.setPlaceholderText(r"C:\Path\To\Game.exe")
        edit.textChanged.connect(self.settings.game_exe_path.set)
        self.settings.game_exe_path.changed.connect(
            lambda val, e=edit: e.setText(val) if val != e.text() else None
        )
        browse = PolishedButton("Browse…")
        browse.setObjectName("BrowseBtn")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(lambda: self._browse_exe(edit))
        row.addWidget(edit, stretch=1)
        row.addWidget(browse)
        v.addLayout(row)
        v.addSpacing(12)

        v.addWidget(self._checkbox("Minimize to tray instead of taskbar", self.settings.minimize_to_tray))
        v.addWidget(self._checkbox("Start minimized", self.settings.start_minimized))
        v.addWidget(self._checkbox("Open debug console on startup", self.settings.debug_console))
        v.addWidget(self._checkbox("Ignore abort on failure", self.settings.ignore_abort))
        v.addStretch()
        return page

    def _build_alerts_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)

        v.addWidget(self._section_title("ALERTS"))
        v.addWidget(self._section_subtitle("Sound and notifications"))
        v.addWidget(self._divider())
        v.addSpacing(6)
        v.addWidget(self._checkbox("SFX", self.settings.sound_effects))
        v.addStretch()
        return page

    def _build_bait_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)

        v.addWidget(self._section_title("BAIT"))
        v.addWidget(self._section_subtitle(
            "Drag to set the priority order used by Auto Switch Bait. "
            "Unavailable baits are remembered but skipped at runtime."
        ))
        v.addWidget(self._divider())
        v.addSpacing(6)

        self.bait_list = BaitPriorityList()
        self.bait_list.setObjectName("BaitPriorityList")
        self.bait_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.bait_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.bait_list.setMovement(QListView.Movement.Free)
        self.bait_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bait_list.setUniformItemSizes(True)
        self.bait_list.setSpacing(2)
        self.bait_list.setMaximumHeight(BAIT_LIST_MAX_H)
        self.bait_list.setFixedHeight(BAIT_LIST_EMPTY_H)
        self._populate_bait_list()
        self.bait_list.model().rowsMoved.connect(self._persist_bait_priority)
        self.bait_list.model().layoutChanged.connect(self._persist_bait_priority)
        v.addWidget(self.bait_list)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        reset_btn = PolishedButton("Reset")
        reset_btn.setObjectName("BrowseBtn")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_bait_priority)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)
        v.addStretch()

        QTimer.singleShot(0, self._adjust_bait_list_height)
        return page

    def _build_capture_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)

        v.addWidget(self._section_title("CAPTURE"))
        v.addWidget(self._section_subtitle("Screen capture mode and source"))
        v.addWidget(self._divider())
        v.addSpacing(6)
        v.addWidget(self._field_label("CAPTURE MODE"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.mode_auto = QRadioButton("Auto")
        self.mode_window = QRadioButton("Window")
        self.mode_monitor = QRadioButton("Monitor")
        mode_val = self.settings.capture_mode.get()
        if mode_val == "auto":
            self.mode_auto.setChecked(True)
        elif mode_val == "monitor":
            self.mode_monitor.setChecked(True)
        else:
            self.mode_window.setChecked(True)

        self.mode_auto.toggled.connect(
            lambda checked: self.settings.capture_mode.set("auto") if checked else None
        )
        self.mode_window.toggled.connect(
            lambda checked: self.settings.capture_mode.set("window") if checked else None
        )
        self.mode_monitor.toggled.connect(
            lambda checked: self.settings.capture_mode.set("monitor") if checked else None
        )
        mode_row.addWidget(self.mode_auto)
        mode_row.addWidget(self.mode_window)
        mode_row.addWidget(self.mode_monitor)
        mode_row.addStretch()
        v.addLayout(mode_row)
        v.addSpacing(12)

        v.addWidget(self._field_label("MONITOR TARGET"))
        self.monitor_combo = QComboBox()
        self.monitor_combo.setObjectName("MonitorCombo")
        with mss.mss() as sct:
            for i, monitor in enumerate(sct.monitors):
                if i == 0:
                    continue
                self.monitor_combo.addItem(
                    f"Monitor {i} ({monitor['width']}x{monitor['height']})",
                    i,
                )
        cur_mon = self.settings.capture_monitor.get()
        if 0 < cur_mon < self.monitor_combo.count() + 1:
            self.monitor_combo.setCurrentIndex(cur_mon - 1)
        self.monitor_combo.currentIndexChanged.connect(
            lambda idx: self.settings.capture_monitor.set(idx + 1)
        )
        v.addWidget(self.monitor_combo)
        v.addSpacing(8)

        v.addWidget(self._field_label(
            "Auto mode tries Window first, then falls back to Monitor. (recommended)\n"
            "Window mode captures the game client even if obstructed, moved or resized.\n"
            "Monitor mode captures the whole monitor, so the game must be visible and "
            "unobstructed at all times."
        ))
        v.addStretch()
        return page

    def _build_hotkeys_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(8)

        v.addWidget(self._section_title("HOTKEYS"))
        v.addWidget(self._section_subtitle("Global hotkeys (disabled while in settings)"))
        v.addWidget(self._divider())
        v.addSpacing(6)

        self.hotkey_game_only = self._checkbox(
            "Only when game is focused", self.settings.hotkey_game_only,
        )
        v.addWidget(self.hotkey_game_only)
        v.addSpacing(8)

        is_admin = is_running_as_admin()
        if not is_admin:
            warn = self._field_label(
                "Administrator mode is required for global hotkeys and window "
                "capture. Local hotkeys (when app is focused) are still active."
            )
            v.addWidget(warn)
            v.addSpacing(8)

        def add_hotkey_row(label_text: str, setting) -> None:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label_text)
            lbl.setObjectName("FieldLabel")
            btn = HotkeyButton(setting.get())
            btn.setEnabled(is_admin)
            btn.keyCaptured.connect(setting.set)
            setting.changed.connect(btn.setText)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(btn)
            v.addLayout(row)

        add_hotkey_row("Start", self.settings.hotkey_start)
        add_hotkey_row("Stop", self.settings.hotkey_stop)
        add_hotkey_row("Auto Switch Bait", self.settings.hotkey_auto_switch)
        add_hotkey_row("Detect Baits", self.settings.hotkey_detect_baits)
        add_hotkey_row("Settings", self.settings.hotkey_settings)
        add_hotkey_row("Debug Console", self.settings.hotkey_debug)
        v.addStretch()
        return page

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    def _section_subtitle(self, text: str) -> QLabel:
        lbl = WrappingLabel(text)
        lbl.setObjectName("SectionSubtitle")
        lbl.setWordWrap(True)
        return lbl

    def _field_label(self, text: str) -> QLabel:
        lbl = WrappingLabel(text)
        lbl.setObjectName("Placeholder")
        lbl.setWordWrap(True)
        return lbl

    def _divider(self) -> QFrame:
        div = QFrame()
        div.setObjectName("Divider")
        div.setFixedHeight(1)
        return div

    def _checkbox(self, label: str, obs) -> AnimatedCheckBox:
        cb = AnimatedCheckBox(label, ui.FishingUI.C)
        cb.set_checked(obs.get())
        cb.toggled.connect(obs.set)
        obs.changed.connect(cb.set_checked)
        return cb

    def _switch(self, label: str, obs) -> SwitchButton:
        sw = SwitchButton(
            label, ui.FishingUI.C,
            on_toggle=obs.set,
            object_name="SwitchButton",
        )
        sw.set_checked(obs.get())
        obs.changed.connect(sw.set_checked)
        return sw

    def _browse_exe(self, edit: QLineEdit) -> None:
        cur = self.settings.game_exe_path.get()
        start_dir = (
            os.path.dirname(cur)
            if cur and os.path.isdir(os.path.dirname(cur))
            else ""
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Game Executable", start_dir, "Executable (*.exe)",
        )
        if path and path.lower().endswith(".exe"):
            edit.setText(path)

    @staticmethod
    def _load_baits() -> list:
        return list(get_baits())

    def _populate_bait_list(self) -> None:
        model = self.bait_list.model()
        self.bait_list.blockSignals(True)
        model.blockSignals(True)
        try:
            self.bait_list.clear()
            baits = self._load_baits()
            for idx in self.settings.get_bait_priority():
                if not (0 <= idx < len(baits)):
                    continue
                bait = baits[idx]
                rarity = bait.get("rarity") or ""
                color = RARITY_COLORS.get(rarity, "#F8FAFC")
                item = QListWidgetItem(f"{idx + 1}. {bait['name']}")
                item.setData(Qt.ItemDataRole.UserRole, idx)
                item.setForeground(QColor(color))
                self.bait_list.addItem(item)
        finally:
            model.blockSignals(False)
            self.bait_list.blockSignals(False)
        self._adjust_bait_list_height()

    def _adjust_bait_list_height(self) -> None:
        self.bait_list.doItemsLayout()
        count = self.bait_list.count()
        if count == 0:
            target_h = BAIT_LIST_EMPTY_H
        else:
            item_h = self.bait_list.sizeHintForRow(0)
            if item_h <= 0:
                item_h = BAIT_LIST_FALLBACK_ITEM_H
            spacing = max(0, self.bait_list.spacing())
            total_h = (
                count * item_h
                + max(0, count - 1) * spacing
                + CONTAINER_PADDING
            )
            if total_h > BAIT_LIST_MAX_H:
                self.bait_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                self.bait_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scrollable_h = BAIT_LIST_MAX_H - CONTAINER_PADDING
                items_in_view = max(1, scrollable_h // (item_h + spacing))
                view_content_h = (
                    items_in_view * item_h
                    + max(0, items_in_view - 1) * spacing
                )
                target_h = view_content_h + CONTAINER_PADDING
            else:
                self.bait_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                target_h = total_h

        anim = self._bait_height_anim
        anim.stop()
        anim.setStartValue(float(self.bait_list.height()))
        anim.setEndValue(float(target_h))
        anim.start()

    def _persist_bait_priority(self, *args) -> None:
        old_order = self.settings.get_bait_priority()
        order: List[int] = []
        for i in range(self.bait_list.count()):
            item = self.bait_list.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(idx, int):
                order.append(idx)
        if order and order != old_order:
            self.settings.set_bait_priority(order)

    def _reset_bait_priority(self) -> None:
        self.settings.set_bait_priority(list(range(len(self._load_baits()))))
        self._populate_bait_list()

    def _apply_style(self) -> None:
        C = ui.FishingUI.C
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {C['bg']};
            }}
            QListWidget#Sidebar {{
                background-color: {C['bg']};
                border: none;
                border-right: 1px solid {C['border']};
                outline: none;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 10pt;
                padding: 10px 0px;
            }}
            QListWidget#Sidebar::item {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                outline: none;
            }}
            QListWidget#Sidebar::item:selected {{
                background: transparent;
                outline: none;
            }}
            QListWidget#Sidebar::item:focus {{
                background: transparent;
                outline: none;
            }}
            QListWidget#BaitPriorityList {{
                background-color: {C['surface']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 4px;
                outline: 0;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
            }}
            QListWidget#BaitPriorityList::item {{
                padding: 4px 8px;
                border-radius: 4px;
                background-color: transparent;
                margin: 0px;
            }}
            QListWidget#BaitPriorityList::item:hover {{
                background-color: {C['border_hi']};
            }}
            QListWidget#BaitPriorityList::item:selected {{
                background-color: {C['accent_dim']};
                color: {C['text']};
            }}
            QWidget#Content {{
                background-color: {C['bg']};
            }}
            QLabel {{
                background: transparent;
                color: {C['text']};
                font-family: '{ui.FONT_FAMILY}';
            }}
            QLabel#SectionTitle {{
                color: {C['text']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 14pt;
                font-weight: bold;
                padding-bottom: 4px;
            }}
            QLabel#SectionSubtitle {{
                color: {C['text_muted']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                padding-bottom: 8px;
            }}
            QLabel#FieldLabel {{
                color: {C['text_muted']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
                padding-bottom: 4px;
            }}
            QLabel#Placeholder {{
                color: {C['text_subtle']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
            }}
            QFrame#Divider {{
                background-color: {C['border']};
                max-height: 1px;
                min-height: 1px;
                border: none;
            }}
            QLineEdit#PathEdit {{
                background-color: {C['surface']};
                color: {C['text']};
                border: 1px solid {C['border_hi']};
                border-radius: 6px;
                padding: 8px 12px;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                selection-background-color: {C['accent']};
                selection-color: {C['bg']};
            }}
            QLineEdit#PathEdit:focus {{
                border: 1px solid {C['accent']};
            }}
            QPushButton {{
                background-color: {C['surface_alt']};
                border: 1px solid {C['border_hi']};
                border-radius: 6px;
                padding: 8px 14px;
                color: {C['text']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C['border_hi']};
                border: 1px solid {C['accent_muted']};
            }}
            QPushButton:pressed {{
                background-color: {C['accent_dim']};
                padding-top: 9px;
                padding-bottom: 7px;
            }}
            QPushButton:disabled {{
                color: {C['text_muted']};
                background-color: {C['surface']};
                border: 1px solid {C['border']};
            }}
            QPushButton#BrowseBtn {{
                background-color: {C['surface_alt']};
                border: 1px solid {C['border_hi']};
                border-radius: 6px;
                padding: 8px 14px;
                color: {C['text']};
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
            }}
            QPushButton#BrowseBtn:hover {{
                background-color: {C['border_hi']};
                border: 1px solid {C['accent_muted']};
            }}
            QPushButton#BrowseBtn:pressed {{
                padding-top: 9px;
                padding-bottom: 7px;
            }}
            QCheckBox {{
                color: {C['text']};
                spacing: 8px;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
                background: transparent;
                padding: 6px 0px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {C['border_hi']};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {C['accent']};
                border: 1px solid {C['accent']};
                image: {_CHECK_URL};
            }}
            QRadioButton {{
                color: {C['text']};
                spacing: 8px;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                font-weight: bold;
                background: transparent;
                padding: 6px 0px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid {C['border_hi']};
                background-color: transparent;
            }}
            QRadioButton::indicator:checked {{
                background-color: {C['accent']};
                border: 1px solid {C['accent']};
            }}
            QComboBox#MonitorCombo {{
                background-color: {C['surface']};
                color: {C['text']};
                border: 1px solid {C['border_hi']};
                border-radius: 6px;
                padding: 8px 12px;
                font-family: '{ui.FONT_FAMILY}';
                font-size: 9pt;
                min-width: 200px;
            }}
            QComboBox#MonitorCombo::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox#MonitorCombo::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {C['text_muted']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {C['surface']};
                color: {C['text']};
                selection-background-color: {C['accent_dim']};
                selection-color: {C['text']};
                border: 1px solid {C['border_hi']};
                outline: 0;
            }}
        """)