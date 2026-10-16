"""Installed and running programs for routing presets: App, scan(), running(), fill_icons(),
from_path(), entry(). The finders themselves are per system (nimbus/platform/apps_*.py)."""
import sys

if sys.platform == "win32":
    from .platform.apps_windows import App, entry, fill_icons, from_path, main_exe, running, scan  # noqa: F401
else:
    from .platform.apps_linux import App, entry, fill_icons, from_path, main_exe, running, scan  # noqa: F401
