from __future__ import annotations

from enum import Enum
from math import floor

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


class IconStatus(str, Enum):
    LIVE = "live"
    STALE = "stale"
    ERROR = "error"
    STARTING = "starting"


PRIMARY_BRIGHT = QColor("#19C37D")
SECONDARY_BRIGHT = QColor("#63D8FF")
USED_DARK = QColor("#30363D")
USED_DARK_INNER = QColor("#444C56")
WARNING = QColor("#F59E0B")
DANGER = QColor("#EF4444")
UNKNOWN = QColor("#6B7280")
OUTLINE = QColor("#111827")


def remaining_color(remaining: int | None, secondary: bool = False) -> QColor:
    if remaining is None:
        return UNKNOWN
    if remaining <= 10:
        return DANGER
    if remaining <= 20:
        return WARNING
    return SECONDARY_BRIGHT if secondary else PRIMARY_BRIGHT


def _clamp(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, min(100, int(value)))


def _draw_ring(
    painter: QPainter,
    rect: QRectF,
    width: float,
    remaining: int | None,
    bright: QColor,
    dark: QColor,
) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(OUTLINE, width + max(0.7, width * 0.18), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(rect, 0, 360 * 16)
    painter.setPen(QPen(dark, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.drawArc(rect, 0, 360 * 16)
    if remaining is None or remaining <= 0:
        return
    span = -floor(360 * 16 * remaining / 100)
    painter.setPen(QPen(bright, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(rect, 90 * 16, span)


def render_usage_pixmap(
    size: int,
    primary_remaining: int | None,
    secondary_remaining: int | None = None,
    status: IconStatus = IconStatus.LIVE,
    center_icon: QIcon | None = None,
) -> QPixmap:
    primary_remaining = _clamp(primary_remaining)
    secondary_remaining = _clamp(secondary_remaining)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if secondary_remaining is None:
        width = max(1.4, size * 0.15)
        margin = width / 2 + max(0.8, size * 0.055)
        rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        _draw_ring(
            painter,
            rect,
            width,
            primary_remaining,
            remaining_color(primary_remaining),
            USED_DARK,
        )
        center_extent = size * 0.43
    else:
        outer_width = max(1.1, size * 0.105)
        outer_margin = outer_width / 2 + max(0.6, size * 0.045)
        outer_rect = QRectF(
            outer_margin,
            outer_margin,
            size - 2 * outer_margin,
            size - 2 * outer_margin,
        )
        _draw_ring(
            painter,
            outer_rect,
            outer_width,
            primary_remaining,
            remaining_color(primary_remaining),
            USED_DARK,
        )
        inner_width = max(1.0, size * 0.09)
        inner_margin = outer_margin + outer_width * 1.38
        inner_rect = QRectF(
            inner_margin,
            inner_margin,
            size - 2 * inner_margin,
            size - 2 * inner_margin,
        )
        _draw_ring(
            painter,
            inner_rect,
            inner_width,
            secondary_remaining,
            remaining_color(secondary_remaining, secondary=True),
            USED_DARK_INNER,
        )
        center_extent = size * 0.31

    if center_icon is not None and not center_icon.isNull() and center_extent >= 4:
        extent = max(4, int(center_extent))
        icon_pixmap = center_icon.pixmap(extent, extent)
        x = (size - icon_pixmap.width()) // 2
        y = (size - icon_pixmap.height()) // 2
        painter.drawPixmap(x, y, icon_pixmap)
    else:
        glyph_extent = max(4.0, center_extent * 0.78)
        glyph_rect = QRectF(
            (size - glyph_extent) / 2,
            (size - glyph_extent) / 2,
            glyph_extent,
            glyph_extent,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                QColor("#F8FAFC"),
                max(1.0, size * 0.055),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(glyph_rect, 45 * 16, 270 * 16)

    if status in {IconStatus.STALE, IconStatus.ERROR}:
        badge = max(3.0, size * 0.22)
        badge_rect = QRectF(size - badge - 0.5, size - badge - 0.5, badge, badge)
        painter.setPen(QPen(OUTLINE, max(0.8, size * 0.035)))
        painter.setBrush(WARNING if status == IconStatus.STALE else DANGER)
        painter.drawEllipse(badge_rect)
    elif status == IconStatus.STARTING:
        dot = max(2.0, size * 0.13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(UNKNOWN)
        painter.drawEllipse(QRectF((size - dot) / 2, size - dot - 1, dot, dot))

    painter.end()
    return pixmap


def build_usage_icon(
    primary_remaining: int | None,
    secondary_remaining: int | None = None,
    status: IconStatus = IconStatus.LIVE,
    center_icon: QIcon | None = None,
) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(
            render_usage_pixmap(size, primary_remaining, secondary_remaining, status, center_icon)
        )
    return icon
