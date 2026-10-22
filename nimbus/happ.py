"""Happ's encrypted links: happ://crypt…/… and crypt://… — the subscription URL or the share
links inside, encrypted to a key the Happ app carries.

    happ://crypt/…  crypt2  crypt3  crypt4   one RSA PKCS#1 v1.5 block per key size
    happ://crypt5/…                          an RSA-wrapped ChaCha20-Poly1305 key, a nonce and
                                             the ciphertext, scrambled by two byte swaps

The plaintext is the link the person holding it already has: their own subscription. It is
decrypted here so a link from a provider's chat or "add to Happ" button opens in Nimbus like
any other subscription link, instead of being a dead end.

No third-party crypto library: RSA is one modular exponentiation, and ChaCha20-Poly1305 is
short enough to keep in the file. Everything is local, so the plaintext never leaves the app.
"""
from __future__ import annotations

import base64
import hmac
import re
from dataclasses import dataclass
from urllib.parse import unquote

from .happ_keys import CRYPT5_KEYS, PKCS1_KEYS

# A link is a few kilobytes at most; the cap keeps a pasted wall of text from being chewed on.
MAX_PAYLOAD = 64 * 1024


class HappError(ValueError):
    """Not a Happ encrypted link, or not one these keys open."""


# -- RSA ---------------------------------------------------------------------------------------

def _tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """Tag, contents and the offset just past one DER element."""
    if pos + 2 > len(data):
        raise HappError("truncated key")
    tag, length = data[pos], data[pos + 1]
    pos += 2
    if length & 0x80:
        n = length & 0x7F
        if not 1 <= n <= 4 or pos + n > len(data):
            raise HappError("bad key length")
        length, pos = int.from_bytes(data[pos:pos + n], "big"), pos + n
    if pos + length > len(data):
        raise HappError("truncated key")
    return tag, data[pos:pos + length], pos + length


@dataclass(frozen=True)
class _Key:
    """The RSA private key of one link format."""
    n: int
    d: int

    @property
    def size(self) -> int:
        return (self.n.bit_length() + 7) // 8

    def decrypt(self, block: bytes) -> bytes:
        """One PKCS#1 v1.5 block: 00 02 <padding> 00 <message>."""
        if len(block) != self.size:
            raise HappError(f"a {len(block)}-byte block, the key takes {self.size}")
        em = pow(int.from_bytes(block, "big"), self.d, self.n).to_bytes(self.size, "big")
        if not em.startswith(b"\x00\x02"):
            raise HappError("the block doesn't belong to this key")
        end = em.find(b"\x00", 2)
        if end < 10:
            raise HappError("bad padding")
        return em[end + 1:]


def _key_from_der(der: bytes) -> _Key:
    """RSAPrivateKey (PKCS#1) or PrivateKeyInfo wrapping one (PKCS#8)."""
    tag, body, _ = _tlv(der, 0)
    if tag != 0x30:
        raise HappError("not a key")
    tag, _, pos = _tlv(body, 0)
    if tag != 0x02:
        raise HappError("not a key")
    if pos < len(body) and body[pos] == 0x30:      # PKCS#8: version, algorithm, OCTET STRING
        _, _, pos = _tlv(body, pos)
        tag, inner, _ = _tlv(body, pos)
        if tag != 0x04:
            raise HappError("not a key")
        return _key_from_der(inner)
    _, modulus, pos = _tlv(body, pos)               # PKCS#1: version, n, e, d, …
    _, _, pos = _tlv(body, pos)
    _, private, _ = _tlv(body, pos)
    return _Key(int.from_bytes(modulus, "big"), int.from_bytes(private, "big"))


_parsed: dict[str, _Key] = {}


def _key(encoded: str) -> _Key:
    key = _parsed.get(encoded)
    if key is None:
        key = _parsed[encoded] = _key_from_der(base64.b64decode(encoded))
    return key


# -- ChaCha20-Poly1305 (RFC 8439) ---------------------------------------------------------------

_MASK = 0xFFFFFFFF


