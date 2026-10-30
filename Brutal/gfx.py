"""Scaleform GFx movies (`Data/UI/<Movie>/Opt/<Movie>.gfx`): the game's UI.

A `.gfx` is a SWF 8 file written by Scaleform's `gfxexport`:

    'GFX' (plain) or 'CFX' (zlib after byte 8), u8 version = 8, u32 length (uncompressed, incl. 8)
    RECT frame size (twips), u16 frame rate (8.8), u16 frame count, then the SWF tag stream

Tag header: u16 `code << 6 | length`, length 63 = long form (u32 follows). The stream ends with
tag 0 exactly at `length` (gate: `Tests/corpus_gfx.py`, all 80 movies; CFX bodies carry zero
padding after it). Scaleform adds tags >= 1000:

    1000 ExporterInfo        u16 version, u32 flags (version >= 0x10A), u16 bitmap format,
                             str prefix, str swf name
    1001 DefineExternalImage u16 id, u16 bitmap format, u16 width, u16 height,
                             str export name, str file name           (str = u8 len + bytes)

Images are not inside the movie: every DefineExternalImage names a Texture resource listed by the
movie's `DUIMovie`, `ui/flash/<prefix>/<lower stem of the file name>` (gate: every external image
resolves). Fonts live in one shared movie (`Fonts/Opt/EnglishFonts.gfx`, named by the
`FlashConfig` resource) as DefineFont3 glyph outlines in 1/20 of a 1024-unit em; 40 other movies
embed 42 DefineFont3 with glyphs of their own (MTL-150, Simeon AS Regular, Zamora, Colossalis
Black, subsets of TG_Menu), and 9 carry 10 glyph-less DefineFont3 records that only name a font
(TG_Condensed, TG_Menu, Arial).

Characters and timelines (standard SWF 8 layouts; gate `Tests/corpus_render.py`: every one of
these tags in the 80 movies, root and nested sprites, decodes to exactly its length):

    DefineShape 2 / 22 / 32 / 83   u16 id, RECT, [83: RECT edge bounds, u8 flags (0x04 non-zero
                                   winding)], fill styles, line styles, SHAPE records. RGB colours
                                   for 2/22, RGBA for 32/83; style counts 0xFF -> u16 (fills from
                                   22 on); LINESTYLE2 in 83. NewStyles in a style-change record
                                   reads byte-aligned style arrays, then fresh fill/line bit counts
    DefineMorphShape 46 / 84       u16 id, start/end RECT [84: two edge RECTs, u8 flags], u32
                                   offset to the end edges (from after the field; the start edges
                                   end exactly there), start/end style pairs, start SHAPE, end SHAPE
    DefineEditText 37              u16 id, RECT, flags u16 (HasText 0x8000, WordWrap 0x4000,
                                   Multiline 0x2000, Password, ReadOnly, HasTextColor 0x0400,
                                   HasMaxLength 0x0200, HasFont 0x0100 | HasFontClass 0x80,
                                   AutoSize 0x40, HasLayout 0x20, NoSelect, Border 0x08, WasStatic,
                                   HTML 0x02, UseOutlines 0x01), [u16 font] [str class]
                                   [u16 height] [RGBA] [u16 max] [u8 align, u16 left, u16 right,
                                   u16 indent, s16 leading], str variable, [str text]
    PlaceObject2 26 / 3 70         flags (+ a second byte for 70), u16 depth, [class], [char],
                                   [MATRIX], [CXFORMWITHALPHA], [u16 ratio], [str name],
                                   [u16 clip depth], [filters], [u8 blend], [u8 cache], [actions]
    DefineSprite 39                u16 id, u16 frame count, control tags until End

Corpus facts (same gate): fills are only solid (981) and bitmap (3,777); no gradient fill is used.
1,774 bitmap fill styles name id 65535 and are never selected by an edge; 99 name an imported id
(`Shared/ControllerIcons.swf` exports, which are external images of `PhysicalInputIcons.gfx`).
PlaceObject3 filters are Glow (157) and DropShadow (24); blend modes multiply (18), add (3),
screen (1); 33 placements carry clip actions. No placement has a ClipDepth. Every fill style's
edges (fill1 forward, fill0 reversed) close into contours, 9,409 of 9,409. Strings in tags 37, 43,
56, 70 are NUL-terminated (UTF-8 decoding assumed for SWF 6+).
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
    83: "DefineShape4", 84: "DefineMorphShape2", 1000: "ExporterInfo", 1001: "DefineExternalImage",
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


# ---------------------------------------------------------------- characters and timelines

def tag_stream(d: bytes, p: int) -> list[Tag]:
    """SWF tags from offset p up to and including End (DefineSprite bodies)."""
    out = []
    while p < len(d):
        h = struct.unpack_from("<H", d, p)[0]
        p += 2
        code, n = h >> 6, h & 63
        if n == 63:
            n = struct.unpack_from("<I", d, p)[0]
            p += 4
        out.append(Tag(code, p, d[p:p + n]))
        p += n
        if code == 0:
            break
    return out


Matrix = tuple  # (a, b, c, d, tx, ty): x' = a x + c y + tx, y' = b x + d y + ty (SVG order)
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def read_matrix(b: Bits) -> Matrix:
    """MATRIX: [scale FB 16.16 x2] [rotate/skew FB x2] translate SB (twips)."""
    a = d = 1.0
    rb = rc = 0.0
    if b.u(1):
        n = b.u(5)
        a, d = b.s(n) / 65536, b.s(n) / 65536
    if b.u(1):
        n = b.u(5)
        rb, rc = b.s(n) / 65536, b.s(n) / 65536  # RotateSkew0 -> b, RotateSkew1 -> c
    n = b.u(5)
    tx, ty = b.s(n), b.s(n)
    return (a, rb, rc, d, float(tx), float(ty))


def read_cxform(b: Bits, alpha: bool = True) -> tuple:
    """CXFORM(WITHALPHA): ((mr, mg, mb, ma) 8.8 fixed, (ar, ag, ab, aa)); missing terms = identity."""
    has_add, has_mult, n = b.u(1), b.u(1), b.u(4)
    k = 4 if alpha else 3
    mult = tuple(b.s(n) for _ in range(k)) if has_mult else (256,) * k
    add = tuple(b.s(n) for _ in range(k)) if has_add else (0,) * k
    if not alpha:
        mult, add = mult + (256,), add + (0,)
    return mult, add


def _rgb(d: bytes, p: int, alpha: bool) -> tuple[tuple, int]:
    if alpha:
        return tuple(d[p:p + 4]), p + 4
    return (*d[p:p + 3], 255), p + 3


def _gradient(d: bytes, p: int, alpha: bool, morph: bool = False) -> tuple[dict, int]:
    h = d[p]
    p += 1
    g = {"spread": h >> 6, "interp": (h >> 4) & 3, "stops": [], "stops_end": []}
    for _ in range(h & 15):
        r, p = d[p], p + 1
        c, p = _rgb(d, p, alpha)
        g["stops"].append((r, c))
        if morph:
            r, p = d[p], p + 1
            c, p = _rgb(d, p, True)
            g["stops_end"].append((r, c))
    return g, p


def _matrix_at(d: bytes, p: int) -> tuple[Matrix, int]:
    b = Bits(d, p)
    m = read_matrix(b)
    return m, b.align()


def _fill_style(d: bytes, p: int, ver: int, morph: bool = False) -> tuple[dict, int]:
    t = d[p]
    p += 1
    alpha = ver >= 3 or morph
    if t == 0x00:
        c, p = _rgb(d, p, alpha)
        f = {"type": "solid", "color": c}
        if morph:
            f["color_end"], p = _rgb(d, p, True)
        return f, p
    if t in (0x10, 0x12, 0x13):
        m, p = _matrix_at(d, p)
        f = {"type": {0x10: "linear", 0x12: "radial", 0x13: "focal"}[t], "matrix": m}
        if morph:
            f["matrix_end"], p = _matrix_at(d, p)
        g, p = _gradient(d, p, alpha, morph)
        f.update(g)
        f["focal"] = 0.0
        if t == 0x13:
            f["focal"] = struct.unpack_from("<h", d, p)[0] / 256
            p += 2
            if morph:
                f["focal_end"] = struct.unpack_from("<h", d, p)[0] / 256
                p += 2
        return f, p
    if t in (0x40, 0x41, 0x42, 0x43):
        bid = struct.unpack_from("<H", d, p)[0]
        m, p = _matrix_at(d, p + 2)
        f = {"type": "bitmap", "id": bid, "matrix": m, "repeat": t in (0x40, 0x42), "smooth": t < 0x42}
        if morph:
            f["matrix_end"], p = _matrix_at(d, p)
        return f, p
    raise ValueError(f"fill style type 0x{t:02x}")


def _styles(d: bytes, p: int, ver: int, morph: bool = False) -> tuple[list, list, int]:
    n = d[p]
    p += 1
    if n == 0xFF and (ver >= 2 or morph):
        n = struct.unpack_from("<H", d, p)[0]
        p += 2
    fills = []
    for _ in range(n):
        f, p = _fill_style(d, p, ver, morph)
        fills.append(f)
    n = d[p]
    p += 1
    if n == 0xFF:
        n = struct.unpack_from("<H", d, p)[0]
        p += 2
    lines = []
    for _ in range(n):
        ln = {"cap": 0, "join": 0, "miter": 3.0, "fill": None, "noclose": False}
        if morph:
            ln["width"], ln["width_end"] = struct.unpack_from("<HH", d, p)
            p += 4
        else:
            ln["width"] = struct.unpack_from("<H", d, p)[0]
            p += 2
        if ver >= 4:
            f1, f2 = d[p], d[p + 1]
            p += 2
            ln["cap"], ln["join"], has_fill = f1 >> 6, (f1 >> 4) & 3, f1 & 8
            ln["noclose"] = bool(f2 & 4)
            if ln["join"] == 2:
                ln["miter"] = struct.unpack_from("<H", d, p)[0] / 256
                p += 2
            if has_fill:
                ln["fill"], p = _fill_style(d, p, ver, morph)
                ln["color"] = (0, 0, 0, 255)
                lines.append(ln)
                continue
        ln["color"], p = _rgb(d, p, ver >= 3 or morph)
        if morph:
            ln["color_end"], p = _rgb(d, p, True)
        lines.append(ln)
    return fills, lines, p


@dataclass
class Shape:
    """A shape as style groups. Edge = (fill0, fill1, line, x0, y0, cx, cy, x1, y1) in twips,
    cx/cy None for a straight edge; style indices are 1-based into the group's arrays, 0 = none."""
    id: int
    bounds: tuple[int, int, int, int]  # RECT: xmin, xmax, ymin, ymax (twips)
    groups: list = field(default_factory=list)  # [(fills, lines, edges)]
    nonzero: bool = False  # DefineShape4 UsesFillWindingRule


