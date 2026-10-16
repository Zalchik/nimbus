"""Build the Linux release into dist/<version>/:

  Nimbus-<version>-x86_64.AppImage   one file: chmod +x and run; updates itself from GitHub Releases
  SHA256SUMS.txt                     its checksum is added (other files' lines are kept)

Requires (on Linux, x86_64): PySide6, httpx, pyinstaller, and vendor/xray with xray, sing-box and
the geo files (python tools/fetch_cores.py linux). appimagetool is downloaded if it isn't on PATH.
Run: python build_linux.py
"""
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NIMBUS_DATA_DIR", str(ROOT / "build" / "data"))

from build import write_checksums  # noqa: E402
from nimbus.paths import VERSION  # noqa: E402

DIST = Path(os.environ.get("NIMBUS_DIST", ROOT / "dist")) / VERSION
VENDOR = ROOT / "vendor" / "xray"
CORE_FILES = ["xray", "sing-box", "geoip.dat", "geosite.dat", "LICENSE", "LICENSE-sing-box"]
APPIMAGETOOL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
DESKTOP = """[Desktop Entry]
Type=Application
Name=Nimbus
Comment=VPN client on Xray-core and sing-box
Exec=Nimbus %u
Icon=nimbus
Categories=Network;
MimeType=x-scheme-handler/nimbus;
Terminal=false
"""
APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/nimbus/Nimbus" "$@"
"""


def make_icon(path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from nimbus.ui.theme import app_pixmap

    QApplication.instance() or QApplication(["build", "-platform", "offscreen"])
    app_pixmap(256).save(str(path), "PNG")


def appimagetool(build: Path) -> Path:
    found = shutil.which("appimagetool")
    if found:
        return Path(found)
    tool = build / "appimagetool-x86_64.AppImage"
    if not tool.exists():
        print("downloading appimagetool")
        urllib.request.urlretrieve(APPIMAGETOOL, tool)
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    return tool


def main() -> None:
    if not sys.platform.startswith("linux"):
        sys.exit("build_linux.py builds on Linux (see .github/workflows/build.yml); on Windows use build.py")
    missing = [f for f in CORE_FILES if not (VENDOR / f).exists()]
    if missing:
        sys.exit(f"vendor/xray is missing: {', '.join(missing)} (python tools/fetch_cores.py linux)")

    build = ROOT / "build" / "linux"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True)
    DIST.mkdir(parents=True, exist_ok=True)

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "Nimbus", "--distpath", str(build / "dist"), "--workpath", str(build / "pyinstaller"),
        "--specpath", str(build),
        "--add-data", f"{ROOT / 'resources'}:resources",
        "--hidden-import", "httpx",  # imported on first use (nimbus/lazy.py)
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtMultimedia", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "tkinter", "--exclude-module", "numpy", "--exclude-module", "PIL",
        str(ROOT / "main.py"),
    ], check=True)

    appdir = build / "Nimbus.AppDir"
    app = appdir / "usr" / "lib" / "nimbus"
    app.parent.mkdir(parents=True)
    shutil.copytree(build / "dist" / "Nimbus", app, symlinks=True)
    core = app / "core"
    core.mkdir()
    for f in CORE_FILES:
        shutil.copy2(VENDOR / f, core / f)
    for f in ("xray", "sing-box"):
        (core / f).chmod(0o755)
    for readme in ("README.md", "README.en.md"):
        shutil.copy2(ROOT / readme, app / readme)
    (appdir / "AppRun").write_text(APPRUN)
    (appdir / "AppRun").chmod(0o755)
    (appdir / "nimbus.desktop").write_text(DESKTOP)
    make_icon(appdir / "nimbus.png")
    shutil.copy2(appdir / "nimbus.png", appdir / ".DirIcon")

    out = DIST / f"Nimbus-{VERSION}-x86_64.AppImage"
    out.unlink(missing_ok=True)
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}   # no FUSE needed to build
    subprocess.run([str(appimagetool(build)), str(appdir), str(out)], check=True, env=env)
    out.chmod(0o755)

    sums = DIST / "SHA256SUMS.txt"
    write_checksums([out], sums, keep=True)
    print(f"\nAppImage {out} ({out.stat().st_size / 1e6:.1f} MB)\nSums     {sums}")


if __name__ == "__main__":
    main()
