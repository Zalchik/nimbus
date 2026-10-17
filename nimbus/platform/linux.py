"""Linux integration, the same names as windows.py.

- System proxy: GNOME (gsettings) and KDE (kioslaverc, then KIO is told to re-read it); other
  desktops only get the environment variables.
- Environment proxy: the user's systemd and D-Bus activation environment, which programs started
  from the desktop (and new terminal windows) inherit.
- TUN: the window never runs as root. sing-box is copied to the data folder once and given
  CAP_NET_ADMIN with one pkexec prompt (the AppImage itself is read-only); strict_route is the
  kill switch.
- Autostart and nimbus:// links: .desktop files in ~/.config/autostart and
  ~/.local/share/applications.

Nothing here imports Linux-only modules at the top, so the module loads on Windows too (tests
compare its names with windows.py)."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

OS_NAME = "Linux"
POPEN: dict = {}
POPEN_BACKGROUND: dict = {}
UI_FONTS = ("Noto Sans", "Cantarell", "DejaVu Sans", "Sans Serif")
MONO_FONTS = ("JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono", "Monospace")
TUN_RELAUNCH = False      # sing-box gets its own rights (grant_tun); the app stays a normal user
BIND_EGRESS = False       # sing-box's process rule sends Xray's traffic straight out instead
NO_PROXY = "localhost,127.0.0.1,::1,.local"
LOCAL_NETS = ["localhost", "127.0.0.0/8", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "*.local"]
DESKTOP_FILE = "nimbus.desktop"


def _host_environment(env=os.environ) -> None:
    """A frozen build (PyInstaller) puts its bundled libraries first in LD_LIBRARY_PATH, and every
    program we start inherits that: Fedora's gsettings loaded the AppImage's (Ubuntu's) GLib and
    failed, so the system proxy was never switched on. Put the user's value back; this process
    keeps its libraries (the loader reads the variable once, at startup)."""
    if not getattr(sys, "frozen", False):
        return
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)


if sys.platform.startswith("linux"):
    _host_environment()


def _run(args: list[str], timeout: float = 5) -> str | None:
    """stdout of a helper program, or None if it's missing or failed."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def exe_name(name: str) -> str:
    return name


def data_dir(app: str) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / app


def machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text().strip()
        except OSError:
            continue
        if value:
            return value
    raise OSError("no machine-id")


# -- system proxy -----------------------------------------------------------------------------
GNOME = "org.gnome.system.proxy"


def _gsettings() -> bool:
    return bool(shutil.which("gsettings")) and GNOME in (_run(["gsettings", "list-schemas"]) or "")


def _gget(schema: str, key: str):
    out = _run(["gsettings", "get", schema, key])
    return None if out is None else out.strip()


def _gset(schema: str, key: str, value: str) -> None:
    _run(["gsettings", "set", schema, key, value])


def _kde_tools() -> tuple[str, str] | None:
    for v in ("6", "5"):
        w, r = shutil.which(f"kwriteconfig{v}"), shutil.which(f"kreadconfig{v}")
        if w and r:
            return w, r
    return None


KDE_KEYS = ("ProxyType", "httpProxy", "httpsProxy", "NoProxyFor")


def _kde_reparse() -> None:
    _run(["dbus-send", "--type=signal", "/KIO/Scheduler", "org.kde.KIO.Scheduler.reparseSlaveConfiguration",
          "string:"])


def read_proxy() -> dict:
    """What the desktop's proxy settings are now: {"gnome": {key: value}, "kde": {key: value}}."""
    out: dict = {}
    if _gsettings():
        out["gnome"] = {"mode": _gget(GNOME, "mode"), "ignore-hosts": _gget(GNOME, "ignore-hosts"),
                        **{f"{k}.{f}": _gget(f"{GNOME}.{k}", f) for k in ("http", "https") for f in ("host", "port")}}
    tools = _kde_tools()
    if tools:
        out["kde"] = {k: (_run([tools[1], "--file", "kioslaverc", "--group", "Proxy Settings", "--key", k]) or "").strip()
                      for k in KDE_KEYS}
    return out


def write_proxy(values: dict) -> None:
    gnome = values.get("gnome")
    if gnome and _gsettings():
        for key, value in gnome.items():
            if value is None or key == "mode":
                continue
            schema, _, field = key.rpartition(".") if "." in key else ("", "", key)
            _gset(f"{GNOME}.{schema}" if schema else GNOME, field, value)
        if gnome.get("mode"):
            _gset(GNOME, "mode", gnome["mode"])   # last: the switch goes on once the rest is set
    kde = values.get("kde")
    tools = _kde_tools()
    if kde and tools:
        for key, value in kde.items():
            if key == "ProxyType":
                continue
            _run([tools[0], "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key, value])
        _run([tools[0], "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "ProxyType",
              kde.get("ProxyType") or "0"])
        _kde_reparse()


def enable_proxy(http_port: int) -> None:
    hosts = "[" + ", ".join(f"'{h}'" for h in LOCAL_NETS) + "]"
    write_proxy({
        "gnome": {"http.host": "'127.0.0.1'", "http.port": str(http_port), "https.host": "'127.0.0.1'",
                  "https.port": str(http_port), "ignore-hosts": hosts, "mode": "'manual'"},
        "kde": {"httpProxy": f"http://127.0.0.1:{http_port}", "httpsProxy": f"http://127.0.0.1:{http_port}",
                "NoProxyFor": ",".join(LOCAL_NETS), "ProxyType": "1"},
    })


def disable_proxy() -> None:
    write_proxy({"gnome": {"mode": "'none'"}, "kde": {"ProxyType": "0"}})


def _local_port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _dead_local(host: str, port: str) -> bool:
    host = host.strip("'\" ").removeprefix("http://")
    return host in ("127.0.0.1", "localhost", "::1") and port.isdigit() and not _local_port_open(int(port))


def without_dead_local_proxy(values: dict) -> dict:
    """Drop a saved proxy pointing at a local port nothing listens on any more (a client that
    exited without cleaning up), so restoring it doesn't break the internet."""
    out = json.loads(json.dumps(values))
    gnome = out.get("gnome") or {}
    if gnome.get("mode") == "'manual'" and _dead_local(gnome.get("http.host") or "", gnome.get("http.port") or ""):
        gnome["mode"] = "'none'"
    kde = out.get("kde") or {}
    if kde.get("ProxyType") == "1":
        addr = (kde.get("httpProxy") or "").removeprefix("http://").replace(" ", ":")
        host, _, port = addr.rpartition(":")
        if _dead_local(host, port):
            kde["ProxyType"] = "0"
    return out


ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


def read_env_proxy() -> dict:
    """The proxy variables in the user's session environment ({name: value or None})."""
    env = {}
    for line in (_run(["systemctl", "--user", "show-environment"]) or "").splitlines():
        name, _, value = line.partition("=")
        env[name] = value
    return {name: env.get(name) for name in ENV_VARS}


def write_env_proxy(values: dict) -> None:
    """Set (or, for None, remove) the variables for programs started from the desktop from now on."""
    if not shutil.which("systemctl"):
        return
    unset = [n for n, v in values.items() if v is None]
    sets = [f"{n}={v[0] if isinstance(v, list) else v}" for n, v in values.items() if v is not None]
    if sets:
        _run(["systemctl", "--user", "set-environment", *sets])
    if unset:
        _run(["systemctl", "--user", "unset-environment", *unset])
    if shutil.which("dbus-update-activation-environment"):
        # D-Bus activated programs (terminals, file managers…) get them too; "" unsets.
        _run(["dbus-update-activation-environment", *sets, *[f"{n}=" for n in unset]])


def enable_env_proxy(http_port: int) -> None:
    url = f"http://127.0.0.1:{http_port}"
    write_env_proxy({"HTTP_PROXY": url, "HTTPS_PROXY": url, "NO_PROXY": NO_PROXY,
                     "http_proxy": url, "https_proxy": url, "no_proxy": NO_PROXY})


# -- network ----------------------------------------------------------------------------------
def default_egress(exclude: str) -> tuple[str, bool] | None:
    """(interface, False) the default IPv4 route goes through, `exclude` (our TUN) left out; None
    without a default route."""
    try:
        return parse_routes(Path("/proc/net/route").read_text(), exclude)
    except OSError:
        return None


def parse_routes(text: str, exclude: str) -> tuple[str, bool] | None:
    """default_egress() from the text of /proc/net/route."""
    best = None
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8 or f[1] != "00000000" or f[0] == exclude or not int(f[3], 16) & 1:   # RTF_UP
            continue
        metric = int(f[6])
        if best is None or metric < best[0]:
            best = (metric, f[0])
    return (best[1], False) if best else None


def ipv6_enabled() -> bool:
    try:
        return Path("/proc/sys/net/ipv6/conf/all/disable_ipv6").read_text().strip() == "0"
    except OSError:
        return False


# -- rights -------------------------------------------------------------------------------------
CAPS = "cap_net_admin,cap_net_raw,cap_net_bind_service+ep"


def is_admin() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def singbox_path() -> Path:
    """The sing-box that runs TUN: the copy with network rights (or the bundled one as root)."""
    from .. import paths
    return paths.SINGBOX_EXE if is_admin() else paths.DATA_DIR / "core" / "sing-box"


def _stamp(src: Path) -> str:
    st = src.stat()
    return f"{st.st_size}:{st.st_mtime_ns}:dns"   # ":dns": granted together with the polkit rule


# On systemd-resolved systems sing-box runs resolvectl to send DNS through its adapter. resolvectl
# doesn't inherit sing-box's capabilities, so each call (3 on connect, 1 on disconnect) asked for
# the password. This rule lets the user change DNS settings of the Nimbus adapter only.
POLKIT_RULE = Path("/etc/polkit-1/rules.d/49-nimbus.rules")
# Run as root by pkexec: $1 setcap, $2 caps, $3 sing-box, $4 rule text ("": none), $5 rule file.
GRANT_SCRIPT = ('"$1" "$2" "$3" || exit 1; [ -z "$4" ] && exit 0; '
                'mkdir -p "$(dirname "$5")" && printf "%s" "$4" > "$5" && chmod 644 "$5"')


def _polkit_rule(user: str, interface: str) -> str:
    return ("// Nimbus: lets " + user + " point DNS at the Nimbus TUN adapter (sing-box runs resolvectl)\n"
            "// without a password. Delete this file to undo.\n"
            "polkit.addRule(function(action, subject) {\n"
            "    if (action.id.indexOf(\"org.freedesktop.resolve1.\") == 0 &&\n"
            f"        action.lookup(\"interface\") == {json.dumps(interface)} &&\n"
            f"        subject.user == {json.dumps(user)} && subject.local && subject.active) {{\n"
            "        return polkit.Result.YES;\n"
            "    }\n"
            "});\n")


def tun_allowed() -> bool:
    """Root, or our sing-box copy is the bundled version and still has its capabilities."""
    if is_admin():
        return True
    from .. import paths
    copy = singbox_path()
    try:
        if (copy.parent / "sing-box.stamp").read_text() != _stamp(paths.SINGBOX_EXE):
            return False
        return bool(os.getxattr(copy, "security.capability"))
    except (OSError, AttributeError):
        return False


def grant_tun() -> bool:
    """Copy sing-box out of the (read-only) app folder and give it the network capabilities with
    one pkexec prompt (plus the DNS rule, where systemd-resolved runs). False if the user
    cancelled or something is missing."""
    import pwd

    from .. import paths
    from ..config_builder import TUN_NAME
    copy = singbox_path()
    copy.parent.mkdir(parents=True, exist_ok=True)
    tmp = copy.with_name("sing-box.new")
    shutil.copyfile(paths.SINGBOX_EXE, tmp)
    tmp.chmod(0o755)
    os.replace(tmp, copy)
    setcap = shutil.which("setcap") or next((p for p in ("/usr/sbin/setcap", "/sbin/setcap") if os.path.exists(p)),
                                            None)
    pkexec, sh = shutil.which("pkexec"), shutil.which("sh") or "/bin/sh"
    if not (setcap and pkexec):
        return False
    rule = _polkit_rule(pwd.getpwuid(os.getuid()).pw_name, TUN_NAME) if shutil.which("resolvectl") else ""
    try:
        ok = subprocess.run([pkexec, sh, "-c", GRANT_SCRIPT, "sh", setcap, CAPS, str(copy), rule, str(POLKIT_RULE)],
                            stdin=subprocess.DEVNULL, timeout=300).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    if ok:
        (copy.parent / "sing-box.stamp").write_text(_stamp(paths.SINGBOX_EXE))
    return ok and tun_allowed()


def relaunch_as_admin(extra_args: list[str]) -> bool:
    """Windows only: TUN never needs the whole app as root here."""
    return False


# -- processes ----------------------------------------------------------------------------------
def background_thread() -> None:
    """Lower the calling thread's priority (on Linux nice is per thread)."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (OSError, AttributeError):
        pass


def trim_memory() -> None:
    """Hand freed heap memory back to the system."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def process_age_ms() -> int:
    try:
        start = int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return int((uptime - start / os.sysconf("SC_CLK_TCK")) * 1000)
    except (OSError, ValueError, IndexError, AttributeError):
        return -1


def app_command(extra_args: list[str]) -> list[str]:
    """How to start this copy: the AppImage (its own path, not the mount inside /tmp), the
    frozen executable, or python with main.py."""
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"], *extra_args]
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    return [sys.executable, os.path.abspath(sys.argv[0]), *extra_args]


def relaunch(extra_args: list[str]) -> None:
    subprocess.Popen(app_command(extra_args), close_fds=True, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_locks: dict[str, int] = {}


def single_instance_lock(name: str):
    """A held lock file if this is the first instance, else None (flock: freed when we exit)."""
    import fcntl
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{name}-{os.getuid()}"
    os.makedirs(run, exist_ok=True)
    fd = os.open(os.path.join(run, f"{name}.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    _locks[name] = fd
    return fd


# -- desktop entries ----------------------------------------------------------------------------
def _exec_line(args: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in args)


def _autostart_file(name: str) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "autostart" / f"{name.lower()}.desktop"


def _desktop_entry(name: str, exec_line: str, icon: str = "", extra: str = "") -> str:
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={name}\nExec={exec_line}\n" + (f"Icon={icon}\n" if icon else "") +
            "Terminal=false\nCategories=Network;\n" + extra)


def autostart_is_this_exe(name: str) -> bool:
    try:
        text = _autostart_file(name).read_text()
    except OSError:
        return False
    return f"Exec={_exec_line(app_command([]))}" in text


def set_autostart(enabled: bool, name: str) -> None:
    path = _autostart_file(name)
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_desktop_entry(name, _exec_line(app_command(["--autostart"])),
                                       extra="X-GNOME-Autostart-enabled=true\n"))
    else:
        path.unlink(missing_ok=True)


def _applications_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(Path.home(), ".local", "share")
    return Path(base) / "applications"


def url_scheme_command(scheme: str) -> str:
    """The Exec line of our .desktop entry if it handles <scheme>:// links ("" otherwise)."""
    path = _applications_dir() / DESKTOP_FILE
    try:
        text = path.read_text()
    except OSError:
        return ""
    if f"x-scheme-handler/{scheme};" not in text:
        return ""
    return next((line[5:] for line in text.splitlines() if line.startswith("Exec=")), "")


def register_url_scheme(scheme: str, title: str, icon: str = "") -> None:
    """A Nimbus entry in the applications menu that also opens <scheme>:// links."""
    exec_line = _exec_line(app_command([])) + " %u"
    path = _applications_dir() / DESKTOP_FILE
    text = _desktop_entry(title, exec_line, icon, f"MimeType=x-scheme-handler/{scheme};\n")
    try:
        if path.read_text() == text:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _run(["xdg-mime", "default", DESKTOP_FILE, f"x-scheme-handler/{scheme}"])
    _run(["update-desktop-database", str(path.parent)])


def unregister_url_scheme(scheme: str) -> None:
    if url_scheme_command(scheme).startswith(_exec_line(app_command([]))):
        (_applications_dir() / DESKTOP_FILE).unlink(missing_ok=True)
        _run(["update-desktop-database", str(_applications_dir())])


# -- window ---------------------------------------------------------------------------------------
def title_bar(hwnd: int, dark: bool = True, caption: str = "#0a0a0a", border: str = "#262626") -> None:
    """The window manager draws the title bar here."""
