"""QR codes, standard library only: enough to pair a phone by pointing its camera at the terminal.

Byte mode (UTF-8), error correction L, M, Q or H, versions 1 to 10 (up to 213 bytes at M). Follows ISO/IEC 18004.

    matrix = encode("http://192.168.1.20:8765/m#t=...")
    print(to_terminal(matrix))
"""
from __future__ import annotations

import struct
import zlib

# Per version: for each level, (EC codewords per block, [(number of blocks, data codewords per block), ...]).
_BLOCKS = {
    1: {"L": (7, [(1, 19)]), "M": (10, [(1, 16)]), "Q": (13, [(1, 13)]), "H": (17, [(1, 9)])},
    2: {"L": (10, [(1, 34)]), "M": (16, [(1, 28)]), "Q": (22, [(1, 22)]), "H": (28, [(1, 16)])},
    3: {"L": (15, [(1, 55)]), "M": (26, [(1, 44)]), "Q": (18, [(2, 17)]), "H": (22, [(2, 13)])},
    4: {"L": (20, [(1, 80)]), "M": (18, [(2, 32)]), "Q": (26, [(2, 24)]), "H": (16, [(4, 9)])},
    5: {"L": (26, [(1, 108)]), "M": (24, [(2, 43)]), "Q": (18, [(2, 15), (2, 16)]), "H": (22, [(2, 11), (2, 12)])},
    6: {"L": (18, [(2, 68)]), "M": (16, [(4, 27)]), "Q": (24, [(4, 19)]), "H": (28, [(4, 15)])},
    7: {"L": (20, [(2, 78)]), "M": (18, [(4, 31)]), "Q": (18, [(2, 14), (4, 15)]), "H": (26, [(4, 13), (1, 14)])},
    8: {"L": (24, [(2, 97)]), "M": (22, [(2, 38), (2, 39)]), "Q": (22, [(4, 18), (2, 19)]), "H": (26, [(4, 14), (2, 15)])},
    9: {"L": (30, [(2, 116)]), "M": (22, [(3, 36), (2, 37)]), "Q": (20, [(4, 16), (4, 17)]), "H": (24, [(4, 12), (4, 13)])},
    10: {"L": (18, [(2, 68), (2, 69)]), "M": (26, [(4, 43), (1, 44)]), "Q": (24, [(6, 19), (2, 20)]),
         "H": (28, [(6, 15), (2, 16)])},
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_LEVEL_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}
_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


# ---------- Reed-Solomon over GF(256), primitive polynomial 0x11D ----------

def _mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _mul(root, 0x02)
    return result


def _remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _mul(coef, factor)
    return result


# ---------- codewords ----------

def _capacity(version: int, level: str) -> int:
    return sum(n * size for n, size in _BLOCKS[version][level][1])


def _codewords(data: bytes, version: int, level: str) -> list[int]:
    count_bits = 8 if version < 10 else 16
    bits: list[int] = []
    put = lambda value, n: bits.extend((value >> i) & 1 for i in reversed(range(n)))
    put(0b0100, 4)
    put(len(data), count_bits)
    for b in data:
        put(b, 8)
    room = _capacity(version, level) * 8
    put(0, min(4, room - len(bits)))                  # terminator
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    for i in range(room // 8 - len(words)):
        words.append((0xEC, 0x11)[i % 2])
    ec_len, groups = _BLOCKS[version][level]
    divisor = _divisor(ec_len)
    blocks, at = [], 0
    for n, size in groups:
        for _ in range(n):
            block = words[at:at + size]
            at += size
            blocks.append((block, _remainder(block, divisor)))
    out = []
    for i in range(max(len(b) for b, _ in blocks)):
        out += [b[i] for b, _ in blocks if i < len(b)]
    for i in range(ec_len):
        out += [ec[i] for _, ec in blocks]
    return out


# ---------- the matrix ----------

class _Matrix:
    def __init__(self, version: int):
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        centres = _ALIGN[self.version]
        last = len(centres) - 1
        for i, cx in enumerate(centres):
            for j, cy in enumerate(centres):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue                          # under a finder pattern
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits("M", 0)                      # reserves the area; drawn for real once the mask is chosen
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def format_bits(self, level: str, mask: int) -> None:
        data = _LEVEL_BITS[level] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        n = self.size
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, n - 15 + i, bit(i))
        self.set(8, n - 8, True)                      # the dark module

    def place(self, codewords: list[int]) -> None:
        n, i, total = self.size, 0, len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fixed[y][x] and i < total:
                        self.dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def masked(self, mask: int) -> list[list[bool]]:
        rule = _MASKS[mask]
        return [[d ^ (not f and rule(x, y)) for x, (d, f) in enumerate(zip(row, frow))]
                for y, (row, frow) in enumerate(zip(self.dark, self.fixed))]


