"""Scaleform GFx movies (`Data/UI/<Movie>/Opt/<Movie>.gfx`): the game's UI.

A `.gfx` is a SWF 8 file written by Scaleform's `gfxexport`:

    'GFX' (plain) or 'CFX' (zlib after byte 8), u8 version = 8, u32 length (uncompressed, incl. 8)
    RECT frame size (twips), u16 frame rate (8.8), u16 frame count, then the SWF tag stream

Tag header: u16 `code << 6 | length`, length 63 = long form (u32 follows). The stream ends with
tag 0 exactly at `length` (gate: `tests/corpus_gfx.py`, all 80 movies; CFX bodies carry zero
padding after it). Scaleform adds tags >= 1000:

    1000 ExporterInfo        u16 version, u32 flags (version >= 0x10A), u16 bitmap format,
                             str prefix, str swf name
    1001 DefineExternalImage u16 id, u16 bitmap format, u16 width, u16 height,
                             str export name, str file name           (str = u8 len + bytes)

Images are not inside the movie: every DefineExternalImage names a Texture resource
`ui/flash/<movie>/<movie>_i<hex id>` listed by the movie's `DUIMovie` resource (gate: every
external image resolves). Fonts live in one shared movie (`Fonts/Opt/EnglishFonts.gfx`, named by
the `FlashConfig` resource) as DefineFont3 glyph outlines in 1/20 of a 1024-unit em.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

TAG_NAMES = {
    0: "End", 1: "ShowFrame", 2: "DefineShape", 9: "SetBackgroundColor", 12: "DoAction",
    22: "DefineShape2", 26: "PlaceObject2", 28: "RemoveObject2", 32: "DefineShape3",
    37: "DefineEditText", 39: "DefineSprite", 43: "FrameLabel", 46: "DefineMorphShape",
    56: "ExportAssets", 59: "DoInitAction", 69: "FileAttributes", 70: "PlaceObject3",
    71: "ImportAssets2", 73: "DefineFontAlignZones", 74: "CSMTextSettings", 75: "DefineFont3",
    83: "DefineShape4", 1000: "ExporterInfo", 1001: "DefineExternalImage",
}


@dataclass
class Tag:
    code: int
    offset: int  # of the body, in the uncompressed movie
    data: bytes

    @property
    def name(self) -> str:
        return TAG_NAMES.get(self.code, f"Tag{self.code}")


@dataclass
class Movie:
    version: int
    compressed: bool
    length: int
    frame_size: tuple[int, int, int, int]  # xmin, xmax, ymin, ymax in twips
    frame_rate: float
    frame_count: int
    tags: list[Tag]
    end: int  # offset just past the End tag

    def find(self, code: int) -> list[Tag]:
        return [t for t in self.tags if t.code == code]


class Bits:
    """MSB-first bit reader (SWF RECT, shape records)."""

    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.bit = data, pos * 8

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.d[self.bit >> 3] >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return v

    def s(self, n: int) -> int:
        v = self.u(n)
        return v - (1 << n) if n and v >> (n - 1) else v

    def align(self) -> int:
        self.bit = (self.bit + 7) & ~7
        return self.bit >> 3


def is_gfx(data: bytes) -> bool:
    return data[:3] in (b"GFX", b"CFX")


def parse(data: bytes) -> Movie:
    sig, version = data[:3], data[3]
    if sig not in (b"GFX", b"CFX"):
        raise ValueError(f"not a gfx: {sig!r}")
    length = struct.unpack_from("<I", data, 4)[0]
    body = data[:8] + (zlib.decompress(data[8:]) if sig == b"CFX" else data[8:])
    b = Bits(body, 8)
    nb = b.u(5)
    rect = tuple(b.s(nb) for _ in range(4))
    p = b.align()
    rate, count = struct.unpack_from("<HH", body, p)
    p += 4
    tags = []
    while True:
        h = struct.unpack_from("<H", body, p)[0]
        p += 2
        code, n = h >> 6, h & 63
        if n == 63:
            n = struct.unpack_from("<I", body, p)[0]
            p += 4
        tags.append(Tag(code, p, body[p:p + n]))
        p += n
        if code == 0:
            break
    return Movie(version, sig == b"CFX", length, rect, rate / 256, count, tags, p)


def _str8(d: bytes, p: int) -> tuple[str, int]:
    n = d[p]
    return d[p + 1:p + 1 + n].decode("latin-1"), p + 1 + n


def _cstr(d: bytes, p: int) -> tuple[str, int]:
    e = d.index(b"\0", p)
    return d[p:e].decode("latin-1"), e + 1


@dataclass
class ExternalImage:
    id: int
    format: int
    width: int
    height: int
    export_name: str
    file_name: str


def external_images(m: Movie) -> list[ExternalImage]:
    out = []
    for t in m.find(1001):
        cid, fmt, w, h = struct.unpack_from("<4H", t.data)
        exp, p = _str8(t.data, 8)
        fn, p = _str8(t.data, p)
        out.append(ExternalImage(cid, fmt, w, h, exp, fn))
    return out


def exports(m: Movie) -> dict[str, int]:
    """ExportAssets: linkage name -> character id."""
    out = {}
    for t in m.find(56):
        n = struct.unpack_from("<H", t.data)[0]
        p = 2
        for _ in range(n):
            cid = struct.unpack_from("<H", t.data, p)[0]
            name, p = _cstr(t.data, p + 2)
            out[name] = cid
    return out


def imports(m: Movie) -> list[tuple[str, dict[str, int]]]:
    """ImportAssets2: (source url, {name: id})."""
    out = []
    for t in m.find(71):
        url, p = _cstr(t.data, 0)
        p += 2  # reserved u8 1, u8 0
        n = struct.unpack_from("<H", t.data, p)[0]
        p += 2
        names = {}
        for _ in range(n):
            cid = struct.unpack_from("<H", t.data, p)[0]
            name, p = _cstr(t.data, p + 2)
            names[name] = cid
        out.append((url, names))
    return out


# ---------------------------------------------------------------- shapes and fonts

def _shape_paths(b: Bits, nfill: int, nline: int) -> list[list]:
    """Shape records -> list of subpaths [('M', x, y), ('L', x, y), ('Q', cx, cy, x, y)...]."""
    x = y = 0
    paths, cur = [], None
    while True:
        if b.u(1) == 0:  # style change / end
            flags = b.u(5)
            if flags == 0:
                break
            if flags & 1:  # move to
                n = b.u(5)
                x, y = b.s(n), b.s(n)
                cur = [("M", x, y)]
                paths.append(cur)
            if flags & 2:
                b.u(nfill)
            if flags & 4:
                b.u(nfill)
            if flags & 8:
                b.u(nline)
            if flags & 16:
                raise NotImplementedError("new styles inside a glyph")
        elif b.u(1):  # straight edge
            n = b.u(4) + 2
            if b.u(1):
                dx, dy = b.s(n), b.s(n)
            else:
                dx, dy = (0, b.s(n)) if b.u(1) else (b.s(n), 0)
            x, y = x + dx, y + dy
            if cur is None:
                cur = [("M", 0, 0)]
                paths.append(cur)
            cur.append(("L", x, y))
        else:  # curved edge
            n = b.u(4) + 2
            cx, cy = x + b.s(n), y + b.s(n)
            x, y = cx + b.s(n), cy + b.s(n)
            if cur is None:
                cur = [("M", 0, 0)]
                paths.append(cur)
            cur.append(("Q", cx, cy, x, y))
    return paths


@dataclass
class Font:
    id: int
    name: str
    bold: bool
    italic: bool
    ascent: int = 0
    descent: int = 0
    leading: int = 0
    glyphs: dict[str, list] = field(default_factory=dict)   # char -> subpaths (em = 20480)
    advance: dict[str, int] = field(default_factory=dict)
    kerning: dict[tuple[str, str], int] = field(default_factory=dict)

    EM = 1024 * 20


def fonts(m: Movie) -> list[Font]:
    """DefineFont3 (tag 75): wide offsets/codes are flag-driven; layout block when flag 0x80."""
    out = []
    for t in m.find(75):
        d = t.data
        fid, flags, _lang = struct.unpack_from("<HBB", d)
        name, p = _str8(d, 4)
        n = struct.unpack_from("<H", d, p)[0]
        p += 2
        wide_off, wide_codes = flags & 8, flags & 4
        fmt = "<I" if wide_off else "<H"
        sz = 4 if wide_off else 2
        base = p
        offs = [struct.unpack_from(fmt, d, p + i * sz)[0] for i in range(n + 1)]
        shapes = []
        for i in range(n):
            b = Bits(d, base + offs[i])
            nfill, nline = b.u(4), b.u(4)
            shapes.append(_shape_paths(b, nfill, nline))
        p = base + offs[n]
        cfmt, csz = ("<H", 2) if wide_codes else ("<B", 1)
        codes = [chr(struct.unpack_from(cfmt, d, p + i * csz)[0]) for i in range(n)]
        p += n * csz
        f = Font(fid, name.rstrip("\0"), bool(flags & 1), bool(flags & 2))
        f.glyphs = dict(zip(codes, shapes))
        if flags & 0x80:
            f.ascent, f.descent, f.leading = struct.unpack_from("<hhh", d, p)
            p += 6
            adv = struct.unpack_from(f"<{n}h", d, p)
            f.advance = dict(zip(codes, adv))
            p += 2 * n
            b = Bits(d, p)
            for _ in range(n):  # bounds RECTs (each byte-aligned), unused
                nb = b.u(5)
                for _ in range(4):
                    b.u(nb)
                b.align()
            p = b.align()
            nk = struct.unpack_from("<H", d, p)[0]
            p += 2
            for _ in range(nk):
                if wide_codes:
                    a, c, k = struct.unpack_from("<HHh", d, p)
                    p += 6
                else:
                    a, c, k = struct.unpack_from("<BBh", d, p)
                    p += 4
                f.kerning[(chr(a), chr(c))] = k
        out.append(f)
    return out


def path_d(paths: list[list], dx: float = 0, dy: float = 0, scale: float = 1.0) -> str:
    """Subpaths -> SVG path data (y down, as SWF), each point mapped to (dx + x*scale, dy + y*scale)."""
    s = []
    for sp in paths:
        for op in sp:
            v = [round((dx if i % 2 == 0 else dy) + c * scale, 2) for i, c in enumerate(op[1:])]
            s.append(op[0] + " ".join(map(str, v)))
        s.append("Z")
    return "".join(s)


def text_svg(font: Font, text: str, size: float = 64.0) -> tuple[str, float, float]:
    """(path d, width, height) of one line set in a game font; glyphs sit on y = ascent."""
    sc = size / Font.EM
    asc, desc = font.ascent * sc, font.descent * sc
    x, parts, prev = 0.0, [], None
    for ch in text:
        if prev is not None:
            x += font.kerning.get((prev, ch), 0) * sc
        if font.glyphs.get(ch):
            parts.append(path_d(font.glyphs[ch], x, asc, sc))
        x += font.advance.get(ch, Font.EM // 4) * sc
        prev = ch
    return "".join(parts), x, asc + desc
