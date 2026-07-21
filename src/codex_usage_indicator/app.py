from __future__ import annotations

import argparse
from datetime import datetime
import logging
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QByteArray, QFileInfo, QLockFile, QObject, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QFileIconProvider,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .constants import (
    APP_NAME,
    APP_VERSION,
    DISPLAY_NAME,
    ORGANIZATION_NAME,
    STALE_AFTER_SECONDS,
    TOOLTIP_MAX_CHARS,
    app_data_dir,
    resource_path,
)
from .icon import IconStatus, build_usage_icon
from .models import (
    CreditsSnapshot,
    RateLimitBucket,
    RateLimitWindow,
    UsageSnapshot,
    format_duration,
    format_reset,
)
from .protocol import CodexAppServerClient, find_codex_executable
from .startup import is_autostart_enabled, open_folder, set_autostart_enabled
from .storage import configure_logging, load_snapshot, logs_dir, save_snapshot

LOGGER = logging.getLogger(__name__)
SINGLE_INSTANCE_NAME = f"CodexUsageIndicator-0.1-{os.environ.get('USERNAME', 'user')}"


def _window_tooltip_line(prefix: str, window: RateLimitWindow) -> str:
    return (
        f"{prefix} {format_duration(window.window_duration_mins)} "
        f"남음 {window.remaining_percent}% · {format_reset(window.resets_at, compact=True)}"
    )


def build_tooltip(
    snapshot: UsageSnapshot | None,
    status: IconStatus,
    detail: str = "",
    now: float | None = None,
) -> str:
    lines = [DISPLAY_NAME]
    bucket = snapshot.icon_bucket if snapshot else None
    if bucket is None:
        lines.append(detail or "Codex 사용량을 확인하는 중입니다.")
    else:
        if bucket.primary:
            lines.append(_window_tooltip_line("외부", bucket.primary))
        if bucket.secondary and bucket.primary:
            lines.append(_window_tooltip_line("내부", bucket.secondary))
        elif bucket.secondary:
            lines.append(_window_tooltip_line("외부(S)", bucket.secondary))
        if status == IconStatus.STALE:
            age = max(0, int((time.time() if now is None else now) - snapshot.fetched_at))
            lines.append(f"오래된 값 · {age // 60}분 전 갱신")
        elif status == IconStatus.ERROR:
            lines.append("현재 값을 확인할 수 없습니다.")
    tooltip = "\n".join(lines)
    if len(tooltip) > TOOLTIP_MAX_CHARS:
        tooltip = tooltip[: TOOLTIP_MAX_CHARS - 1] + "…"
    return tooltip


def _credits_text(credits: CreditsSnapshot | None) -> str:
    if credits is None:
        return "크레딧 정보 없음"
    if credits.unlimited:
        return "크레딧: 무제한"
    if credits.has_credits:
        return f"크레딧: {credits.balance or '사용 가능'}"
    return f"크레딧: 없음 ({credits.balance or '0'})"


class DetailsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(DISPLAY_NAME)
        self.setMinimumSize(760, 390)
        layout = QVBoxLayout(self)
        self.title_label = QLabel(f"<h2>{DISPLAY_NAME}</h2>")
        self.state_label = QLabel("사용량을 확인하는 중입니다.")
        self.state_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["제한", "구간", "사용", "남음", "기간", "초기화", "상태"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.meta_label = QLabel("")
        self.meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.refresh_button = QPushButton("새로 고침")
        self.refresh_button.clicked.connect(self._emit_refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.hide)
        buttons.addButton(self.refresh_button, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(self.title_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.meta_label)
        layout.addWidget(buttons)
        self._refresh_callback = None

    def set_refresh_callback(self, callback) -> None:
        self._refresh_callback = callback

    def _emit_refresh(self) -> None:
        if self._refresh_callback:
            self._refresh_callback()

    def update_snapshot(
        self,
        snapshot: UsageSnapshot | None,
        status: IconStatus,
        detail: str,
    ) -> None:
        state_names = {
            IconStatus.LIVE: "정상",
            IconStatus.STALE: "오래된 값",
            IconStatus.ERROR: "오류",
            IconStatus.STARTING: "연결 중",
        }
        self.state_label.setText(f"상태: {state_names[status]} · {detail}")
        self.table.setRowCount(0)
        if snapshot is None:
            self.meta_label.setText("아직 표시할 사용량이 없습니다.")
            return
        for bucket in snapshot.buckets:
            self._add_bucket_window(bucket, "Primary", bucket.primary)
            self._add_bucket_window(bucket, "Secondary", bucket.secondary)
        updated = datetime.fromtimestamp(snapshot.fetched_at).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        icon_bucket = snapshot.icon_bucket
        meta = [f"마지막 정상 갱신: {updated}"]
        if icon_bucket:
            meta.extend(
                [
                    f"플랜: {icon_bucket.plan_type or '미상'}",
                    _credits_text(icon_bucket.credits),
                ]
            )
        self.meta_label.setText(" · ".join(meta))

    def _add_bucket_window(
        self, bucket: RateLimitBucket, window_name: str, window: RateLimitWindow | None
    ) -> None:
        if window is None:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        reached = bucket.reached_type or "정상"
        values = [
            bucket.display_name,
            window_name,
            f"{window.used_percent}%",
            f"{window.remaining_percent}%",
            format_duration(window.window_duration_mins),
            format_reset(window.resets_at),
            reached,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in {2, 3}:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, column, item)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        event.ignore()
        self.hide()


class SingleInstance(QObject):
    def __init__(
        self,
        on_activate=None,
        on_quit=None,
        parent: QObject | None = None,
        lock_path: Path | None = None,
        server_name: str = SINGLE_INSTANCE_NAME,
    ) -> None:
        super().__init__(parent)
        self._on_activate = on_activate
        self._on_quit = on_quit
        resolved_lock_path = lock_path or (app_data_dir() / "instance.lock")
        resolved_lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(resolved_lock_path))
        self.lock.setStaleLockTime(0)
        self.server_name = server_name
        if not self.lock.tryLock(0):
            self.notify_existing(server_name=self.server_name)
            raise AlreadyRunningError
        self.server = QLocalServer(self)
        if not self.server.listen(self.server_name):
            self.lock.unlock()
            raise RuntimeError(self.server.errorString())
        self.server.newConnection.connect(self._handle_connection)

    @staticmethod
    def notify_existing(command: str = "show", server_name: str = SINGLE_INSTANCE_NAME) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if not socket.waitForConnected(500):
            return False
        if socket.write(QByteArray(command.encode("ascii", errors="ignore"))) < 0:
            socket.abort()
            return False
        socket.flush()
        if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(500):
            socket.abort()
            return False
        if socket.bytesAvailable() == 0 and not socket.waitForReadyRead(1_000):
            socket.abort()
            return False
        acknowledged = bytes(socket.readAll()).strip() == b"ok"
        socket.disconnectFromServer()
        return acknowledged

    def set_callbacks(self, on_activate, on_quit) -> None:
        self._on_activate = on_activate
        self._on_quit = on_quit

    @Slot()
    def close(self) -> None:
        self.server.close()
        self.lock.unlock()

    @Slot()
    def _handle_connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setParent(self)
            socket.readyRead.connect(lambda active=socket: self._handle_command(active))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable() > 0 or socket.waitForReadyRead(500):
                self._handle_command(socket)

    def _handle_command(self, socket: QLocalSocket) -> None:
        if socket.property("commandHandled"):
            return
        command = bytes(socket.readAll()).decode("ascii", errors="ignore").strip().lower()
        if not command:
            return
        socket.setProperty("commandHandled", True)
        socket.write(QByteArray(b"ok"))
        socket.flush()
        if socket.bytesToWrite() > 0:
            socket.waitForBytesWritten(500)
        if command == "quit" and self._on_quit:
            self._on_quit()
        elif self._on_activate:
            self._on_activate()


class AlreadyRunningError(RuntimeError):
    pass


class UsageIndicatorController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.snapshot = load_snapshot()
        self.status = IconStatus.STALE if self.snapshot else IconStatus.STARTING
        self.detail = "저장된 마지막 값을 불러왔습니다." if self.snapshot else "연결 준비 중"
        self.center_icon = self._load_codex_icon(find_codex_executable())
        self.details = DetailsDialog()
        self.details.set_refresh_callback(self.refresh)
        self.tray = QSystemTrayIcon(self)
        self.menu = QMenu()
        self.details_action = QAction("상세 정보", self.menu)
        self.refresh_action = QAction("새로 고침", self.menu)
        self.autostart_action = QAction("Windows 시작 시 실행", self.menu, checkable=True)
        self.logs_action = QAction("로그 폴더 열기", self.menu)
        self.about_action = QAction("정보", self.menu)
        self.quit_action = QAction("종료", self.menu)
        self.autostart_action.setChecked(is_autostart_enabled())
        self.menu.addAction(self.details_action)
        self.menu.addAction(self.refresh_action)
        self.menu.addSeparator()
        self.menu.addAction(self.autostart_action)
        self.menu.addAction(self.logs_action)
        self.menu.addSeparator()
        self.menu.addAction(self.about_action)
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)
        self.details_action.triggered.connect(self.show_details)
        self.refresh_action.triggered.connect(self.refresh)
        self.autostart_action.toggled.connect(self._toggle_autostart)
        self.logs_action.triggered.connect(lambda: open_folder(logs_dir()))
        self.about_action.triggered.connect(self._show_about)
        self.quit_action.triggered.connect(self.quit)
        self.tray.activated.connect(self._tray_activated)
        self.client = CodexAppServerClient(parent=self)
        self.client.snapshot_received.connect(self._on_snapshot)
        self.client.connection_state.connect(self._on_connection_state)
        self.client.codex_path_changed.connect(self._on_codex_path)
        self.stale_timer = QTimer(self)
        self.stale_timer.setInterval(30_000)
        self.stale_timer.timeout.connect(self._check_stale)
        self.stale_timer.start()
        self._render()
        self.tray.show()
        self.client.start()

    @staticmethod
    def _load_codex_icon(path: Path | None) -> QIcon | None:
        if path is None:
            return None
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(str(path)))
        return None if icon.isNull() else icon

    @Slot(str)
    def _on_codex_path(self, path: str) -> None:
        self.center_icon = self._load_codex_icon(Path(path))
        self._render()

    @Slot(object)
    def _on_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot = snapshot
        self.status = IconStatus.LIVE
        self.detail = "사용량을 정상적으로 갱신했습니다."
        try:
            save_snapshot(snapshot)
        except OSError as exc:
            LOGGER.warning("Could not save sanitized usage cache: %s", exc)
        self._render()

    @Slot(str, str)
    def _on_connection_state(self, state: str, detail: str) -> None:
        self.detail = detail
        if state == "live":
            self.status = IconStatus.LIVE
        elif state == "starting":
            self.status = IconStatus.STALE if self.snapshot else IconStatus.STARTING
        else:
            self.status = IconStatus.STALE if self.snapshot else IconStatus.ERROR
            LOGGER.warning("Codex app-server state: %s", detail)
        self._render()

    @Slot()
    def _check_stale(self) -> None:
        if (
            self.snapshot
            and self.status == IconStatus.LIVE
            and time.time() - self.snapshot.fetched_at > STALE_AFTER_SECONDS
        ):
            self.status = IconStatus.STALE
            self.detail = "마지막 정상 갱신 후 2분이 지났습니다."
            self._render()

    def _render(self) -> None:
        bucket = self.snapshot.icon_bucket if self.snapshot else None
        primary_window = bucket.primary if bucket else None
        secondary_window = bucket.secondary if bucket else None
        if primary_window is None and secondary_window is not None:
            primary_window, secondary_window = secondary_window, None
        primary = primary_window.remaining_percent if primary_window else None
        secondary = secondary_window.remaining_percent if secondary_window else None
        icon = build_usage_icon(primary, secondary, self.status, self.center_icon)
        self.tray.setIcon(icon)
        self.app.setWindowIcon(icon)
        self.tray.setToolTip(build_tooltip(self.snapshot, self.status, self.detail))
        self.details.update_snapshot(self.snapshot, self.status, self.detail)

    @Slot()
    def refresh(self) -> None:
        self.refresh_action.setEnabled(False)
        self.detail = "사용량을 새로 고치는 중입니다."
        self.status = IconStatus.STALE if self.snapshot else IconStatus.STARTING
        self._render()
        self.client.refresh()
        QTimer.singleShot(1500, lambda: self.refresh_action.setEnabled(True))

    @Slot()
    def show_details(self) -> None:
        self.details.show()
        self.details.raise_()
        self.details.activateWindow()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_details()

    @Slot(bool)
    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            set_autostart_enabled(enabled)
        except OSError as exc:
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(not enabled)
            self.autostart_action.blockSignals(False)
            QMessageBox.warning(self.details, DISPLAY_NAME, f"자동 시작 설정을 변경하지 못했습니다.\n{exc}")

    @Slot()
    def _show_about(self) -> None:
        QMessageBox.about(
            self.details,
            DISPLAY_NAME,
            f"<b>{DISPLAY_NAME}</b><br><br>"
            "Codex App Server의 로그인 상태를 재사용하여 사용량 제한을 표시합니다.<br>"
            "API 키와 인증 토큰은 읽거나 저장하지 않습니다.",
        )

    @Slot()
    def quit(self) -> None:
        self.client.stop()
        self.tray.hide()
        self.details.hide()
        self.app.quit()


