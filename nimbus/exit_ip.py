"""The address sites see while connected, and the country it belongs to.

The IP comes from our own endpoint (no limits, unlike free "what's my IP" APIs, which throttle a
VPN exit shared by many users), which also names the country from a fresh database (DB-IP,
updated monthly on the server): what sites like whoer show. Cloudflare's trace is asked only
when ours is slow or down: VPN servers often send traffic for Cloudflare out through another
address than the rest. The geoip.dat Xray ships is the last resort for the country: it can be
months old, and addresses of hosting providers move between countries.

Every check opens a new connection through the VPN. A balancer sends each new connection to the
node it prefers at that moment, so this is what a site opened now would see; a kept-open
connection would go on showing the node picked when it was opened.
"""
from __future__ import annotations

import bisect
import ipaddress
import threading
import time
from array import array
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .lazy import httpx

from . import paths


def _json_ip(r: httpx.Response) -> tuple[str, str | None]:
    d = r.json()
    return d.get("ip"), d.get("country_code") or d.get("country")


def _trace(r: httpx.Response) -> tuple[str, str | None]:
    kv = dict(line.split("=", 1) for line in r.text.splitlines() if "=" in line)
    return kv.get("ip"), kv.get("loc")


# All foreign, so the "Smart" routing (Russian sites direct) still sends them through the VPN.
OWN = "https://zalchikmods.site/nimbus/ip"
PRIMARY = (OWN, _json_ip)
FALLBACKS = [
    ("https://1.1.1.1/cdn-cgi/trace", _trace),
    ("https://www.cloudflare.com/cdn-cgi/trace", _trace),
    ("https://ipwho.is/", _json_ip),
]
HEDGE_AFTER = 1.2   # seconds to give our endpoint before the fallbacks are asked as well


def _client(proxy: str | None, timeout: float) -> httpx.Client:
    # trust_env off: on Windows httpx would otherwise pick the system proxy from the registry.
    return httpx.Client(proxy=proxy, trust_env=False, timeout=httpx.Timeout(timeout, connect=4.0),
                        headers={"User-Agent": "Nimbus", "Connection": "close", "Cache-Control": "no-cache"})


def _ask(client: httpx.Client, url: str, parse) -> tuple[str, str | None]:
    r = client.get(url)
    r.raise_for_status()
    ip, code = parse(r)
    ip = str(ipaddress.ip_address(str(ip).strip()))
    code = str(code).upper() if code and len(str(code)) == 2 and str(code).isalpha() else None
    return ip, code


def _first_answer(proxy: str | None, timeout: float) -> tuple[str, str | None, bool]:
    """(IP, country code, whether our endpoint gave it)."""
    pool = ThreadPoolExecutor(max_workers=1 + len(FALLBACKS))
    errors = []
    with _client(proxy, timeout) as client:
        try:
            primary = pool.submit(_ask, client, *PRIMARY)
            done, _ = wait({primary}, timeout=HEDGE_AFTER)
            if primary in done and primary.exception() is None:
                return (*primary.result(), True)
            if primary in done:
                errors.append(str(primary.exception()))
                pending = set()
            else:
                pending = {primary}
            pending |= {pool.submit(_ask, client, url, parse) for url, parse in FALLBACKS}
            deadline = time.monotonic() + timeout + 1
            while pending and time.monotonic() < deadline:
                done, pending = wait(pending, timeout=deadline - time.monotonic(), return_when=FIRST_COMPLETED)
                # Ours still wins if it answers in the same moment as a fallback.
                for f in sorted(done, key=lambda f: f is not primary):
                    if f.exception() is None:
                        return (*f.result(), f is primary)
                    errors.append(str(f.exception()))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    raise RuntimeError("; ".join(errors) or "timeout")


def own_country(ip: str, proxy: str | None, timeout: float = 3.0) -> str | None:
    """Country of ip by our endpoint's database, when the IP itself came from elsewhere."""
    try:
        with _client(proxy, timeout) as client:
            r = client.get(OWN, params={"ip": ip})
            r.raise_for_status()
            code = r.json().get("country")
    except Exception:
        return None
    return str(code).upper() if code and len(str(code)) == 2 and str(code).isalpha() else None


def lookup(proxy: str | None, timeout: float = 5.0, attempts: int = 3) -> tuple[str, str | None]:
    """(IP, two-letter country code or None), asked through proxy (Nimbus' HTTP inbound).
    Right after connecting the balancer may not have picked a node yet, so a failed round is
    tried again a little later. Raises if every round fails."""
    for attempt in range(attempts):
        try:
            ip, code, own = _first_answer(proxy, timeout)
            break
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + 2 * attempt)
    if not own:
        code = own_country(ip, proxy) or code
    return ip, code or country(ip)


# -- country from geoip.dat -----------------------------------------------------------------


def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if c < 0x80:
            return result, i
        shift += 7