def _records(d: bytes, p: int, ver: int) -> tuple[list, int]:
    """SHAPE -> records ('S', move|None, f0|None, f1|None, line|None, (fills, lines)|None) and
    ('E', dx, dy, None, None) / ('E', cdx, cdy, adx, ady); returns (records, end byte offset)."""
    b = Bits(d, p)
    nf, nl = b.u(4), b.u(4)
    out = []
    while True:
        if b.u(1) == 0:
            flags = b.u(5)
            if flags == 0:
                break
            move = f0 = f1 = ln = new = None
            if flags & 1:
                n = b.u(5)
                move = (b.s(n), b.s(n))
            if flags & 2:
                f0 = b.u(nf)
            if flags & 4:
                f1 = b.u(nf)
            if flags & 8:
                ln = b.u(nl)
            if flags & 16:
                fs, ls, q = _styles(d, b.align(), ver)
                new = (fs, ls)
                b = Bits(d, q)
                nf, nl = b.u(4), b.u(4)
            out.append(("S", move, f0, f1, ln, new))
        elif b.u(1):
            n = b.u(4) + 2
            if b.u(1):
                dx, dy = b.s(n), b.s(n)
            else:
                dx, dy = (0, b.s(n)) if b.u(1) else (b.s(n), 0)
            out.append(("E", dx, dy, None, None))
        else:
            n = b.u(4) + 2
            out.append(("E", b.s(n), b.s(n), b.s(n), b.s(n)))
    return out, b.align()


