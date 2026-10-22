"""Install Nimbus on Linux from the source code; the Makefile runs this (make install / uninstall).

    python3 tools/linux_install.py install   [--prefix P] [--destdir D]
    python3 tools/linux_install.py uninstall [--prefix P]

Layout under the prefix (default ~/.local, for you only and without root):

  lib/nimbus/app/         the program: main.py, nimbus/, resources/, vendor/xray/ (the cores)
  lib/nimbus/venv/        its own Python environment with PySide6 and httpx
  bin/nimbus              the command that starts it
  share/applications/nimbus.desktop                the menu entry; it also opens nimbus:// links
  share/icons/hicolor/256x256/apps/nimbus.png

Settings and subscriptions live in ~/.config/Nimbus, as with the AppImage, so both see the same
servers and an uninstall keeps them. Run with the Python the program should use.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nimbus.platform import linux  # noqa: E402  (stdlib only at import, creates nothing)

MIN_PYTHON = (3, 10)
CORES = ["xray", "sing-box", "geoip.dat", "geosite.dat", "LICENSE", "LICENSE-sing-box"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "p.json", "xlog.txt")
ICON = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(["nimbus", "-platform", "offscreen"])
from nimbus.ui.theme import app_pixmap
sys.exit(0 if app_pixmap(256).save(sys.argv[1], "PNG") else 1)
"""


class Layout:
    def __init__(self, prefix: str, destdir: str = ""):
        self.prefix = Path(os.path.expanduser(prefix)).absolute()
        self.root = Path(destdir + str(self.prefix)) if destdir else self.prefix   # where files are written
        self.destdir = destdir

    def at(self, *parts: str) -> Path:
        """A path where it's written (under DESTDIR, when packaging)."""
        return self.root.joinpath(*parts)

    def final(self, *parts: str) -> Path:
        """The same path as the installed system sees it."""
        return self.prefix.joinpath(*parts)

    lib = property(lambda self: self.at("lib", "nimbus"))
    launcher = property(lambda self: self.at("bin", "nimbus"))
    desktop = property(lambda self: self.at("share", "applications", linux.DESKTOP_FILE))
    icon = property(lambda self: self.at("share", "icons", "hicolor", "256x256", "apps", "nimbus.png"))


def launcher_script(layout: Layout) -> str:
    python = layout.final("lib", "nimbus", "venv", "bin", "python")
    main = layout.final("lib", "nimbus", "app", "main.py")
    # NIMBUS_LAUNCHER: autostart and restarts go through this command (see linux.app_command).
    return ("#!/bin/sh\n"
            "# Nimbus, installed from the source code by `make install`. `make uninstall` removes it.\n"
            f"NIMBUS_LAUNCHER={linux._exec_line([str(layout.final('bin', 'nimbus'))])}\n"
            "export NIMBUS_LAUNCHER\n"
            f"exec {linux._exec_line([str(python), str(main)])} \"$@\"\n")


def desktop_entry(layout: Layout) -> str:
    """The same entry the AppImage writes, pointing at our command."""
    exec_line = linux._exec_line([str(layout.final("bin", "nimbus"))]) + " %u"
    return linux._desktop_entry("Nimbus", exec_line, "nimbus", "MimeType=x-scheme-handler/nimbus;\n")


def ours(desktop: Path, layout: Layout) -> bool:
    """Whether a nimbus.desktop starts our command (the AppImage writes one by the same name)."""
    try:
        text = desktop.read_text()
    except OSError:
        return False
    return f"Exec={linux._exec_line([str(layout.final('bin', 'nimbus'))])} " in text


