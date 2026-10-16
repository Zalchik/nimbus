"""What the Windows and Linux program finders share: the App entry and picking a game's main
executable among those in its folder."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

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


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def choose_main_exe(folder: str, name: str, exes: list[str]) -> str:
    """The game's own executable: named like the game or its folder, else the shallowest and biggest."""
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
