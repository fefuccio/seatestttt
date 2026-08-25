"""Application-wide QSS definitions extracted for clarity."""

from __future__ import annotations

from typing import Dict

FONT_FAMILY = "Segoe UI"


def get_app_qss(
    C: Dict[str, str],
    font_family: str,
    font_family_mono: str,
    check_url: str,
) -> str:
    return f"""
        QMainWindow,
        QWidget#Container {{
            background-color: {C['bg']};
        }}

        QLabel {{
            color: {C['text']};
            background: transparent;
        }}

        QLabel#Muted {{
            color: {C['text_muted']};
        }}

        QLabel#StatusValue,
        QLabel#ControllerStatus {{
            background: transparent;
        }}

        QFrame#Divider {{
            background-color: {C['border']};
            max-height: 1px;
            min-height: 1px;
        }}

        QFrame#TopRule {{
            background-color: {C['text_muted']};
            max-height: 3px;
            min-height: 3px;
        }}

        QFrame#TopRule[running="true"] {{
            background-color: {C['accent']};
        }}

        QPushButton {{
            background-color: {C['surface_alt']};
            border: 1px solid {C['border_hi']};
            border-radius: 4px;
            padding: 6px 12px;
            color: {C['text']};
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
            text-align: left;
        }}

        QPushButton:hover {{
            background-color: {C['border_hi']};
            border: 1px solid {C['accent_muted']};
        }}

        QPushButton:pressed {{
            background-color: {C['accent_dim']};
            padding-top: 7px;
            padding-bottom: 5px;
        }}

        QPushButton:disabled {{
            color: {C['text_muted']};
            background-color: {C['surface']};
            border: 1px solid {C['border']};
        }}

        QPushButton#ActionBtn {{
            background-color: {C['accent']};
            color: {C['bg']};
            border: none;
            border-radius: 4px;
            padding: 14px 12px;
            text-align: center;
            font-size: 12pt;
        }}

        QPushButton#ActionBtn:hover {{
            background-color: {C['accent_hover']};
        }}

        QPushButton#ActionBtn:pressed {{
            padding-top: 16px;
            padding-bottom: 10px;
        }}

        QPushButton#ActionBtnStop {{
            background-color: #FFB610;
            color: #0B0E14;
            border: none;
            border-radius: 4px;
            padding: 14px 12px;
            text-align: center;
            font-size: 12pt;
        }}

        QPushButton#ActionBtnStop:hover {{
            background-color: #E6A30E;
        }}

        QPushButton#ActionBtnStop:pressed {{
            padding-top: 16px;
            padding-bottom: 10px;
        }}

        QPushButton#EquippedBait {{
            background-color: {C['surface_alt']};
            border: 1px solid {C['border_hi']};
            border-radius: 4px;
            padding: 5px 10px;
            text-align: left;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
        }}

        QPushButton#EquippedBait:hover {{
            border: 1px solid {C['accent_muted']};
        }}

        QPushButton#EquippedBait:pressed {{
            padding-top: 6px;
            padding-bottom: 4px;
        }}

        QPushButton#EquippedBait:disabled {{
            color: {C['text_muted']};
            background-color: {C['surface']};
            border: 1px solid {C['border']};
        }}

        QPushButton#GearBtn {{
            background-color: transparent;
            border: none;
            border-radius: 4px;
            padding: 0px;
            color: {C['text']};
            font-size: 14pt;
            text-align: center;
        }}

        QPushButton#GearBtn:hover {{
            background-color: transparent;
            color: {C['accent']};
            border: none;
        }}

        QPushButton#GearBtn:pressed {{
            background-color: transparent;
            border: none;
        }}

        QLabel#ToggleSwitchLabel {{
            color: {C['text_muted']};
            background: transparent;
        }}

        QCheckBox {{
            color: {C['text']};
            spacing: 6px;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
            background: transparent;
            padding: 6px 12px;
        }}

        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 3px;
            border: 1px solid {C['border_hi']};
            background-color: transparent;
        }}

        QCheckBox::indicator:checked {{
            background-color: {C['accent']};
            border: 1px solid {C['accent']};
            image: {check_url};
        }}

        QPlainTextEdit#LogView {{
            background-color: {C['surface']};
            color: {C['text']};
            border: 1px solid {C['border']};
            border-radius: 4px;
            padding: 6px;
            font-family: '{font_family_mono}';
            font-size: 10pt;
        }}

        QPlainTextEdit#LogView:focus {{
            border: 1px solid {C['accent_muted']};
        }}

        QPlainTextEdit#LogView QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0px;
        }}

        QPlainTextEdit#LogView QScrollBar::handle:vertical {{
            background: {C['border_hi']};
            min-height: 24px;
            min-width: 8px;
            border-radius: 5px;
        }}

        QPlainTextEdit#LogView QScrollBar::handle:vertical:hover {{
            background: {C['text_muted']};
        }}

        QPlainTextEdit#LogView QScrollBar::add-line:vertical,
        QPlainTextEdit#LogView QScrollBar::sub-line:vertical {{
            height: 0px;
            background: transparent;
        }}

        QPlainTextEdit#LogView QScrollBar::add-page:vertical,
        QPlainTextEdit#LogView QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QMenu {{
            background-color: {C['surface']};
            border: 1px solid {C['border_hi']};
            border-radius: 4px;
            padding: 0px;
            margin: 0px;
        }}

        QMenu::item {{
            background-color: transparent;
        }}

        QPushButton#BaitItem[accent="green"] {{
            color: #21A28F;
            background-color: transparent;
            border: none;
            text-align: left;
            padding: 8px 12px;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
        }}

        QPushButton#BaitItem[accent="blue"] {{
            color: #3C69FF;
            background-color: transparent;
            border: none;
            text-align: left;
            padding: 8px 12px;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
        }}

        QPushButton#BaitItem[accent="purple"] {{
            color: #E741BD;
            background-color: transparent;
            border: none;
            text-align: left;
            padding: 8px 12px;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
        }}

        QPushButton#BaitItem[accent="orange"] {{
            color: #FFB610;
            background-color: transparent;
            border: none;
            text-align: left;
            padding: 8px 12px;
            font-family: {font_family};
            font-size: 9pt;
            font-weight: bold;
        }}

        QPushButton#BaitItem:hover {{
            background-color: {C['surface_alt']};
        }}
    """