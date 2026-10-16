"""Windows integration: system proxy, elevation, autostart. linux.py has the same names."""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import winreg
from pathlib import Path

INET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROXY_VALUES = ("ProxyEnable", "ProxyServer", "ProxyOverride")
BYPASS = ("localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;"
          "172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;"
          "192.168.*;<local>")
NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000   # process priority class for background work

OS_NAME = "Windows"
POPEN = {"creationflags": NO_WINDOW}                       # Popen kwargs: no console window
POPEN_BACKGROUND = {"creationflags": NO_WINDOW | BELOW_NORMAL}
UI_FONTS = ("Segoe UI",)                    # if the bundled fonts don't load, the first one found
MONO_FONTS = ("Cascadia Mono", "Consolas")
# TUN needs the whole app elevated (relaunch_as_admin); Xray's sockets are bound to the physical
# adapter so they don't loop back into the tunnel.
TUN_RELAUNCH = True
BIND_EGRESS = True


def exe_name(name: str) -> str:
    return name + ".exe"


def data_dir(app: str) -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / app


def machine_id() -> str:
    """Windows' MachineGuid."""
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        return str(winreg.QueryValueEx(k, "MachineGuid")[0])


def _refresh_wininet() -> None:
    wininet = ctypes.windll.wininet
    wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
    wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH


def read_proxy() -> dict:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INET_KEY) as k:
        out = {}
        for name in PROXY_VALUES:
            try:
                out[name] = list(winreg.QueryValueEx(k, name))
            except FileNotFoundError:
                out[name] = None
        return out


def write_proxy(values: dict) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INET_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name, val in values.items():
            if val is None:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, name, 0, val[1], val[0])
    _refresh_wininet()


def enable_proxy(http_port: int) -> None:
    write_proxy({
        "ProxyEnable": [1, winreg.REG_DWORD],
        "ProxyServer": [f"127.0.0.1:{http_port}", winreg.REG_SZ],
        "ProxyOverride": [BYPASS, winreg.REG_SZ],
    })


def disable_proxy() -> None:
    write_proxy({"ProxyEnable": [0, winreg.REG_DWORD]})


ENV_KEY = "Environment"
ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
NO_PROXY = "localhost,127.0.0.1,::1,.local"


def _broadcast_env_change() -> None:
    """Tell Explorer (and so every program started from now on) that the environment changed.
    Slow windows can hold a broadcast for seconds, so it runs aside; not a daemon thread, so it
    still finishes when the app quits right after disconnecting."""
    def send():
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000,
                                                 ctypes.byref(result))   # WM_SETTINGCHANGE, SMTO_ABORTIFHUNG
    threading.Thread(target=send).start()


def read_env_proxy() -> dict:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_KEY) as k:
        out = {}
        for name in ENV_VARS:
            try:
                out[name] = list(winreg.QueryValueEx(k, name))
            except FileNotFoundError:
                out[name] = None
        return out


def write_env_proxy(values: dict) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name, val in values.items():
            if val is None:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, name, 0, val[1], val[0])
    _broadcast_env_change()


def enable_env_proxy(http_port: int) -> None:
    url = f"http://127.0.0.1:{http_port}"
    write_env_proxy({"HTTP_PROXY": [url, winreg.REG_SZ], "HTTPS_PROXY": [url, winreg.REG_SZ],
                     "NO_PROXY": [NO_PROXY, winreg.REG_SZ]})


def _local_port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def without_dead_local_proxy(values: dict) -> dict:
    """Drop a saved proxy that points at a local port nothing listens on any more
    (left behind by a client that exited without cleaning up), so restoring it
    doesn't break the user's internet."""
    enabled, server = values.get("ProxyEnable"), values.get("ProxyServer")
    if not (enabled and enabled[0] == 1 and server):
        return values
    for entry in str(server[0]).split(";"):
        addr = entry.split("=", 1)[-1].strip()
        host, _, port = addr.rpartition(":")
        if host in ("127.0.0.1", "localhost", "[::1]") and port.isdigit() and not _local_port_open(int(port)):
            return {**values, "ProxyEnable": [0, winreg.REG_DWORD]}
    return values


class _SockaddrInet(ctypes.Structure):
    _fields_ = [("family", ctypes.c_ushort), ("port", ctypes.c_ushort), ("data", ctypes.c_ulong * 6)]


class _IpAddressPrefix(ctypes.Structure):
    _fields_ = [("prefix", _SockaddrInet), ("length", ctypes.c_ubyte)]


