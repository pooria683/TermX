"""Design tokens and stylesheet generation.

The whole look of TermX is defined here: colours, spacing, radii, typography,
and the Qt stylesheet that applies them. Keeping it in one place means the
pages never hard-code colours, and a future light theme is a single extra
palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Palette:
    """Colour tokens for one theme."""

    name: str = "dark"
    # surfaces
    bg: str = "#0B0D12"
    surface: str = "#121722"
    surface_alt: str = "#161C28"
    surface_high: str = "#1B2230"
    elevated: str = "#1E2636"
    overlay: str = "#0E1218"
    # borders
    border: str = "#232B3A"
    border_soft: str = "#1C2331"
    border_strong: str = "#2F3A4D"
    border_accent: str = "#3B4A66"
    # text
    text: str = "#E8ECF4"
    text_muted: str = "#9AA6BC"
    text_dim: str = "#6B788F"
    text_faint: str = "#4A5568"
    # brand
    accent: str = "#4C8DFF"
    accent_hover: str = "#6BA1FF"
    accent_pressed: str = "#3A78E8"
    accent_soft: str = "rgba(76, 141, 255, 0.14)"
    purple: str = "#9B7BFF"
    purple_soft: str = "rgba(155, 123, 255, 0.14)"
    cyan: str = "#22D3EE"
    # semantic
    success: str = "#34D399"
    success_soft: str = "rgba(52, 211, 153, 0.14)"
    warning: str = "#FBBF24"
    warning_soft: str = "rgba(251, 191, 36, 0.14)"
    danger: str = "#F87171"
    danger_soft: str = "rgba(248, 113, 113, 0.14)"
    info: str = "#60A5FA"
    # terminal
    term_bg: str = "#0A0C11"
    term_text: str = "#D6DEEB"
    term_dim: str = "#5C6A80"
    term_prompt: str = "#4C8DFF"
    term_success: str = "#34D399"
    term_error: str = "#F87171"
    term_warning: str = "#FBBF24"
    term_info: str = "#9B7BFF"

    # typography
    font_ui: str = "Inter"
    font_mono: str = "JetBrains Mono"
    font_fallback_ui: str = '"Inter Variable", "Segoe UI", "SF Pro Display", Ubuntu, Cantarell, sans-serif'
    font_fallback_mono: str = '"Cascadia Code", Consolas, Menlo, "DejaVu Sans Mono", monospace'

    @property
    def ui_stack(self) -> str:
        """Full CSS font-family stack with the resolved UI family first."""
        return f'"{self.font_ui}", {self.font_fallback_ui}'

    @property
    def mono_stack(self) -> str:
        return f'"{self.font_mono}", {self.font_fallback_mono}'

    @property
    def background(self) -> str:
        """Alias used by darker sub-surfaces."""
        return self.bg

    # geometry
    radius_sm: int = 6
    radius: int = 10
    radius_lg: int = 14
    radius_xl: int = 20
    spacing: int = 8
    sidebar_width: int = 232

    def soft(self, color_name: str) -> str:
        return {
            "accent": self.accent_soft,
            "purple": self.purple_soft,
            "success": self.success_soft,
            "warning": self.warning_soft,
            "danger": self.danger_soft,
        }.get(color_name, self.surface_alt)


DARK = Palette()


@dataclass
class ThemeManager:
    """Holds the active palette and produces stylesheets."""

    palette: Palette = field(default_factory=lambda: DARK)
    font_scale: float = 1.0
    mono_size: int = 13

    def px(self, base: float) -> int:
        return max(1, round(base * self.font_scale))

    def app_stylesheet(self) -> str:
        p = self.palette
        return f"""
/* ---------------------------------------------------------------- base */
QWidget {{
    color: {p.text};
    font-family: {p.ui_stack};
    font-size: {self.px(13)}px;
}}
QMainWindow, QDialog {{
    background-color: {p.bg};
}}
QWidget#Page, QWidget#PageBody {{
    background-color: transparent;
}}
QToolTip {{
    background-color: {p.elevated};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {p.radius_sm}px;
    padding: 6px 9px;
    font-size: {self.px(12)}px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

/* ------------------------------------------------------------- sidebar */
QFrame#Sidebar {{
    background-color: {p.overlay};
    border-right: 1px solid {p.border};
}}
QPushButton#NavButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {p.radius}px;
    padding: 9px 12px;
    text-align: left;
    color: {p.text_muted};
    font-size: {self.px(13)}px;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background-color: {p.surface};
    color: {p.text};
}}
QPushButton#NavButton:checked {{
    background-color: {p.accent_soft};
    color: {p.text};
    border: 1px solid rgba(76, 141, 255, 0.32);
    font-weight: 600;
}}
QPushButton#NavButton:focus {{
    outline: none;
}}
QLabel#BrandName {{
    color: {p.text};
    font-size: {self.px(19)}px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}
