"""Build a release into dist/<version>/:

  Nimbus/                          the app folder (keeps data in %APPDATA%, like an installed copy)
  Nimbus-<version>-portable.zip    the same plus a "portable" marker: data stays in Nimbus/data
  Nimbus-<version>-setup.exe       installer; also updates an installed copy, has an uninstaller
  SHA256SUMS.txt                   checksums of the two above; upload it with them: the in-app
                                   updater checks downloads against it

Requires: PySide6, httpx, pyinstaller, Pillow, and vendor/xray with xray.exe, sing-box.exe (TUN), geo files.
The setup needs Inno Setup 6 (https://jrsoftware.org/isinfo.php); without it the rest is still built.
Run: python build.py
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NIMBUS_DATA_DIR", str(ROOT / "build" / "data"))

from nimbus.paths import VERSION  # noqa: E402

DIST = Path(os.environ.get("NIMBUS_DIST", ROOT / "dist")) / VERSION
VENDOR = ROOT / "vendor" / "xray"
# sing-box carries Wintun inside, so no wintun.dll any more.
CORE_FILES = ["xray.exe", "sing-box.exe", "geoip.dat", "geosite.dat", "LICENSE", "LICENSE-sing-box"]
# Qt pieces a widgets-only app never loads.
PRUNE = ["opengl32sw.dll", "Qt6Quick*.dll", "Qt6Qml*.dll", "Qt6Pdf.dll", "Qt6OpenGL.dll",
         "Qt6VirtualKeyboard.dll", "translations", "plugins/imageformats/qpdf.dll",
         "plugins/platforminputcontexts", "plugins/generic"]


def make_icon(path: Path) -> None:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from nimbus.ui.theme import app_pixmap

    app = QApplication.instance() or QApplication(["build", "-platform", "offscreen"])
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_pixmap(256).save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(buf.data())))
    img.save(path, sizes=[(s, s) for s in (16, 20, 24, 32, 48, 64, 128, 256)])


def find_iscc() -> Path | None:
    """Inno Setup's command-line compiler, wherever the Inno Setup 6 installer put it."""
    found = shutil.which("iscc")
    if found:
        return Path(found)
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(base) / "Inno Setup 6" / "ISCC.exe"
    return None


PORTABLE_NOTE = ("This copy keeps its settings and subscriptions in the data folder next to Nimbus.exe.\r\n"
                 "Delete this file to keep them in %APPDATA%\\Nimbus instead.\r\n")


def make_portable_zip(app_dir: Path, archive: Path) -> None:
    """The app folder plus the "portable" marker that keeps the data beside the exe."""
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in app_dir.rglob("*"):
            z.write(p, Path("Nimbus") / p.relative_to(app_dir))
        z.writestr("Nimbus/portable", PORTABLE_NOTE)


def make_setup(app_dir: Path, icon: Path) -> Path | None:
    """Nimbus-<version>-setup.exe: installs, updates an installed copy, and has an uninstaller."""
    iscc = find_iscc()
    if not iscc:
        print("\nInno Setup 6 не найден, установщик не собран. Установите его "
              "(winget install JRSoftware.InnoSetup) и запустите сборку снова.")
        return None
    subprocess.run([str(iscc), "/Q", f"/DAppVersion={VERSION}", f"/DSourceDir={app_dir}", f"/DOutputDir={DIST}",
                    f"/DIconFile={icon}", str(ROOT / "installer" / "nimbus.iss")], check=True)
    return DIST / f"Nimbus-{VERSION}-setup.exe"


def write_checksums(files: list[Path], out: Path) -> None:
    """sha256sum-style list ("<hex>  <name>") that the in-app updater checks downloads against."""
    lines = []
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {f.name}")
    out.write_bytes("".join(line + "\n" for line in lines).encode())


def main() -> None:
    missing = [f for f in CORE_FILES if not (VENDOR / f).exists()]
    if missing:
        sys.exit(f"vendor/xray is missing: {', '.join(missing)}")

    # PyInstaller wipes dist/Nimbus first and dies halfway with WinError 5 if something there is
    # still in use, most often the previous build running (it hides in the tray) or its xray.exe.
    old = DIST / "Nimbus"
    if old.exists():
        try:
            shutil.rmtree(old)
        except PermissionError as e:
            sys.exit(f"\nНе удаётся удалить старую сборку: {e.filename}\n"
                     f"Закройте Nimbus, запущенный из {old} (значок в трее → Выход), и его xray.exe "
                     f"(Диспетчер задач), закройте окна Проводника с этой папкой и запустите сборку снова.")

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    icon = build / "nimbus.ico"
    make_icon(icon)

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "Nimbus", "--icon", str(icon),
        "--distpath", str(DIST), "--workpath", str(build / "pyinstaller"),
        "--specpath", str(build),
        "--add-data", f"{ROOT / 'resources'};resources",
        "--hidden-import", "httpx",  # imported on first use (nimbus/lazy.py), invisible to the analysis
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtMultimedia", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "tkinter", "--exclude-module", "numpy", "--exclude-module", "PIL",
        str(ROOT / "main.py"),
    ], check=True)

    app_dir = DIST / "Nimbus"
    qt = app_dir / "_internal" / "PySide6"
    for pattern in PRUNE:
        for p in qt.glob(pattern):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    core = app_dir / "core"
    core.mkdir(exist_ok=True)
    for f in CORE_FILES:
        shutil.copy2(VENDOR / f, core / f)
    shutil.copy2(ROOT / "README.md", app_dir / "README.md")

    archive = DIST / f"Nimbus-{VERSION}-portable.zip"
    make_portable_zip(app_dir, archive)
    setup = make_setup(app_dir, icon)
    sums = DIST / "SHA256SUMS.txt"
    write_checksums([archive] + ([setup] if setup else []), sums)
    print(f"\nBuilt    {app_dir}\nPortable {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    if setup:
        print(f"Setup    {setup} ({setup.stat().st_size / 1e6:.1f} MB)")
    print(f"Sums     {sums}  (upload it to the release too)")


if __name__ == "__main__":
    main()
