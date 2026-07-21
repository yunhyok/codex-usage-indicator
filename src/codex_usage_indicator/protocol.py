from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Mapping, TextIO

from PySide6.QtCore import QObject, Signal

from .constants import (
    APP_NAME,
    APP_VERSION,
    POLL_INTERVAL_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    STARTUP_TIMEOUT_SECONDS,
)
from .models import (
    UsagePayloadError,
    UsageSnapshot,
    snapshot_from_notification,
    snapshot_from_result,
)


class AppServerError(RuntimeError):
    pass


def find_codex_executable() -> Path | None:
    candidates: list[Path] = []
    resolved = shutil.which("codex")
    if resolved:
        candidates.append(Path(resolved))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "OpenAI" / "Codex" / "bin" / "codex.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def initialize_request(request_id: int = 1) -> dict[str, Any]:
    return {
        "id": request_id,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": "codex-usage-indicator",
                "title": APP_NAME,
                "version": APP_VERSION,
            },
            "capabilities": {"experimentalApi": True},
        },
    }


_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+|[\"']?(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|authorization)[\"']?\s*[:=]\s*[\"']?)([^\s,;\"']+)"
)
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_UUID_PATTERN = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_ACCOUNT_ID_PATTERN = re.compile(
    r"(?i)([\"']?(?:chatgptAccountId|account[_ -]?id|user[_ -]?id|workspace[_ -]?id|organization[_ -]?id)[\"']?\s*[:=]\s*[\"']?)([^\s,;\"']+)"
)


def sanitize_diagnostic(value: str) -> str:
    sanitized = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>", value)
    sanitized = _EMAIL_PATTERN.sub("<redacted-email>", sanitized)
    sanitized = _UUID_PATTERN.sub("<redacted-id>", sanitized)
    sanitized = _ACCOUNT_ID_PATTERN.sub(
        lambda match: f"{match.group(1)}<redacted-id>", sanitized
    )
    return sanitized.strip()[-1000:]