QLabel#BrandTag {{
    color: {p.text_dim};
    font-size: {self.px(10)}px;
    font-weight: 600;
    letter-spacing: 1.4px;
}}
QLabel#NavSection {{
    color: {p.text_faint};
    font-size: {self.px(10)}px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 14px 12px 6px 12px;
}}

/* --------------------------------------------------------------- cards */
QFrame#Card {{
    background-color: {p.surface};
    border: 1px solid {p.border_soft};
    border-radius: {p.radius_lg}px;
}}
QFrame#CardHover {{
    background-color: {p.surface};
    border: 1px solid {p.border_soft};
    border-radius: {p.radius_lg}px;
}}
QFrame#CardHover:hover {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border_accent};
}}
QFrame#Panel {{
    background-color: {p.surface};
    border: 1px solid {p.border_soft};
    border-radius: {p.radius_lg}px;
}}
QFrame#Inset {{
    background-color: {p.term_bg};
    border: 1px solid {p.border_soft};
    border-radius: {p.radius}px;
}}
QFrame#Divider {{
    background-color: {p.border};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ------------------------------------------------------------ typography */
QLabel#PageTitle {{
    color: {p.text};
    font-size: {self.px(23)}px;
    font-weight: 800;
    letter-spacing: -0.3px;
}}
QLabel#PageSubtitle {{
    color: {p.text_muted};
    font-size: {self.px(13)}px;
}}
QLabel#CardTitle {{
    color: {p.text};
    font-size: {self.px(13)}px;
    font-weight: 600;
}}
QLabel#CardCaption {{
    color: {p.text_dim};
    font-size: {self.px(11)}px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}
QLabel#MetricValue {{
    color: {p.text};
    font-size: {self.px(26)}px;
    font-weight: 800;
    letter-spacing: -0.6px;
}}
QLabel#MetricLabel {{
    color: {p.text_muted};
    font-size: {self.px(12)}px;
    font-weight: 500;
}}
QLabel#Muted {{
    color: {p.text_muted};
    font-size: {self.px(12)}px;
}}
QLabel#Dim {{
    color: {p.text_dim};
    font-size: {self.px(11)}px;
}}
QLabel#Mono {{
    font-family: {p.mono_stack};
    color: {p.text};
    font-size: {self.px(12)}px;
}}
QLabel#EmptyTitle {{
    color: {p.text};
    font-size: {self.px(15)}px;
    font-weight: 600;
}}
QLabel#EmptyBody {{
    color: {p.text_muted};
    font-size: {self.px(12)}px;
}}

/* --------------------------------------------------------------- inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {p.radius}px;
    padding: 9px 12px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border: 1px solid {p.border_strong};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {p.accent};
    background-color: {p.surface_high};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {p.text_faint};
    background-color: {p.surface};
}}
QLineEdit#Prompt {{
    background-color: {p.term_bg};
    border: 1px solid {p.border_strong};
    border-radius: {p.radius}px;
    padding: 12px 14px;
    font-size: {self.px(14)}px;
}}
QLineEdit#Prompt:focus {{
    border: 1px solid {p.accent};
}}
QLineEdit#Search {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {p.radius}px;
    padding: 8px 12px;
    font-size: {self.px(12)}px;
}}
QPlainTextEdit#CodeEdit {{
    background-color: {p.term_bg};
    border: 1px solid {p.border};
    border-radius: {p.radius}px;
    font-family: {p.mono_stack};
    font-size: {self.px(13)}px;
    padding: 12px 14px;
    color: {p.term_text};
}}
QComboBox {{
    padding-right: 28px;
    min-height: 18px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_muted};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.elevated};
    border: 1px solid {p.border_strong};
    border-radius: {p.radius_sm}px;
    padding: 4px;
    outline: none;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {p.surface_high};
    border: none;
    width: 16px;
}}

/* -------------------------------------------------------------- buttons */
QPushButton {{
    background-color: {p.surface_high};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {p.radius}px;
    padding: 8px 14px;
    font-size: {self.px(12)}px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {p.elevated};
    border: 1px solid {p.border_strong};
}}
QPushButton:pressed {{
    background-color: {p.surface_alt};
}}
QPushButton:disabled {{
    color: {p.text_faint};
    background-color: {p.surface};
    border: 1px solid {p.border};
}}
QPushButton#Primary {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p.accent}, stop:1 {p.purple});
    color: #ffffff;
    border: 1px solid transparent;
    padding: 10px 18px;
    font-size: {self.px(13)}px;
    font-weight: 700;
}}
QPushButton#Primary:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p.accent_hover}, stop:1 #AC92FF);
}}
QPushButton#Primary:pressed {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p.accent_pressed}, stop:1 #8360F0);
}}
QPushButton#Primary:disabled {{
    background-color: {p.surface_high};
    color: {p.text_faint};
}}
QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid {p.border};
    color: {p.text_muted};
}}
QPushButton#Ghost:hover {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border_strong};
}}
QPushButton#Danger {{
    background-color: {p.danger_soft};
    border: 1px solid rgba(248, 113, 113, 0.4);
    color: {p.danger};
}}
QPushButton#Danger:hover {{
    background-color: rgba(248, 113, 113, 0.22);
    border: 1px solid {p.danger};
}}
QPushButton#Chip {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {p.radius_xl}px;
    padding: 6px 12px;
    color: {p.text_muted};
    font-size: {self.px(11)}px;
    font-weight: 500;
}}
QPushButton#Chip:hover {{
    background-color: {p.accent_soft};
    border: 1px solid rgba(76, 141, 255, 0.36);
    color: {p.text};
}}
QPushButton#IconButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {p.radius_sm}px;
    padding: 5px;
}}
QPushButton#IconButton:hover {{
    background-color: {p.surface_high};
    border: 1px solid {p.border};
}}
QPushButton#Segment {{
    background-color: transparent;
    border: none;
    border-radius: {p.radius_sm}px;
    padding: 6px 12px;
    color: {p.text_muted};
    font-size: {self.px(11)}px;
    font-weight: 600;
}}
QPushButton#Segment:hover {{
    color: {p.text};
    background-color: {p.surface_high};
}}
QPushButton#Segment:checked {{
    background-color: {p.surface_high};
    color: {p.text};
    border: 1px solid {p.border_strong};
}}
QPushButton#Link {{
    background: transparent;
    border: none;
    color: {p.accent};
    padding: 2px 4px;
    font-size: {self.px(12)}px;
    font-weight: 600;
    text-align: left;
}}
QPushButton#Link:hover {{
    color: {p.accent_hover};
    text-decoration: underline;
}}

