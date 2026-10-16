"""Finding installed programs for routing presets: Start menu and desktop shortcuts, the
uninstall registry, App Paths, Steam and Epic libraries and running processes.

Everything is read directly (shortcuts are parsed, not resolved through COM), and the sources
are scanned in parallel, so a full scan takes well under a second.
"""
from __future__ import annotations

import ctypes
import glob
import json
import os
import re
import struct
import sys
import winreg
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass

WINDIR = os.environ.get("SystemRoot", r"C:\Windows").lower()
_JUNK_EXE = re.compile(r"unins|uninst|setup|install|crash|report|helper|updater|update\.exe$|vcredist|dxsetup"
                       r"|redist|elevat|bugsplat|cefsharp|notification|squirrel", re.I)
_JUNK_NAME = re.compile(r"uninstall|удал|readme|help|справк|manual|руководств|documentation|website|сайт|"
                        r"license|лиценз|changelog|what'?s new|release notes|support|поддержк", re.I)
_SKIP_GAMES = re.compile(r"redistributable|steamworks|proton|steam linux runtime|directx", re.I)


@dataclass
class App:
    name: str
    path: str            # exe file, or folder for kind "dir"
    kind: str = "exe"    # "exe" | "dir"
    source: str = ""     # "Steam", "Epic", "Запущена", ""
    icon: str = ""       # file to take the icon from (an exe inside a game folder)

    @property
    def key(self) -> str:
        return os.path.normcase(os.path.normpath(self.path))

    def as_dict(self) -> dict:
        return {"name": self.name, "path": self.path, "kind": self.kind}


# -- shortcuts -----------------------------------------------------------------------------
def _cstr(data: bytes, pos: int, wide: bool) -> str:
    if wide:
        end = pos
        while end + 1 < len(data) and data[end:end + 2] != b"\0\0":
            end += 2
        return data[pos:end].decode("utf-16-le", "replace")
    end = data.find(b"\0", pos)
    return data[pos:end if end >= 0 else len(data)].decode("mbcs", "replace")


def lnk_target(path: str) -> tuple[str, str] | None:
    """(target path, arguments) of a .lnk file, from its binary format [MS-SHLLINK]."""
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 16)
    except OSError:
        return None
    if len(data) < 0x4C or data[:4] != b"L\0\0\0":
        return None
    u16 = lambda o: struct.unpack_from("<H", data, o)[0]  # noqa: E731
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]  # noqa: E731
    try:
        flags = u32(0x14)
        pos = 0x4C
        if flags & 0x01:                       # HasLinkTargetIDList
            pos += 2 + u16(pos)
        target = ""
        if flags & 0x02:                       # HasLinkInfo
            li = pos
            size, header, li_flags = u32(li), u32(li + 4), u32(li + 8)
            if li_flags & 0x01:                # VolumeIDAndLocalBasePath
                if header >= 0x24:
                    target = _cstr(data, li + u32(li + 0x1C), True) + _cstr(data, li + u32(li + 0x20), True)
                else:
                    target = _cstr(data, li + u32(li + 0x10), False) + _cstr(data, li + u32(li + 0x18), False)
            pos += size
        wide = bool(flags & 0x80)
        strings = {}
        for bit, key in ((0x04, "name"), (0x08, "rel"), (0x10, "dir"), (0x20, "args"), (0x40, "icon")):
            if flags & bit:
                n = u16(pos)
                pos += 2
                raw = data[pos:pos + (2 * n if wide else n)]
                strings[key] = raw.decode("utf-16-le" if wide else "mbcs", "replace")
                pos += len(raw)
        if not target:
            while pos + 8 <= len(data):        # EnvironmentVariableDataBlock
                block, sig = u32(pos), u32(pos + 4)
                if block < 8:
                    break
                if sig == 0xA0000001 and block >= 0x314:
                    target = os.path.expandvars(_cstr(data, pos + 8 + 260, True))
                    break
                pos += block
        if not target and strings.get("rel"):
            target = os.path.normpath(os.path.join(os.path.dirname(path), strings["rel"]))
    except (struct.error, IndexError):
        return None
    return (target, strings.get("args", "")) if target else None


