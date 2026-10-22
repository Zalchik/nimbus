"""Download the Xray-core and sing-box builds Nimbus ships with into vendor/xray/ (used by CI;
by hand works too). Versions are pinned here: change them together with testing.

Run: python tools/fetch_cores.py [windows|linux] [--if-needed]   (default: this system)
--if-needed: do nothing when vendor/xray already has these versions (make install uses it).
Linux on ARM (aarch64) gets the arm64 builds; everything else is x86-64.
"""
import io
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

XRAY = "26.10.21"   # 26.10.10 was withdrawn: it trusted compromised root certificates
SINGBOX = "1.15.0-alpha.12"
OUT = Path(__file__).resolve().parent.parent / "vendor" / "xray"


def get(url: str) -> bytes:
    print("downloading", url)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


STAMP = OUT / ".versions"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    system = args[0] if args else ("windows" if sys.platform == "win32" else "linux")
    exe = ".exe" if system == "windows" else ""
    arm = system == "linux" and platform.machine().lower() in ("aarch64", "arm64")
    stamp = f"{system} {'arm64' if arm else 'amd64'} xray {XRAY} sing-box {SINGBOX}\n"
    files = [f"xray{exe}", f"sing-box{exe}", "geoip.dat", "geosite.dat", "LICENSE", "LICENSE-sing-box"]
    if ("--if-needed" in sys.argv and STAMP.exists() and STAMP.read_text() == stamp
            and all((OUT / f).exists() for f in files)):
        print("cores are up to date:", stamp.strip())
        return
    OUT.mkdir(parents=True, exist_ok=True)

    xray = (f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY}/"
            f"Xray-{system}-{'arm64-v8a' if arm else '64'}.zip")
    with zipfile.ZipFile(io.BytesIO(get(xray))) as z:
        for name, dest in ((f"xray{exe}", f"xray{exe}"), ("geoip.dat", "geoip.dat"),
                           ("geosite.dat", "geosite.dat"), ("LICENSE", "LICENSE")):
            (OUT / dest).write_bytes(z.read(name))

    base = f"sing-box-{SINGBOX}-{system}-{'arm64' if arm else 'amd64'}"
    url = f"https://github.com/SagerNet/sing-box/releases/download/v{SINGBOX}/{base}"
    if system == "windows":
        with zipfile.ZipFile(io.BytesIO(get(url + ".zip"))) as z:
            (OUT / "sing-box.exe").write_bytes(z.read(f"{base}/sing-box.exe"))
            (OUT / "LICENSE-sing-box").write_bytes(z.read(f"{base}/LICENSE"))
    else:
        with tarfile.open(fileobj=io.BytesIO(get(url + ".tar.gz"))) as t:
            for member, dest in (("sing-box", "sing-box"), ("LICENSE", "LICENSE-sing-box")):
                f = t.extractfile(f"{base}/{member}")
                with open(OUT / dest, "wb") as out:
                    shutil.copyfileobj(f, out)
    for name in (f"xray{exe}", f"sing-box{exe}"):
        (OUT / name).chmod(0o755)
    STAMP.write_text(stamp)
    print("done:", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