def _build(records, fills, lines) -> list:
    """Records -> style groups [(fills, lines, absolute edges)]. NewStyles opens a group and resets
    the selections; the selections of that record then index the new arrays."""
    groups = [(fills, lines, [])]
    x = y = 0
    f0 = f1 = ln = 0
    for r in records:
        if r[0] == "S":
            _, move, a, c, l, new = r
            if new is not None:
                groups.append((new[0], new[1], []))
                f0 = f1 = ln = 0
            if move is not None:
                x, y = move
            if a is not None:
                f0 = a
            if c is not None:
                f1 = c
            if l is not None:
                ln = l
        else:
            _, dx, dy, ex, ey = r
            if ex is None:
                groups[-1][2].append((f0, f1, ln, x, y, None, None, x + dx, y + dy))
                x, y = x + dx, y + dy
            else:
                cx, cy = x + dx, y + dy
                groups[-1][2].append((f0, f1, ln, x, y, cx, cy, cx + ex, cy + ey))
                x, y = cx + ex, cy + ey
    return groups


def _rect(d: bytes, p: int) -> tuple[tuple, int]:
    b = Bits(d, p)
    n = b.u(5)
    r = tuple(b.s(n) for _ in range(4))
    return r, b.align()


SHAPE_TAGS = {2: 1, 22: 2, 32: 3, 83: 4}  # tag code -> DefineShape version


