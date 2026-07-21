from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from codex_usage_indicator.icon import IconStatus, render_usage_pixmap

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    QApplication.instance() or QApplication([])
    cases = [
        ("100%", 100, None, IconStatus.LIVE),
        ("75%", 75, None, IconStatus.LIVE),
        ("Dual 75/40", 75, 40, IconStatus.LIVE),
        ("Low 20/10", 20, 10, IconStatus.LIVE),
        ("Stale", 60, 35, IconStatus.STALE),
        ("Error", None, None, IconStatus.ERROR),
    ]
    width, height = 900, 190
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#0D1117"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#F8FAFC"))
    painter.setFont(QFont("Segoe UI", 11))
    for index, (label, primary, secondary, status) in enumerate(cases):
        x = 18 + index * 146
        icon = render_usage_pixmap(112, primary, secondary, status)
        painter.drawPixmap(x + 8, 15, icon)
        painter.drawText(QRect(x, 137, 136, 35), Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    output = ROOT / "build" / "icon_preview.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output))
    print(output)


if __name__ == "__main__":
    main()
