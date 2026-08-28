from __future__ import annotations

import os
import math
from typing import (
    Any, Callable, Dict, Optional, List, Tuple,
)

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation,
    QRectF, QRect, Qt, Signal, QTimer, QVariantAnimation,
)
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QKeySequence,
    QPainter, QPen, QBrush, QPixmap, QTextCharFormat,
    QTextCursor, QTextBlockFormat, QLinearGradient, QPainterPath,
    QRadialGradient, QShortcut, QGuiApplication,
)
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMenu,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
    QGraphicsOpacityEffect,
)

from paths import bundled_resource


# ==========================================
# CENTRALIZED FONT LOADER & VARIABLES
# ==========================================

FONT_FAMILY = "Inter"
FONT_MONO = "Share Tech Mono"

def load_custom_fonts() -> Tuple[str, str]:
    global FONT_FAMILY, FONT_MONO
    main_font_path = bundled_resource("fonts", "Inter-Regular.ttf")
    main_id = QFontDatabase.addApplicationFont(main_font_path)
    if main_id != -1:
        families = QFontDatabase.applicationFontFamilies(main_id)
        if families:
            FONT_FAMILY = families[0]
    mono_font_path = bundled_resource("fonts", "ShareTechMono.ttf")
    mono_id = QFontDatabase.addApplicationFont(mono_font_path)
    if mono_id != -1:
        families = QFontDatabase.applicationFontFamilies(mono_id)
        if families:
            FONT_MONO = families[0]
    return FONT_FAMILY, FONT_MONO

_UI_DIR = bundled_resource("ui")
_CHECKMARK_FILE = os.path.join(_UI_DIR, "checkmark.svg")
_CHECKMARK_FILE_URL = _CHECKMARK_FILE.replace(os.sep, "/")
CHECK_URL = f"url('{_CHECKMARK_FILE_URL}')"


# ==========================================
# ANIMATED MENU
# ==========================================

class AnimatedMenu(QMenu):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._effect, b"opacity")
        self._fade_anim.setDuration(160)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim = QPropertyAnimation(self, b"geometry")
        self._slide_anim.setDuration(160)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.aboutToShow.connect(self._animate_in)

    def _animate_in(self):
        QTimer.singleShot(0, self._start_slide)

    def _start_slide(self):
        geo = self.geometry()
        start_geo = QRect(geo.x(), geo.y() - 8, geo.width(), geo.height())
        self.setGeometry(start_geo)
        self._slide_anim.stop()
        self._slide_anim.setStartValue(start_geo)
        self._slide_anim.setEndValue(geo)
        self._slide_anim.start()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()


# ==========================================
# LOG VIEW
# ==========================================