class CodexAppServerClient(QObject):
    snapshot_received = Signal(object)
    connection_state = Signal(str, str)
    codex_path_changed = Signal(str)

    def __init__(
        self,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.poll_interval = poll_interval
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._snapshot: UsageSnapshot | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._supervise, name="codex-app-server", daemon=True)
        self._thread.start()

    def refresh(self) -> None:
        self._refresh_event.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        self._refresh_event.set()
        self._terminate_process()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)
        self._terminate_process(force=True)

    def _supervise(self) -> None:
        backoffs = (5.0, 15.0, 30.0, 60.0, 300.0)
        failure_index = 0
        while not self._stop_event.is_set():
            try:
                self._run_session()
                failure_index = 0
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                message = sanitize_diagnostic(str(exc)) or exc.__class__.__name__
                self.connection_state.emit("error", message)
                self._terminate_process()
                delay = backoffs[min(failure_index, len(backoffs) - 1)]
                failure_index += 1
                if self._wait_for_retry(delay):
                    continue
            finally:
                self._terminate_process()

    def _wait_for_retry(self, delay: float) -> bool:
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if self._refresh_event.wait(min(0.25, max(0.0, deadline - time.monotonic()))):
                self._refresh_event.clear()
                return True
        return not self._stop_event.is_set()

    def _run_session(self) -> None:
        executable = find_codex_executable()
        if executable is None:
            raise AppServerError("Codex CLI를 찾을 수 없습니다. Codex를 설치하거나 PATH를 확인하세요.")
        self.codex_path_changed.emit(str(executable))
        self.connection_state.emit("starting", "Codex App Server를 시작하는 중입니다.")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(executable), "app-server", "-c", 'service_tier="fast"'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        with self._process_lock:
            self._process = process
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise AppServerError("Codex App Server stdio를 열 수 없습니다.")

        messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
        stderr_tail: deque[str] = deque(maxlen=20)
        threading.Thread(
            target=self._read_stream,
            args=(process.stdout, "stdout", messages),
            name="codex-app-server-stdout",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stderr,
            args=(process.stderr, stderr_tail),
            name="codex-app-server-stderr",
            daemon=True,
        ).start()

        self._send(process.stdin, initialize_request(1))
        initialized = self._wait_for_response(process, messages, 1, self.startup_timeout, stderr_tail)
        if "error" in initialized:
            raise AppServerError(self._error_text(initialized["error"]))
        self._send(process.stdin, {"method": "initialized"})

        request_id = 2
        pending_id: int | None = None
        pending_since = 0.0
        next_poll = 0.0
        self._refresh_event.set()
        while not self._stop_event.is_set():
            if process.poll() is not None:
                detail = "\n".join(stderr_tail)
                raise AppServerError(
                    f"Codex App Server가 종료되었습니다 (code {process.returncode}). {detail}"
                )
            now = time.monotonic()
            should_refresh = self._refresh_event.is_set() or now >= next_poll
            if should_refresh and pending_id is None:
                self._refresh_event.clear()
                self._send(process.stdin, {"id": request_id, "method": "account/rateLimits/read"})
                pending_id = request_id
                request_id += 1
                pending_since = now
            if pending_id is not None and now - pending_since > self.request_timeout:
                raise AppServerError("Codex 사용량 조회 응답 시간이 초과되었습니다.")

            try:
                source, line = messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if source == "stdout_eof":
                continue
            if line is None:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, Mapping):
                continue
            if pending_id is not None and payload.get("id") == pending_id:
                pending_id = None
                if "error" in payload:
                    raise AppServerError(self._error_text(payload["error"]))
                result = payload.get("result")
                if not isinstance(result, Mapping):
                    raise AppServerError("Codex 사용량 응답 형식이 올바르지 않습니다.")
                self._snapshot = snapshot_from_result(result)
                self.snapshot_received.emit(self._snapshot)
                self.connection_state.emit("live", "사용량을 정상적으로 갱신했습니다.")
                next_poll = time.monotonic() + self.poll_interval
            elif payload.get("method") == "account/rateLimits/updated":
                params = payload.get("params")
                if isinstance(params, Mapping):
                    try:
                        self._snapshot = snapshot_from_notification(params, self._snapshot)
                    except UsagePayloadError:
                        self._refresh_event.set()
                        continue
                    self.snapshot_received.emit(self._snapshot)
                    self.connection_state.emit("live", "사용량 변경 알림을 반영했습니다.")
                    self._refresh_event.set()
                    next_poll = time.monotonic() + self.poll_interval

    @staticmethod
    def _send(stream: TextIO, payload: Mapping[str, Any]) -> None:
        stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        stream.flush()

    @staticmethod
    def _read_stream(
        stream: TextIO, source: str, messages: queue.Queue[tuple[str, str | None]]
    ) -> None:
        for line in stream:
            messages.put((source, line.rstrip("\r\n")))
        messages.put((f"{source}_eof", None))

    @staticmethod
    def _read_stderr(stream: TextIO, stderr_tail: deque[str]) -> None:
        for line in stream:
            value = sanitize_diagnostic(line)
            if value:
                stderr_tail.append(value)

    def _wait_for_response(
        self,
        process: subprocess.Popen[str],
        messages: queue.Queue[tuple[str, str | None]],
        request_id: int,
        timeout: float,
        stderr_tail: deque[str],
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if process.poll() is not None:
                detail = "\n".join(stderr_tail)
                raise AppServerError(
                    f"Codex App Server 초기화 중 종료되었습니다 (code {process.returncode}). {detail}"
                )
            try:
                source, line = messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if source != "stdout" or line is None:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping) and payload.get("id") == request_id:
                return payload
        raise AppServerError("Codex App Server 초기화 시간이 초과되었습니다.")

    @staticmethod
    def _error_text(error: Any) -> str:
        if isinstance(error, Mapping):
            message = error.get("message")
            code = error.get("code")
            if message:
                return f"Codex 오류 {code}: {message}" if code is not None else str(message)
        return str(error)

    def _terminate_process(self, force: bool = False) -> None:
        with self._process_lock:
            process = self._process
            if process is not None and self._process is process:
                self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        if not force:
            try:
                process.wait(timeout=0.5)
                return
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            if not force:
                process.terminate()
                process.wait(timeout=2.0)
                return
        except OSError:
            pass
        except subprocess.TimeoutExpired:
            pass
        try:
            process.kill()
            try:
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            if force:
                try:
                    process.kill()
                except OSError:
                    pass