def shape(t: Tag) -> tuple[Shape, int]:
    """DefineShape/2/3/4 -> (Shape, bytes consumed)."""
    ver = SHAPE_TAGS[t.code]
    d = t.data
    sid = struct.unpack_from("<H", d)[0]
    bounds, p = _rect(d, 2)
    nonzero = False
    if ver == 4:
        _, p = _rect(d, p)
        nonzero = bool(d[p] & 4)
        p += 1
    fills, lines, p = _styles(d, p, ver)
    recs, end = _records(d, p, ver)
    return Shape(sid, bounds, _build(recs, fills, lines), nonzero), end


@dataclass
class MorphShape:
    id: int
    start: list   # records of the start shape
    end: list     # records of the end shape (edges and moves only)
    fills: list
    lines: list


def morph_shape(t: Tag) -> tuple[MorphShape, int]:
    """DefineMorphShape (46) / DefineMorphShape2 (84) -> (MorphShape, bytes consumed)."""
    d = t.data
    mid = struct.unpack_from("<H", d)[0]
    _, p = _rect(d, 2)
    _, p = _rect(d, p)
    ver = 3
    if t.code == 84:
        _, p = _rect(d, p)
        _, p = _rect(d, p)
        p += 1
        ver = 4
    off = struct.unpack_from("<I", d, p)[0]
    p += 4
    end_at = p + off
    fills, lines, p = _styles(d, p, ver, morph=True)
    start, q0 = _records(d, p, ver)
    if q0 != end_at:
        raise ValueError(f"morph start edges end at {q0}, offset says {end_at}")
    end, q = _records(d, end_at, ver)
    return MorphShape(mid, start, end, fills, lines), q


