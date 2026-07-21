from __future__ import annotations

import re
from pathlib import Path

from codex_usage_indicator.constants import APP_VERSION, DISPLAY_NAME

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_launcher_uses_absolute_package_import():
    launcher = (ROOT / "src" / "codex_usage_indicator" / "launcher.py").read_text(encoding="utf-8")
    spec = (ROOT / "CodexUsageIndicator.spec").read_text(encoding="utf-8")
    assert "from codex_usage_indicator.app import main" in launcher
    assert '"launcher.py"' in spec
    assert '"__main__.py"' not in spec


def test_version_is_aligned_across_release_surfaces():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "CodexUsageIndicator.iss").read_text(encoding="utf-8")
    version_info = (ROOT / "installer" / "version_info.txt").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f'version = "{APP_VERSION}"' in pyproject
    assert f'#define MyAppVersion "{APP_VERSION}"' in installer
    assert f"StringStruct(u'ProductVersion', u'{APP_VERSION}')" in version_info
    assert DISPLAY_NAME.replace(" v", " ") in readme


def test_build_script_has_bounded_packaged_smoke_test():
    script = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
    assert re.search(r"Wait-Process -Timeout 30", script)
    assert "smoke test timed out" in script
