"""Reusable, themed widgets that make up the TermX design system."""

from termx.ui.widgets.badges import Badge, Chip, RiskBadge, ShellBadge, StatusDot
from termx.ui.widgets.buttons import IconButton, PillButton, PrimaryButton, SegmentedControl
from termx.ui.widgets.cards import Card, MetricCard, SectionHeader, StatTile
from termx.ui.widgets.charts import BarChart, Sparkline
from termx.ui.widgets.command_panel import CommandPreviewPanel
from termx.ui.widgets.inputs import PromptInput, SearchField
from termx.ui.widgets.misc import (
    ClickableFrame,
    Divider,
    ElidedLabel,
    EmptyState,
    InfoRow,
    LoadingBar,
    ToggleSwitch,
    VDivider,
    animate,
    fade_in,
)
from termx.ui.widgets.terminal import TerminalView

__all__ = [
    "Badge",
    "BarChart",
    "Card",
    "Chip",
    "ClickableFrame",
    "CommandPreviewPanel",
    "Divider",
    "ElidedLabel",
    "EmptyState",
    "IconButton",
    "InfoRow",
    "LoadingBar",
    "MetricCard",
    "PillButton",
    "PrimaryButton",
    "PromptInput",
    "RiskBadge",
    "SearchField",
    "SectionHeader",
    "SegmentedControl",
    "ShellBadge",
    "Sparkline",
    "StatTile",
    "StatusDot",
    "TerminalView",
    "ToggleSwitch",
    "VDivider",
    "animate",
    "fade_in",
]
