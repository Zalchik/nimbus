"""Deep links that add a subscription or configs: nimbus://import/<url>, and the formats other
clients' "add to app" buttons use (happ://add/<url>, v2rayn://install-sub?url=…,
clash://install-config?url=…, sing-box://import-remote-profile?url=…).

Happ's encrypted links (happ://crypt…/…) are its own protected format and are not decrypted:
they're recognised only to ask for the provider's plain https link instead."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from . import links

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
SCHEMES = tuple(sorted(set(_PATH_FORMS) | set(_QUERY_FORMS)))


@dataclass
class DeepLink:
    kind: str          # "subscription" (payload: its URL) | "configs" (share links) | "crypt" | "invalid"
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


def _classify(value: str, name: str = "") -> DeepLink:
    value = _payload(value)
    if re.match(r"(?i)https?://", value) and urlsplit(value).netloc and not any(c.isspace() for c in value):
        return DeepLink("subscription", value, name)
    if any(links.is_link(line.strip()) for line in value.splitlines()):
        return DeepLink("configs", value, name)
    return DeepLink("invalid", value, name)


def parse(text: str) -> DeepLink | None:
    """The deep link in `text`, or None if it isn't one."""
    text = (text or "").strip()
    if not is_deep_link(text):
        return None
    scheme, rest = text.split("://", 1)
    scheme = scheme.lower()
    if scheme == "happ" and re.match(r"(?i)crypt\d*/", rest):
        return DeepLink("crypt")
    for prefix in _PATH_FORMS.get(scheme, ()):
        if rest.lower().startswith(prefix):
            return _classify(rest[len(prefix):])
    action, _, query = rest.partition("?")
    if action.strip("/").lower() in _QUERY_FORMS.get(scheme, ()):
        query, _, fragment = query.partition("#")
        q = parse_qs(query, keep_blank_values=True)
        url = (q.get("url") or [""])[0]
        name = (q.get("name") or [""])[0] or unquote(fragment)
        return _classify(url, name) if url else DeepLink("invalid")
    return DeepLink("invalid")


def from_args(args) -> str:
    """The first deep link among command-line arguments ("" if none)."""
    return next((a for a in args if is_deep_link(a)), "")
