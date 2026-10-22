"""Deep links that add a subscription or configs: nimbus://import/<url>, and the formats other
clients' "add to app" buttons use (happ://add/<url>, v2rayn://install-sub?url=…,
clash://install-config?url=…, sing-box://import-remote-profile?url=…).

Happ's encrypted links (happ://crypt…/…, and the crypt://crypt4/… form some providers shorten them
to) carry the subscription URL or the share links inside, encrypted to a key the Happ app ships.
They're decrypted here — see nimbus/happ.py — so such a link adds what it holds, like any other:
a "subscription" when it carries a URL, "configs" when it carries share links."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from . import happ, links

SCHEME = "nimbus"
# scheme -> (path prefixes with the URL after them, actions with ?url=…)
_PATH_FORMS = {"nimbus": ("import/", "add/"), "happ": ("add/",)}
_QUERY_FORMS = {
    "nimbus": ("import",),
    "v2rayn": ("install-sub", "install-config"),
    "v2rayng": ("install-sub", "install-config"),
    "clash": ("install-config",),
    "clashmeta": ("install-config",),
    "sing-box": ("import-remote-profile",),
}
SCHEMES = tuple(sorted(set(_PATH_FORMS) | set(_QUERY_FORMS) | {"crypt"}))


@dataclass
class DeepLink:
    kind: str          # "subscription" (payload: its URL) | "configs" (share links) |
                       # "crypt" (an encrypted link that won't open; payload: why) | "invalid"
    payload: str = ""
    name: str = ""


def is_deep_link(text: str) -> bool:
    head = (text or "").strip().split("://", 1)
    return len(head) == 2 and head[0].lower() in SCHEMES


def _payload(value: str) -> str:
    """What the link carries, percent-decoded once if it came encoded."""
    value = value.strip()
    if "://" not in value and "://" in unquote(value):
        value = unquote(value)
    return value


def _is_json(value: str) -> bool:
    if value.lstrip()[:1] not in "[{":
        return False
    try:
        return bool(json.loads(value))
    except ValueError:
        return False


def _classify(value: str, name: str = "", depth: int = 0) -> DeepLink:
    value = _payload(value)
    if depth < 4 and is_deep_link(value):
        inner = parse(value, depth + 1)
        if inner is not None:
            return DeepLink(inner.kind, inner.payload, name or inner.name)
    if re.match(r"(?i)https?://", value) and urlsplit(value).netloc and not any(c.isspace() for c in value):
        return DeepLink("subscription", value, name)
    if _is_json(value) or any(links.is_link(line.strip()) for line in value.splitlines()):
        return DeepLink("configs", value, name)
    return DeepLink("invalid", value, name)


def _encrypted(text: str) -> DeepLink:
    """A Happ encrypted link: whatever it carries is what gets added."""
    try:
        plain = happ.unwrap(text)
    except happ.HappError as e:
        return DeepLink("crypt", str(e))
    return _classify(plain)


def parse(text: str, depth: int = 0) -> DeepLink | None:
    """The deep link in `text`, or None if it isn't one."""
    text = (text or "").strip()
    if not is_deep_link(text):
        return None
    scheme, rest = text.split("://", 1)
    scheme = scheme.lower()
    if scheme in ("happ", "crypt") and happ.is_crypt_link(text):
        return _encrypted(text)
    for prefix in _PATH_FORMS.get(scheme, ()):
        if rest.lower().startswith(prefix):
            return _classify(rest[len(prefix):], depth=depth + 1)
    action, _, query = rest.partition("?")
    if action.strip("/").lower() in _QUERY_FORMS.get(scheme, ()):
        query, _, fragment = query.partition("#")
        q = parse_qs(query, keep_blank_values=True)
        url = (q.get("url") or [""])[0]
        name = (q.get("name") or [""])[0] or unquote(fragment)
        return _classify(url, name, depth + 1) if url else DeepLink("invalid")
    return DeepLink("invalid")


def from_args(args) -> str:
    """The first deep link among command-line arguments ("" if none)."""
    return next((a for a in args if is_deep_link(a)), "")
