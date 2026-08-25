from __future__ import annotations

import colorsys
import os
import re
import sys
import threading
from ctypes import wintypes
from typing import Callable, Dict, List, Optional, Any, Tuple

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    Qt,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    QRectF,
    QEvent,
    QTimer,
    QByteArray,
    QVariantAnimation,
    QRect,
    QSize,
    QSignalBlocker,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QPainter,
    QPen,
    QBrush,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    QGraphicsOpacityEffect,
    QGraphicsEffect,
)

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None

from observables import (
    ObservableBool,
    ObservableInt,
    ObservableStr,
)
from paths import bundled_resource
from config import (
    get_baits,
    DEBUG_WINDOW_H,
    RARITY_COLORS,
    WINDOW_H,
    WINDOW_W,
    WINDOW_X_PCT,
    WINDOW_Y_PCT,
    SIDEBAR_WIDTH,
    DROPDOWN_WIDTH,
    GEAR_SIZE,
)
from widgets import (
    LogView,
    SwitchButton,
    AdminWarningDialog,
    UpdatePromptDialog,
    CHECK_URL,
    PolishedButton,
    AnimatedMenu,
    CatchBurst,
    Toast,
    ToastManager,
    AnimatedCheckIndicator,
)
from styles import get_app_qss


ICON_PATH: str = bundled_resource("icon.ico")
SETTINGS_ICON_PATH: str = bundled_resource("ui", "settings.svg")

FONT_FAMILY: str = "Inter"


# ============================================================
# MOTION CONSTANTS (Refined)
# ============================================================

ANIM_FAST_MS = 100
ANIM_QUICK_MS = 160
ANIM_BASE_MS = 220
ANIM_POP_MS = 260
ANIM_MEDIUM_MS = 340
ANIM_SLOW_MS = 400
ANIM_COUNT_MS = 450
ANIM_MILESTONE_MS = 600
ANIM_BREATH_MS = 2600

BAIT_CHECK_ANIM_MS = 280  # 300 -> 280

EASE_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)
EASE_IN_OUT = QEasingCurve(QEasingCurve.Type.InOutCubic)
EASE_IN_OUT_SINE = QEasingCurve(QEasingCurve.Type.InOutSine)
EASE_OUT_BACK = QEasingCurve(QEasingCurve.Type.OutBack)
EASE_IN_OUT_QUAD = QEasingCurve(QEasingCurve.Type.InOutQuad)


# ============================================================
# FONT LOADING
# ============================================================

def load_custom_fonts() -> Tuple[str, str]:
    main_family = "Inter"
    mono_family = "Consolas"

    main_font_path = bundled_resource("fonts", "AlbertSans.ttf")
    main_id = QFontDatabase.addApplicationFont(main_font_path)

    if main_id != -1:
        families = QFontDatabase.applicationFontFamilies(main_id)
        if families:
            main_family = families[0]

    mono_font_path = bundled_resource("fonts", "ShareTechMono.ttf")
    mono_id = QFontDatabase.addApplicationFont(mono_font_path)

    if mono_id != -1:
        families = QFontDatabase.applicationFontFamilies(mono_id)
        if families:
            mono_family = families[0]

    return main_family, mono_family


def _shade(hex_color: str, lightness_offset: float) -> str:
    value = hex_color.lstrip("#")

    if len(value) != 6:
        raise ValueError(
            f"Expected a 6-digit hex color, got {hex_color!r}"
        )

    r = int(value[0:2], 16) / 255.0
    g = int(value[2:4], 16) / 255.0
    b = int(value[4:6], 16) / 255.0

    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + lightness_offset))

    r, g, b = colorsys.hls_to_rgb(h, l, s)

    return (
        f"#{round(r * 255):02X}"
        f"{round(g * 255):02X}"
        f"{round(b * 255):02X}"
    )


# ============================================================
# SELECTABLE BAIT WIDGET
# ============================================================

class SelectableBaitWidget(QWidget):
    """
    Custom bait selection row that uses the same checkbox widget
    as the settings dialog for consistent animation and appearance.
    """

    def __init__(
        self,
        bait_name: str = "",
        accent_color: str = "#FA468E",
        is_checked: bool = False,
        on_toggle: Optional[Callable[[bool], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._bait_name = str(bait_name)
        self._accent_color = QColor(accent_color)
        self._on_toggle = on_toggle

        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        # Use main font (Inter) 9pt bold (same as EQUIPPED buttons)
        font = QFont(FONT_FAMILY, 9, QFont.Weight.Bold)
        self.setFont(font)

        # Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        # Checkbox indicator (reuse the settings one)
        self.indicator = AnimatedCheckIndicator(
            {
                "surface_alt": "#161C27",
                "border_hi": "#2A313F",
                "accent": accent_color,
            },
            size=16,
            parent=self,
        )
        self.indicator.set_checked(is_checked, animate=False)
        self.indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.indicator.toggled.connect(self._on_indicator_toggled)

        # Label
        self.label = QLabel(self._bait_name)
        self.label.setStyleSheet(
            f"""
            color: {accent_color};
            background: transparent;
            font-family: '{FONT_FAMILY}';
            font-size: 9pt;
            font-weight: bold;
            """
        )
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.indicator)
        layout.addWidget(self.label)
        layout.addStretch()

        # Hover animation
        self._hover_alpha = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover_alpha)

    def _set_hover_alpha(self, v):
        self._hover_alpha = float(v)
        self.update()

    def _on_indicator_toggled(self, checked: bool):
        if self._on_toggle is not None:
            self._on_toggle(checked)

    # --------------------------------------------------------
    # Public state API
    # --------------------------------------------------------

    def is_checked(self) -> bool:
        return self.indicator.is_checked()

    def set_checked(self, checked: bool, animate: bool = True) -> None:
        self.indicator.set_checked(checked, animate=animate)

    def set_checked_immediate(self, checked: bool) -> None:
        self.indicator.set_checked(checked, animate=False)

    def toggle(self) -> None:
        self.indicator.toggle()

    # --------------------------------------------------------
    # Size hints for QWidgetAction
    # --------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(200, 34)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 34)

    # --------------------------------------------------------
    # Painting (background and hover)
    # --------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#11161F"))
        painter.drawRoundedRect(rect, 4, 4)

        # Hover background
        if self._hover_alpha > 0.0:
            color = QColor("#161C27")
            color.setAlphaF(self._hover_alpha)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 4, 4)

        super().paintEvent(event)

    # --------------------------------------------------------
    # Mouse events
    # --------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.indicator.mousePressEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.indicator.mouseReleaseEvent(event)
        event.accept()


# ============================================================
# SCALABLE LABEL
# ============================================================

class ScalableLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._scale = 1.0
        self._base_font: Optional[QFont] = None

        self._anim = QPropertyAnimation(
            self,
            b"scaleFactor",
            self,
        )
        self._anim.setDuration(ANIM_BASE_MS)
        self._anim.setEasingCurve(EASE_OUT)

    def get_scale(self):
        return self._scale

    def set_scale(self, val):
        self._scale = val

        if self._base_font is None:
            self._base_font = QFont(self.font())

        font = QFont(self._base_font)

        font.setPointSizeF(
            max(
                1.0,
                self._base_font.pointSizeF() * val,
            )
        )

        self.setFont(font)

    scaleFactor = Property(
        float,
        get_scale,
        set_scale,
    )

    def pop(self):
        self._anim.stop()
        self._anim.setDuration(ANIM_POP_MS)
        self._anim.setEasingCurve(EASE_OUT)

        self._anim.setKeyValues([
            (0.0, 1.0),
            (0.4, 1.10),
            (1.0, 1.0),
        ])

        self._anim.start()

    def milestone_pop(self):
        self._anim.stop()
        self._anim.setDuration(ANIM_MILESTONE_MS)
        self._anim.setEasingCurve(EASE_OUT)

        self._anim.setKeyValues([
            (0.0, 1.0),
            (0.2, 1.25),
            (0.55, 0.97),
            (1.0, 1.0),
        ])

        self._anim.start()

    def reset_pop(self):
        self._anim.stop()
        self._anim.setDuration(ANIM_POP_MS)
        self._anim.setEasingCurve(EASE_OUT)

        self._anim.setKeyValues([
            (0.0, 1.0),
            (0.4, 1.10),
            (1.0, 1.0),
        ])