def _shortcut_dirs() -> list[str]:
    env = os.environ.get
    roots = [
        os.path.join(env("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(env("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(env("USERPROFILE", ""), "Desktop"),
        os.path.join(env("PUBLIC", r"C:\Users\Public"), "Desktop"),
        os.path.join(env("USERPROFILE", ""), "OneDrive", "Desktop"),
    ]
    return [r for r in roots if os.path.isdir(r)]


def _from_shortcuts() -> list[App]:
    out = []
    for root in _shortcut_dirs():
        for lnk in glob.iglob(os.path.join(root, "**", "*.lnk"), recursive=True):
            name = os.path.splitext(os.path.basename(lnk))[0]
            if _JUNK_NAME.search(name):
                continue
            res = lnk_target(lnk)
            if not res:
                continue
            target, args = res
            m = re.search(r"--processStart\s+\"?([^\"\s]+\.exe)", args, re.I)
            if m and os.path.basename(target).lower() == "update.exe":
                # Squirrel apps (Discord, Slack…) live in versioned subfolders: match the folder.
                out.append(App(name, os.path.dirname(target), "dir", icon=_newest(os.path.dirname(target), m.group(1))))
                continue
            out.append(App(name, target))
    return out


def _newest(folder: str, exe: str) -> str:
    hits = sorted(glob.glob(os.path.join(folder, "app-*", exe)))
    return hits[-1] if hits else ""


# -- registry ------------------------------------------------------------------------------
def _subkeys(root, path: str, view: int = 0):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, name) as sub:
                        yield name, sub
                except OSError:
                    continue
    except OSError:
        return


def _value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _from_registry() -> list[App]:
    out = []
    hives = [(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
             (winreg.HKEY_CURRENT_USER, 0)]
    for root, view in hives:
        for _, key in _subkeys(root, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", view):
            name = _value(key, "DisplayName")
            if not name or _value(key, "SystemComponent") == 1 or _JUNK_NAME.search(name):
                continue
            icon = str(_value(key, "DisplayIcon") or "").strip()
            icon = re.sub(r",\s*-?\d+$", "", icon).strip().strip('"')
            if icon.lower().endswith(".exe"):
                out.append(App(name, os.path.expandvars(icon)))
        for exe, key in _subkeys(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths", view):
            path = str(_value(key, "") or "").strip().strip('"')
            if path.lower().endswith(".exe"):
                out.append(App(os.path.splitext(exe)[0], os.path.expandvars(path)))
    return out


# -- game libraries ------------------------------------------------------------------------
def folder_exes(folder: str, depth: int = 4, limit: int = 60) -> list[str]:
    """Executables a few levels deep in a program folder, installers and crash handlers left out."""
    out = []
    base = folder.rstrip("\\/").count(os.sep)
    for dirpath, dirs, files in os.walk(folder):
        if dirpath.count(os.sep) - base >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not _SKIP_GAMES.search(d) and d.lower() not in ("_commonredist", "redist")]
        out += [os.path.join(dirpath, f) for f in files if f.lower().endswith(".exe") and not _JUNK_EXE.search(f)]
        if len(out) >= limit:
            break
    return out[:limit]


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def main_exe(folder: str, name: str = "", exes: list[str] | None = None) -> str:
    """The game's own executable: named like the game or its folder, else the shallowest and biggest."""
    exes = folder_exes(folder) if exes is None else exes
    words = re.findall(r"\w+", name.lower())
    acronym = "".join(w[0] for w in words if not w.isdigit()) + "".join(w for w in words if w.isdigit())
    names = {n for n in (_norm(name), _norm(os.path.basename(folder.rstrip("\\/"))), acronym) if len(n) >= 2}
    base = folder.rstrip("\\/").count(os.sep)

    def score(path: str):
        stem = _norm(os.path.splitext(os.path.basename(path))[0])
        similar = any(n in stem or stem in n for n in names) or "shipping" in stem
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        return similar, -(path.count(os.sep) - base), size

    return max(exes, key=score, default="")


def _from_steam() -> list[App]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = os.path.normpath(_value(key, "SteamPath") or "")
    except OSError:
        return []
    out = []
    if os.path.isfile(os.path.join(steam, "steam.exe")):
        out.append(App("Steam", os.path.join(steam, "steam.exe")))
    libraries = {steam}
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
            libraries |= {os.path.normpath(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', f.read())}
    except OSError:
        pass
    games = []
    for lib in libraries:
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
    return out + games


def _from_epic() -> list[App]:
    out = []
    root = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Epic\EpicGamesLauncher\Data\Manifests")
    for item in glob.glob(os.path.join(root, "*.item")):
        try:
            with open(item, encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        folder = j.get("InstallLocation", "")
        if j.get("DisplayName") and os.path.isdir(folder):
            exe = os.path.join(folder, j.get("LaunchExecutable", ""))
            out.append(App(j["DisplayName"], folder, "dir", "Epic", exe if os.path.isfile(exe) else ""))
    return out


# -- running processes ---------------------------------------------------------------------
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def running_paths() -> list[str]:
    return sorted(set(running_processes().values()))


def running_processes() -> dict[int, str]:
    """pid -> exe path of every process we may query (elevated ones are skipped without admin)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    paths: dict[int, str] = {}
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    ok = k32.Process32FirstW(snap, ctypes.byref(entry))
    buf = ctypes.create_unicode_buffer(1024)
    while ok:
        h = k32.OpenProcess(0x1000, False, entry.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                paths[entry.th32ProcessID] = buf.value
            k32.CloseHandle(h)
        ok = k32.Process32NextW(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return paths


def window_titles() -> dict[int, str]:
    """pid -> title of its main visible window (top-level, not a tool window, has a title)."""
    u32 = ctypes.WinDLL("user32")
    titles: dict[int, str] = {}
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.GetWindowLongW.restype = ctypes.c_long

    def visit(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.GetWindow(hwnd, 4):        # GW_OWNER
            return True
        if u32.GetWindowLongW(hwnd, -20) & 0x80:                           # WS_EX_TOOLWINDOW
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        titles.setdefault(pid.value, buf.value)
        return True

    u32.EnumWindows(proto(visit), 0)
    return titles


def running() -> list[App]:
    """Running programs, those with a window first. source holds the window title or "в фоне"."""
    own = os.path.normcase(os.path.abspath(sys.executable))
    titles = window_titles()
    by_path: dict[str, App] = {}
    for pid, path in running_processes().items():
        low = path.lower()
        if low.startswith(WINDIR) or os.path.normcase(path) == own or low.endswith("xray.exe"):
            continue
        app = by_path.get(low)
        if app is None:
            app = by_path[low] = App(describe(path), path, source="в фоне")
        if pid in titles and app.source == "в фоне":
            title = titles[pid]
            app.source = title if len(title) <= 48 else title[:47] + "…"
    return sorted(by_path.values(), key=lambda a: (a.source == "в фоне", a.name.casefold()))


def describe(path: str) -> str:
    """FileDescription from an exe's version resource, or its file name."""
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        ver = ctypes.WinDLL("version")
        n = ver.GetFileVersionInfoSizeW(path, None)
        if not n:
            return stem
        buf = ctypes.create_string_buffer(n)
        if not ver.GetFileVersionInfoW(path, 0, n, buf):
            return stem
        ptr, size = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(size)) \
                or size.value < 4:
            return stem
        lang, cp = struct.unpack("<HH", ctypes.string_at(ptr, 4))
        key = rf"\StringFileInfo\{lang:04x}{cp:04x}\FileDescription"
        if ver.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(size)) and size.value > 1:
            text = ctypes.wstring_at(ptr, size.value - 1).strip()
            if text and len(text) < 60 and text.isprintable():
                return text
    except OSError:
        pass
    return stem


def _from_processes() -> list[App]:
    own = {os.path.normcase(os.path.abspath(sys.executable))}
    out = []
    for path in running_paths():
        low = path.lower()
        if low.startswith(WINDIR) or os.path.normcase(path) in own or low.endswith("xray.exe"):
            continue
        out.append(App(describe(path), path, source="Запущена"))
    return out


# -- all together --------------------------------------------------------------------------
def _usable(app: App) -> bool:
    low = app.path.lower()
    if app.kind == "dir":
        return os.path.isdir(app.path)
    return (low.endswith(".exe") and not low.startswith(WINDIR) and not _JUNK_EXE.search(os.path.basename(low))
            and os.path.isfile(app.path))


_SHORTCUT_SUFFIX = re.compile(r"(\.exe)?(\s*[-—–]\s*(ярлык|shortcut))?$", re.I)


def scan() -> list[App]:
    """Installed programs, quickly: no folder walking here (see fill_icons)."""
    sources = (_from_shortcuts, _from_steam, _from_epic, _from_registry, _from_processes)
    with ThreadPoolExecutor(len(sources)) as pool:
        results = list(pool.map(_safe, sources))
    seen: dict[str, App] = {}
    names: set[str] = set()
    for batch in results:                      # earlier sources name things better
        for app in batch:
            app.name = _SHORTCUT_SUFFIX.sub("", app.name.strip()) or app.name
            if app.key in seen or app.name.casefold() in names or not _usable(app):
                continue
            # Windows paths keep whatever case they were typed with; matching needs the real one.
            app.path = os.path.realpath(app.path)
            seen[app.key] = app
            names.add(app.name.casefold())
    return sorted(seen.values(), key=lambda a: a.name.casefold())


def fill_icons(apps: list[App]) -> None:
    """Find the main executable of every folder entry (games), for its icon. Walks folders."""
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
        name = os.path.basename(path.rstrip("\\/")) or path
        return App(name, path, "dir", icon=main_exe(path, name))
    return App(describe(path), path)


def entry(app: App) -> dict:
    """What a preset stores. Folders also list their executables: Windows reports a process path
    in whatever case it was started with, but the file name is stable."""
    d = app.as_dict()
    if app.kind == "dir":
        d["exes"] = sorted({os.path.basename(p) for p in folder_exes(app.path)})
    return d