def _rotl(value: int, bits: int) -> int:
    return ((value << bits) | (value >> (32 - bits))) & _MASK


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    state += [int.from_bytes(key[i:i + 4], "little") for i in range(0, 32, 4)]
    state.append(counter & _MASK)
    state += [int.from_bytes(nonce[i:i + 4], "little") for i in range(0, 12, 4)]
    x = list(state)

    def quarter(a: int, b: int, c: int, d: int) -> None:
        x[a] = (x[a] + x[b]) & _MASK
        x[d] = _rotl(x[d] ^ x[a], 16)
        x[c] = (x[c] + x[d]) & _MASK
        x[b] = _rotl(x[b] ^ x[c], 12)
        x[a] = (x[a] + x[b]) & _MASK
        x[d] = _rotl(x[d] ^ x[a], 8)
        x[c] = (x[c] + x[d]) & _MASK
        x[b] = _rotl(x[b] ^ x[c], 7)

    for _ in range(10):
        quarter(0, 4, 8, 12), quarter(1, 5, 9, 13), quarter(2, 6, 10, 14), quarter(3, 7, 11, 15)
        quarter(0, 5, 10, 15), quarter(1, 6, 11, 12), quarter(2, 7, 8, 13), quarter(3, 4, 9, 14)
    return b"".join(((x[i] + state[i]) & _MASK).to_bytes(4, "little") for i in range(16))


def _chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    for offset in range(0, len(data), 64):
        stream = _chacha20_block(key, counter + offset // 64, nonce)
        chunk = data[offset:offset + 64]
        out[offset:offset + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, stream))
    return bytes(out)


