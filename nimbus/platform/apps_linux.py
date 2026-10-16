"""Linux: finding installed programs for routing presets: .desktop entries (system, user,
Flatpak, Snap), Steam libraries and running processes. Same names as apps_windows.py."""
from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from ..i18n import tr
from .apps_common import _JUNK_NAME, _SKIP_GAMES, App, choose_main_exe

_JUNK_EXE = re.compile(r"unins|uninst|setup|install|crash|report|updater|redist|\.so(\.\d+)*$|\.sh$|\.py$", re.I)
_SYSTEM = ("/usr/lib/systemd", "/usr/libexec", "/usr/sbin", "/sbin", "/lib/systemd")
# Exec wrappers whose own name says nothing about the program they start.
_WRAPPERS = {"env", "sh", "bash", "flatpak", "snap", "gtk-launch", "kioclient", "kioclient5", "xdg-open", "steam"}


def _application_dirs() -> list[str]:
    home = os.path.expanduser("~")
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [data_home] + data_dirs + [os.path.join(data_home, "flatpak", "exports", "share"),
                                       "/var/lib/flatpak/exports/share"]
    dirs = [os.path.join(r, "applications") for r in roots] + ["/var/lib/snapd/desktop/applications"]
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def _desktop_entry(path: str) -> dict[str, str]:
    """The [Desktop Entry] section's keys, the name in the interface's language if there is one."""
    out: dict[str, str] = {}
    lang = (os.environ.get("LANG") or "").split(".")[0]
    section = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    section = line
                elif section == "[Desktop Entry]" and "=" in line:
                    key, _, value = line.partition("=")
                    out.setdefault(key.strip(), value.strip())
    except OSError:
        return {}
    for key in (f"Name[{lang}]", f"Name[{lang.split('_')[0]}]"):
        if out.get(key):
            out["Name"] = out[key]
            break
    return out


def _exec_target(exec_line: str) -> str:
    """The program a .desktop Exec line starts, as a real path ("" if it can't be told)."""
    try:
        words = shlex.split(exec_line)
    except ValueError:
        return ""
    words = [w for w in words if not w.startswith("%") and "=" not in w.split("/")[0]]
    if not words or os.path.basename(words[0]) in _WRAPPERS:
        return ""
    path = words[0] if os.path.isabs(words[0]) else shutil.which(words[0]) or ""
    return os.path.realpath(path) if path else ""


def _from_desktop_files() -> list[App]:
    out = []
    for folder in _application_dirs():
        for path in glob.glob(os.path.join(folder, "**", "*.desktop"), recursive=True):
            e = _desktop_entry(path)
            if e.get("Type", "Application") != "Application" or e.get("NoDisplay") == "true" \
                    or e.get("Hidden") == "true" or not e.get("Name") or _JUNK_NAME.search(e["Name"]):
                continue
            target = _exec_target(e.get("TryExec") or e.get("Exec", ""))
            if target:
                out.append(App(e["Name"], target))
    return out


