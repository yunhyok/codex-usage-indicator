"""PyInstaller-safe launcher.

PyInstaller analyzes this file directly, so it must use an absolute package import.
"""

from codex_usage_indicator.app import main


if __name__ == "__main__":
    raise SystemExit(main())