class _NewLogsBadge(QWidget):
    clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)
        self._label = "New logs"
        self.hide()
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._hide_on_finish_connected = False
        fm = self.fontMetrics()
        self._text_w = fm.horizontalAdvance(self._label)
        self.setFixedWidth(self._text_w + 28)

    def show_animated(self) -> None:
        if self.isVisible() and self._opacity_effect.opacity() >= 0.99:
            return
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._opacity_effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def hide_animated(self) -> None:
        if not self.isVisible():
            return
        self._anim.stop()
        self._anim.setStartValue(self._opacity_effect.opacity())
        self._anim.setEndValue(0.0)
        if self._hide_on_finish_connected:
            try:
                self._anim.finished.disconnect(self.hide)
            except (TypeError, RuntimeError):
                pass
        self._anim.finished.connect(self.hide)
        self._hide_on_finish_connected = True
        self._anim.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor("#FA468E"), 1))
        p.setBrush(QBrush(QColor(0x16, 0x1C, 0x27, 235)))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(QColor("#FA468E"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class LogView(QPlainTextEdit):
    FADE_DISTANCE = 24
    PIN_THRESHOLD = 4
    SEVERITY_BORDER_W = 3

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setAccessibleName("Debug Console")
        self.setAccessibleDescription("Live application log output")

        self._log_buffer: List[Tuple[str, str]] = []
        self._paused = False
        self._pending_while_paused: List[Tuple[str, str]] = []

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_buffer)

        self._fade_color = QColor("#11161F")
        self.setViewportMargins(0, 0, 0, 0)

        # Cached fade values
        self._top_fade_opacity = 0.0
        self._bottom_fade_opacity = 0.0
        self._cached_top = -1.0
        self._cached_bottom = -1.0

        self._is_pinned = True
        self._suppress_fade_for_selection = False
        self._entry_count = 0

        self._new_logs_badge = _NewLogsBadge(self)
        self._new_logs_badge.clicked.connect(self._on_badge_clicked)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.selectionChanged.connect(self._on_selection_changed)

        self._copy_all_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self._copy_all_shortcut.activated.connect(self.copy_all)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._update_fade_state()

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def append(self, text: str, color: str = "#E7E7E7") -> None:
        if self._paused:
            self._pending_while_paused.append((text, color))
            return
        self._log_buffer.append((text, color))
        self._flush_timer.start()

    def replace_last_line(self, text: str, color: str = "#E7E7E7") -> None:
        if self._paused:
            if self._pending_while_paused:
                self._pending_while_paused[-1] = (text, color)
            else:
                self._pending_while_paused.append((text, color))
            return
        if self._log_buffer:
            self._log_buffer[-1] = (text, color)
            self._flush_timer.start()
            return
        was_pinned = self._is_pinned
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.deleteChar()
        self._insert_entry(cursor, text, color)
        if was_pinned:
            self.setTextCursor(cursor)
            self._scroll_to_bottom()
        self._update_fade_state()

    def clear_log(self) -> None:
        self._log_buffer.clear()
        self._pending_while_paused.clear()
        self._flush_timer.stop()
        self._entry_count = 0
        self.clear()
        self._new_logs_badge.hide()
        self._update_fade_state()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        if paused == self._paused:
            return
        self._paused = paused
        if not paused and self._pending_while_paused:
            self._log_buffer.extend(self._pending_while_paused)
            self._pending_while_paused.clear()
            self._flush_timer.start()

    def copy_all(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.toPlainText())

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy_selection = menu.addAction("Copy")
        copy_selection.setEnabled(self.textCursor().hasSelection())
        copy_selection.triggered.connect(self.copy)
        copy_all = menu.addAction("Copy All")
        copy_all.triggered.connect(self.copy_all)
        menu.exec(self.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------
    # Buffer flush / rendering
    # ------------------------------------------------------------
    def _insert_entry(self, cursor: "QTextCursor", text: str, color: str) -> None:
        block_fmt = QTextBlockFormat()
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)
        block_fmt.setLineHeight(140.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        left_border = self._border_color_for(color)
        if left_border is not None:
            block_fmt.setLeftMargin(self.SEVERITY_BORDER_W + 4)
        cursor.setBlockFormat(block_fmt)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text.rstrip("\n"))

    @staticmethod
    def _border_color_for(color: str) -> Optional[str]:
        severity_colors = {"#EF4444": "#EF4444", "#FFB610": "#FFB610"}
        return severity_colors.get(color.upper() if color else "")

    def _flush_buffer(self) -> None:
        if not self._log_buffer:
            self._flush_timer.stop()
            return
        was_pinned = self._is_pinned
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        at_start = self.document().isEmpty()
        for text, color in self._log_buffer:
            if not at_start:
                cursor.insertBlock()
            at_start = False
            self._entry_count += 1
            self._insert_entry(cursor, text, color)
        self._log_buffer.clear()
        self._flush_timer.stop()
        self._prune_if_needed()
        if was_pinned:
            self.setTextCursor(cursor)
            self._scroll_to_bottom()
            self._new_logs_badge.hide_animated()
        else:
            self._new_logs_badge.show_animated()
            self._position_badge()
        self._update_fade_state()

    def _prune_if_needed(self) -> None:
        pass

    # ------------------------------------------------------------
    # Scroll tracking / pin-to-bottom
    # ------------------------------------------------------------
    def _max_scroll(self) -> int:
        return self.verticalScrollBar().maximum()

    def _scroll_to_bottom(self) -> None:
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_scroll(self, _value: int) -> None:
        sb = self.verticalScrollBar()
        max_scroll = sb.maximum()
        pos = max(0, sb.value())
        self._is_pinned = (max_scroll - pos) < self.PIN_THRESHOLD
        if self._is_pinned:
            self._new_logs_badge.hide_animated()
        self._update_fade_state()
        self._position_badge()

    def _on_selection_changed(self) -> None:
        has_selection = self.textCursor().hasSelection()
        if has_selection != self._suppress_fade_for_selection:
            self._suppress_fade_for_selection = has_selection
            self.viewport().update()

    def _on_badge_clicked(self) -> None:
        self._scroll_to_bottom()
        self._new_logs_badge.hide_animated()

    # ------------------------------------------------------------
    # Fade math with caching
    # ------------------------------------------------------------
    def _update_fade_state(self) -> None:
        sb = self.verticalScrollBar()
        max_scroll = sb.maximum()
        if max_scroll <= 0:
            new_top = 0.0
            new_bottom = 0.0
        else:
            scroll_top = max(0, sb.value())
            bottom_distance = max_scroll - scroll_top
            new_top = _clamp(scroll_top / self.FADE_DISTANCE, 0.0, 1.0)
            new_bottom = _clamp(bottom_distance / self.FADE_DISTANCE, 0.0, 1.0)

        # Only update if values changed to avoid unnecessary repaints
        if new_top != self._cached_top or new_bottom != self._cached_bottom:
            self._cached_top = new_top
            self._cached_bottom = new_bottom
            self._top_fade_opacity = new_top
            self._bottom_fade_opacity = new_bottom
            self.viewport().update()

    # ------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        was_pinned = self._is_pinned
        if was_pinned:
            self._scroll_to_bottom()
        self._update_fade_state()
        self._position_badge()

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        self._update_fade_state()

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        self._on_scroll(self.verticalScrollBar().value())

    def _position_badge(self) -> None:
        if not self._new_logs_badge.isVisible():
            return
        vp = self.viewport()
        badge = self._new_logs_badge
        x = (vp.width() - badge.width()) // 2
        y = vp.height() - badge.height() - 10
        badge.move(x, max(0, y))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._suppress_fade_for_selection:
            return
        if self._top_fade_opacity <= 0.0 and self._bottom_fade_opacity <= 0.0:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.viewport().height()
        w = self.viewport().width()
        fade_h = self.FADE_DISTANCE

        if self._top_fade_opacity > 0.0:
            top_grad = QLinearGradient(0, 0, 0, fade_h)
            start_color = QColor(self._fade_color)
            start_color.setAlphaF(self._top_fade_opacity)
            top_grad.setColorAt(0, start_color)
            end_color = QColor(self._fade_color)
            end_color.setAlphaF(0.0)
            top_grad.setColorAt(1, end_color)
            p.fillRect(0, 0, w, fade_h, QBrush(top_grad))

        if self._bottom_fade_opacity > 0.0:
            bottom_grad = QLinearGradient(0, h - fade_h, 0, h)
            start_color = QColor(self._fade_color)
            start_color.setAlphaF(0.0)
            bottom_grad.setColorAt(0, start_color)
            end_color = QColor(self._fade_color)
            end_color.setAlphaF(self._bottom_fade_opacity)
            bottom_grad.setColorAt(1, end_color)
            p.fillRect(0, h - fade_h, w, fade_h, QBrush(bottom_grad))
        p.end()

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ==========================================
# POLISHED BUTTON
# ==========================================

class PolishedButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scale = 1.0
        self._base_font = None
        self._hover_scale = 1.0
        self._hover_rotate = 0.0
        self._icon_rotation = 0.0
        self._base_icon: Optional[QPixmap] = None
        self._squish_anim = QPropertyAnimation(self, b"scaleFactor")
        self._squish_anim.setDuration(100)
        self._squish_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._rotate_anim = QPropertyAnimation(self, b"iconRotation")
        self._rotate_anim.setDuration(200)
        self._rotate_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glow = 0.0
        self._glow_enabled = True
        self._glow_anim = QPropertyAnimation(self, b"glow")
        self._glow_anim.setDuration(180)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_scale(self):
        return self._scale
    def set_scale(self, val):
        self._scale = val
        if self._base_font is None:
            self._base_font = QFont(self.font())
        f = QFont(self._base_font)
        f.setPointSizeF(max(1.0, self._base_font.pointSizeF() * val))
        self.setFont(f)
    scaleFactor = Property(float, get_scale, set_scale)

    def get_icon_rotation(self):
        return self._icon_rotation
    def set_icon_rotation(self, val):
        self._icon_rotation = val
        self.update()
    iconRotation = Property(float, get_icon_rotation, set_icon_rotation)

    def get_glow(self):
        return self._glow
    def set_glow(self, val):
        self._glow = val
        self.update()
    glow = Property(float, get_glow, set_glow)

    def setIcon(self, icon):
        if icon.isNull():
            self._base_icon = None
            super().setIcon(QIcon())
            return
        sizes = icon.availableSizes()
        if sizes:
            self._base_icon = icon.pixmap(max(sizes, key=lambda s: s.width() * s.height()))
        else:
            self._base_icon = icon.pixmap(self.iconSize())
        super().setIcon(QIcon())

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._glow > 0.01 and self._glow_enabled:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect())
            wash = QColor(255, 255, 255, int(self._glow * 25))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(wash))
            painter.drawRoundedRect(rect, 4.0, 4.0)
            ring = QColor(250, 70, 142, int(self._glow * 120))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ring, 1.5))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4.0, 4.0)
            painter.end()
        if self._base_icon is None or self._base_icon.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        center = self.rect().center()
        painter.translate(center)
        if self._icon_rotation != 0.0:
            painter.rotate(self._icon_rotation)
        pm = self._base_icon
        painter.drawPixmap(-pm.width() // 2, -pm.height() // 2, pm)
        painter.end()

    def mousePressEvent(self, e):
        if self.isEnabled():
            self._squish_anim.stop()
            self._squish_anim.setStartValue(self._scale)
            self._squish_anim.setEndValue(0.94)
            self._squish_anim.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isEnabled():
            self._squish_anim.stop()
            self._squish_anim.setStartValue(self._scale)
            self._squish_anim.setEndValue(self._hover_scale)
            self._squish_anim.start()
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        if self.isEnabled():
            if self._glow_enabled:
                self._glow_anim.stop()
                self._glow_anim.setStartValue(self._glow)
                self._glow_anim.setEndValue(1.0)
                self._glow_anim.start()
            if self._hover_scale > 1.0:
                self._squish_anim.stop()
                self._squish_anim.setStartValue(self._scale)
                self._squish_anim.setEndValue(self._hover_scale)
                self._squish_anim.start()
            if self._hover_rotate != 0.0:
                self._rotate_anim.stop()
                self._rotate_anim.setStartValue(self._icon_rotation)
                self._rotate_anim.setEndValue(self._hover_rotate)
                self._rotate_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.isEnabled():
            if self._glow_enabled:
                self._glow_anim.stop()
                self._glow_anim.setStartValue(self._glow)
                self._glow_anim.setEndValue(0.0)
                self._glow_anim.start()
            if self._hover_scale > 1.0:
                self._squish_anim.stop()
                self._squish_anim.setStartValue(self._scale)
                self._squish_anim.setEndValue(1.0)
                self._squish_anim.start()
            if self._hover_rotate != 0.0:
                self._rotate_anim.stop()
                self._rotate_anim.setStartValue(self._icon_rotation)
                self._rotate_anim.setEndValue(0.0)
                self._rotate_anim.start()
        super().leaveEvent(e)


# ==========================================
# SWITCH BUTTON
# ==========================================

class SwitchButton(QWidget):
    toggled = Signal(bool)
    knobPosChanged = Signal(float)

    def __init__(self, label_text: str, colors: Dict[str, str],
                 on_toggle: Optional[Callable[[bool], None]] = None,
                 object_name: str = "SwitchButton") -> None:
        super().__init__()
        self._colors = colors
        self._checked = False
        self._knob_x = 3.0
        self._knob_squash = 0.0
        self.setObjectName(object_name)
        self.setFixedHeight(24)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel(label_text)
        self._label.setObjectName("ToggleSwitchLabel")
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(10)

        self._track = QWidget()
        self._track.setFixedSize(40, 22)
        self._track.setCursor(Qt.CursorShape.PointingHandCursor)
        self._track.paintEvent = self._paint_track
        self._track.mousePressEvent = self.mousePressEvent
        self._track.mouseReleaseEvent = self.mouseReleaseEvent

        track_container = QHBoxLayout()
        track_container.setContentsMargins(0, 0, 0, 0)
        track_container.addWidget(self._track)
        layout.addLayout(track_container)

        self._anim = QPropertyAnimation(self, b"knobPos")
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._squash_anim = QVariantAnimation(self)
        self._squash_anim.setDuration(70)
        self._squash_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._squash_anim.valueChanged.connect(self._on_squash)

        if on_toggle is not None:
            self.toggled.connect(on_toggle)

    def get_knobPos(self) -> float:
        return self._knob_x
    def set_knobPos(self, x: float) -> None:
        if self._knob_x == x:
            return
        self._knob_x = x
        self._track.update()
        self.knobPosChanged.emit(x)
    knobPos = Property(float, get_knobPos, set_knobPos, notify=knobPosChanged)

    def _on_squash(self, v) -> None:
        self._knob_squash = float(v)
        self._track.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._squash_anim.stop()
            self._squash_anim.setStartValue(0.0)
            self._squash_anim.setEndValue(1.0)
            self._squash_anim.start()
            self.set_checked(not self._checked)
            self.toggled.emit(self._checked)

    def mouseReleaseEvent(self, event) -> None:
        self._squash_anim.stop()
        self._squash_anim.setStartValue(self._knob_squash)
        self._squash_anim.setEndValue(0.0)
        self._squash_anim.start()
        super().mouseReleaseEvent(event)

    def set_checked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        x = 21.0 if checked else 3.0
        self._anim.stop()
        self._anim.setStartValue(float(self._knob_x))
        self._anim.setEndValue(float(x))
        self._anim.start()

    def is_checked(self) -> bool:
        return self._checked

    def _paint_track(self, event) -> None:
        p = QPainter(self._track)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = max(0.0, min(1.0, (self._knob_x - 3.0) / 18.0))

        if progress > 0.01:
            glow_rect = QRectF(-4, -4, self._track.width() + 8, self._track.height() + 8)
            glow = QRadialGradient(glow_rect.center(), max(glow_rect.width(), glow_rect.height()) * 0.6)
            accent = QColor(self._colors["accent"])
            glow_c = QColor(accent)
            glow_c.setAlpha(int(60 * progress))
            glow_edge = QColor(accent)
            glow_edge.setAlpha(0)
            glow.setColorAt(0.0, glow_c)
            glow.setColorAt(1.0, glow_edge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawRect(glow_rect)

        track_off = QColor(self._colors["surface_alt"])
        track_on = QColor(self._colors["accent"])
        track_color = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * progress),
            int(track_off.green() + (track_on.green() - track_off.green()) * progress),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * progress),
        )
        border_off = QColor(self._colors["border_hi"])
        border_on = QColor(self._colors["accent"])
        border_color = QColor(
            int(border_off.red() + (border_on.red() - border_off.red()) * progress),
            int(border_off.green() + (border_on.green() - border_off.green()) * progress),
            int(border_off.blue() + (border_on.blue() - border_off.blue()) * progress),
        )
        p.setPen(QPen(border_color, 1))
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(QRectF(0, 0, self._track.width(), self._track.height()), 11.0, 11.0)

        knob_off = QColor(self._colors["text_muted"])
        knob_on = QColor("#FFFFFF")
        knob_color = QColor(
            int(knob_off.red() + (knob_on.red() - knob_off.red()) * progress),
            int(knob_off.green() + (knob_on.green() - knob_off.green()) * progress),
            int(knob_off.blue() + (knob_on.blue() - knob_off.blue()) * progress),
        )
        squash = self._knob_squash
        knob_size = 16.0 * (1.0 - squash * 0.12)
        knob_x = self._knob_x + (16.0 - knob_size) / 2
        knob_y = 3.0 + (16.0 - knob_size) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(knob_color))
        p.drawRoundedRect(QRectF(knob_x, knob_y, knob_size, knob_size), knob_size / 2, knob_size / 2)
        p.end()