def _poly1305(key: bytes, message: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    modulus = (1 << 130) - 5
    acc = 0
    for offset in range(0, len(message), 16):
        chunk = message[offset:offset + 16]
        acc = (acc + int.from_bytes(chunk + b"\x01", "little")) * r % modulus
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _aead_open(key: bytes, nonce: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
    """ChaCha20-Poly1305 open; the tag is the last 16 bytes of `sealed`."""
    if len(key) != 32 or len(nonce) != 12 or len(sealed) < 16:
        raise HappError("bad ChaCha20-Poly1305 input")
    body, tag = sealed[:-16], sealed[-16:]
    mac = _poly1305(_chacha20_block(key, 0, nonce)[:32],
                    aad + b"\x00" * (-len(aad) % 16) + body + b"\x00" * (-len(body) % 16)
                    + len(aad).to_bytes(8, "little") + len(body).to_bytes(8, "little"))
    if not hmac.compare_digest(mac, tag):
        raise HappError("the link is damaged or was encrypted to another key")
    return _chacha20_xor(key, 1, nonce, body)


# -- the formats -------------------------------------------------------------------------------

def _b64(text: str) -> bytes:
    """Happ's base64: url-safe or standard alphabet, padding optional, whitespace tolerated."""
    clean = "".join(text.split()).replace("-", "+").replace("_", "/").replace("=", "")
    if not clean:
        raise HappError("empty payload")
    if len(clean) > MAX_PAYLOAD:
        raise HappError("the payload is too long for a link")
    try:
        return base64.b64decode(clean + "=" * (-len(clean) % 4))
    except Exception as e:
        raise HappError(f"bad base64 payload: {e}") from e


def _swap_pairs(data: bytes) -> bytes:
    """AB -> BA over every pair; its own inverse."""
    out = bytearray(data)
    for i in range(0, len(out) - 1, 2):
        out[i], out[i + 1] = out[i + 1], out[i]
    return bytes(out)


def _swap_block_halves(data: bytes) -> bytes:
    """ABCD -> CDAB over every whole four-byte block; its own inverse."""
    out = bytearray(data)
    for i in range(0, len(out) - 3, 4):
        out[i], out[i + 2] = out[i + 2], out[i]
        out[i + 1], out[i + 3] = out[i + 3], out[i + 1]
    return bytes(out)


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HappError("the plaintext isn't text") from e


_RSA_VERSION = {1: "crypt", 2: "crypt2", 3: "crypt3", 4: "crypt4"}


def _rsa(payload: str, version: int) -> str:
    """crypt … crypt4: the whole payload is PKCS#1 v1.5 blocks of one key."""
    key = _key(PKCS1_KEYS[_RSA_VERSION[version]])
    data = _b64(payload)
    if len(data) % key.size:
        raise HappError(f"the payload isn't a multiple of {key.size} bytes")
    blocks = [data[i:i + key.size] for i in range(0, len(data), key.size)]
    if len(blocks) > 16:
        raise HappError("the payload has too many blocks")
    return _text(b"".join(key.decrypt(block) for block in blocks))


def _crypt5_body(body: bytes, key: _Key, salted: bool) -> str:
    """nonce | salt? | <ciphertext length in digits> | mark | ciphertext | RSA-wrapped key."""
    if len(body) < 13:
        raise HappError("the payload is too short")
    nonce = body[:12]
    if salted:
        if len(body) < 22:
            raise HappError("the payload is too short")
        salt, start = body[14:22], 22
    else:
        salt, start = b"", 12
    end = start
    while end < len(body) and 0x30 <= body[end] <= 0x39:
        end += 1
    if end == start or end - start > 9:
        raise HappError("the payload has no ciphertext length")
    segment = int(body[start:end])
    packed = body[end:]
    if segment < 1 or segment + 1 > len(packed):
        raise HappError("the payload is truncated")

    wrapped = _swap_pairs(key.decrypt(_b64(packed[segment + 1:].decode("latin-1"))))
    content_key = bytearray(_b64(wrapped.decode("latin-1")))
    if len(content_key) != 32:
        raise HappError(f"a {len(content_key)}-byte content key, 32 expected")
    if salt:
        for i in range(len(content_key)):
            content_key[i] ^= salt[i % len(salt)]
    sealed = _b64(packed[1:segment + 1].decode("latin-1"))
    return _text(_b64(_swap_pairs(_aead_open(bytes(content_key), nonce, sealed)).decode("latin-1")))


def _crypt5(payload: str) -> str:
    """crypt5: the link names its key by an 8-character marker and swaps bytes twice."""
    shuffled = _swap_block_halves(payload.encode("latin-1"))
    if len(shuffled) < 9:
        raise HappError("the payload is too short")
    marker = (shuffled[:4] + shuffled[-4:]).decode("latin-1")
    encoded = CRYPT5_KEYS.get(marker)
    if not encoded:
        raise HappError(f"unknown crypt5 key {marker!r}")
    body, key = shuffled[4:-4], _key(encoded)
    # Older links have no salt; where the salt would be, a digit means exactly that.
    salted = len(body) > 12 and not 0x30 <= body[12] <= 0x39
    for attempt in (salted, not salted):
        try:
            return _crypt5_body(body, key, attempt)
        except HappError:
            pass
    raise HappError(f"crypt5 key {marker!r} doesn't open this link")


def decrypt(payload: str, version: int = 0) -> str:
    """The plaintext of an encrypted payload. version 1–5 as named in the link, 0 = try them."""
    payload = payload.strip()
    if not payload:
        raise HappError("the link is empty")
    if version == 5:
        return _crypt5(payload)
    if version in _RSA_VERSION:
        return _rsa(payload, version)
    error: Exception = HappError("nothing to try")
    for candidate in (4, 3, 2, 1):
        try:
            return _rsa(payload, candidate)
        except HappError as e:
            error = e
    try:
        return _crypt5(payload)
    except HappError as e:
        error = e
    raise HappError(str(error))


# -- links -------------------------------------------------------------------------------------

# The word after the scheme: happ://crypt4/… and, from providers that shorten it, crypt://crypt4/…
_ACTIONS = {"crypt": 1, "crypt1": 1, "crypt2": 2, "crypt3": 3, "crypt4": 4, "crypt5": 5}
_CRYPT_ACTION = re.compile(r"(?i)^crypt\d*$")


def is_crypt_link(text: str) -> bool:
    scheme, _, rest = (text or "").strip().partition("://")
    scheme = scheme.lower()
    if scheme == "happ":
        return bool(_CRYPT_ACTION.match(rest.lstrip("/").split("/", 1)[0].split("?", 1)[0]))
    return scheme == "crypt"


def _payload(value: str) -> str:
    """A payload: no query or fragment (neither can appear in base64), percent-decoded once."""
    return unquote(value.split("?", 1)[0].split("#", 1)[0].strip())


def _parts(text: str) -> tuple[int, str]:
    """(version, payload) of a crypt link; version 0 when the link doesn't say."""
    scheme, _, rest = text.strip().partition("://")
    if not rest:
        raise HappError("not a link")
    rest = rest.lstrip("/")
    action, _, payload = rest.partition("/")
    action = action.lower()
    if "?" in action:
        action, _, query = action.partition("?")
        payload = payload or query.split("url=", 1)[-1]
    if action in _ACTIONS:
        return _ACTIONS[action], _payload(payload)
    if scheme.lower() == "crypt":
        value = rest.partition("?")[2] or rest
        if value.startswith("url="):
            value = value[4:]
        return 0, _payload(value)
    raise HappError(f"unsupported Happ action: {action}")


def unwrap(text: str, depth: int = 0) -> str:
    """What an encrypted link carries. A link inside a link is followed, as Happ does."""
    version, payload = _parts(text)
    plain = decrypt(payload, version).strip()
    if depth < 8 and is_crypt_link(plain):
        return unwrap(plain, depth + 1)
    return plain
