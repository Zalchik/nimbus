"""Portable self-update. The NEW version runs this from the unpacked update:

    Nimbus.exe --apply-update <pid> <target dir> [arguments for the restarted Nimbus…]

It waits for the old Nimbus (<pid>) to exit, replaces the program files in <target dir> with the
files next to its own exe, keeps data/ and the "portable" marker, and starts Nimbus again. If
anything can't be moved or copied (a file still locked, a full disk), everything is put back as
it was and the old version starts with --update-failed.

A .deb / .rpm copy updates through its package manager instead: install_package().

Standard library only, and nimbus.paths is never imported: that would create data folders
inside the temporary copy."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

KEEP = frozenset({"data", "portable"})
BACKUP = ".update-backup"
LOG = Path(tempfile.gettempdir()) / "Nimbus-update.log"


def _log(text: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
    except OSError:
        pass


def _retry(action: Callable[[], object], seconds: float) -> None:
    """Run action, again and again while it fails with OSError (an antivirus or the old core
    still holding a file), for up to `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            action()
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def replace(src: Path, dst: Path, keep: frozenset[str] = KEEP, wait: float = 20.0,
            copy: Callable[[Path, Path], None] = _copy) -> None:
    """Make dst hold src's files, leaving dst's `keep` entries alone (src's are not copied).
    The old files go to dst/.update-backup first (a rename: same disk); on any failure the new
    files are removed and the old ones moved back, and the error is raised."""
    backup = dst / BACKUP
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir()
    skip = set(keep) | {BACKUP}
    moved: list[str] = []
    copied: list[str] = []
    try:
        for item in sorted(dst.iterdir()):
            if item.name in skip:
                continue
            _retry(lambda item=item: item.rename(backup / item.name), wait)
            moved.append(item.name)
        for item in sorted(src.iterdir()):
            if item.name in skip:
                continue
            copied.append(item.name)
            copy(item, dst / item.name)
    except BaseException:
        for name in copied:
            if (dst / name).exists() or (dst / name).is_symlink():
                _retry(lambda name=name: _remove(dst / name), wait)
        for name in moved:
            _retry(lambda name=name: (backup / name).rename(dst / name), wait)
        shutil.rmtree(backup, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def wait_for_exit(pid: int, timeout: float = 60.0) -> bool:
    """True once process `pid` has exited (or never existed), False after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if not handle:
            return True
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout * 1000)) == 0
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)   # signal 0 only checks; on Windows os.kill would terminate instead
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        try:   # exited but not reaped yet (a zombie) counts as gone
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
        except (OSError, IndexError):
            pass
        time.sleep(0.25)
    return False


def start_detached(exe: Path, args: list[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent), close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def package_command(kind: str, package: Path, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """The package manager's command (run as root through pkexec) that installs a downloaded
    .deb / .rpm over the installed one."""
    if kind == "deb":
        return [which("env") or "/usr/bin/env", "DEBIAN_FRONTEND=noninteractive",
                which("apt-get") or "/usr/bin/apt-get", "install", "-y", "--allow-downgrades", str(package)]
    if which("dnf"):
        return [which("dnf"), "install", "-y", str(package)]
    if which("zypper"):
        return [which("zypper"), "--non-interactive", "install", "--allow-unsigned-rpm", str(package)]
    return [which("rpm") or "/usr/bin/rpm", "-U", "--replacepkgs", str(package)]


def install_package(argv: list[str], run: Callable[[list[str]], int] = subprocess.call,
                    start: Callable[[Path, list[str]], None] | None = None,
                    wait: Callable[[int], bool] | None = None) -> int:
    """`Nimbus --install-package <pid> <deb|rpm> <file> [arguments for the restarted Nimbus…]`:
    once the old Nimbus has quit, the package manager installs the update (one password
    prompt), then Nimbus starts again: the new version with --updated, or with --update-failed
    if the user cancelled or the install failed."""
    start = start or start_detached
    wait = wait or wait_for_exit
    try:
        pid, kind, package, rest = int(argv[0]), argv[1], Path(argv[2]), list(argv[3:])
    except (IndexError, ValueError):
        _log(f"bad arguments: {argv}")
        return 2
    exe = Path(sys.executable)
    _log(f"installing {package}, waiting for {pid}")
    if not wait(pid):
        _log("the old Nimbus did not exit")
        start(exe, ["--update-failed"])
        return 1
    cmd = [shutil.which("pkexec") or "/usr/bin/pkexec", *package_command(kind, package)]
    try:
        code = run(cmd)
    except OSError as e:
        code = -1
        _log(f"couldn't run {cmd[0]}: {e!r}")
    if code != 0:
        _log(f"{' '.join(cmd)} exited with {code}")
        start(exe, ["--update-failed"])
        return 1
    _log("done")
    start(exe, ["--updated", *rest])
    return 0


def main(argv: list[str]) -> int:
    """argv: <pid> <target dir> [arguments for the restarted Nimbus…]"""
    try:
        pid, target, rest = int(argv[0]), Path(argv[1]), list(argv[2:])
    except (IndexError, ValueError):
        _log(f"bad arguments: {argv}")
        return 2
    src = Path(sys.executable).resolve().parent
    exe = target / Path(sys.executable).name
    _log(f"updating {target} from {src}, waiting for {pid}")
    if not wait_for_exit(pid):
        _log("the old Nimbus did not exit")
        start_detached(exe, ["--update-failed"])
        return 1
    try:
        replace(src, target)
    except Exception as e:
        _log(f"failed, rolled back: {e!r}")
        start_detached(exe, ["--update-failed"])
        return 1
    _log("done")
    start_detached(exe, ["--updated", *rest])
    return 0