def _steam_libraries() -> list[str]:
    home = os.path.expanduser("~")
    roots = [os.path.join(home, p) for p in (".steam/steam", ".local/share/Steam",
                                             ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    libs = set()
    for root in roots:
        if not os.path.isdir(os.path.join(root, "steamapps")):
            continue
        libs.add(os.path.realpath(root))
        try:
            with open(os.path.join(root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                libs |= {os.path.realpath(p) for p in re.findall(r'"path"\s+"([^"]+)"', f.read())}
        except OSError:
            pass
    return sorted(libs)


def _from_steam() -> list[App]:
    games = []
    for lib in _steam_libraries():
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(acf, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            name = re.search(r'"name"\s+"([^"]+)"', text)
            folder = re.search(r'"installdir"\s+"([^"]+)"', text)
            if name and folder and not _SKIP_GAMES.search(name.group(1)):
                path = os.path.join(lib, "steamapps", "common", folder.group(1))
                if os.path.isdir(path):
                    games.append(App(name.group(1), path, "dir", "Steam"))
    return games


# -- folders --------------------------------------------------------------------------------
def _is_program(path: str) -> bool:
    """An ELF executable, or a Windows .exe run through Proton / Wine."""
    name = os.path.basename(path)
    if _JUNK_EXE.search(name):
        return False
    if name.lower().endswith(".exe"):
        return True
    try:
        if not os.access(path, os.X_OK) or not os.path.isfile(path):
            return False
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def folder_exes(folder: str, depth: int = 4, limit: int = 60) -> list[str]:
    """Programs a few levels deep in a folder, installers and helpers left out."""
    out = []
    base = folder.rstrip("/").count(os.sep)
    for dirpath, dirs, files in os.walk(folder):
        if dirpath.count(os.sep) - base >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not _SKIP_GAMES.search(d) and d.lower() not in ("_commonredist", "redist")]
        out += [p for p in (os.path.join(dirpath, f) for f in files) if _is_program(p)]
        if len(out) >= limit:
            break
    return out[:limit]


def main_exe(folder: str, name: str = "", exes: list[str] | None = None) -> str:
    return choose_main_exe(folder, name, folder_exes(folder) if exes is None else exes)


# -- running processes ----------------------------------------------------------------------
def running_processes() -> dict[int, str]:
    """pid -> executable of this user's processes."""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            out[int(d)] = os.readlink(f"/proc/{d}/exe")
        except OSError:
            continue
    return out


def window_titles() -> dict[int, str]:
    """pid -> window title, where wmctrl can tell (X11 and XWayland windows)."""
    titles: dict[int, str] = {}
    if not shutil.which("wmctrl"):
        return titles
    try:
        out = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return titles
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[2].isdigit():
            titles.setdefault(int(parts[2]), parts[4])
    return titles


def _skip(path: str) -> bool:
    own = os.path.realpath(sys.executable)
    base = os.path.basename(path)
    return (path.startswith(_SYSTEM) or os.path.realpath(path) == own or base in ("xray", "sing-box")
            or path.endswith(" (deleted)"))


def running() -> list[App]:
    """Running programs, those with a window first. source holds the window title or "в фоне"."""
    titles = window_titles()
    by_path: dict[str, App] = {}
    for pid, path in running_processes().items():
        if _skip(path):
            continue
        app = by_path.get(path)
        if app is None:
            app = by_path[path] = App(describe(path), path, source=tr("в фоне"))
        if pid in titles and app.source == tr("в фоне"):
            title = titles[pid]
            app.source = title if len(title) <= 48 else title[:47] + "…"
    return sorted(by_path.values(), key=lambda a: (a.source == tr("в фоне"), a.name.casefold()))


def describe(path: str) -> str:
    return os.path.basename(path)


def _from_processes() -> list[App]:
    paths = {p for p in running_processes().values() if not _skip(p)}
    return [App(describe(p), p, source=tr("Запущена")) for p in sorted(paths)]


# -- all together -----------------------------------------------------------------------------
def _usable(app: App) -> bool:
    if app.kind == "dir":
        return os.path.isdir(app.path)
    return os.path.isfile(app.path) and not app.path.startswith(_SYSTEM)


def scan() -> list[App]:
    """Installed programs, quickly: no folder walking here (see fill_icons)."""
    sources = (_from_desktop_files, _from_steam, _from_processes)
    with ThreadPoolExecutor(len(sources)) as pool:
        results = list(pool.map(_safe, sources))
    seen: dict[str, App] = {}
    names: set[str] = set()
    for batch in results:                      # earlier sources name things better
        for app in batch:
            if app.key in seen or app.name.casefold() in names or not _usable(app):
                continue
            seen[app.key] = app
            names.add(app.name.casefold())
    return sorted(seen.values(), key=lambda a: a.name.casefold())


def fill_icons(apps: list[App]) -> None:
    """Find the main executable of every folder entry (games). Walks folders."""
    todo = [a for a in apps if a.kind == "dir" and not a.icon]
    with ThreadPoolExecutor(8) as pool:
        for app, exe in zip(todo, pool.map(lambda a: main_exe(a.path, a.name), todo)):
            app.icon = exe


def _safe(source) -> list[App]:
    try:
        return source()
    except Exception:  # one broken source shouldn't hide the others
        return []


def from_path(path: str) -> App:
    """An entry for a file or folder the user picked by hand."""
    path = os.path.realpath(path)
    if os.path.isdir(path):
        name = os.path.basename(path.rstrip("/")) or path
        return App(name, path, "dir", icon=main_exe(path, name))
    return App(describe(path), path)


def entry(app: App) -> dict:
    """What a preset stores. Folders also list their programs, matched by name."""
    d = app.as_dict()
    if app.kind == "dir":
        d["exes"] = sorted({os.path.basename(p) for p in folder_exes(app.path)})
    return d