def _fields(b: bytes, start: int, end: int):
    """(field number, wire type, value or (start, end) of a length-delimited value)."""
    i = start
    while i < end:
        key, i = _varint(b, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
            yield num, wt, v
        elif wt == 2:
            n, i = _varint(b, i)
            yield num, wt, (i, i + n)
            i += n
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            return


def country_in(data: bytes, ip: str) -> str | None:
    """Country code of ip in a geoip.dat (GeoIPList{GeoIP{country_code=1, CIDR{ip=1, prefix=2}=2}}).
    Lists that aren't countries (PRIVATE, CLOUDFLARE, TELEGRAM …) are skipped."""
    addr = ipaddress.ip_address(ip)
    size = 4 if addr.version == 4 else 16
    target, bits = int(addr), size * 8
    for num, wt, (s, e) in ((n, w, v) for n, w, v in _fields(data, 0, len(data)) if n == 1 and w == 2):
        code = None
        for fnum, fwt, val in _fields(data, s, e):
            if fnum == 1 and fwt == 2:
                code = data[val[0]:val[1]].decode("ascii", "replace")
                if not (len(code) == 2 and code.isalpha()):
                    break
            elif fnum == 2 and fwt == 2 and code:
                net, prefix = b"", 0
                for cnum, cwt, cval in _fields(data, val[0], val[1]):
                    if cnum == 1 and cwt == 2:
                        net = data[cval[0]:cval[1]]
                    elif cnum == 2 and cwt == 0:
                        prefix = cval
                if len(net) == size and (int.from_bytes(net, "big") >> (bits - prefix)) == (target >> (bits - prefix)):
                    return code.upper()
    return None


_index: dict[int, tuple[array, array, array]] | None = None   # starts, prefixes, country numbers
_codes: list[str] = []
_index_lock = threading.Lock()


def build_index(data: bytes) -> dict[int, tuple[array, array, array]]:
    """Per IP version: sorted range starts, their prefix lengths and country numbers (into
    _codes), in compact arrays (~15 MB for a full geoip.dat instead of ~100 MB of Python
    objects). IPv6 is kept to its top 64 bits, which is as fine as country lists go. Each range
    is packed into one int while sorting, to keep the memory peak of the build low."""
    keys: dict[int, list[int]] = {4: [], 6: []}
    numbers: dict[str, int] = {}
    for _, _, (s, e) in ((n, w, v) for n, w, v in _fields(data, 0, len(data)) if n == 1 and w == 2):
        code = None
        for fnum, fwt, val in _fields(data, s, e):
            if fnum == 1 and fwt == 2:
                code = data[val[0]:val[1]].decode("ascii", "replace").upper()
                if not (len(code) == 2 and code.isalpha()) or len(numbers) >= 255 and code not in numbers:
                    code = None
                    break
                numbers.setdefault(code, len(numbers))
            elif fnum == 2 and fwt == 2 and code:
                net, prefix = b"", 0
                for cnum, cwt, cval in _fields(data, val[0], val[1]):
                    if cnum == 1 and cwt == 2:
                        net = data[cval[0]:cval[1]]
                    elif cnum == 2 and cwt == 0:
                        prefix = cval
                if len(net) == 4:
                    bits, value = 32, int.from_bytes(net, "big")
                elif len(net) == 16:
                    bits, value, prefix = 64, int.from_bytes(net[:8], "big"), min(prefix, 64)
                else:
                    continue
                start = value >> (bits - prefix) << (bits - prefix)
                keys[4 if bits == 32 else 6].append(start << 16 | prefix << 8 | numbers[code])
    _codes[:] = sorted(numbers, key=numbers.get)
    out = {}
    for v in (4, 6):
        ks = keys.pop(v)
        ks.sort()
        out[v] = (array("I" if v == 4 else "Q", (k >> 16 for k in ks)),
                  array("B", (k >> 8 & 0xFF for k in ks)), array("B", (k & 0xFF for k in ks)))
        del ks
    return out


def warm(geoip: Path | None = None) -> None:
    """Read geoip.dat into memory once (a second or two), so later lookups are instant.
    Only done when it's needed: it is the last resort for the country."""
    global _index
    with _index_lock:
        if _index is None:
            try:
                _index = build_index((geoip or paths.asset_dir() / "geoip.dat").read_bytes())
            except Exception:
                _index = {v: (array("Q"), array("B"), array("B")) for v in (4, 6)}


def country(ip: str, geoip: Path | None = None) -> str | None:
    """Country code of ip from the geoip.dat Xray uses, or None if unknown or unreadable."""
    warm(geoip)
    addr = ipaddress.ip_address(ip)
    starts, prefixes, codes = _index[addr.version]
    bits = 32 if addr.version == 4 else 64
    target = int(addr) if addr.version == 4 else int(addr) >> 64
    i = bisect.bisect_right(starts, target) - 1
    # Ranges are mostly disjoint; look back a little in case a wide one encloses narrower ones.
    for j in range(i, max(i - 8, -1), -1):
        if target - starts[j] < 1 << (bits - prefixes[j]):
            return _codes[codes[j]]
    return None