/* --------------------------------------------------------------- tables */
QTableWidget, QTableView {{
    background-color: {p.surface};
    alternate-background-color: transparent;
    border: none;
    gridline-color: transparent;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
    outline: none;
}}
QTableWidget::item {{
    padding: 8px 10px;
    border-bottom: 1px solid {p.border};
    color: {p.text_muted};
}}
QTableWidget::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}
QTableWidget::item:hover {{
    background-color: {p.surface_alt};
}}
QHeaderView {{
    background-color: {p.surface};
}}
QTableView QTableCornerButton::section {{
    background-color: {p.surface};
    border: none;
}}
QHeaderView::section {{
    background-color: {p.surface};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 8px 10px;
    font-size: {self.px(10)}px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QTableCornerButton::section {{
    background-color: transparent;
    border: none;
}}

/* ------------------------------------------------------------ scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.border_accent};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-width: 32px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* -------------------------------------------------------------- checkbox */
QCheckBox {{
    color: {p.text_muted};
    spacing: 9px;
    font-size: {self.px(12)}px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {p.border_strong};
    background-color: {p.surface_alt};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {p.accent};
}}
QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border: 1px solid {p.accent};
    image: url(:/icons/check.svg);
}}

/* --------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {p.surface_high};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.purple});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p.text};
    border: 2px solid {p.accent};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}

/* ------------------------------------------------------------ statusbar */
QFrame#StatusBar {{
    background-color: {p.overlay};
    border-top: 1px solid {p.border};
}}
QLabel#StatusText {{
    color: {p.text_dim};
    font-size: {self.px(11)}px;
    font-weight: 500;
}}
QLabel#StatusValue {{
    color: {p.text_muted};
    font-size: {self.px(11)}px;
    font-weight: 600;
}}
QFrame#StatusDivider {{
    background-color: {p.border};
    max-width: 1px;
    min-width: 1px;
}}

/* --------------------------------------------------------------- menus */
QMenu {{
    background-color: {p.elevated};
    border: 1px solid {p.border_strong};
    border-radius: {p.radius}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 12px;
    border-radius: {p.radius_sm}px;
    color: {p.text_muted};
    font-size: {self.px(12)}px;
}}
QMenu::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: 5px 8px;
}}

/* ------------------------------------------------------------ progress */
QProgressBar {{
    background-color: {p.surface_high};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.purple});
    border-radius: 3px;
}}

/* --------------------------------------------------------------- tabs */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 8px 14px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: {self.px(12)}px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabBar::tab:hover {{
    color: {p.text};
}}
"""

    def terminal_colors(self) -> dict[str, str]:
        p = self.palette
        return {
            "bg": p.term_bg,
            "text": p.term_text,
            "dim": p.term_dim,
            "prompt": p.term_prompt,
            "success": p.term_success,
            "error": p.term_error,
            "warning": p.term_warning,
            "info": p.term_info,
            "accent": p.accent,
            "purple": p.purple,
            "cyan": p.cyan,
        }