def _lerp(a, b, r):
    return a + (b - a) * r


def _lerp_color(a, b, r):
    return tuple(int(round(_lerp(x, y, r))) for x, y in zip(a, b))


def morph_at(m: MorphShape, ratio: int) -> Shape:
    """Interpolate a morph shape at a PlaceObject ratio (0..65535)."""
    r = ratio / 65535

    def fill(f):
        f = dict(f)
        if f["type"] == "solid":
            f["color"] = _lerp_color(f["color"], f["color_end"], r)
        else:
            f["matrix"] = tuple(_lerp(a, b, r) for a, b in zip(f["matrix"], f["matrix_end"]))
            if "stops" in f:
                f["stops"] = [(int(round(_lerp(a[0], b[0], r))), _lerp_color(a[1], b[1], r))
                              for a, b in zip(f["stops"], f["stops_end"])]
        return f

    fills = [fill(f) for f in m.fills]
    lines = []
    for ln in m.lines:
        ln = dict(ln)
        ln["width"] = _lerp(ln["width"], ln["width_end"], r)
        if ln.get("fill"):
            ln["fill"] = fill(ln["fill"])
        else:
            ln["color"] = _lerp_color(ln["color"], ln["color_end"], r)
        lines.append(ln)

    def curve(rr):
        if rr[3] is None:
            return rr[1] / 2, rr[2] / 2, rr[1] / 2, rr[2] / 2
        return rr[1:]

    out, ei, end = [], 0, m.end
    ex = ey = 0
    sx = sy = 0
    for rec in m.start:
        if rec[0] == "S":
            move = rec[1]
            if move is not None:
                sx, sy = move
                if ei < len(end) and end[ei][0] == "S":
                    if end[ei][1] is not None:
                        ex, ey = end[ei][1]
                    ei += 1
                move = (_lerp(sx, ex, r), _lerp(sy, ey, r))
            out.append(("S", move) + rec[2:])
            continue
        while ei < len(end) and end[ei][0] == "S":
            if end[ei][1] is not None:
                ex, ey = end[ei][1]
            ei += 1
        er = end[ei] if ei < len(end) else ("E", 0, 0, None, None)
        ei += 1
        if rec[3] is None and er[3] is None:
            out.append(("E", _lerp(rec[1], er[1], r), _lerp(rec[2], er[2], r), None, None))
        else:
            a, b = curve(rec), curve(er)
            out.append(("E",) + tuple(_lerp(u, v, r) for u, v in zip(a, b)))
    return Shape(m.id, (0, 0, 0, 0), _build(out, fills, lines))


@dataclass
class EditText:
    id: int
    bounds: tuple[int, int, int, int]  # RECT: xmin, xmax, ymin, ymax (twips)
    flags: int  # the two flag bytes as a big-endian u16 (HasText = 0x8000 ... UseOutlines = 0x0001)
    font_id: int | None = None
    font_class: str | None = None
    height: int = 240  # twips
    color: tuple = (0, 0, 0, 255)
    max_length: int | None = None
    align: int = 0  # 0 left, 1 right, 2 center, 3 justify
    left: int = 0
    right: int = 0
    indent: int = 0
    leading: int = 0
    variable: str = ""
    text: str = ""

    word_wrap = property(lambda s: bool(s.flags & 0x4000))
    multiline = property(lambda s: bool(s.flags & 0x2000))
    html = property(lambda s: bool(s.flags & 0x0002))
    auto_size = property(lambda s: bool(s.flags & 0x0040))
    border = property(lambda s: bool(s.flags & 0x0008))
    use_outlines = property(lambda s: bool(s.flags & 0x0001))


def _ustr(d: bytes, p: int) -> tuple[str, int]:
    e = d.index(b"\0", p)
    return d[p:e].decode("utf-8", "replace"), e + 1