# ============================================================
# FADING LABEL
# ============================================================

class FadingLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(1.0)

        self._fade_anim = QPropertyAnimation(
            self._effect,
            b"opacity",
        )
        self._fade_anim.setDuration(ANIM_QUICK_MS)
        self._fade_anim.setEasingCurve(EASE_IN_OUT)
        self._fade_anim.finished.connect(
            self._on_fade_finished
        )

        self._breath_anim = QPropertyAnimation(
            self._effect,
            b"opacity",
        )
        self._breath_anim.setDuration(ANIM_BREATH_MS)
        self._breath_anim.setEasingCurve(EASE_IN_OUT_SINE)
        self._breath_anim.setStartValue(1.0)
        self._breath_anim.setKeyValueAt(0.5, 0.65)
        self._breath_anim.setEndValue(1.0)
        self._breath_anim.setLoopCount(-1)

        self._is_breathing = False
        self._was_breathing = False
        self._pending_text = ""
        self._fade_state = 0

    def setTextFade(self, text):
        if self.text() == text:
            if (
                self._is_breathing
                and self._breath_anim.state()
                != QPropertyAnimation.State.Running
            ):
                self._breath_anim.start()
            return

        self._was_breathing = self._is_breathing

        if self._is_breathing:
            self._breath_anim.stop()

        self._pending_text = text
        self._fade_state = 1

        self._fade_anim.stop()
        self._fade_anim.setStartValue(
            self._effect.opacity()
        )
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self):
        if self._fade_state == 1:
            self.setText(self._pending_text)
            self._fade_state = 2

            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()

        elif self._fade_state == 2:
            self._fade_state = 0

            if (
                self._was_breathing
                and self._breath_anim.state()
                != QPropertyAnimation.State.Running
            ):
                self._breath_anim.start()

    def start_breathing(self):
        self._is_breathing = True
        self._fade_anim.stop()
        self._effect.setOpacity(1.0)
        self._breath_anim.start()

    def stop_breathing(self):
        self._is_breathing = False
        self._breath_anim.stop()
        self._effect.setOpacity(1.0)


# ============================================================
# GEAR HOVER FILTER
# ============================================================

class _GearHoverFilter(QObject):
    def __init__(self, button: PolishedButton, scale: float):
        super().__init__(button)

        self._button = button
        self._scale = scale

        self._anim = QPropertyAnimation(
            button,
            b"scaleFactor",
            button,
        )
        self._anim.setDuration(ANIM_QUICK_MS)
        self._anim.setEasingCurve(EASE_OUT)

    def eventFilter(self, obj, event):
        if obj is self._button:
            if event.type() == QEvent.Type.Enter:
                self._animate_to(self._scale)

            elif event.type() == QEvent.Type.Leave:
                self._animate_to(1.0)

        return False

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(
            self._button.scaleFactor
        )
        self._anim.setEndValue(target)
        self._anim.start()


# ============================================================
# BAIT MENU DRAG FILTER (ANIMATION ENABLED)
# ============================================================

