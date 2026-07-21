from __future__ import annotations

from codex_usage_indicator.constants import APP_NAME, APP_VERSION
import subprocess

from codex_usage_indicator.protocol import (
    CodexAppServerClient,
    initialize_request,
    sanitize_diagnostic,
)


def test_initialize_request_identifies_version_and_enables_protocol_fields():
    request = initialize_request(7)
    assert request["id"] == 7
    assert request["method"] == "initialize"
    assert request["params"]["clientInfo"]["title"] == APP_NAME
    assert request["params"]["clientInfo"]["version"] == APP_VERSION
    assert request["params"]["capabilities"]["experimentalApi"] is True


def test_diagnostics_redact_common_secret_shapes():
    value = sanitize_diagnostic(
        'Bearer abc123 api_key=secret access-token:tokenvalue '
        '"refresh_token":"refresh-secret" "id_token":"id-secret" '
        'person@example.com 019f83bf-3ed5-48c1-b897-07411437b93c '
        'chatgptAccountId=org-123 account_id=acct-secret user-id=user-456'
    )
    assert "abc123" not in value
    assert "secret" not in value
    assert "tokenvalue" not in value
    assert "person@example.com" not in value
    assert "019f83bf" not in value
    assert "org-123" not in value
    assert "acct-secret" not in value
    assert "user-456" not in value
    assert value.count("<redacted>") == 5
    assert "<redacted-email>" in value
    assert "<redacted-id>" in value


class _FakeStdin:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _HungProcess:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("fake", timeout)

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1


def test_hung_child_is_killed_and_reference_cleared(qapp):
    client = CodexAppServerClient()
    process = _HungProcess()
    client._process = process
    client._terminate_process()
    assert process.stdin.closed
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert client._process is None