def _run(args: list, **kw) -> bool:
    try:
        return subprocess.run([str(a) for a in args], **kw).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _quiet(args: list) -> None:
    if shutil.which(str(args[0])) or Path(str(args[0])).exists():
        _run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def _close_running(layout: Layout) -> None:
    """Close a running Nimbus the normal way (it disconnects and puts the proxy settings back),
    as the Windows installer does. Not as root: that would be root's own Nimbus."""
    if layout.destdir or os.geteuid() == 0 or not layout.launcher.exists():
        return
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    _run([layout.launcher, "--quit"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def _venv_ok(python: Path) -> bool:
    """The environment exists, runs, and was made by this Python version (a system upgrade to
    a new Python leaves it without its packages)."""
    want = tuple(sys.version_info[:2])
    return _run([python, "-c", f"import sys; sys.exit(tuple(sys.version_info[:2]) != {want})"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _copy_app(dest: Path) -> None:
    new = dest.with_name("app.new")
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir(parents=True)
    for name in ("main.py", "requirements.txt", "README.md", "README.en.md"):
        shutil.copy2(ROOT / name, new / name)
    for name in ("nimbus", "resources"):
        shutil.copytree(ROOT / name, new / name, ignore=SKIP)
    cores = new / "vendor" / "xray"
    cores.mkdir(parents=True)
    for name in CORES:
        shutil.copy2(ROOT / "vendor" / "xray" / name, cores / name)
    for name in ("xray", "sing-box"):
        (cores / name).chmod(0o755)
    shutil.rmtree(dest, ignore_errors=True)
    new.rename(dest)


def install(layout: Layout) -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Nimbus needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer, this is {sys.version.split()[0]}. "
              "Run: make install PYTHON=python3.12 (or another version you have)")
        return 1
    try:
        import ensurepip  # noqa: F401  (python -m venv needs it)
    except ImportError:
        print("Python can't make environments here. Install the venv module: "
              "sudo apt install python3-venv (Debian, Ubuntu, Mint)")
        return 1
    missing = [n for n in CORES if not (ROOT / "vendor" / "xray" / n).exists()]
    if missing:
        print(f"vendor/xray is missing {', '.join(missing)}: run make install (it downloads them) "
              "or python3 tools/fetch_cores.py linux")
        return 1

    updating = layout.launcher.exists()
    _close_running(layout)
    print(f"installing into {layout.root}")
    _copy_app(layout.lib / "app")

    venv = layout.lib / "venv"
    python = venv / "bin" / "python"
    if not _venv_ok(python):
        shutil.rmtree(venv, ignore_errors=True)
        if not _run([sys.executable, "-m", "venv", venv]):
            print("couldn't create the Python environment (see above)")
            return 1
    print("installing PySide6 and httpx into it (the first time downloads about 250 MB)")
    if not _run([python, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
                 "-r", layout.lib / "app" / "requirements.txt"]):
        print("pip couldn't install the packages (see above)")
        return 1

    layout.launcher.parent.mkdir(parents=True, exist_ok=True)
    layout.launcher.write_text(launcher_script(layout))
    layout.launcher.chmod(0o755)
    layout.desktop.parent.mkdir(parents=True, exist_ok=True)
    layout.desktop.write_text(desktop_entry(layout))
    layout.icon.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as data:   # the app module makes its data folders on import
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "NIMBUS_DATA_DIR": data,
               "PYTHONPATH": str(layout.lib / "app")}
        if not _run([python, "-c", ICON, layout.icon], env=env):
            print("warning: couldn't draw the menu icon")

    if not layout.destdir:
        _quiet(["update-desktop-database", layout.desktop.parent])
        _quiet(["gtk-update-icon-cache", "-q", "-t", "-f", layout.at("share", "icons", "hicolor")])
        if os.geteuid() != 0:
            _quiet(["xdg-mime", "default", linux.DESKTOP_FILE, "x-scheme-handler/nimbus"])

    print(f"\nDone. Start Nimbus from the applications menu or with: {layout.final('bin', 'nimbus')}")
    if updating and not layout.destdir:
        print("(a running Nimbus was closed for the update: start it again)")
    on_path = str(layout.final("bin")) in os.environ.get("PATH", "").split(os.pathsep)
    if not on_path:
        print(f"({layout.final('bin')} isn't on your PATH: the menu entry works, the bare `nimbus` "
              "command will after you log in again, or use the full path)")
    return 0


def uninstall(layout: Layout) -> int:
    if not layout.lib.exists() and not layout.launcher.exists():
        print(f"Nimbus isn't installed in {layout.root}")
        return 0
    if not layout.destdir and os.geteuid() != 0 and layout.launcher.exists():
        # Its own clean-up, as the Windows uninstaller runs it: closes Nimbus, puts the proxy
        # settings back, removes its autostart entry and nimbus:// handler.
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        _run([layout.launcher, "--quit", "--uninstall"], env=env, stdout=subprocess.DEVNULL,
             stderr=subprocess.DEVNULL, timeout=60)
    elif os.geteuid() == 0:
        print("Close Nimbus first if it's running (as root this can't close your copy).")
    if ours(layout.desktop, layout):
        layout.desktop.unlink()
    for path in (layout.launcher, layout.icon):
        path.unlink(missing_ok=True)
    shutil.rmtree(layout.lib, ignore_errors=True)
    if not layout.destdir:
        _quiet(["update-desktop-database", layout.desktop.parent])
    print(f"Nimbus is removed from {layout.root}.")
    data = linux.data_dir("Nimbus")
    print(f"Settings and subscriptions stay in {data}: rm -rf {linux._exec_line([str(data)])} removes them.")
    if (data / "core" / "sing-box").exists():
        print("TUN mode was set up: sudo rm -f /etc/polkit-1/rules.d/49-nimbus.rules removes its DNS rule.")
    return 0


def main(argv: list[str]) -> int:
    if not sys.platform.startswith("linux"):
        print("This installs Nimbus on Linux. On Windows use the installer or the portable zip.")
        return 1
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("install", "uninstall"))
    p.add_argument("--prefix", default=os.path.join(Path.home(), ".local"))
    p.add_argument("--destdir", default="")
    a = p.parse_args(argv)
    layout = Layout(a.prefix, a.destdir)
    return install(layout) if a.action == "install" else uninstall(layout)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