class _BaitMenuDragFilter(QObject):
    """
    Handles mouse/touch interaction for bait selection.

    All updates (both single clicks and drags) now animate the checkbox
    for a smooth, consistent experience.
    """

    def __init__(
        self,
        ui,
        bait_widgets,
        bait_vars,
        on_change=None,
    ):
        super().__init__()

        self._ui = ui
        self._widgets = bait_widgets
        self._vars = bait_vars
        self._on_change = on_change

        self._widget_index = {
            widget: index
            for index, widget in enumerate(bait_widgets)
        }

        self._touch_active = False
        self._press_active = False
        self._drag_active = False

        self._anchor_idx = -1
        self._current_idx = -1
        self._target_state = False

        self._original_states: List[bool] = []
        self._press_pos = QPoint()
        self._dirty = False

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _find_selectable_widget(self, widget):
        while widget is not None:
            if isinstance(widget, SelectableBaitWidget):
                return widget

            widget = widget.parentWidget()

        return None

    def _find_selectable_index(self, widget):
        selectable = self._find_selectable_widget(widget)

        if selectable is None:
            return -1

        return self._widget_index.get(
            selectable,
            -1,
        )

    def _menu_visible(self) -> bool:
        menu = getattr(
            self._ui,
            "_bait_menu",
            None,
        )

        return (
            menu is not None
            and menu.isVisible()
        )

    @staticmethod
    def _mouse_global_pos(event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()

        if hasattr(event, "globalPos"):
            return event.globalPos()

        return None

    @staticmethod
    def _touch_global_pos(event):
        points = (
            event.points()
            if hasattr(event, "points")
            else []
        )

        if not points:
            return None

        return points[0].globalPosition().toPoint()

    # --------------------------------------------------------
    # Interaction state
    # --------------------------------------------------------

    def _begin_press(
        self,
        idx: int,
        pos: QPoint,
    ) -> None:
        self._press_active = True
        self._drag_active = False

        self._anchor_idx = idx
        self._current_idx = idx
        self._press_pos = pos

        self._original_states = [
            bool(variable.get())
            for variable in self._vars
        ]

        self._target_state = (
            not self._original_states[idx]
        )

    def _activate_drag(self, pos: QPoint) -> None:
        self._drag_active = True

        # First item changes with animation
        if self._set_widget_state(
            self._anchor_idx,
            self._target_state,
        ):
            self._dirty = True

        widget = QApplication.widgetAt(pos)

        idx = self._find_selectable_index(widget)

        if (
            idx != -1
            and idx != self._current_idx
        ):
            self._update_range(
                self._current_idx,
                idx,
            )
            self._current_idx = idx

    def _update_drag(self, pos: QPoint) -> None:
        if not self._drag_active:
            distance = (
                pos - self._press_pos
            ).manhattanLength()

            if distance > QApplication.startDragDistance():
                self._activate_drag(pos)

            return

        widget = QApplication.widgetAt(pos)

        idx = self._find_selectable_index(widget)

        if (
            idx != -1
            and idx != self._current_idx
        ):
            self._update_range(
                self._current_idx,
                idx,
            )
            self._current_idx = idx

    # --------------------------------------------------------
    # Drag range
    # --------------------------------------------------------

    def _update_range(
        self,
        old_idx: int,
        new_idx: int,
    ) -> None:
        """
        Incrementally update the crossed range.

        Items inside anchor -> new index receive the drag target state.
        Items crossed back over receive their original state.
        """

        start = min(old_idx, new_idx)
        end = max(old_idx, new_idx)

        changed = False

        anchor_start = min(
            self._anchor_idx,
            new_idx,
        )
        anchor_end = max(
            self._anchor_idx,
            new_idx,
        )

        for index in range(start, end + 1):
            in_selection = (
                anchor_start
                <= index
                <= anchor_end
            )

            if in_selection:
                if self._set_widget_state(
                    index,
                    self._target_state,
                ):
                    changed = True
            else:
                if self._set_widget_state(
                    index,
                    self._original_states[index],
                ):
                    changed = True

        if changed:
            self._dirty = True

    # --------------------------------------------------------
    # State setter (animated)
    # --------------------------------------------------------

    def _set_widget_state(
        self,
        idx: int,
        state: bool,
    ) -> bool:
        """
        Set the state of a widget, always with animation.
        """
        if idx < 0 or idx >= len(self._widgets):
            return False

        state = bool(state)

        current = bool(
            self._vars[idx].get()
        )

        if current == state:
            return False

        # Data model first.
        self._vars[idx].set(state)

        # Visual state second (always animated)
        widget = self._widgets[idx]

        set_checked = getattr(
            widget,
            "set_checked",
            None,
        )

        if callable(set_checked):
            try:
                set_checked(
                    state,
                    animate=True,
                )
            except TypeError:
                set_checked(state)

        # Fallback: if set_checked doesn't exist, try immediate
        else:
            set_immediate = getattr(
                widget,
                "set_checked_immediate",
                None,
            )

            if callable(set_immediate):
                set_immediate(state)

            widget.update()

        return True

    # --------------------------------------------------------
    # Completion
    # --------------------------------------------------------

    def _flush_change(self) -> None:
        if (
            self._dirty
            and self._on_change is not None
        ):
            self._on_change()

        self._dirty = False

    def _handle_release(self, idx: int) -> None:
        if self._drag_active:
            self._finish_interaction()
            return

        # ----------------------------------------------------
        # NORMAL SINGLE CLICK
        # ----------------------------------------------------

        if (
            idx == self._anchor_idx
            and self._anchor_idx != -1
        ):
            target = self._target_state
            widget = self._widgets[idx]

            # Update the authoritative data state.
            self._vars[idx].set(target)

            # IMPORTANT:
            # Normal clicks use the animated path.
            set_checked = getattr(
                widget,
                "set_checked",
                None,
            )

            if callable(set_checked):
                try:
                    set_checked(
                        target,
                        animate=True,
                    )
                except TypeError:
                    set_checked(target)

            else:
                # Defensive fallback.
                set_immediate = getattr(
                    widget,
                    "set_checked_immediate",
                    None,
                )

                if callable(set_immediate):
                    set_immediate(target)

            self._dirty = True

        self._finish_interaction()

    def _finish_interaction(self) -> None:
        self._flush_change()
        self._reset_state()

    def _reset_state(self) -> None:
        self._press_active = False
        self._drag_active = False

        self._anchor_idx = -1
        self._current_idx = -1

        self._original_states = []
        self._press_pos = QPoint()

        self._dirty = False

    # --------------------------------------------------------
    # Event filter
    # --------------------------------------------------------

    def eventFilter(self, obj, event):
        event_type = event.type()

        # Touch-generated mouse events must not cause a second toggle.
        if self._touch_active:
            if event_type in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseMove,
            ):
                return True

            if event_type not in (
                QEvent.Type.TouchBegin,
                QEvent.Type.TouchUpdate,
                QEvent.Type.TouchEnd,
                QEvent.Type.TouchCancel,
            ):
                return False

        # ----------------------------------------------------
        # TOUCH BEGIN
        # ----------------------------------------------------

        if event_type == QEvent.Type.TouchBegin:
            if not self._menu_visible():
                return False

            pos = self._touch_global_pos(event)

            if pos is None:
                return False

            widget = QApplication.widgetAt(pos)

            idx = self._find_selectable_index(widget)

            if idx != -1:
                self._begin_press(idx, pos)
                self._touch_active = True
                return True

            return False

        # ----------------------------------------------------
        # TOUCH UPDATE
        # ----------------------------------------------------

        if event_type == QEvent.Type.TouchUpdate:
            if (
                not self._touch_active
                or not self._press_active
            ):
                return False

            pos = self._touch_global_pos(event)

            if pos is not None:
                self._update_drag(pos)

            return True

        # ----------------------------------------------------
        # TOUCH END
        # ----------------------------------------------------

        if event_type == QEvent.Type.TouchEnd:
            if not self._touch_active:
                return False

            pos = self._touch_global_pos(event)

            idx = -1

            if pos is not None:
                widget = QApplication.widgetAt(pos)
                idx = self._find_selectable_index(widget)

            self._handle_release(idx)

            self._touch_active = False

            return True

        # ----------------------------------------------------
        # TOUCH CANCEL
        # ----------------------------------------------------

        if event_type == QEvent.Type.TouchCancel:
            self._reset_state()
            self._touch_active = False
            return True

        # ----------------------------------------------------
        # MOUSE PRESS
        # ----------------------------------------------------

        if (
            event_type == QEvent.Type.MouseButtonPress
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            if not self._menu_visible():
                return False

            pos = self._mouse_global_pos(event)

            if pos is None:
                return False

            widget = QApplication.widgetAt(pos)

            idx = self._find_selectable_index(widget)

            if idx != -1:
                self._begin_press(idx, pos)
                return True

            return False

        # ----------------------------------------------------
        # MOUSE MOVE
        # ----------------------------------------------------

        if event_type == QEvent.Type.MouseMove:
            if self._press_active:
                pos = self._mouse_global_pos(event)

                if pos is not None:
                    self._update_drag(pos)

                return True

            return False

        # ----------------------------------------------------
        # MOUSE RELEASE
        # ----------------------------------------------------

        if (
            event_type
            == QEvent.Type.MouseButtonRelease
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            if not self._press_active:
                return False

            pos = self._mouse_global_pos(event)

            idx = -1

            if pos is not None:
                widget = QApplication.widgetAt(pos)
                idx = self._find_selectable_index(widget)

            self._handle_release(idx)

            return True

        # ----------------------------------------------------
        # DOUBLE CLICK
        # ----------------------------------------------------

        if event_type == QEvent.Type.MouseButtonDblClick:
            if self._press_active:
                return True

            return False

        return False


# ============================================================
# MAIN WINDOW
# ============================================================

class FishingUI(QMainWindow):
    _BASE: Dict[str, str] = {
        "bg": "#0B0E14",
        "surface": "#11161F",
        "surface_alt": "#161C27",
        "border": "#1E2530",
        "border_hi": "#2A313F",
        "text": "#E7E7E7",
        "text_muted": "#64748B",
        "text_subtle": "#94A3B8",
        "accent": "#FA468E",
        "danger": "#9B1C47",
    }

    C: Dict[str, str] = {
        **_BASE,
        "accent_hover": _shade(
            _BASE["accent"],
            0.15,
        ),
        "accent_dim": _shade(
            _BASE["accent"],
            -0.10,
        ),
        "accent_muted": _shade(
            _BASE["accent"],
            -0.35,
        ),
        "danger_dim": _shade(
            _BASE["danger"],
            -0.10,
        ),
    }

    PAD_SM = 6
    PAD_MD = 10

    running: bool = False
    _tray_manager = None
    _force_quit: bool = False
    _hotkey_manager: Any = None

    _FISH_MILESTONES = (
        10,
        25,
        50,
        100,
        250,
        500,
        1000,
    )

    def stop(self) -> None:
        raise NotImplementedError

    def toggle(self) -> None:
        raise NotImplementedError

    def focus_game_window(self) -> bool:
        raise NotImplementedError

    def equip_next_bait(self) -> bool:
        raise NotImplementedError

    def auto_detect_baits(self) -> bool:
        raise NotImplementedError

    # ========================================================
    # WINDOWS HOTKEY
    # ========================================================

    def nativeEvent(
        self,
        eventType: QByteArray,
        message: int,
    ):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(
                int(message)
            )

            if msg.message == 0x0312:
                hotkey_id = msg.wParam

                if (
                    self._hotkey_manager
                    and hotkey_id
                    in self._hotkey_manager.hotkeys
                ):
                    self._hotkey_manager.hotkeys[
                        hotkey_id
                    ]()

                    return True, 0

        return super().nativeEvent(
            eventType,
            message,
        )

    # ========================================================
    # BUILD UI
    # ========================================================

    def build_ui(self) -> None:
        self.app = (
            QApplication.instance()
            or QApplication(sys.argv)
        )

        super().__init__()

        self.setWindowTitle(
            "Sea Angler Assist"
        )

        try:
            self.setWindowIcon(
                QIcon(ICON_PATH)
            )
        except Exception:
            pass

        global FONT_FAMILY

        self.FONT_MAIN, self.FONT_MONO = (
            load_custom_fonts()
        )

        FONT_FAMILY = self.FONT_MAIN

        self.fonts = self._build_fonts()

        self._build_stylesheet()
        self._init_state()
        self._build_widgets()
        self._install_shortcuts()

        self._resize_window_to(
            DEBUG_WINDOW_H
            if self.debug_console_active.get()
            else WINDOW_H
        )

        self.set_mode_colors(False)

        self._sync_console_widgets_to_state()

        self.root = self

        self._install_entrance_fade()

    def _install_entrance_fade(self) -> None:
        self.setWindowOpacity(0.0)

        anim = QPropertyAnimation(
            self,
            b"windowOpacity",
            self,
        )

        anim.setDuration(ANIM_MEDIUM_MS)
        anim.setEasingCurve(EASE_OUT)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        self._entrance_anim = anim

    def showEvent(self, event) -> None:
        super().showEvent(event)

        if hasattr(self, "catch_burst"):
            self.catch_burst.setGeometry(
                self.container.rect()
            )

        height = (
            DEBUG_WINDOW_H
            if self.debug_console_active.get()
            else WINDOW_H
        )

        self._apply_geometry(height)

        anim = getattr(
            self,
            "_entrance_anim",
            None,
        )

        if anim is not None:
            anim.start()
            self._entrance_anim = None

    # ========================================================
    # FONTS / STYLE
    # ========================================================

    def _build_fonts(self) -> Dict[str, QFont]:
        return {
            "title": QFont(
                self.FONT_MAIN,
                14,
                QFont.Weight.Bold,
            ),
            "subtitle": QFont(
                self.FONT_MAIN,
                8,
            ),
            "label": QFont(
                self.FONT_MAIN,
                9,
                QFont.Weight.Bold,
            ),
            "value": QFont(
                self.FONT_MAIN,
                24,
                QFont.Weight.Bold,
            ),
            "status": QFont(
                self.FONT_MAIN,
                16,
                QFont.Weight.Bold,
            ),
            "button": QFont(
                self.FONT_MAIN,
                12,
                QFont.Weight.Bold,
            ),
            "mono": QFont(
                self.FONT_MONO,
                12,
                QFont.Weight.Bold,
            ),
            "log": QFont(
                self.FONT_MONO,
                10,
            ),
        }

    def _build_stylesheet(self) -> None:
        self.QSS = get_app_qss(
            self.C,
            self.FONT_MAIN,
            self.FONT_MONO,
            CHECK_URL,
        )

        self.setStyleSheet(self.QSS)

    # ========================================================
    # STATE
    # ========================================================

    def _init_state(self) -> None:
        from settings import get_settings

        self.settings = get_settings()

        self.auto_bait_var = ObservableBool(False)

        self._sync_baits_from_json()

        self.current_bait_idx = ObservableInt(0)

        self.debug_console_active = ObservableBool(
            self.settings.debug_console.get()
        )

        self.abort_behavior_var = (
            self.settings.ignore_abort
        )

        self.timer_var = ObservableStr(
            "00:00:00"
        )

        self.fish_count_var = ObservableInt(0)

        self.status_var = ObservableStr(
            "Idle"
        )

        self.controller_status_var = (
            ObservableStr("")
        )

        self._displayed_fish_count = 0

        self._console_fade_in_anim = None
        self._console_anim_slot = None

    def _sync_baits_from_json(
        self,
    ) -> List[Dict[str, Any]]:
        baits = list(get_baits())

        old_vars = getattr(
            self,
            "bait_vars",
            [],
        )

        self.bait_vars = [
            (
                old_vars[index]
                if index < len(old_vars)
                else ObservableBool(False)
            )
            for index in range(len(baits))
        ]

        if hasattr(
            self,
            "current_bait_idx",
        ):
            if not baits:
                self.current_bait_idx.set(0)
            else:
                self.current_bait_idx.set(
                    min(
                        self.current_bait_idx.get(),
                        len(baits) - 1,
                    )
                )

        return baits

    # ========================================================
    # MAIN WIDGET TREE
    # ========================================================

    def _build_widgets(self) -> None:
        central = QWidget()
        central.setObjectName("Container")

        self.setCentralWidget(central)

        self.top_rule = QFrame()
        self.top_rule.setObjectName("TopRule")

        self.top_rule.setStyleSheet(
            """
            QFrame#TopRule {
                max-height: 6px;
                min-height: 6px;
            }
            """
        )

        self.container = QWidget()
        self.container.setObjectName("Container")

        body = QVBoxLayout(
            self.container
        )

        body.setContentsMargins(
            16,
            14,
            16,
            14,
        )

        body.setSpacing(0)

        self._build_header(body)
        self._build_divider(body)
        self._build_stats(body)
        self._build_divider(body)
        self._build_bait(body)
        self._build_divider(body)
        self._build_settings(body)
        self._build_log(body)
        self._build_action(body)

        self.catch_burst = CatchBurst(
            self.container
        )

        self.catch_burst.setGeometry(
            self.container.rect()
        )

        self.toast_manager = ToastManager(self)

        main = QVBoxLayout(central)

        main.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        main.setSpacing(0)

        main.addWidget(self.top_rule)
        main.addWidget(self.container)

    # ========================================================
    # SHORTCUTS
    # ========================================================

    def _install_shortcuts(self) -> None:
        shortcut = QShortcut(
            QKeySequence(
                Qt.Key.Key_Escape
            ),
            self,
        )

        shortcut.activated.connect(
            self._on_escape
        )

    # ========================================================
    # LABEL HELPERS
    # ========================================================

    def _make_label(
        self,
        text: str,
        font_key: str,
        muted: bool = False,
    ) -> QLabel:
        label = QLabel(text)
        label.setFont(
            self.fonts[font_key]
        )

        if muted:
            label.setObjectName("Muted")

        return label

    def _build_divider(
        self,
        parent: QVBoxLayout,
    ) -> None:
        divider = QFrame()
        divider.setObjectName("Divider")

        parent.addWidget(divider)
        parent.addSpacing(self.PAD_MD)

    # ========================================================
    # HEADER
    # ========================================================

    def _build_header(
        self,
        parent: QVBoxLayout,
    ) -> None:
        grid = QGridLayout()

        grid.setContentsMargins(
            0,
            0,
            0,
            self.PAD_MD,
        )

        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(1)

        title = self._make_label(
            "Sea Angler Assist",
            "title",
        )

        subtitle = self._make_label(
            "by fefuccio <3",
            "subtitle",
            muted=True,
        )

        self._timer_lbl = self._make_label(
            "00:00:00",
            "mono",
        )

        self._timer_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        self._session_lbl = self._make_label(
            "SESSION TIME",
            "subtitle",
            muted=True,
        )

        self._session_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        self.timer_var.changed.connect(
            self._timer_lbl.setText
        )

        grid.addWidget(
            title,
            0,
            0,
        )

        grid.addWidget(
            subtitle,
            1,
            0,
        )

        grid.addWidget(
            self._timer_lbl,
            0,
            2,
            alignment=(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            ),
        )

        grid.addWidget(
            self._session_lbl,
            1,
            2,
            alignment=(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            ),
        )

        grid.setColumnStretch(1, 1)

        parent.addLayout(grid)

    # ========================================================
    # STATS
    # ========================================================

    def _build_stats(
        self,
        parent: QVBoxLayout,
    ) -> None:
        panel = QVBoxLayout()

        panel.setContentsMargins(
            0,
            0,
            0,
            self.PAD_MD,
        )

        panel.setSpacing(6)
        panel.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        fish_label = self._make_label(
            "FISH CAUGHT",
            "label",
            muted=True,
        )

        fish_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.fish_val_lbl = ScalableLabel("0")
        self.fish_val_lbl.setObjectName(
            "StatusValue"
        )

        self.fish_val_lbl.setFont(
            self.fonts["value"]
        )

        self.fish_val_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.fish_val_lbl.setMinimumHeight(45)

        self._fish_count_anim = QVariantAnimation(
            self
        )

        self._fish_count_anim.setDuration(
            ANIM_COUNT_MS
        )

        self._fish_count_anim.setEasingCurve(
            EASE_OUT
        )

        self._fish_count_anim.valueChanged.connect(
            lambda value: self._update_fish_display(
                int(value)
            )
        )

        def animate_fish(value):
            self._fish_count_anim.stop()

            start_value = float(
                self._displayed_fish_count
            )

            end_value = float(value)

            if abs(
                start_value - end_value
            ) < 0.5:
                self._update_fish_display(
                    int(end_value)
                )
            else:
                self._fish_count_anim.setStartValue(
                    start_value
                )

                self._fish_count_anim.setEndValue(
                    end_value
                )

                self._fish_count_anim.start()

            if value in self._FISH_MILESTONES:
                self.fish_val_lbl.milestone_pop()
            else:
                self.fish_val_lbl.pop()

        self.fish_count_var.changed.connect(
            animate_fish
        )

        panel.addWidget(fish_label)
        panel.addWidget(self.fish_val_lbl)
        panel.addSpacing(8)

        self.status_val_lbl = FadingLabel(
            "Idle"
        )

        self.status_val_lbl.setObjectName(
            "StatusValue"
        )

        self.status_val_lbl.setFont(
            self.fonts["status"]
        )

        self.status_val_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.status_var.changed.connect(
            self.status_val_lbl.setTextFade
        )

        panel.addWidget(
            self.status_val_lbl
        )

        parent.addLayout(panel)

    def _update_fish_display(
        self,
        value: int,
    ) -> None:
        self._displayed_fish_count = int(value)

        self.fish_val_lbl.setText(
            str(int(value))
        )

    # ========================================================
    # BAIT SECTION
    # ========================================================

    def _build_bait(
        self,
        parent: QVBoxLayout,
    ) -> None:
        panel = QVBoxLayout()

        panel.setContentsMargins(
            0,
            0,
            0,
            self.PAD_MD,
        )

        panel.setSpacing(
            self.PAD_SM
        )

        # ----------------------------------------------------
        # AUTO SWITCH
        # ----------------------------------------------------

        row_header = QHBoxLayout()
        row_header.setSpacing(
            self.PAD_SM
        )

        self.auto_switch = SwitchButton(
            "AUTO SWITCH BAIT",
            self.C,
            on_toggle=self.auto_bait_var.set,
            object_name="AutoSwitch",
        )

        self.auto_bait_var.changed.connect(
            self.auto_switch.set_checked
        )

        row_header.addWidget(
            self.auto_switch
        )

        row_header.addStretch()

        panel.addLayout(row_header)

        # ----------------------------------------------------
        # EQUIPPED BAIT
        # ----------------------------------------------------

        row_equipped = QHBoxLayout()
        row_equipped.setSpacing(
            self.PAD_SM
        )

        label_equipped = self._make_label(
            "EQUIPPED",
            "label",
            muted=True,
        )

        label_equipped.setMinimumWidth(65)

        label_equipped.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        row_equipped.addWidget(
            label_equipped
        )

        baits = self._sync_baits_from_json()

        if not baits:
            raise RuntimeError(
                "baits.json contains no baits"
            )

        self.equipped_btn = PolishedButton(
            f"1. {baits[0]['name']}"
        )

        self.equipped_btn.setObjectName(
            "EquippedBait"
        )

        self.equipped_btn.setProperty(
            "accent",
            baits[0]["rarity"],
        )

        self.equipped_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.equipped_btn.clicked.connect(
            self._toggle_equipped_dropdown
        )

        row_equipped.addWidget(
            self.equipped_btn,
            stretch=1,
        )

        panel.addLayout(
            row_equipped
        )

        # ----------------------------------------------------
        # SELECTED BAIT
        # ----------------------------------------------------

        row_selected = QHBoxLayout()
        row_selected.setSpacing(
            self.PAD_SM
        )

        label_selected = self._make_label(
            "SELECTED",
            "label",
            muted=True,
        )

        label_selected.setMinimumWidth(65)

        label_selected.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        row_selected.addWidget(
            label_selected
        )

        self.bait_select_btn = PolishedButton(
            "No baits"
        )

        self.bait_select_btn.setObjectName(
            "EquippedBait"
        )

        self.bait_select_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.bait_select_btn.clicked.connect(
            self._toggle_bait_dropdown
        )

        row_selected.addWidget(
            self.bait_select_btn,
            stretch=1,
        )

        self.detect_baits_btn = PolishedButton(
            "Detect Baits"
        )

        self.detect_baits_btn.setObjectName(
            "EquippedBait"
        )

        self.detect_baits_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.detect_baits_btn.clicked.connect(
            self._on_auto_detect_baits
        )

        row_selected.addWidget(
            self.detect_baits_btn
        )

        panel.addLayout(
            row_selected
        )

        parent.addLayout(panel)

        self.current_bait_idx.changed.connect(
            self._refresh_bait_highlight
        )

        self._refresh_bait_highlight(
            self.current_bait_idx.get()
        )

        self._tray_manager = None

        self.auto_bait_var.changed.connect(
            self._set_bait_controls_enabled
        )

        self._set_bait_controls_enabled(
            self.auto_bait_var.get()
        )

    def _set_bait_controls_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.equipped_btn.setEnabled(
            enabled
        )

        self.bait_select_btn.setEnabled(
            enabled
        )

        self.detect_baits_btn.setEnabled(
            enabled
        )

    def _on_auto_detect_baits(self) -> None:
        if getattr(
            self,
            "running",
            False,
        ):
            self.log(
                "Stop the bot before detecting baits."
            )
            return

        self.log(
            "Auto-detecting available baits..."
        )

        def run_detect():
            if self.focus_game_window():
                self.auto_detect_baits()

        threading.Thread(
            target=run_detect,
            daemon=True,
        ).start()

    # ========================================================
    # EQUIPPED BAIT MENU
    # ========================================================

    def _toggle_equipped_dropdown(
        self,
    ) -> None:
        if (
            hasattr(
                self,
                "_equipped_menu",
            )
            and self._equipped_menu.isVisible()
        ):
            self._equipped_menu.close()
            return

        menu = AnimatedMenu(self)

        self._equipped_menu = menu

        menu.setFixedWidth(
            DROPDOWN_WIDTH
        )

        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {self.C['surface']};
                border: 1px solid {self.C['border_hi']};
                border-radius: 4px;
                padding: 0px;
                margin: 0px;
            }}
            """
        )

        for index, bait in enumerate(
            self._sync_baits_from_json()
        ):
            button = PolishedButton(
                f"{index + 1}. {bait['name']}"
            )

            button.setObjectName(
                "BaitItem"
            )

            button.setProperty(
                "accent",
                bait["rarity"],
            )

            button.setCursor(
                Qt.CursorShape.PointingHandCursor
            )

            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

            action = QWidgetAction(menu)
            action.setDefaultWidget(button)

            menu.addAction(action)

            button.clicked.connect(
                lambda _,
                idx=index,
                current_menu=menu:
                self._select_equipped_bait(
                    idx,
                    current_menu,
                )
            )

        menu.exec(
            self.equipped_btn.mapToGlobal(
                QPoint(
                    0,
                    self.equipped_btn.height(),
                )
            )
        )

    def _select_equipped_bait(
        self,
        idx: int,
        menu: QMenu,
    ) -> None:
        self.current_bait_idx.set(idx)
        menu.close()

    # ========================================================
    # BAIT SELECTION MENU
    # ========================================================

    def _toggle_bait_dropdown(
        self,
    ) -> None:
        """
        Opens the bait selector.

        Each bait is added as its own QWidgetAction, exactly like the EQUIPPED menu.
        The SelectableBaitWidget now uses the same AnimatedCheckIndicator as settings.
        """

        if (
            hasattr(
                self,
                "_bait_menu",
            )
            and self._bait_menu.isVisible()
        ):
            self._bait_menu.close()
            return

        menu = AnimatedMenu(self)

        self._bait_menu = menu

        menu.setFixedWidth(
            DROPDOWN_WIDTH
        )

        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {self.C['surface']};
                border: 1px solid {self.C['border_hi']};
                border-radius: 4px;
                padding: 0px;
                margin: 0px;
            }}
            """
        )

        widgets: List[SelectableBaitWidget] = []
        baits = self._sync_baits_from_json()

        for index, bait in enumerate(baits):
            def on_toggle(checked: bool, idx: int = index) -> None:
                self.bait_vars[idx].set(bool(checked))
                self._update_bait_select_text()

            widget = SelectableBaitWidget(
                bait_name=f"{index + 1}. {bait['name']}",
                accent_color=RARITY_COLORS[bait["rarity"]],
                is_checked=self.bait_vars[index].get(),
                on_toggle=on_toggle,
            )
            widget.setMinimumWidth(DROPDOWN_WIDTH)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

            action = QWidgetAction(menu)
            action.setDefaultWidget(widget)
            menu.addAction(action)

            widgets.append(widget)

        # ----------------------------------------------------
        # Drag interaction filter (now animates)
        # ----------------------------------------------------

        drag_filter = _BaitMenuDragFilter(
            self,
            widgets,
            self.bait_vars,
            on_change=self._update_bait_select_text,
        )

        self.app.installEventFilter(drag_filter)
        self._bait_drag_filter = drag_filter

        try:
            menu.exec(
                self.bait_select_btn.mapToGlobal(
                    QPoint(0, self.bait_select_btn.height())
                )
            )
        finally:
            self.app.removeEventFilter(drag_filter)
            self._bait_drag_filter = None
            self._update_bait_select_text()

    # ------------------------------------------------------------
    # Update SELECTED button text to show names
    # ------------------------------------------------------------
    def _update_bait_select_text(self) -> None:
        """Update the SELECTED button to display the names of selected baits."""
        if not hasattr(self, "bait_select_btn"):
            return

        baits = self._sync_baits_from_json()

        selected_indices = [i for i, var in enumerate(self.bait_vars) if var.get()]

        if not selected_indices:
            text = "No baits"
        elif len(selected_indices) == 1:
            idx = selected_indices[0]
            text = baits[idx]["name"] if idx < len(baits) else "Bait"
        else:
            first_idx = selected_indices[0]
            first_name = baits[first_idx]["name"] if first_idx < len(baits) else "Bait"
            remaining = len(selected_indices) - 1
            text = f"{first_name} +{remaining} more"

        self.bait_select_btn.setText(text)

    # ========================================================
    # EQUIPPED BAIT HIGHLIGHT
    # ========================================================

    def _refresh_bait_highlight(
        self,
        idx: int,
    ) -> None:
        try:
            baits = self._sync_baits_from_json()

            if 0 <= idx < len(baits):
                bait = baits[idx]

                self.equipped_btn.setText(
                    f"{idx + 1}. {bait['name']}"
                )

                self.equipped_btn.setProperty(
                    "accent",
                    bait["rarity"],
                )

                self.equipped_btn.style().unpolish(
                    self.equipped_btn
                )

                self.equipped_btn.style().polish(
                    self.equipped_btn
                )

                self._pop_equipped_btn()

                return

        except (
            ValueError,
            IndexError,
            TypeError,
        ):
            pass

        self.equipped_btn.setText(
            "Select Bait"
        )

        self.equipped_btn.setProperty(
            "accent",
            None,
        )

        self.equipped_btn.style().unpolish(
            self.equipped_btn
        )

        self.equipped_btn.style().polish(
            self.equipped_btn
        )

    def _pop_equipped_btn(self) -> None:
        button = self.equipped_btn

        if not hasattr(
            self,
            "_equipped_pop_anim",
        ):
            anim = QPropertyAnimation(
                button,
                b"scaleFactor",
                self,
            )

            anim.setDuration(
                ANIM_POP_MS
            )

            anim.setEasingCurve(
                EASE_OUT_BACK
            )

            self._equipped_pop_anim = anim

        anim = self._equipped_pop_anim

        anim.stop()

        anim.setKeyValues([
            (0.0, 1.0),
            (0.4, 1.08),
            (1.0, 1.0),
        ])

        anim.start()

    # ========================================================
    # SETTINGS
    # ========================================================

    def _build_settings(
        self,
        parent: QVBoxLayout,
    ) -> None:
        panel = QVBoxLayout()

        panel.setContentsMargins(
            0,
            0,
            0,
            self.PAD_MD,
        )

        panel.setSpacing(
            self.PAD_SM
        )

        row_switches = QHBoxLayout()

        row_switches.setSpacing(
            self.PAD_MD
        )

        self.debug_switch = SwitchButton(
            "DEBUG CONSOLE",
            self.C,
            on_toggle=(
                self.debug_console_active.set
            ),
            object_name="ToggleSwitch",
        )

        self.debug_console_active.changed.connect(
            self.debug_switch.set_checked
        )

        self.debug_switch.set_checked(
            self.debug_console_active.get()
        )

        row_switches.addWidget(
            self.debug_switch
        )

        row_switches.addStretch()

        row_switches.addWidget(
            self._build_settings_gear()
        )

        panel.addLayout(
            row_switches
        )

        self.controller_status_container = QWidget()

        ctrl_row = QHBoxLayout(
            self.controller_status_container
        )

        ctrl_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        ctrl_row.addStretch()

        self.controller_status_lbl = QLabel("")

        self.controller_status_lbl.setObjectName(
            "ControllerStatus"
        )

        self.controller_status_lbl.setFont(
            self.fonts["subtitle"]
        )

        self.controller_status_var.changed.connect(
            self.controller_status_lbl.setText
        )

        self.controller_status_var.changed.connect(
            self._apply_controller_status_color
        )

        ctrl_row.addWidget(
            self.controller_status_lbl
        )

        ctrl_row.addStretch()

        self.controller_status_container.setVisible(
            False
        )

        self._status_fade_effect = (
            QGraphicsOpacityEffect(
                self.controller_status_container
            )
        )

        self._status_fade_effect.setOpacity(
            0.0
        )

        self.controller_status_container.setGraphicsEffect(
            self._status_fade_effect
        )

        self._status_fade_anim = QPropertyAnimation(
            self._status_fade_effect,
            b"opacity",
        )

        self._status_fade_anim.setDuration(
            ANIM_QUICK_MS
        )

        self._status_fade_anim.setEasingCurve(
            EASE_IN_OUT
        )

        self._status_fade_anim.finished.connect(
            self._on_status_fade_finished
        )

        panel.addWidget(
            self.controller_status_container
        )

        parent.addLayout(panel)

    def _build_settings_gear(
        self,
    ) -> QPushButton:
        gear = PolishedButton()

        gear.setObjectName(
            "GearBtn"
        )

        gear.setFixedSize(
            GEAR_SIZE,
            GEAR_SIZE,
        )

        gear.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        gear.setToolTip(
            "Settings"
        )

        gear._hover_scale = 1.3
        gear._hover_rotate = -60
        gear._glow_enabled = False

        gear.setStyleSheet(
            """
            QPushButton#GearBtn {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 0px;
            }

            QPushButton#GearBtn:hover {
                background-color: transparent;
                border: none;
            }

            QPushButton#GearBtn:pressed {
                background-color: transparent;
                border: none;
            }
            """
        )

        try:
            if QSvgRenderer is not None:
                with open(
                    SETTINGS_ICON_PATH,
                    "r",
                    encoding="utf-8",
                ) as file:
                    svg_data = file.read()

                svg_data = re.sub(
                    r'fill="(?!none)[^"]*"',
                    'fill="#E7E7E7"',
                    svg_data,
                    flags=re.IGNORECASE,
                )

                svg_data = re.sub(
                    r'fill:\s*(?!none)#?[0-9a-fA-F]+',
                    'fill:#E7E7E7',
                    svg_data,
                    flags=re.IGNORECASE,
                )

                renderer = QSvgRenderer(
                    QByteArray(
                        svg_data.encode("utf-8")
                    )
                )

                pixmap = QPixmap(
                    GEAR_SIZE,
                    GEAR_SIZE,
                )

                pixmap.fill(
                    Qt.GlobalColor.transparent
                )

                painter = QPainter(pixmap)

                renderer.render(painter)

                painter.end()

                gear.setIconSize(
                    QSize(
                        GEAR_SIZE,
                        GEAR_SIZE,
                    )
                )

                gear.setIcon(
                    QIcon(pixmap)
                )

            else:
                gear.setIcon(
                    QIcon(SETTINGS_ICON_PATH)
                )

        except Exception:
            gear.setText("\u2699")

        gear.installEventFilter(
            _GearHoverFilter(
                gear,
                gear._hover_scale,
            )
        )

        gear.clicked.connect(
            self._open_settings
        )

        return gear

    def _open_settings(self) -> None:
        if getattr(
            self,
            "_settings_dialog_open",
            False,
        ):
            return

        from settings_window import SettingsDialog

        self._settings_dialog_open = True

        try:
            dialog = SettingsDialog(
                self.settings,
                self,
            )

            dialog.exec()

        finally:
            self._settings_dialog_open = False

    # ========================================================
    # CONTROLLER STATUS
    # ========================================================

    def _apply_controller_status_color(
        self,
        value: str,
    ) -> None:
        if value.startswith("Gamepad"):
            color = self.C["accent"]

        elif value.startswith("Error"):
            color = self.C["danger"]

        else:
            color = self.C["text_muted"]

        self.controller_status_lbl.setStyleSheet(
            f"""
            QLabel#ControllerStatus {{
                color: {color};
                background: transparent;
            }}
            """
        )

        should_show = bool(value)

        self._status_target_visible = (
            should_show
        )

        if (
            should_show
            and self._status_fade_effect.opacity()
            < 1.0
        ):
            self.controller_status_container.show()

            self._status_fade_anim.stop()

            self._status_fade_anim.setStartValue(
                self._status_fade_effect.opacity()
            )

            self._status_fade_anim.setEndValue(
                1.0
            )

            self._status_fade_anim.start()

        elif (
            not should_show
            and self._status_fade_effect.opacity()
            > 0.0
        ):
            self._status_fade_anim.stop()

            self._status_fade_anim.setStartValue(
                self._status_fade_effect.opacity()
            )

            self._status_fade_anim.setEndValue(
                0.0
            )

            self._status_fade_anim.start()

    def _on_status_fade_finished(self):
        if not self._status_target_visible:
            self.controller_status_container.hide()

    # ========================================================
    # WINDOW RESIZING
    # ========================================================

    def _resize_window_to(
        self,
        height: int,
    ) -> None:
        self.setFixedSize(
            WINDOW_W,
            height,
        )

        self._apply_geometry(height)

        QTimer.singleShot(
            0,
            lambda h=height:
            self._apply_geometry(h),
        )

    def _handle_debug_toggle(
        self,
        is_on: bool,
    ) -> None:
        self._console_is_on = is_on

        if not hasattr(
            self,
            "_console_anim",
        ):
            self._console_anim = QPropertyAnimation(
                self,
                b"windowOpacity",
                self,
            )

            self._console_anim.setDuration(
                ANIM_BASE_MS
            )

            self._console_anim.setEasingCurve(
                EASE_IN_OUT
            )

        self._console_anim.stop()

        if (
            hasattr(
                self,
                "_console_fade_in_anim",
            )
            and self._console_fade_in_anim is not None
        ):
            self._console_fade_in_anim.stop()
            self._console_fade_in_anim = None

        if self._console_anim_slot is not None:
            try:
                self._console_anim.finished.disconnect(
                    self._console_anim_slot
                )
            except (TypeError, RuntimeError):
                pass

            self._console_anim_slot = None

        target_height = (
            DEBUG_WINDOW_H
            if is_on
            else WINDOW_H
        )

        def fade_out_finished() -> None:
            self._sync_console_widgets_to_state()

            self._resize_window_to(
                target_height
            )

            fade_in = QPropertyAnimation(
                self,
                b"windowOpacity",
                self,
            )

            fade_in.setDuration(
                ANIM_BASE_MS
            )

            fade_in.setEasingCurve(
                EASE_IN_OUT
            )

            fade_in.setStartValue(
                self.windowOpacity()
            )

            fade_in.setEndValue(1.0)

            self._console_fade_in_anim = fade_in

            fade_in.start()

        self._console_anim_slot = (
            fade_out_finished
        )

        self._console_anim.finished.connect(
            fade_out_finished
        )

        self._console_anim.setStartValue(
            self.windowOpacity()
        )

        self._console_anim.setEndValue(0.0)

        self._console_anim.start()

    def _sync_console_widgets_to_state(
        self,
    ) -> None:
        is_on = (
            self.debug_console_active.get()
        )

        self._console_is_on = is_on

        if is_on:
            self.log_outer.show()
            self.log_box.setVisible(True)

        else:
            self.log_outer.hide()
            self.log_box.setVisible(True)

    # ========================================================
    # LOG
    # ========================================================

    def _build_log(
        self,
        parent: QVBoxLayout,
    ) -> None:
        self.log_outer = QWidget()

        self._log_layout = QVBoxLayout(
            self.log_outer
        )

        self._log_layout.setContentsMargins(
            0,
            0,
            0,
            self.PAD_MD,
        )

        self._log_layout.setSpacing(
            self.PAD_SM
        )

        header_row = QHBoxLayout()

        header_row.setContentsMargins(
            0, 0, 0, 0,
        )

        header = self._make_label(
            "SESSION LOG",
            "label",
            muted=True,
        )

        header_row.addWidget(
            header
        )

        header_row.addStretch()

        self.log_pause_btn = QPushButton(
            "PAUSE"
        )

        self.log_pause_btn.setObjectName(
            "LogPauseBtn"
        )

        self.log_pause_btn.setCheckable(
            True
        )

        self.log_pause_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.log_pause_btn.setToolTip(
            "Pause log rendering (entries keep being stored)"
        )

        self.log_pause_btn.setStyleSheet(
            f"""
            QPushButton#LogPauseBtn {{
                background-color: transparent;
                border: 1px solid {self.C['border_hi']};
                border-radius: 4px;
                padding: 2px 8px;
                color: {self.C['text_muted']};
                font-family: {self.FONT_MAIN};
                font-size: 8pt;
                font-weight: bold;
                text-align: center;
            }}

            QPushButton#LogPauseBtn:hover {{
                border: 1px solid {self.C['accent_muted']};
                color: {self.C['text']};
            }}

            QPushButton#LogPauseBtn:checked {{
                background-color: {self.C['accent_dim']};
                border: 1px solid {self.C['accent']};
                color: {self.C['text']};
            }}
            """
        )

        self.log_pause_btn.toggled.connect(
            self._on_log_pause_toggled
        )

        header_row.addWidget(
            self.log_pause_btn
        )

        self._log_layout.addLayout(
            header_row
        )

        self.log_box = LogView()

        self.log_box.setObjectName(
            "LogView"
        )

        self.log_box.setFont(
            self.fonts["log"]
        )

        self._log_layout.addWidget(
            self.log_box
        )

        self.log_outer.hide()

        parent.addWidget(
            self.log_outer
        )

        self.debug_console_active.changed.connect(
            self._handle_debug_toggle
        )

    def _on_log_pause_toggled(
        self,
        is_paused: bool,
    ) -> None:
        self.log_box.set_paused(is_paused)

        self.log_pause_btn.setText(
            "RESUME"
            if is_paused
            else "PAUSE"
        )

    # ========================================================
    # ACTION BUTTON
    # ========================================================

    def _build_action(
        self,
        parent: QVBoxLayout,
    ) -> None:
        parent.addSpacing(
            self.PAD_MD
        )

        self.toggle_btn = PolishedButton(
            "START"
        )

        self.toggle_btn.setObjectName(
            "ActionBtn"
        )

        self.toggle_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.toggle_btn.clicked.connect(
            self.toggle
        )

        parent.addWidget(
            self.toggle_btn
        )

    # ========================================================
    # RUNNING / STOPPED VISUAL STATE
    # ========================================================

    def set_mode_colors(
        self,
        running: bool,
    ) -> None:
        self.running = running

        self.top_rule.setProperty(
            "running",
            "true" if running else "false",
        )

        self.top_rule.style().unpolish(
            self.top_rule
        )

        self.top_rule.style().polish(
            self.top_rule
        )

        self._pulse_top_rule()

        if running:
            self._animate_status_color(
                self.C["text_muted"],
                self.C["accent"],
            )

            self.status_val_lbl.start_breathing()

            self._animate_button_color(
                self.C["accent"],
                "#FFB610",
            )

            self.toggle_btn.setText(
                "STOP"
            )

        else:
            self._animate_status_color(
                self.C["accent"],
                self.C["text_muted"],
            )

            self.status_val_lbl.stop_breathing()

            self._animate_button_color(
                "#FFB610",
                self.C["accent"],
            )

            self.toggle_btn.setText(
                "START"
            )

        animation = getattr(
            self,
            "_console_anim",
            None,
        )

        if (
            animation is None
            or animation.state()
            != QPropertyAnimation.State.Running
        ):
            height = (
                DEBUG_WINDOW_H
                if self.debug_console_active.get()
                else WINDOW_H
            )

            if abs(
                self.height() - height
            ) > 2:
                self._resize_window_to(
                    height
                )

            self._sync_console_widgets_to_state()

    # ========================================================
    # TOP RULE ANIMATION
    # ========================================================

    def _apply_top_rule_height(
        self,
        value,
    ) -> None:
        self.top_rule.setStyleSheet(
            f"""
            QFrame#TopRule {{
                max-height: {int(value)}px;
                min-height: {int(value)}px;
            }}
            """
        )

    def _pulse_top_rule(self) -> None:
        if (
            hasattr(
                self,
                "_rule_loop_anim",
            )
            and self._rule_loop_anim.state()
            == QVariantAnimation.State.Running
        ):
            self._rule_loop_anim.stop()

        if not hasattr(
            self,
            "_rule_pulse_anim",
        ):
            animation = QVariantAnimation(
                self
            )

            animation.setDuration(
                ANIM_MEDIUM_MS
            )

            animation.setEasingCurve(
                EASE_IN_OUT
            )

            animation.valueChanged.connect(
                self._apply_top_rule_height
            )

            animation.finished.connect(
                self._maybe_start_continuous_pulse
            )

            self._rule_pulse_anim = animation

        animation = self._rule_pulse_anim

        animation.stop()

        animation.setStartValue(
            float(self.top_rule.height())
        )

        animation.setKeyValueAt(
            0.35,
            6.0,
        )

        animation.setEndValue(3.0)

        animation.start()

    def _maybe_start_continuous_pulse(
        self,
    ) -> None:
        if self.running:
            self._start_continuous_pulse()

    def _start_continuous_pulse(
        self,
    ) -> None:
        if not hasattr(
            self,
            "_rule_loop_anim",
        ):
            animation = QVariantAnimation(
                self
            )

            animation.setDuration(
                ANIM_BREATH_MS
            )

            animation.setEasingCurve(
                EASE_IN_OUT_SINE
            )

            animation.setStartValue(3.0)

            animation.setKeyValueAt(
                0.5,
                4.5,
            )

            animation.setEndValue(3.0)

            animation.setLoopCount(-1)

            animation.valueChanged.connect(
                self._apply_top_rule_height
            )

            self._rule_loop_anim = animation

        self._rule_loop_anim.start()

    def _stop_continuous_pulse(
        self,
    ) -> None:
        if hasattr(
            self,
            "_rule_loop_anim",
        ):
            self._rule_loop_anim.stop()

    # ========================================================
    # STATUS COLOR
    # ========================================================

    def _animate_status_color(
        self,
        start_color: str,
        end_color: str,
    ) -> None:
        if not hasattr(
            self,
            "_status_color_anim",
        ):
            self._status_color_anim = (
                QVariantAnimation(self)
            )

            self._status_color_anim.setDuration(
                ANIM_SLOW_MS
            )

            self._status_color_anim.setEasingCurve(
                EASE_IN_OUT
            )

            def update_status_color(
                color: QColor,
            ):
                hex_color = color.name()

                self.status_val_lbl.setStyleSheet(
                    f"""
                    QLabel#StatusValue {{
                        color: {hex_color};
                        background: transparent;
                    }}
                    """
                )

            self._status_color_anim.valueChanged.connect(
                update_status_color
            )

        self._status_color_anim.stop()

        self._status_color_anim.setStartValue(
            QColor(start_color)
        )

        self._status_color_anim.setEndValue(
            QColor(end_color)
        )

        self._status_color_anim.start()

    # ========================================================
    # ACTION BUTTON COLOR
    # ========================================================

    def _animate_button_color(
        self,
        start_color: str,
        end_color: str,
    ) -> None:
        if not hasattr(
            self,
            "_btn_anim",
        ):
            self._btn_anim = QVariantAnimation(
                self
            )

            self._btn_anim.setDuration(
                ANIM_BASE_MS
            )

            self._btn_anim.setEasingCurve(
                EASE_IN_OUT
            )

            def update_color(
                color: QColor,
            ):
                hex_color = color.name()

                hover_color = _shade(
                    hex_color,
                    0.15,
                )

                pressed_color = _shade(
                    hex_color,
                    -0.10,
                )

                text_color = (
                    "#0B0E14"
                    if QColor(hex_color).lightness()
                    > 128
                    else self.C["bg"]
                )

                self.toggle_btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {hex_color};
                        color: {text_color};
                        border: none;
                        border-radius: 4px;
                        padding: 14px 12px;
                        text-align: center;
                        font-size: 12pt;
                        font-family: '{self.FONT_MAIN}';
                        font-weight: bold;
                    }}

                    QPushButton:hover {{
                        background-color: {hover_color};
                    }}

                    QPushButton:pressed {{
                        background-color: {pressed_color};
                        padding-top: 16px;
                        padding-bottom: 10px;
                    }}
                    """
                )

            self._btn_anim.valueChanged.connect(
                update_color
            )

        self._btn_anim.stop()

        self._btn_anim.setStartValue(
            QColor(start_color)
        )

        self._btn_anim.setEndValue(
            QColor(end_color)
        )

        self._btn_anim.start()

    # ========================================================
    # ESCAPE
    # ========================================================

    def _on_escape(self) -> None:
        if getattr(
            self,
            "running",
            False,
        ):
            self.stop()

    # ========================================================
    # GEOMETRY
    # ========================================================

    def _apply_geometry(
        self,
        height: int,
    ) -> None:
        screen = self.screen()

        if screen is None:
            screen = QApplication.primaryScreen()

        if screen is None:
            return

        screen_geometry = (
            screen.availableGeometry()
        )

        x = (
            screen_geometry.x()
            + max(
                0,
                int(
                    screen_geometry.width()
                    * WINDOW_X_PCT
                ),
            )
        )

        y = (
            screen_geometry.y()
            + max(
                0,
                int(
                    screen_geometry.height()
                    * WINDOW_Y_PCT
                    - height
                ),
            )
        )

        self.setGeometry(
            x,
            y,
            WINDOW_W,
            height,
        )

    # ========================================================
    # TKINTER-COMPATIBILITY HELPERS
    # ========================================================

    def winfo_id(self) -> int:
        return int(self.winId())

    def protocol(
        self,
        name: str,
        func: Callable[[], None],
    ) -> None:
        if name == "WM_DELETE_WINDOW":
            self._close_handler = func

    # ========================================================
    # PUBLIC STATE API
    # ========================================================

    def set_status(
        self,
        text: str,
    ) -> None:
        self.status_var.set(text)

        if (
            text == "Caught!"
            and hasattr(
                self,
                "catch_burst",
            )
        ):
            self.catch_burst.setGeometry(
                self.container.rect()
            )

            self.catch_burst.play()

    def set_fish_count(
        self,
        count: int,
    ) -> None:
        self.fish_count_var.set(count)

    def set_timer(
        self,
        text: str,
    ) -> None:
        self.timer_var.set(text)

    def set_controller_status(
        self,
        text: str,
    ) -> None:
        self.controller_status_var.set(text)

    def log(
        self,
        text: str,
        color: str = "#E7E7E7",
    ) -> None:
        self.log_box.append(
            text,
            color,
        )