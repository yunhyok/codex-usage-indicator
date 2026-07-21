from __future__ import annotations

from codex_usage_indicator.startup import autostart_command, quote_windows_argument


def test_windows_argument_quoting_handles_spaces():
    assert quote_windows_argument(r"C:\Program Files\Codex Usage Indicator\app.exe").startswith('"')


def test_source_autostart_uses_module_entrypoint():
    assert "-m codex_usage_indicator" in autostart_command()