def edit_text(t: Tag) -> tuple[EditText, int]:
    """DefineEditText (37) -> (EditText, bytes consumed)."""
    d = t.data
    eid = struct.unpack_from("<H", d)[0]
    bounds, p = _rect(d, 2)
    flags = d[p] << 8 | d[p + 1]
    p += 2
    e = EditText(eid, bounds, flags)
    if flags & 0x0100:
        e.font_id = struct.unpack_from("<H", d, p)[0]
        p += 2
    if flags & 0x0080:
        e.font_class, p = _ustr(d, p)
    if flags & 0x0180:
        e.height = struct.unpack_from("<H", d, p)[0]
        p += 2
    if flags & 0x0400:
        e.color = tuple(d[p:p + 4])
        p += 4
    if flags & 0x0200:
        e.max_length = struct.unpack_from("<H", d, p)[0]
        p += 2
    if flags & 0x0020:
        e.align = d[p]
        e.left, e.right, e.indent, e.leading = struct.unpack_from("<HHHh", d, p + 1)
        p += 9
    e.variable, p = _ustr(d, p)
    if flags & 0x8000:
        e.text, p = _ustr(d, p)
    return e, p


BLEND_MODES = {0: "normal", 1: "normal", 2: "layer", 3: "multiply", 4: "screen", 5: "lighten",
               6: "darken", 7: "difference", 8: "add", 9: "subtract", 10: "invert", 11: "alpha",
               12: "erase", 13: "overlay", 14: "hardlight"}
FILTER_NAMES = {0: "DropShadow", 1: "Blur", 2: "Glow", 3: "Bevel", 4: "GradientGlow",
                5: "Convolution", 6: "ColorMatrix", 7: "GradientBevel"}
_FILTER_SIZE = {0: 23, 1: 9, 2: 15, 3: 27, 6: 80}


@dataclass
class Place:
    depth: int
    move: bool
    char: int | None = None
    matrix: Matrix | None = None
    cxform: tuple | None = None
    ratio: int | None = None
    name: str | None = None
    clip_depth: int | None = None
    filters: list | None = None   # [(filter id, body bytes)]
    blend: int | None = None
    cache_as_bitmap: bool | None = None
    class_name: str | None = None
    clip_actions: bool = False

    KEEP = ("char", "matrix", "cxform", "ratio", "name", "clip_depth", "filters", "blend",
            "cache_as_bitmap", "class_name")


def _filters(d: bytes, p: int) -> tuple[list, int]:
    n = d[p]
    p += 1
    out = []
    for _ in range(n):
        fid = d[p]
        q = p + 1
        if fid in _FILTER_SIZE:
            q += _FILTER_SIZE[fid]
        elif fid in (4, 7):
            q += 1 + 5 * d[q] + 19
        elif fid == 5:
            q += 2 + 8 + 4 * d[q] * d[q + 1] + 4 + 1
        else:
            raise ValueError(f"filter {fid}")
        out.append((fid, d[p + 1:q]))
        p = q
    return out, p


def place(t: Tag) -> tuple[Place, int]:
    """PlaceObject2 (26) / PlaceObject3 (70) -> (Place, bytes consumed before clip actions)."""
    d = t.data
    f = d[0]
    f2 = d[1] if t.code == 70 else 0
    p = 2 if t.code == 70 else 1
    depth = struct.unpack_from("<H", d, p)[0]
    p += 2
    o = Place(depth, bool(f & 1), clip_actions=bool(f & 0x80))
    if f2 & 0x08 or (f2 & 0x10 and f & 2):
        o.class_name, p = _ustr(d, p)
    if f & 2:
        o.char = struct.unpack_from("<H", d, p)[0]
        p += 2
    if f & 4:
        o.matrix, p = _matrix_at(d, p)
    if f & 8:
        b = Bits(d, p)
        o.cxform = read_cxform(b)
        p = b.align()
    if f & 0x10:
        o.ratio = struct.unpack_from("<H", d, p)[0]
        p += 2
    if f & 0x20:
        o.name, p = _ustr(d, p)
    if f & 0x40:
        o.clip_depth = struct.unpack_from("<H", d, p)[0]
        p += 2
    if f2 & 0x01:
        o.filters, p = _filters(d, p)
    if f2 & 0x02:
        o.blend = d[p]
        p += 1
    if f2 & 0x04:
        o.cache_as_bitmap = bool(d[p])
        p += 1
    return o, p


