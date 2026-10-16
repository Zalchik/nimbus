"""Updates from GitHub Releases: find a newer release, download and check it, then hand over to
the installer (installed copy) or to the swap helper (portable copy, see swap.py)."""
from __future__ import annotations

import calendar
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .lazy import httpx

from . import paths

REPO = "Zalchik/nimbus"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECKSUMS = "SHA256SUMS.txt"
CHECK_HOURS = 6
WORK_DIR = Path(tempfile.gettempdir()) / "Nimbus-update"


class UpdateError(Exception):
    pass


class Cancelled(UpdateError):
    pass


@dataclass
class Asset:
    name: str
    url: str
    size: int


@dataclass
class Release:
    version: str                 # "0.2.1"
    tag: str                     # "v0.2.1"
    published: float = 0.0       # unix time, 0 = unknown
    body: str = ""               # markdown
    page: str = RELEASES_URL
    assets: dict[str, Asset] = field(default_factory=dict)


def parse_version(text: str) -> tuple[int, ...] | None:
    """"v0.2.1" -> (0, 2, 1); None for anything that isn't a plain dotted version."""
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+){0,3})\s*", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(version: str, current: str = paths.VERSION) -> bool:
    new, cur = parse_version(version), parse_version(current)
    if new is None or cur is None:
        return False
    width = max(len(new), len(cur))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def _time(stamp: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


def parse_release(data: dict) -> Release | None:
    """The GitHub API's release object; None for drafts, prereleases and odd tags."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None:
        return None
    assets = {}
    for a in data.get("assets") or []:
        if isinstance(a, dict) and a.get("name") and a.get("browser_download_url"):
            assets[a["name"]] = Asset(a["name"], a["browser_download_url"], int(a.get("size") or 0))
    return Release(version=".".join(map(str, version)), tag=tag, published=_time(data.get("published_at", "")),
                   body=str(data.get("body") or ""), page=str(data.get("html_url") or RELEASES_URL), assets=assets)


def _headers() -> dict[str, str]:
    return {"User-Agent": f"Nimbus/{paths.VERSION}", "Accept": "application/vnd.github+json"}


def latest(proxy: str | None = None) -> Release | None:
    """The newest published release, or None if there's none."""
    r = httpx.get(API_URL, headers=_headers(), follow_redirects=True, timeout=20, proxy=proxy)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return parse_release(r.json())


# -- what to download ---------------------------------------------------------------------------
def install_kind() -> str:
    """How this copy updates: "setup" (installed: run the new installer), "portable" (a folder of
    files: swap them), "" (running from source: only the release page)."""
    if not getattr(sys, "frozen", False):
        return ""
    return "setup" if paths.UNINSTALLER else "portable"


def asset_name(version: str, kind: str) -> str:
    return {"setup": f"Nimbus-{version}-setup.exe", "portable": f"Nimbus-{version}-portable.zip"}[kind]


def parse_checksums(text: str) -> dict[str, str]:
    """sha256sum output ("<hex>  <name>" or "<hex> *<name>") -> {name: hex}."""
    out = {}
    for line in text.splitlines():
        m = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def verify(size: int, digest: str, want_size: int, want_digest: str = "") -> None:
    """Raise UpdateError if the file isn't what the release says (want_size 0 = unknown)."""
    if want_size and size != want_size:
        raise UpdateError(f"файл скачался не полностью ({size} из {want_size} байт)")
    if want_digest and digest.lower() != want_digest.lower():
        raise UpdateError("контрольная сумма SHA-256 не совпадает: файл повреждён или подменён")


def _checksum(release: Release, name: str, proxy: str | None) -> str:
    """SHA-256 of `name` from the release's checksum file; "" if the release has none."""
    asset = release.assets.get(CHECKSUMS)
    if asset is None:
        return ""
    r = httpx.get(asset.url, headers=_headers(), follow_redirects=True, timeout=30, proxy=proxy)
    r.raise_for_status()
    digest = parse_checksums(r.text).get(name, "")
    if not digest:
        raise UpdateError(f"в {CHECKSUMS} нет {name}")
    return digest


def download(release: Release, kind: str, proxy: str | None = None,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download this copy's file of the release into WORK_DIR and check its size and SHA-256."""
    name = asset_name(release.version, kind)
    asset = release.assets.get(name)
    if asset is None:
        raise UpdateError(f"в релизе {release.tag} нет файла {name}")
    want_digest = _checksum(release, name, proxy)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    dest = WORK_DIR / name
    part = dest.with_name(name + ".part")
    sha, done, last = hashlib.sha256(), 0, 0.0
    try:
        with httpx.stream("GET", asset.url, headers=_headers(), follow_redirects=True, proxy=proxy,
                          timeout=httpx.Timeout(30, read=60)) as r:
            r.raise_for_status()
            total = asset.size or int(r.headers.get("content-length") or 0)
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    if cancelled():
                        raise Cancelled("загрузка отменена")
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if progress and (now - last > 0.1 or done == total):
                        last = now
                        progress(done, total)
        verify(done, sha.hexdigest(), asset.size, want_digest)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


def unpack(archive: Path) -> Path:
    """Unpack the portable zip next to it; returns the Nimbus folder inside."""
    out = archive.with_suffix("")
    shutil.rmtree(out, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        root = out.resolve()
        for member in z.namelist():   # nothing may land outside `out`
            if not (out / member).resolve().is_relative_to(root):
                raise UpdateError(f"в архиве недопустимый путь: {member}")
        z.extractall(out)
    app = out / "Nimbus"
    if not (app / Path(sys.executable).name).exists():
        raise UpdateError("в архиве нет программы")
    return app


def cleanup() -> None:
    """Drop what an earlier update left in the temp folder."""
    shutil.rmtree(WORK_DIR, ignore_errors=True)


# -- handing over -------------------------------------------------------------------------------
def _start(args: list[str], cwd: Path) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, cwd=str(cwd), close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def setup_args(setup: Path, connect: bool) -> list[str]:
    """The installer, silent. It closes Nimbus, updates it and (see nimbus.iss) starts it again."""
    return [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/NIMBUSRESTART={'connect' if connect else '1'}"]


def swap_args(app: Path, pid: int, target: Path, connect: bool) -> list[str]:
    return [str(app / Path(sys.executable).name), "--apply-update", str(pid), str(target)] + \
        (["--connect"] if connect else [])


def prepare(release: Release, kind: str, proxy: str | None = None,
            progress: Callable[[int, int], None] | None = None,
            cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download and check the update; for a portable copy also unpack it. Returns what
    install() takes: the installer, or the unpacked Nimbus folder."""
    if kind not in ("setup", "portable"):
        raise UpdateError("эта копия не обновляется сама")
    path = download(release, kind, proxy, progress, cancelled)
    return unpack(path) if kind == "portable" else path


def install(prepared: Path, kind: str, pid: int, connect: bool) -> None:
    """Start whatever replaces this copy once it has quit (the caller quits right after)."""
    if kind == "setup":
        _start(setup_args(prepared, connect), prepared.parent)
    else:
        _start(swap_args(prepared, pid, paths.APP_DIR, connect), prepared)