def _run_smoke_test() -> int:
    app = QApplication.instance() or QApplication([])
    icon = build_usage_icon(75, 40, IconStatus.LIVE)
    if icon.isNull() or icon.pixmap(32, 32).isNull():
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--quit-existing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-for", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.version:
        print(DISPLAY_NAME)
        return 0
    if args.smoke_test:
        return _run_smoke_test()

    if args.quit_existing:
        quit_app = QApplication.instance() or QApplication(sys.argv[:1])
        SingleInstance.notify_existing("quit")
        del quit_app
        return 0

    configure_logging()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setQuitOnLastWindowClosed(False)
    static_icon_path = resource_path("assets/app_icon.ico")
    if static_icon_path.exists():
        app.setWindowIcon(QIcon(str(static_icon_path)))
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, DISPLAY_NAME, "Windows 시스템 트레이를 사용할 수 없습니다.")
        return 2
    if SingleInstance.notify_existing():
        return 0
    try:
        single_instance = SingleInstance(parent=app)
    except AlreadyRunningError:
        return 0
    controller = UsageIndicatorController(app)
    single_instance.set_callbacks(controller.show_details, controller.quit)
    app.aboutToQuit.connect(controller.client.stop)
    app.aboutToQuit.connect(single_instance.close)
    if args.run_for is not None:
        QTimer.singleShot(max(1, int(args.run_for * 1000)), controller.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
