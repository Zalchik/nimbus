"""Build the Linux release into dist/<version>/:

  Nimbus-<version>-x86_64.AppImage   one file: chmod +x and run; updates itself from GitHub Releases
  Nimbus-<version>-amd64.deb         Debian, Ubuntu, Mint…: installs into /opt/nimbus
  Nimbus-<version>-x86_64.rpm        Fedora, openSUSE…: the same
  SHA256SUMS.txt                     their checksums are added (other files' lines are kept)

The packages hold the same program as the AppImage. They update themselves through the package
manager (swap.install_package), and close a running Nimbus before an upgrade or removal changes
its files, so it disconnects and puts the proxy settings back.

Requires (on Linux, x86_64): PySide6, httpx, pyinstaller, and vendor/xray with xray, sing-box and
the geo files (python tools/fetch_cores.py linux). appimagetool is downloaded if it isn't on PATH;
the .deb needs dpkg-deb and the .rpm rpmbuild (Ubuntu: apt install rpm), else they're skipped.
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
Exec={exec} %u
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


# -- .deb and .rpm ----------------------------------------------------------------------------
PACKAGE = "nimbus-vpn"
OPT = "/opt/nimbus"
SUMMARY = "VPN client on Xray-core and sing-box"
DESCRIPTION = ("Nimbus connects through VLESS, VMess, Trojan, Shadowsocks, Hysteria and WireGuard "
               "servers from subscriptions, as a system proxy or with a TUN adapter.")
MAINTAINER = "Zalchik <210491893+Zalchik@users.noreply.github.com>"
HOMEPAGE = "https://github.com/Zalchik/nimbus"
# The cores and fonts it carries; Nimbus' own code has no license file yet.
LICENSE = "LicenseRef-Nimbus AND MPL-2.0 AND GPL-3.0 AND OFL-1.1"

# Shell for the maintainer scripts. Before an upgrade or a removal changes the files, every
# running Nimbus is closed the normal way, as its user: `Nimbus --quit` tells it to quit (it
# disconnects and puts the proxy settings back) and waits until it has gone. On removal
# --uninstall also drops its autostart entry. Found by its executable, not its name: started as
# `nimbus` (the menu, the command) the process is called that. /proc rather than ps: minimal
# systems lack procps.
CLOSE = f"""nimbus_close() {{
    [ -x {OPT}/Nimbus ] || return 0
    for uid in $(for d in /proc/[0-9]*; do
                     [ "$(readlink "$d/exe" 2>/dev/null)" = {OPT}/Nimbus ] && stat -c %u "$d" 2>/dev/null
                 done | sort -u); do
        [ "$uid" -eq 0 ] && continue
        user=$(id -nu "$uid" 2>/dev/null) || continue
        rt=/run/user/$uid
        [ -d "$rt" ] || rt=
        runuser -u "$user" -- env ${{rt:+XDG_RUNTIME_DIR=$rt}} ${{rt:+DBUS_SESSION_BUS_ADDRESS=unix:path=$rt/bus}} \\
            QT_QPA_PLATFORM=offscreen timeout 40 {OPT}/Nimbus --quit "$@" >/dev/null 2>&1 || true
    done
}}
"""
REFRESH = """if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
"""
# Written by the app the first time TUN is allowed (linux.POLKIT_RULE).
DROP_RULE = "rm -f /etc/polkit-1/rules.d/49-nimbus.rules\n"


def deb_scripts() -> dict[str, str]:
    return {
        "postinst": "#!/bin/sh\nset -e\n" + REFRESH,
        "prerm": ("#!/bin/sh\nset -e\n" + CLOSE +
                  'case "$1" in\n    remove|deconfigure) nimbus_close --uninstall ;;\n    *) nimbus_close ;;\nesac\n'),
        "postrm": ("#!/bin/sh\nset -e\n" + REFRESH +
                   'if [ "$1" = purge ]; then\n    ' + DROP_RULE + "fi\n"),
    }


def deb_control(installed_kb: int) -> str:
    return (f"Package: {PACKAGE}\nVersion: {VERSION}\nArchitecture: amd64\nMaintainer: {MAINTAINER}\n"
            f"Installed-Size: {installed_kb}\nSection: net\nPriority: optional\nHomepage: {HOMEPAGE}\n"
            "Depends: libc6 (>= 2.35), libegl1, libgl1, libfontconfig1, libxkbcommon-x11-0, libdbus-1-3\n"
            "Recommends: libcap2-bin, pkexec | policykit-1\n"
            f"Description: {SUMMARY}\n {DESCRIPTION}\n")


def rpm_spec(root: Path) -> str:
    # rpm runs %pre of the new package before its files land and %preun of the old one after:
    # an upgrade closes Nimbus in %pre ($1 >= 2), a removal in %preun ($1 = 0).
    return f"""%global debug_package %{{nil}}
