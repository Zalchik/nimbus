"""QR Code encoder (byte mode, versions 1-40), after Project Nayuki's reference implementation.

Small enough to keep in the app instead of shipping a dependency for one dialog.
"""
from __future__ import annotations

# Error correction levels, weakest first: (format bits, index into the tables below).
LEVELS = {"L": (1, 0), "M": (0, 1), "Q": (3, 2), "H": (2, 3)}

_ECC_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28,
     28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
_NUM_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18,
     19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31,
     33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40,
     43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48,
     51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)


class DataTooLong(ValueError):
    pass


def _raw_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int, ecl: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver] * _NUM_BLOCKS[ecl][ver]


def _rs_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_multiply(root, 0x02)
    return result


def _rs_remainder(data: bytes | list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_multiply(coef, factor)
    return result


class QrCode:
    """modules[y][x] is True for a dark module."""

    def __init__(self, ver: int, ecl: str, data: list[int]):
        self.version = ver
        self.size = ver * 4 + 17
        self.ecl = ecl
        n = self.size
        self.modules = [[False] * n for _ in range(n)]
        self._func = [[False] * n for _ in range(n)]
        self._draw_function_patterns()
        self._draw_codewords(self._interleave(data))
        best, best_penalty = 0, None
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format_bits(mask)
            penalty = self._penalty()
            if best_penalty is None or penalty < best_penalty:
                best, best_penalty = mask, penalty
            self._apply_mask(mask)  # XOR undoes it
        self.mask = best
        self._apply_mask(best)
        self._draw_format_bits(best)

    # -- function patterns ---------------------------------------------------------------
    def _set(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self._func[y][x] = True

    def _draw_function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self._set(x, y, d not in (2, 4))
        pos = self._alignment_positions()
        last = len(pos) - 1
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format_bits(0)
        self._draw_version()

    def _alignment_positions(self) -> list[int]:
        ver = self.version
        if ver == 1:
            return []
        count = ver // 7 + 2
        step = (ver * 8 + count * 3 + 5) // (count * 4 - 4) * 2
        result = [self.size - 7 - i * step for i in range(count - 1)] + [6]
        return list(reversed(result))

    def _draw_format_bits(self, mask: int) -> None:
        data = LEVELS[self.ecl][0] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        n = self.size
        bit = lambda i: (bits >> i) & 1 != 0  # noqa: E731
        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, bit(i))
        self._set(8, n - 8, True)

    def _draw_version(self) -> None:
        if self.version < 7:
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.version << 12 | rem
        for i in range(18):
            dark = (bits >> i) & 1 != 0
            a, b = self.size - 11 + i % 3, i // 3
            self._set(a, b, dark)
            self._set(b, a, dark)

    # -- data ----------------------------------------------------------------------------
    def _interleave(self, data: list[int]) -> list[int]:
        ver, ecl = self.version, LEVELS[self.ecl][1]
        blocks_n = _NUM_BLOCKS[ecl][ver]
        ecc_len = _ECC_PER_BLOCK[ecl][ver]
        raw = _raw_modules(ver) // 8
        short_n = blocks_n - raw % blocks_n
        short_len = raw // blocks_n
        divisor = _rs_divisor(ecc_len)
        blocks, k = [], 0
        for i in range(blocks_n):
            dat = data[k: k + short_len - ecc_len + (0 if i < short_n else 1)]
            k += len(dat)
            ecc = _rs_remainder(dat, divisor)
            if i < short_n:
                dat = dat + [0]  # padding byte, skipped when interleaving
            blocks.append(dat + ecc)
        result = []
        for i in range(len(blocks[0])):
            for j, blk in enumerate(blocks):
                if i != short_len - ecc_len or j >= short_n:
                    result.append(blk[i])
        return result

    def _draw_codewords(self, data: list[int]) -> None:
        n, i = self.size, 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = n - 1 - vert if upward else vert
                    if not self._func[y][x] and i < len(data) * 8:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 != 0
                        i += 1
            right -= 2

    def _apply_mask(self, mask: int) -> None:
        f = (
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        )[mask]
        for y in range(self.size):
            row, func = self.modules[y], self._func[y]
            for x in range(self.size):
                if not func[x] and f(x, y):
                    row[x] = not row[x]

    # -- mask scoring --------------------------------------------------------------------
    def _penalty(self) -> int:
        n, m = self.size, self.modules
        result = 0
        lines = [m[y] for y in range(n)] + [[m[y][x] for y in range(n)] for x in range(n)]
        for line in lines:
            run_color, run = False, 0
            history = [0] * 7
            for dark in line:
                if dark == run_color:
                    run += 1
                    if run == 5:
                        result += 3
                    elif run > 5:
                        result += 1
                else:
                    self._push_run(run, history)
                    if not run_color:
                        result += self._finder_like(history) * 40
                    run_color, run = dark, 1
            result += self._finder_terminate(run_color, run, history) * 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    result += 3
        dark = sum(sum(row) for row in m)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += k * 10
        return result

    def _push_run(self, run: int, history: list[int]) -> None:
        if history[0] == 0:
            run += self.size  # light border before the first module
        history.pop()
        history.insert(0, run)

    def _finder_like(self, h: list[int]) -> int:
        n = h[1]
        core = n > 0 and h[2] == h[4] == h[5] == n and h[3] == n * 3
        return (int(core and h[0] >= n * 4 and h[6] >= n) +
                int(core and h[6] >= n * 4 and h[0] >= n))

    def _finder_terminate(self, run_color: bool, run: int, history: list[int]) -> int:
        if run_color:
            self._push_run(run, history)
            run = 0
        run += self.size
        self._push_run(run, history)
        return self._finder_like(history)


def encode(text: str, ecl: str = "M") -> QrCode:
    """Smallest QR code holding text (UTF-8, byte mode). The error correction level is raised
    above ecl whenever that fits the same version."""
    data = text.encode("utf-8")
    names = list(LEVELS)  # L, M, Q, H
    lo = names.index(ecl)
    for ver in range(1, 41):
        count_bits = 8 if ver <= 9 else 16
        used = 4 + count_bits + len(data) * 8
        if used <= _data_codewords(ver, LEVELS[ecl][1]) * 8:
            break
    else:
        raise DataTooLong(f"{len(data)} bytes don't fit in a QR code")
    for name in names[lo + 1:]:
        if used <= _data_codewords(ver, LEVELS[name][1]) * 8:
            ecl = name
    capacity = _data_codewords(ver, LEVELS[ecl][1]) * 8
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)
    put(len(data), count_bits)
    for b in data:
        put(b, 8)
    put(0, min(4, capacity - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i: i + 8])), 2) for i in range(0, len(bits), 8)]
    return QrCode(ver, ecl, codewords)
