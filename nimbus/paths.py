"""Where Nimbus keeps its binaries and data."""
import os
import sys
from pathlib import Path

APP_NAME = "Nimbus"
VERSION = "0.2.0"

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    CORE_DIR = APP_DIR / "core"
    RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "resources"
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    CORE_DIR = APP_DIR / "vendor" / "xray"
    RES_DIR = APP_DIR / "resources"



def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


# The portable build ships a "portable" marker file next to the exe: all data stays in "data"
# beside it, so the folder can be moved or carried on a USB stick. The installed build has no
# marker and keeps data in %APPDATA%\Nimbus, which survives updates and reinstalls.
# A portable copy put somewhere read-only (e.g. Program Files) falls back to %APPDATA%.
APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
PORTABLE = False
if os.environ.get("NIMBUS_DATA_DIR"):
    DATA_DIR = Path(os.environ["NIMBUS_DATA_DIR"])
elif (APP_DIR / "portable").exists() and _writable(APP_DIR / "data"):
    DATA_DIR = APP_DIR / "data"
    PORTABLE = True
else:
    DATA_DIR = APPDATA_DIR

# Set up by the installer: its uninstaller sits next to the exe (Inno Setup names it unins000.exe).
UNINSTALLER = next(iter(sorted(APP_DIR.glob("unins*.exe"))), None) if not PORTABLE else None

XRAY_EXE = CORE_DIR / "xray.exe"
SINGBOX_EXE = CORE_DIR / "sing-box.exe"   # TUN mode only
GEO_DIR = DATA_DIR / "geo"          # user-updated geo files override the bundled ones
LOG_DIR = DATA_DIR / "logs"
RUN_DIR = DATA_DIR / "run"
SETTINGS_FILE = DATA_DIR / "settings.json"
PROFILES_FILE = DATA_DIR / "profiles.json"

for d in (DATA_DIR, GEO_DIR, LOG_DIR, RUN_DIR):
    d.mkdir(parents=True, exist_ok=True)


def asset_dir() -> Path:
    """Directory Xray should read geoip.dat/geosite.dat from."""
    if (GEO_DIR / "geosite.dat").exists() and (GEO_DIR / "geoip.dat").exists():
        return GEO_DIR
    return CORE_DIR