def _penalty(m: list[list[bool]]) -> int:
    n = len(m)
    score = 0
    lines = m + [list(col) for col in zip(*m)]
    for line in lines:                                # runs of five or more
        run = 1
        for a, b in zip(line, line[1:]):
            if a == b:
                run += 1
            else:
                score += run - 2 if run >= 5 else 0
                run = 1
        score += run - 2 if run >= 5 else 0
    for y in range(n - 1):                            # 2x2 blocks
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    finder_like = ([True, False, True, True, True, False, True, False, False, False, False],
                   [False, False, False, False, True, False, True, True, True, False, True])
    for line in lines:
        for i in range(len(line) - 10):
            if line[i:i + 11] in finder_like:
                score += 40
    dark = sum(map(sum, m))
    score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return score


def encode(text: str, ecc: str = "M") -> list[list[bool]]:
    """The module matrix (True is dark), without the quiet zone. ValueError if it is too long for version 10."""
    ecc = ecc.upper()
    if ecc not in _LEVEL_BITS:
        raise ValueError("error correction is L, M, Q or H")
    data = text.encode("utf-8")
    for version in range(1, 11):
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + len(data) * 8 <= _capacity(version, ecc) * 8:
            break
    else:
        raise ValueError(f"too long for a QR code at level {ecc}: {len(data)} bytes")
    matrix = _Matrix(version)
    matrix.function_patterns()
    matrix.place(_codewords(data, version, ecc))
    best = min(range(8), key=lambda k: _penalty(_with_format(matrix, ecc, k)))
    return _with_format(matrix, ecc, best)


def _with_format(matrix: _Matrix, level: str, mask: int) -> list[list[bool]]:
    matrix.format_bits(level, mask)
    return matrix.masked(mask)


# ---------- drawing ----------

def to_terminal(matrix: list[list[bool]], border: int = 2) -> str:
    """Two rows per line in half blocks, black on white whatever the terminal's colours, so any phone can scan it."""
    n = len(matrix) + 2 * border
    at = lambda x, y: 0 <= y - border < len(matrix) and 0 <= x - border < len(matrix) and matrix[y - border][x - border]
    lines = []
    for y in range(0, n, 2):
        chars = []
        for x in range(n):
            top, bottom = at(x, y), at(x, y + 1) if y + 1 < n else False
            chars.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
        lines.append("\033[30;107m" + "".join(chars) + "\033[0m")
    return "\n".join(lines)


def to_png(matrix: list[list[bool]], scale: int = 8, border: int = 4) -> bytes:
    """A greyscale PNG."""
    n = (len(matrix) + 2 * border) * scale
    rows = []
    for y in range(n):
        my = y // scale - border
        row = bytearray([0])                          # filter: none
        for x in range(n):
            mx = x // scale - border
            dark = 0 <= my < len(matrix) and 0 <= mx < len(matrix) and matrix[my][mx]
            row.append(0 if dark else 255)
        rows.append(bytes(row))
    chunk = lambda kind, body: struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
