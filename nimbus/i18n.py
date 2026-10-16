"""Interface language. Russian is the source: tr("Подключиться") is looked up in the English
table (locale_en.py) when the language is English, and stays as it is otherwise. Placeholders are
str.format ones: tr("Добавлено: {title}", title=…).

The language is fixed for the life of the process (module-level texts are translated when they
are imported): settings.language "auto" | "ru" | "en", with NIMBUS_LANG overriding it. Changing it
restarts Nimbus."""
from __future__ import annotations

import json
import os
import sys

LANGUAGES = {"ru": "Русский", "en": "English"}
# Systems in these languages get Russian on "auto"; everything else gets English.
_RUSSIAN_SPEAKING = {"ru", "be", "kk", "ky", "tg"}


def system_language() -> str:
    """"ru" or "en" from the user's interface language."""
    code = ""
    if sys.platform == "win32":
        try:
            import ctypes
            import locale
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code = locale.windows_locale.get(langid, "")
        except Exception:
            code = ""
    else:
        for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            if os.environ.get(var):
                code = os.environ[var].split(":")[0]
                break
    return "ru" if code.split("_")[0].split(".")[0].lower() in _RUSSIAN_SPEAKING else "en"


def resolve(choice: str) -> str:
    return choice if choice in LANGUAGES else system_language()


def _initial() -> str:
    if os.environ.get("NIMBUS_LANG") in LANGUAGES:
        return os.environ["NIMBUS_LANG"]
    try:
        from .paths import SETTINGS_FILE
        choice = json.loads(SETTINGS_FILE.read_text("utf-8")).get("language", "auto")
    except Exception:
        choice = "auto"
    return resolve(str(choice))


LANG = _initial()
_table: dict | None = None
_plurals: dict | None = None


def set_language(lang: str) -> None:
    """For tests and tools: texts already translated at import time keep their language."""
    global LANG
    LANG = lang if lang in LANGUAGES else "ru"


def _load() -> None:
    global _table, _plurals
    if _table is None:
        from . import locale_en
        _table, _plurals = locale_en.TEXTS, locale_en.PLURALS


def tr(text: str, /, ctx: str = "", **values) -> str:
    """`text` in the interface language, with {placeholders} filled from `values`. ctx tells
    apart the same Russian text meaning different things ("Подключение": a state, a tab); the
    English table then has it as "<ctx>|<text>"."""
    if LANG != "ru":
        _load()
        text = _table.get(f"{ctx}|{text}" if ctx else text, text)
    return text.format(**values) if values else text


def date(stamp: float) -> str:
    """A day as people write it: 16.10.2026 in Russian, 2026-10-16 otherwise."""
    import time
    return time.strftime("%d.%m.%Y" if LANG == "ru" else "%Y-%m-%d", time.localtime(stamp))


def plural(n: int, one: str, few: str, many: str) -> str:
    """The word for n things: plural(5, "сервер", "сервера", "серверов") -> "серверов" / "servers"."""
    if LANG != "ru":
        _load()
        forms = _plurals.get(one)
        if forms:
            return forms[0] if n == 1 else forms[1]
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many