@dataclass
class Sprite:
    id: int
    frame_count: int
    tags: list


def sprite(t: Tag) -> Sprite:
    """DefineSprite (39): u16 id, u16 frame count, control-tag stream ending with End."""
    sid, n = struct.unpack_from("<HH", t.data)
    return Sprite(sid, n, tag_stream(t.data, 4))


def frame_labels(tags: list[Tag]) -> dict[str, int]:
    """FrameLabel (43, NUL-terminated name) -> 0-based index of the frame it is in (first wins)."""
    out, frame = {}, 0
    for t in tags:
        if t.code == 1:
            frame += 1
        elif t.code == 43:
            out.setdefault(_ustr(t.data, 0)[0], frame)
    return out


def display_list(tags: list[Tag], frame: int = 0) -> dict[int, Place]:
    """Depth -> placement after the control tags of frames 0..frame, played in order."""
    dl: dict[int, Place] = {}
    cur = 0
    for t in tags:
        if t.code in (26, 70):
            o, _ = place(t)
            old = dl.get(o.depth)
            if not o.move or old is None:
                if o.char is not None:
                    dl[o.depth] = o
                continue
            new = Place(o.depth, True, **{k: getattr(old, k) for k in Place.KEEP})
            for k in Place.KEEP:
                v = getattr(o, k)
                if v is not None:
                    setattr(new, k, v)
            dl[o.depth] = new
        elif t.code == 28:
            dl.pop(struct.unpack_from("<H", t.data)[0], None)
        elif t.code == 5:
            dl.pop(struct.unpack_from("<H", t.data, 2)[0], None)
        elif t.code == 1:
            if cur == frame:
                return dl
            cur += 1
    return dl


CHARACTER_TAGS = (2, 22, 32, 83, 37, 39, 46, 84, 75, 1001)


def dictionary(m: Movie) -> dict[int, Tag]:
    """Character id -> defining tag, over the whole root stream."""
    return {struct.unpack_from("<H", t.data)[0]: t for t in m.tags if t.code in CHARACTER_TAGS}


def font(t: Tag) -> Font:
    """One DefineFont3 tag -> Font (see `fonts`)."""
    return fonts(Movie(8, False, 0, (0, 0, 0, 0), 0, 0, [t], 0))[0]


def external_image(t: Tag) -> ExternalImage:
    cid, fmt, w, h = struct.unpack_from("<4H", t.data)
    exp, p = _str8(t.data, 8)
    fn, p = _str8(t.data, p)
    return ExternalImage(cid, fmt, w, h, exp, fn)


def stop_frame(tags: list[Tag]) -> int | None:
    """First frame whose DoAction holds a top-level ActionStop (0x07), else None. AS2 records:
    u8 code, and for code >= 0x80 a u16 length and body; DefineFunction (0x9B), DefineFunction2
    (0x8E) and With (0x94) bodies (code size = the record's last u16) are skipped. A stop behind
    a branch counts too: this is a heuristic for the frame a timeline rests on, not execution."""
    frame = 0
    for t in tags:
        if t.code == 1:
            frame += 1
        elif t.code == 12:
            d, p = t.data, 0
            while p < len(d) and d[p]:
                code = d[p]
                if code == 0x07:
                    return frame
                if code < 0x80:
                    p += 1
                    continue
                n = struct.unpack_from("<H", d, p + 1)[0]
                p += 3 + n
                if code in (0x9B, 0x8E, 0x94) and n >= 2:
                    p += struct.unpack_from("<H", d, p - 2)[0]
    return None