class _ForwardRow(ctypes.Structure):   # MIB_IPFORWARD_ROW2
    _fields_ = [("luid", ctypes.c_uint64), ("index", ctypes.c_ulong), ("dest", _IpAddressPrefix),
                ("next_hop", _SockaddrInet), ("site_prefix_length", ctypes.c_ubyte),
                ("valid_lifetime", ctypes.c_ulong), ("preferred_lifetime", ctypes.c_ulong),
                ("metric", ctypes.c_ulong), ("protocol", ctypes.c_int), ("loopback", ctypes.c_ubyte),
                ("autoconf", ctypes.c_ubyte), ("publish", ctypes.c_ubyte), ("immortal", ctypes.c_ubyte),
                ("age", ctypes.c_ulong), ("origin", ctypes.c_int)]


class _IpInterfaceRow(ctypes.Structure):   # MIB_IPINTERFACE_ROW
    _fields_ = [("family", ctypes.c_ushort), ("luid", ctypes.c_uint64), ("index", ctypes.c_ulong),
                ("max_reassembly", ctypes.c_ulong), ("identifier", ctypes.c_uint64),
                ("min_ra_interval", ctypes.c_ulong), ("max_ra_interval", ctypes.c_ulong),
                ("advertising", ctypes.c_ubyte), ("forwarding", ctypes.c_ubyte),
                ("flags", ctypes.c_ubyte * 7), ("router_discovery", ctypes.c_int),
                ("dad_transmits", ctypes.c_ulong), ("base_reachable", ctypes.c_ulong),
                ("retransmit", ctypes.c_ulong), ("pmtu_timeout", ctypes.c_ulong),
                ("link_local_behavior", ctypes.c_int), ("link_local_timeout", ctypes.c_ulong),
                ("zone_indices", ctypes.c_ulong * 16), ("site_prefix_length", ctypes.c_ulong),
                ("metric", ctypes.c_ulong), ("nl_mtu", ctypes.c_ulong), ("connected", ctypes.c_ubyte),
                ("caps", ctypes.c_ubyte * 3), ("reachable_time", ctypes.c_ulong),
                ("offload", ctypes.c_ubyte * 2), ("disable_default_routes", ctypes.c_ubyte)]


def _interface_alias(luid: int) -> str:
    buf = ctypes.create_unicode_buffer(257)
    if ctypes.windll.iphlpapi.ConvertInterfaceLuidToAlias(ctypes.byref(ctypes.c_uint64(luid)), buf, 257):
        return ""
    return buf.value


def default_egress(exclude: str) -> tuple[str, bool] | None:
    """(name, IPv4 forwarding on) of the adapter Windows sends internet traffic through, the
    adapter called `exclude` (our TUN) left out; None without a default route. The name is what
    Xray's sockopt "interface" takes."""
    iphlp = ctypes.windll.iphlpapi
    table = ctypes.c_void_p()
    if iphlp.GetIpForwardTable2(socket.AF_INET, ctypes.byref(table)):
        return None
    try:
        count = ctypes.c_ulong.from_address(table.value).value
        rows = (_ForwardRow * count).from_address(table.value + ctypes.sizeof(ctypes.c_uint64))
        best = None
        for row in rows:
            if row.dest.length != 0 or row.dest.prefix.family != socket.AF_INET or row.loopback:
                continue
            iface = _IpInterfaceRow()
            iphlp.InitializeIpInterfaceEntry(ctypes.byref(iface))
            iface.family, iface.luid = socket.AF_INET, row.luid
            if iphlp.GetIpInterfaceEntry(ctypes.byref(iface)) or not iface.connected:
                continue
            alias = _interface_alias(row.luid)
            if not alias or alias == exclude:
                continue
            metric = row.metric + iface.metric   # what Windows itself compares
            if best is None or metric < best[0]:
                best = (metric, alias, bool(iface.forwarding))
        return (best[1], best[2]) if best else None
    finally:
        iphlp.FreeMibTable(table)


def ipv6_enabled() -> bool:
    """False when IPv6 is switched off system-wide (Tcpip6 DisabledComponents, e.g. 0xFF).
    The TUN adapter can't be given an IPv6 address then."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters") as k:
            value = winreg.QueryValueEx(k, "DisabledComponents")[0]
    except OSError:
        return True
    return not (int(value) & 0x10)  # 0x10: IPv6 off on all non-tunnel interfaces (0xFF has it too)


def single_instance_mutex(name: str):
    """Handle of a named mutex if this is the first instance, else None. Works across elevation:
    an elevated owner makes CreateMutex fail with access denied, which also means "taken"."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    err = ctypes.get_last_error()
    if not handle:
        return None
    if err == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle


def _colorref(hex_color: str) -> int:
    """'#rrggbb' -> COLORREF 0x00BBGGRR."""
    v = int(hex_color.lstrip("#"), 16)
    return ((v & 0xFF) << 16) | (v & 0xFF00) | (v >> 16)


def title_bar(hwnd: int, dark: bool = True, caption: str = "#0a0a0a", border: str = "#262626") -> None:
    """Window frame to match the app's theme (dark mode on Windows 10 20H1+; caption and
    border colors on Windows 11)."""
    try:
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(on), 4)
        color = ctypes.c_int(_colorref(caption))
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 35, ctypes.byref(color), 4)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 34, ctypes.byref(ctypes.c_int(_colorref(border))), 4)
    except Exception:
        pass


def background_thread() -> None:
    """Lower the calling thread's priority so bulk work never makes the UI or the cursor stutter."""
    try:
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:
        pass


def trim_memory() -> None:
    """Hand this process's RAM back to Windows (EmptyWorkingSet). Nothing is lost: pages that
    are needed again come back on their own, mostly from RAM Windows kept on standby."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        ctypes.windll.psapi.EmptyWorkingSet(k32.GetCurrentProcess())
    except Exception:
        pass


def process_age_ms() -> int:
    """Milliseconds since this process was created (includes loading Python and Qt)."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        created, exited, kern, user = (ctypes.c_ulonglong() for _ in range(4))
        k32.GetProcessTimes(ctypes.c_void_p(k32.GetCurrentProcess()), ctypes.byref(created), ctypes.byref(exited),
                            ctypes.byref(kern), ctypes.byref(user))
        now = ctypes.c_ulonglong()
        k32.GetSystemTimeAsFileTime(ctypes.byref(now))
        return int((now.value - created.value) / 10_000)  # 100 ns units
    except Exception:
        return -1


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def tun_allowed() -> bool:
    return is_admin()


def grant_tun() -> bool:
    """Linux only: Windows elevates the whole app instead (TUN_RELAUNCH)."""
    return False


def singbox_path() -> Path:
    from .. import paths
    return paths.SINGBOX_EXE


def single_instance_lock(name: str):
    return single_instance_mutex(name)


def relaunch_as_admin(extra_args: list[str]) -> bool:
    """Start an elevated copy of the app. Returns False if the user declined UAC."""
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, extra_args
    else:
        # Absolute: the elevated copy starts in System32, where "main.py" isn't.
        exe, args = sys.executable, [os.path.abspath(sys.argv[0]), *extra_args]
    params = subprocess.list2cmdline(args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def app_command(extra_args: list[str]) -> list[str]:
    """How to start this copy of the app."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return [pythonw, os.path.abspath(sys.argv[0]), *extra_args]


def relaunch(extra_args: list[str]) -> None:
    """Start another copy of the app with the same rights as this one."""
    subprocess.Popen(app_command(extra_args), close_fds=True, creationflags=subprocess.DETACHED_PROCESS)


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "--autostart"])
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return subprocess.list2cmdline([pythonw, sys.argv[0], "--autostart"])


def autostart_is_this_exe(name: str) -> bool:
    """The autostart entry `name` launches this very exe (not, say, a portable copy elsewhere)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, name)
    except OSError:
        return False
    return str(value).lower().startswith(subprocess.list2cmdline([sys.executable]).lower())


CLASSES_KEY = r"Software\Classes"


def _open_command() -> str:
    """How Windows should start this copy with a link: `"Nimbus.exe" "%1"`."""
    return f'"{sys.executable}" "%1"'


def url_scheme_command(scheme: str) -> str:
    """The command HKCU\\Software\\Classes\\<scheme> opens links with ("" if there's none)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{CLASSES_KEY}\{scheme}\shell\open\command") as k:
            return str(winreg.QueryValueEx(k, "")[0])
    except OSError:
        return ""


def register_url_scheme(scheme: str, title: str, icon: str = "") -> None:
    """Make <scheme>:// links open this exe (per user, no administrator rights needed)."""
    if url_scheme_command(scheme) == _open_command():
        return
    base = rf"{CLASSES_KEY}\{scheme}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:{title}")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{sys.executable}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _open_command())


def unregister_url_scheme(scheme: str) -> None:
    """Remove <scheme>:// if it opens this very exe (a portable copy elsewhere keeps its own)."""
    if url_scheme_command(scheme).lower() != _open_command().lower():
        return
    base = rf"{CLASSES_KEY}\{scheme}"
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", r"\DefaultIcon", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
        except OSError:
            pass


def set_autostart(enabled: bool, name: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