%global __os_install_post %{{nil}}
%global __arch_install_post %{{nil}}
%define _build_id_links none

Name: {PACKAGE}
Version: {VERSION}
Release: 1
Summary: {SUMMARY}
License: {LICENSE}
URL: {HOMEPAGE}
BuildArch: x86_64
# The bundled Qt and Python libraries are inside: no dependencies on the system's versions.
AutoReqProv: no
Recommends: libcap
Recommends: polkit

%description
{DESCRIPTION}

%install
mkdir -p %{{buildroot}}
cp -a {root}/. %{{buildroot}}/

%files
%defattr(-,root,root,-)
{OPT}
/usr/bin/nimbus
/usr/share/applications/nimbus.desktop
/usr/share/icons/hicolor/256x256/apps/nimbus.png

%pre
{CLOSE}if [ "$1" -ge 2 ]; then
    nimbus_close
fi
exit 0

%preun
{CLOSE}if [ "$1" -eq 0 ]; then
    nimbus_close --uninstall
fi
exit 0

%post
{REFRESH}exit 0

%postun
{REFRESH}if [ "$1" -eq 0 ]; then
    {DROP_RULE}fi
exit 0
"""


def stage_package(app: Path, icon: Path, kind: str, build: Path) -> Path:
    """The files of the package as they land on the system: the app in /opt/nimbus with a
    marker saying how it updates (paths.PACKAGE), the `nimbus` command, the menu entry (it also
    opens nimbus:// links) and the icon."""
    root = build / f"pkg-{kind}"
    shutil.rmtree(root, ignore_errors=True)
    opt = root / OPT.lstrip("/")
    shutil.copytree(app, opt, symlinks=True)
    (opt / "package").write_text(kind + "\n")
    (root / "usr" / "bin").mkdir(parents=True)
    os.symlink(f"{OPT}/Nimbus", root / "usr" / "bin" / "nimbus")
    apps = root / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "nimbus.desktop").write_text(DESKTOP.format(exec="/usr/bin/nimbus"))
    icons = root / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icons.mkdir(parents=True)
    shutil.copy2(icon, icons / "nimbus.png")
    return root


def make_deb(app: Path, icon: Path, build: Path) -> Path | None:
    if not shutil.which("dpkg-deb"):
        print("dpkg-deb not found: no .deb")
        return None
    root = stage_package(app, icon, "deb", build)
    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file() and not f.is_symlink())
    debian = root / "DEBIAN"
    debian.mkdir()
    (debian / "control").write_text(deb_control(size // 1024))
    for name, text in deb_scripts().items():
        (debian / name).write_text(text)
        (debian / name).chmod(0o755)
    out = DIST / f"Nimbus-{VERSION}-amd64.deb"
    out.unlink(missing_ok=True)
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(out)], check=True)
    return out


def make_rpm(app: Path, icon: Path, build: Path) -> Path | None:
    if not shutil.which("rpmbuild"):
        print("rpmbuild not found: no .rpm")
        return None
    root = stage_package(app, icon, "rpm", build)
    top = build / "rpmbuild"
    shutil.rmtree(top, ignore_errors=True)
    (top / "SPECS").mkdir(parents=True)
    spec = top / "SPECS" / "nimbus.spec"
    spec.write_text(rpm_spec(root))
    subprocess.run(["rpmbuild", "-bb", "--define", f"_topdir {top}", str(spec)], check=True)
    built = next((top / "RPMS").rglob("*.rpm"))
    out = DIST / f"Nimbus-{VERSION}-x86_64.rpm"
    out.unlink(missing_ok=True)
    shutil.move(built, out)
    return out


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
    (appdir / "nimbus.desktop").write_text(DESKTOP.format(exec="Nimbus"))
    make_icon(appdir / "nimbus.png")
    shutil.copy2(appdir / "nimbus.png", appdir / ".DirIcon")

    out = DIST / f"Nimbus-{VERSION}-x86_64.AppImage"
    out.unlink(missing_ok=True)
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}   # no FUSE needed to build
    subprocess.run([str(appimagetool(build)), str(appdir), str(out)], check=True, env=env)
    out.chmod(0o755)

    packages = [p for p in (make_deb(app, appdir / "nimbus.png", build),
                            make_rpm(app, appdir / "nimbus.png", build)) if p]
    sums = DIST / "SHA256SUMS.txt"
    write_checksums([out, *packages], sums, keep=True)
    print(f"\nAppImage {out} ({out.stat().st_size / 1e6:.1f} MB)")
    for p in packages:
        print(f"Package  {p} ({p.stat().st_size / 1e6:.1f} MB)")
    print(f"Sums     {sums}")


if __name__ == "__main__":
    main()
