from __future__ import annotations

from PySide6.QtGui import QColor

from codex_usage_indicator.icon import (
    IconStatus,
    PRIMARY_BRIGHT,
    SECONDARY_BRIGHT,
    WARNING,
    build_usage_icon,
    remaining_color,
    render_usage_pixmap,
)


def color_count(pixmap, color: QColor) -> int:
    image = pixmap.toImage()
    target = color.rgba()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixel(x, y) == target
    )


def test_bright_arc_grows_with_remaining(qapp):
    counts = []
    for remaining in (0, 25, 50, 100):
        pixmap = render_usage_pixmap(128, remaining)
        counts.append(color_count(pixmap, PRIMARY_BRIGHT))
    assert counts[0] == 0
    assert counts == sorted(counts)
    assert len(set(counts)) == 4


def test_dual_ring_contains_two_bright_colors(qapp):
    pixmap = render_usage_pixmap(128, 75, 40)
    assert color_count(pixmap, PRIMARY_BRIGHT) > 0
    assert color_count(pixmap, SECONDARY_BRIGHT) > 0


def test_threshold_colors_are_stable():
    assert remaining_color(21) == PRIMARY_BRIGHT
    assert remaining_color(20) == WARNING
    assert remaining_color(11) == WARNING
    assert remaining_color(10).name() == "#ef4444"


def test_all_tray_sizes_render(qapp):
    icon = build_usage_icon(75, 40, IconStatus.STALE)
    assert not icon.isNull()
    for size in (16, 20, 24, 32, 48, 64):
        assert not icon.pixmap(size, size).isNull()
