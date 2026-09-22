"""Theme constants + QSS stylesheets for the NOVA desktop UI.

A futuristic, minimal glass/dark aesthetic with a light-mode variant.
"""
from __future__ import annotations

ACCENT = "#4fd1c5"        # teal-400
ACCENT_2 = "#7c9af2"      # periwinkle
DANGER = "#f56565"
OK = "#48bb78"
WARN = "#ed8936"

DARK_BG = "#0b0e14"
DARK_PANEL = "#12161f"
DARK_CARD = "#171c28"
DARK_BORDER = "#232a3a"
DARK_TEXT = "#e6eaf2"
DARK_MUTED = "#8b94a7"

LIGHT_BG = "#f4f6fb"
LIGHT_PANEL = "#ffffff"
LIGHT_CARD = "#f0f2f8"
LIGHT_BORDER = "#dbe1ee"
LIGHT_TEXT = "#1a2233"
LIGHT_MUTED = "#5c6678"

FONT = '"Segoe UI", "Inter", "SF Pro Display", "Helvetica Neue", Arial, sans-serif'
MONO = '"Cascadia Code", "Consolas", "JetBrains Mono", monospace'


def palette(dark: bool) -> dict:
    if dark:
        return {"bg": DARK_BG, "panel": DARK_PANEL, "card": DARK_CARD,
                "border": DARK_BORDER, "text": DARK_TEXT, "muted": DARK_MUTED}
    return {"bg": LIGHT_BG, "panel": LIGHT_PANEL, "card": LIGHT_CARD,
            "border": LIGHT_BORDER, "text": LIGHT_TEXT, "muted": LIGHT_MUTED}


def build_qss(dark: bool = True) -> str:
    p = palette(dark)
    radius = "14px"
    return f"""
    * {{ font-family: {FONT}; }}
    QWidget {{ color: {p['text']}; }}
    QLabel {{ background: transparent; }}

    QFrame#orb {{
        background-color: rgba(18, 22, 31, 215);
        border: 1px solid rgba(79, 209, 197, 90);
        border-radius: 34px;
    }}
    QFrame#panel {{
        background-color: {p['panel']};
        border: 1px solid {p['border']};
        border-radius: {radius};
    }}
    QFrame#card {{
        background-color: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 10px;
    }}
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 7px 10px;
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QPushButton {{
        background-color: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ border: 1px solid {ACCENT}; }}
    QPushButton:pressed {{ background-color: {p['border']}; }}
    QPushButton#primary {{
        background-color: {ACCENT};
        color: #04211f;
        font-weight: 600;
        border: none;
    }}
    QPushButton#primary:hover {{ background-color: #5cdad0; }}
    QPushButton#danger {{
        background-color: rgba(245, 101, 101, 24);
        color: {DANGER};
        border: 1px solid rgba(245, 101, 101, 120);
    }}
    QPushButton#ghost {{
        background: transparent; border: none; color: {p['muted']};
    }}
    QListWidget, QListView, QTableWidget, QTreeWidget {{
        background-color: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 4px;
    }}
    QListWidget::item {{ padding: 6px; border-radius: 6px; }}
    QListWidget::item:selected {{ background-color: rgba(79, 209, 197, 40); }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; }}
    QTabBar::tab {{
        background: transparent; padding: 8px 16px; color: {p['muted']};
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
    QCheckBox, QRadioButton {{ spacing: 6px; }}
    QGroupBox {{
        border: 1px solid {p['border']}; border-radius: 10px;
        margin-top: 12px; padding-top: 8px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {p['muted']}; }}
    QToolTip {{
        background-color: {p['card']}; color: {p['text']};
        border: 1px solid {p['border']}; padding: 6px; border-radius: 6px;
    }}
    QMenu {{ background-color: {p['panel']}; border: 1px solid {p['border']};
            border-radius: 8px; padding: 6px; }}
    QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
    QMenu::item:selected {{ background-color: rgba(79, 209, 197, 40); }}
    QProgressBar {{
        background: {p['card']}; border: none; border-radius: 4px;
        height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 4px; }}
    """