# ==========================================
# HOTKEY BUTTON
# ==========================================

class HotkeyButton(PolishedButton):
    keyCaptured = Signal(str)
    EXCLUDED = [Qt.Key.Key_Space, Qt.Key.Key_R, Qt.Key.Key_Q, Qt.Key.Key_E,
                Qt.Key.Key_F, Qt.Key.Key_Escape, Qt.Key.Key_Shift,
                Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right]

    def __init__(self, current_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(current_key if current_key else "None", parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_click)
        self._original_key = current_key
        self._listen_glow = 0.0
        self._listen_anim = QVariantAnimation(self)
        self._listen_anim.setDuration(800)
        self._listen_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._listen_anim.setStartValue(0.35)
        self._listen_anim.setKeyValueAt(0.5, 1.0)
        self._listen_anim.setEndValue(0.35)
        self._listen_anim.setLoopCount(-1)
        self._listen_anim.valueChanged.connect(self._set_listen_glow)

    def get_listen_glow(self) -> float:
        return self._listen_glow
    def set_listen_glow(self, v: float) -> None:
        self._listen_glow = float(v)
        self.update()
    listenGlow = Property(float, get_listen_glow, set_listen_glow)

    def _set_listen_glow(self, v) -> None:
        self._listen_glow = float(v)
        self.update()

    def paintEvent(self, event):
        if self._listen_glow > 0.0:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor(250, 70, 142, int(self._listen_glow * 180))
            pen = QPen(color, 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
            p.end()
        super().paintEvent(event)

    def _start_listening(self) -> None:
        self._listen_anim.stop()
        self._listen_anim.start()

    def _stop_listening(self) -> None:
        self._listen_anim.stop()
        self._listen_glow = 0.0
        self.update()

    def _on_click(self, checked: bool) -> None:
        if checked:
            self._original_key = self.text()
            self.setText("Press a key...")
            self.grabKeyboard()
            self.setFocus()
            self._start_listening()
        else:
            self.releaseKeyboard()
            self._stop_listening()

    def keyPressEvent(self, event) -> None:
        if self.isChecked():
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.setText(self._original_key if self._original_key else "None")
                self.setChecked(False)
                self.releaseKeyboard()
                self._stop_listening()
            elif key in self.EXCLUDED:
                pass
            else:
                key_str = QKeySequence(key).toString()
                self.setText(key_str)
                self.keyCaptured.emit(key_str)
                self.setChecked(False)
                self.releaseKeyboard()
                self._stop_listening()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        if self.isChecked():
            self.setText(self._original_key if self._original_key else "None")
            self.setChecked(False)
            self.releaseKeyboard()
            self._stop_listening()
        super().focusOutEvent(event)


# ==========================================
# ANIMATED CHECK INDICATOR
# ==========================================

class AnimatedCheckIndicator(QWidget):
    toggled = Signal(bool)

    def __init__(self, colors: Dict[str, str], size: int = 16, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._checked = False
        self._progress = 0.0
        self.setFixedSize(size, size)
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def get_progress(self) -> float:
        return self._progress
    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()
    progress = Property(float, get_progress, set_progress)

    def set_checked(self, checked: bool, animate: bool = True) -> None:
        checked = bool(checked)
        if self._checked == checked:
            if not animate:
                self._anim.stop()
                self.set_progress(1.0 if checked else 0.0)
            return
        self._checked = checked
        self.toggled.emit(checked)
        self._anim.stop()
        target = 1.0 if checked else 0.0
        if not animate:
            self.set_progress(target)
            return
        start = self._progress
        if abs(start - target) < 0.001:
            self.set_progress(target)
            return
        self._anim.setStartValue(start)
        self._anim.setEndValue(target)
        self._anim.start()

    def is_checked(self) -> bool:
        return self._checked

    def toggle(self) -> None:
        self.set_checked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        rect = QRectF(0, 0, w, h)
        t = self._progress
        c1 = QColor(self._colors["surface_alt"])
        c2 = QColor(self._colors["accent"])
        bg_color = QColor(
            int(c1.red() + (c2.red() - c1.red()) * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue() + (c2.blue() - c1.blue()) * t),
        )
        b1 = QColor(self._colors["border_hi"])
        b2 = QColor(self._colors["accent"])
        border_color = QColor(
            int(b1.red() + (b2.red() - b1.red()) * t),
            int(b1.green() + (b2.green() - b1.green()) * t),
            int(b1.blue() + (b2.blue() - b1.blue()) * t),
        )
        p.setBrush(QBrush(bg_color))
        p.setPen(QPen(border_color, 1))
        p.drawRoundedRect(rect, 3.0, 3.0)

        if t > 0.0:
            p.setPen(QPen(QColor("#FFFFFF"), 2, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p1 = QPointF(w * 0.25, h * 0.50)
            p2 = QPointF(w * 0.44, h * 0.69)
            p3 = QPointF(w * 0.75, h * 0.31)
            path = QPainterPath()
            path.moveTo(p1)
            if t < 0.5:
                t1 = t / 0.5
                path.lineTo(p1.x() + (p2.x() - p1.x()) * t1,
                            p1.y() + (p2.y() - p1.y()) * t1)
            else:
                path.lineTo(p2)
                t2 = (t - 0.5) / 0.5
                path.lineTo(p2.x() + (p3.x() - p2.x()) * t2,
                            p2.y() + (p3.y() - p2.y()) * t2)
            p.setOpacity(max(0.0, min(1.0, t * 1.5)))
            p.drawPath(path)
        p.end()


# ==========================================
# ANIMATED CHECK BOX
# ==========================================

class AnimatedCheckBox(QWidget):
    toggled = Signal(bool)

    def __init__(self, text: str, colors: Dict[str, str], parent=None):
        super().__init__(parent)
        self._colors = colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._box = AnimatedCheckIndicator(colors, 16)
        self._label = QLabel(text)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._box)
        layout.addWidget(self._label)
        layout.addStretch()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._box.toggle()
            self.toggled.emit(self._box.is_checked())

    def set_checked(self, checked):
        self._box.set_checked(checked)

    def is_checked(self):
        return self._box.is_checked()


# ==========================================
# FADE-IN DIALOG
# ==========================================

class FadeInDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._is_closing = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._is_closing:
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()

    def closeEvent(self, event):
        if not self._is_closing:
            self._is_closing = True
            event.ignore()
            self._fade_anim.stop()
            self._fade_anim.setStartValue(self.windowOpacity())
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.start()
        else:
            super().closeEvent(event)

    def _on_fade_finished(self):
        if self._is_closing:
            super().close()


# ==========================================
# ADMIN WARNING DIALOG
# ==========================================

class AdminWarningDialog(FadeInDialog):
    def __init__(self, colors: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sea Angler Assist (Warning)")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowCloseButtonHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.C = colors
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(self._make_label("Administrator Privileges Recommended", "DialogTitle"))
        msg = QLabel("Without them, window mode detection and keyboard hotkeys won't work in-game.\nInput remains unaffected.")
        msg.setObjectName("DialogMessage")
        msg.setWordWrap(True)
        layout.addWidget(msg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 10, 0, 0)
        btn_layout.addStretch()
        proceed_btn = PolishedButton("Proceed Anyway")
        proceed_btn.setObjectName("ProceedBtn")
        proceed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        proceed_btn.clicked.connect(self.reject)
        btn_layout.addWidget(proceed_btn)
        restart_btn = PolishedButton("Restart as Admin")
        restart_btn.setObjectName("RestartBtn")
        restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restart_btn.clicked.connect(self.accept)
        btn_layout.addWidget(restart_btn)
        layout.addLayout(btn_layout)

    def _make_label(self, text, obj_name):
        lbl = QLabel(text)
        lbl.setObjectName(obj_name)
        return lbl

    def _apply_style(self) -> None:
        C = self.C
        self.setStyleSheet(f"""
            QDialog {{ background-color: {C['bg']}; }}
            QLabel#DialogTitle {{ color: {C['text']}; font-family: '{FONT_FAMILY}'; font-size: 12pt; font-weight: bold; }}
            QLabel#DialogMessage {{ color: {C['text_subtle']}; font-family: '{FONT_FAMILY}'; font-size: 10pt; }}
            QPushButton#ProceedBtn {{ background-color: {C['surface_alt']}; color: {C['text']}; border: 1px solid {C['border_hi']}; border-radius: 4px; padding: 8px 16px; font-family: '{FONT_FAMILY}'; font-size: 10pt; font-weight: bold; }}
            QPushButton#ProceedBtn:hover {{ background-color: {C['border_hi']}; }}
            QPushButton#ProceedBtn:pressed {{ padding-top: 9px; padding-bottom: 7px; }}
            QPushButton#RestartBtn {{ background-color: {C['accent']}; color: {C['bg']}; border: none; border-radius: 4px; padding: 8px 16px; font-family: '{FONT_FAMILY}'; font-size: 10pt; font-weight: bold; }}
            QPushButton#RestartBtn:hover {{ background-color: {C['accent_hover']}; }}
            QPushButton#RestartBtn:pressed {{ padding-top: 9px; padding-bottom: 7px; }}
        """)


# ==========================================
# UPDATE PROMPT DIALOG
# ==========================================

class UpdatePromptDialog(FadeInDialog):
    def __init__(self, summary_text: str, colors: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sea Angler Assist (Update Available)")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowCloseButtonHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.C = colors
        self.summary_text = summary_text
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(self._make_label("Update Available", "DialogTitle"))
        msg = QLabel("A new version of Sea Angler Assist is available.")
        msg.setObjectName("DialogMessage")
        msg.setWordWrap(True)
        layout.addWidget(msg)
        summary = QPlainTextEdit()
        summary.setObjectName("SummaryText")
        summary.setPlainText(self.summary_text)
        summary.setReadOnly(True)
        summary.setMaximumHeight(150)
        layout.addWidget(summary)
        details = QLabel("Your settings will not be affected. Apply this update?")
        details.setObjectName("DialogMessage")
        details.setWordWrap(True)
        layout.addWidget(details)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 10, 0, 0)
        btn_layout.addStretch()
        skip_btn = PolishedButton("Skip for Now")
        skip_btn.setObjectName("SkipBtn")
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(skip_btn)
        apply_btn = PolishedButton("Apply Update")
        apply_btn.setObjectName("ApplyBtn")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)
        layout.addLayout(btn_layout)

    def _make_label(self, text, obj_name):
        lbl = QLabel(text)
        lbl.setObjectName(obj_name)
        return lbl

    def _apply_style(self) -> None:
        C = self.C
        self.setStyleSheet(f"""
            QDialog {{ background-color: {C['bg']}; }}
            QLabel#DialogTitle {{ color: {C['text']}; font-family: '{FONT_FAMILY}'; font-size: 12pt; font-weight: bold; }}
            QLabel#DialogMessage {{ color: {C['text_subtle']}; font-family: '{FONT_FAMILY}'; font-size: 10pt; }}
            QPlainTextEdit#SummaryText {{ background-color: {C['surface_alt']}; color: {C['text_muted']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 8px; font-family: '{FONT_MONO}'; font-size: 9pt; }}
            QPushButton#SkipBtn {{ background-color: {C['surface_alt']}; color: {C['text']}; border: 1px solid {C['border_hi']}; border-radius: 4px; padding: 8px 16px; font-family: '{FONT_FAMILY}'; font-size: 10pt; font-weight: bold; }}
            QPushButton#SkipBtn:hover {{ background-color: {C['border_hi']}; }}
            QPushButton#SkipBtn:pressed {{ padding-top: 9px; padding-bottom: 7px; }}
            QPushButton#ApplyBtn {{ background-color: {C['accent']}; color: {C['bg']}; border: none; border-radius: 4px; padding: 8px 16px; font-family: '{FONT_FAMILY}'; font-size: 10pt; font-weight: bold; }}
            QPushButton#ApplyBtn:hover {{ background-color: {C['accent_hover']}; }}
            QPushButton#ApplyBtn:pressed {{ padding-top: 9px; padding-bottom: 7px; }}
        """)


# ==========================================
# CATCH BURST
# ==========================================

class CatchBurst(QWidget):
    def __init__(self, parent: QWidget, accent_color: str = "#FA468E"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._accent = QColor(accent_color)
        self._text_color = QColor("#FFFFFF")
        self._t = 0.0
        self._duration_ms = 850
        self._ring_radius = 0.0
        self._ring2_radius = 0.0
        self._ring_color = QColor(self._accent)
        self._ring2_color = QColor(self._accent)
        self._flash_opacity = 0.0
        self._plus_opacity = 1.0
        self._plus_y_offset = 0.0
        self.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def play(self) -> None:
        parent = self.parent()
        if isinstance(parent, QWidget):
            self.setGeometry(parent.rect())
        else:
            self.setGeometry(self.rect())
        self._t = 0.0
        self._ring_radius = 0.0
        self._ring2_radius = 0.0
        self._flash_opacity = 0.4
        self._plus_opacity = 1.0
        self._plus_y_offset = 0.0
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self) -> None:
        self._t += 16 / self._duration_ms
        if self._t >= 1.0:
            self._timer.stop()
            self.hide()
            return
        self._ring_radius = 80 * (1 - (1 - self._t) ** 3)
        ring_alpha = int(255 * (1 - self._t))
        self._ring_color = QColor(self._accent.red(), self._accent.green(),
                                  self._accent.blue(), max(0, ring_alpha))
        if self._t > 0.15:
            t2 = (self._t - 0.15) / 0.85
            self._ring2_radius = 50 * (1 - (1 - t2) ** 3)
            ring2_alpha = int(180 * (1 - t2))
            self._ring2_color = QColor(self._accent.red(), self._accent.green(),
                                       self._accent.blue(), max(0, ring2_alpha))
        else:
            self._ring2_radius = 0.0
        if self._t < 0.2:
            self._flash_opacity = 0.4 * (1 - self._t / 0.2)
        else:
            self._flash_opacity = 0.0
        self._plus_opacity = max(0.0, 1.0 - self._t * 1.2)
        self._plus_y_offset = -50 * (1 - (1 - self._t) ** 2)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2
        cy = self.height() // 2
        if self._flash_opacity > 0.0:
            flash_color = QColor(self._accent)
            flash_color.setAlphaF(self._flash_opacity)
            p.fillRect(self.rect(), flash_color)
        if self._t < 1.0 and self._ring_radius > 0:
            p.setPen(QPen(self._ring_color, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPoint(cx, cy), int(self._ring_radius), int(self._ring_radius))
        if self._ring2_radius > 0:
            p.setPen(QPen(self._ring2_color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPoint(cx, cy), int(self._ring2_radius), int(self._ring2_radius))
        num_particles = 8
        for i in range(num_particles):
            angle = (2 * math.pi * i) / num_particles + self._t * 0.5
            particle_t = min(1.0, self._t * 1.5)
            dist = 90 * (1 - (1 - particle_t) ** 2)
            px = cx + math.cos(angle) * dist
            py = cy + math.sin(angle) * dist
            p_size = max(0.0, 5.0 * (1 - self._t))
            p_alpha = int(255 * max(0.0, 1.0 - self._t * 1.2))
            if p_size > 0 and p_alpha > 0:
                p_color = QColor(self._accent)
                p_color.setAlpha(p_alpha)
                p.setBrush(QBrush(p_color))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(px, py), p_size, p_size)
        if self._plus_opacity > 0.0:
            color = QColor(self._text_color)
            color.setAlphaF(self._plus_opacity)
            p.setPen(color)
            font = QFont(FONT_FAMILY, 32, QFont.Weight.Bold)
            p.setFont(font)
            rect = QRectF(0, cy + self._plus_y_offset - 30, self.width(), 60)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "+1 FISH")
        p.end()


# ==========================================
# TOAST
# ==========================================

class Toast(QWidget):
    request_close = Signal()
    COLORS = {
        "info": ("#FA468E", "#0B0E14"),
        "success": ("#21A28F", "#0B0E14"),
        "warning": ("#FFB610", "#0B0E14"),
        "error": ("#EF4444", "#FFFFFF"),
    }

    def __init__(self, message: str, kind: str = "info", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._kind = kind
        self._build(message)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._fade_in = QPropertyAnimation(self._effect, b"opacity")
        self._fade_in.setDuration(200)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_out = QPropertyAnimation(self._effect, b"opacity")
        self._fade_out.setDuration(350)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_out.finished.connect(self.deleteLater)
        self._slide_anim: Optional[QPropertyAnimation] = None
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._start_fade_out)

    def _build(self, message: str) -> None:
        accent, text = self.COLORS.get(self._kind, self.COLORS["info"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        self._bar = QFrame()
        self._bar.setFixedWidth(4)
        self._bar.setStyleSheet(f"background-color: {accent}; border: none;")
        layout.addWidget(self._bar)
        lbl = QLabel(message)
        lbl.setStyleSheet(f"color: {text}; background: transparent; font-family: '{FONT_FAMILY}'; font-size: 10pt; font-weight: bold;")
        lbl.setWordWrap(False)
        layout.addWidget(lbl)
        self.setStyleSheet("QWidget { background-color: #11161F; border: 1px solid #2A313F; border-radius: 6px; }")
        self.adjustSize()

    def popup(self, anchor_widget: QWidget, y_offset: int = 0) -> None:
        if anchor_widget is None:
            return
        anchor_rect = anchor_widget.frameGeometry()
        end_x = anchor_rect.right() - self.width() - 16
        y = anchor_rect.top() + 16 + y_offset
        start_x = anchor_rect.right() + 20
        self.move(start_x, y)
        self.show()
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(280)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.setStartValue(QPoint(start_x, y))
        self._slide_anim.setEndValue(QPoint(end_x, y))
        self._slide_anim.start()
        self._fade_in.stop()
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()
        self._dismiss_timer.start(2800)

    def _start_fade_out(self) -> None:
        self._fade_out.stop()
        self._fade_out.setStartValue(self._effect.opacity())
        self._fade_out.setEndValue(0.0)
        self._fade_out.start()
        if self._slide_anim is not None:
            self._slide_anim.stop()
            cur_pos = self.pos()
            self._slide_anim.setDuration(300)
            self._slide_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self._slide_anim.setStartValue(cur_pos)
            self._slide_anim.setEndValue(QPoint(cur_pos.x() + 30, cur_pos.y()))
            self._slide_anim.start()


# ==========================================
# TOAST MANAGER
# ==========================================

class ToastManager:
    def __init__(self, anchor: QWidget) -> None:
        self._anchor = anchor
        self._active: List[Toast] = []
        self._queue: List[Tuple[str, str]] = []
        self._spacing = 8

    def show(self, message: str, kind: str = "info") -> None:
        self._queue.append((message, kind))
        self._drain()

    def _drain(self) -> None:
        if not self._queue:
            return
        if any(t.isVisible() for t in self._active):
            return
        msg, kind = self._queue.pop(0)
        toast = Toast(msg, kind, self._anchor)
        toast.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        offset = self._spacing
        for t in self._active:
            offset += t.height() + self._spacing
        toast.popup(self._anchor, y_offset=offset)
        self._active.append(toast)
        toast._fade_out.finished.connect(lambda t=toast: self._on_close(t))

    def _on_close(self, toast: Toast) -> None:
        if toast in self._active:
            self._active.remove(toast)
        self._drain()