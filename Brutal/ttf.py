"""TrueType export of a Scaleform DefineFont3 (`gfx.Font`).

DefineFont3 glyphs are quadratic outlines in a 1024 x 20 = 20480-unit em, y down, baseline y = 0
(the shared fonts carry only multiples of 10). The `.ttf` uses `unitsPerEm` 2048, so a font unit
is 10 SWF units and `ttf_x = x / 10`, `ttf_y = -y / 10` (rounded half away from zero).

Glyph outlines map to `glyf` directly: an `M` / `L` end point is an on-curve point, a `Q` control
point an off-curve point. A subpath whose last point equals its first drops the repeated point
(TrueType contours close implicitly); a subpath without edges is dropped. Contours are oriented
for the non-zero rule: each contour's nesting depth (how many other contours of the glyph contain
it) decides the direction, even depth clockwise (filled), odd depth counter-clockwise (hole). The
SWF fill side is not consulted; that matches even-odd filling of non-intersecting contours.

Tables: `cmap` (format 4 under platform 3/1 and 0/3), `glyf`/`loca` (long offsets), `hmtx` from
the layout advances (left side bearing = glyph xMin), `kern` (version 0, one format-0 subtable)
from the layout kerning pairs, `head`, `hhea` (ascender / descender / line gap from the layout
block), `maxp` 1.0, `OS/2` version 4, `name` (Windows, en-US), `post` 3.0 (no glyph names).
Glyph 0 is an empty `.notdef`. No hinting instructions. Gate: `Tests/corpus_ttf.py`.
"""

from __future__ import annotations

import struct

UNITS_PER_EM = 2048
SCALE = 20480 // UNITS_PER_EM  # SWF DefineFont3 units per font unit
STAMP = 3338236800  # head created/modified: 2009-10-13 00:00 UTC (seconds since 1904), fixed for reproducible files


def _r(v: float) -> int:
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def to_units(x: int, y: int) -> tuple[int, int]:
    """SWF glyph point (em 20480, y down) -> TrueType point (em 2048, y up)."""
    return _r(x / SCALE), _r(-y / SCALE)


def _area(pts) -> float:
    """Shoelace area in TrueType space (positive = counter-clockwise, y up)."""
    s = 0.0
    for i, (x0, y0, _) in enumerate(pts):
        x1, y1, _ = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return s / 2


def _inside(px: float, py: float, poly) -> bool:
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def contours(subpaths: list[list]) -> list[list[tuple[int, int, bool]]]:
    """SWF subpaths -> TrueType contours [(x, y, on_curve)], oriented for the non-zero rule."""
    raw = []
    for sp in subpaths:
        if len(sp) < 2:
            continue
        pts = []
        for op in sp:
            if op[0] == "Q":
                pts.append((*to_units(op[1], op[2]), False))
            pts.append((*to_units(op[-2], op[-1]), True))
        if len(pts) > 1 and pts[-1] == pts[0]:
            pts.pop()
        if len(pts) >= 2:
            raw.append(pts)
    out = []
    for i, c in enumerate(raw):
        # depth: contours containing a probe point of c (an on-curve point not on the other contour)
        depth = 0
        for j, o in enumerate(raw):
            if i == j:
                continue
            on = [p for p in c if p[2]] or c
            probe = next((p for p in on if (p[0], p[1]) not in {(q[0], q[1]) for q in o}), on[0])
            if _inside(probe[0] + 0.01, probe[1] + 0.013, o):
                depth += 1
        a = _area(c)
        clockwise = a < 0
        if clockwise != (depth % 2 == 0):
            c = [c[0]] + c[1:][::-1]
        out.append(c)
    return out


def _checksum(b: bytes) -> int:
    b += b"\0" * (-len(b) % 4)
    return sum(struct.unpack(f">{len(b) // 4}I", b)) & 0xFFFFFFFF


def _glyph(cs) -> tuple[bytes, tuple[int, int, int, int], int]:
    if not cs:
        return b"", (0, 0, 0, 0), 0
    pts = [p for c in cs for p in c]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    ends, n = [], 0
    for c in cs:
        n += len(c)
        ends.append(n - 1)
    flags, xb, yb = bytearray(), bytearray(), bytearray()
    px = py = 0
    for x, y, on in pts:
        f = 1 if on else 0
        dx, dy = x - px, y - py
        if dx == 0:
            f |= 0x10
        elif -255 <= dx <= 255:
            f |= 0x02 | (0x10 if dx > 0 else 0)
            xb.append(abs(dx))
        else:
            xb += struct.pack(">h", dx)
        if dy == 0:
            f |= 0x20
        elif -255 <= dy <= 255:
            f |= 0x04 | (0x20 if dy > 0 else 0)
            yb.append(abs(dy))
        else:
            yb += struct.pack(">h", dy)
        flags.append(f)
        px, py = x, y
    data = struct.pack(">h4h", len(cs), *bbox) + struct.pack(f">{len(ends)}H", *ends)
    data += struct.pack(">H", 0) + bytes(flags) + bytes(xb) + bytes(yb)
    data += b"\0" * (-len(data) % 4)
    return data, bbox, len(pts)


def _name_table(names: dict[int, str]) -> bytes:
    recs, strings = [], b""
    for nid in sorted(names):
        s = names[nid].encode("utf-16-be")
        recs.append(struct.pack(">6H", 3, 1, 0x409, nid, len(s), len(strings)))
        strings += s
    return struct.pack(">3H", 0, len(recs), 6 + 12 * len(recs)) + b"".join(recs) + strings


def _cmap(codes: dict[int, int]) -> bytes:
    keys = sorted(c for c in codes if c <= 0xFFFF and c != 0xFFFF)
    segs = []  # runs of consecutive codes with consecutive glyph ids
    for c in keys:
        if segs and c == segs[-1][1] + 1 and codes[c] - c == segs[-1][2]:
            segs[-1][1] = c
        else:
            segs.append([c, c, codes[c] - c])
    segs.append([0xFFFF, 0xFFFF, 1])
    n = len(segs)
    sr = 2 * (1 << (n.bit_length() - 1))
    es = (n.bit_length() - 1)
    body = struct.pack(">4H", 2 * n, sr, es, 2 * n - sr)
    body += struct.pack(f">{n}H", *(s[1] for s in segs)) + b"\0\0"
    body += struct.pack(f">{n}H", *(s[0] for s in segs))
    body += struct.pack(f">{n}H", *((s[2]) & 0xFFFF for s in segs))
    body += struct.pack(f">{n}H", *([0] * n))
    sub = struct.pack(">3H", 4, 6 + len(body), 0) + body
    return struct.pack(">2H", 0, 2) + struct.pack(">2HI", 0, 3, 20) + struct.pack(">2HI", 3, 1, 20) + sub


def build(font, family: str | None = None) -> bytes:
    """A complete .ttf for a `gfx.Font` with layout (advances and kerning)."""
    family = family or font.name
    chars = sorted(font.glyphs, key=ord)
    gid = {ch: i + 1 for i, ch in enumerate(chars)}
    glyphs = [(b"", (0, 0, 0, 0), 0, 0)]  # .notdef
    for ch in chars:
        cs = contours(font.glyphs[ch])
        data, bbox, npts = _glyph(cs)
        glyphs.append((data, bbox, npts, len(cs)))
    adv = [UNITS_PER_EM // 2] + [_r(font.advance.get(ch, 0) / SCALE) for ch in chars]
    ng = len(glyphs)

    glyf, loca = b"", []
    for g in glyphs:
        loca.append(len(glyf))
        glyf += g[0]
    loca.append(len(glyf))
    nonempty = [g[1] for g in glyphs if g[0]]
    xmin = min((b[0] for b in nonempty), default=0)
    ymin = min((b[1] for b in nonempty), default=0)
    xmax = max((b[2] for b in nonempty), default=0)
    ymax = max((b[3] for b in nonempty), default=0)
    lsb = [g[1][0] for g in glyphs]
    rsb = [a - (g[1][2] - g[1][0]) - g[1][0] for a, g in zip(adv, glyphs) if g[0]]
    ext = [g[1][0] + (g[1][2] - g[1][0]) for g in glyphs if g[0]]
    asc, desc, gap = _r(font.ascent / SCALE), _r(font.descent / SCALE), _r(font.leading / SCALE)
    style = ("Bold " if font.bold else "") + ("Italic" if font.italic else "")
    style = style.strip() or "Regular"
    mac_style = (1 if font.bold else 0) | (2 if font.italic else 0)

    t = {}
    t[b"glyf"] = glyf
    t[b"loca"] = struct.pack(f">{len(loca)}I", *loca)
    t[b"head"] = struct.pack(">HHiIIHHqqhhhhHHhhh", 1, 0, 0x10000, 0, 0x5F0F3CF5, 0x000B,
                             UNITS_PER_EM, STAMP, STAMP, xmin, ymin, xmax, ymax, mac_style, 8, 2, 1, 0)
    t[b"hhea"] = struct.pack(">HHhhhHhhhhhhhhhhhH", 1, 0, asc, -desc, gap, max(adv),
                             min((g[1][0] for g in glyphs if g[0]), default=0),
                             min(rsb, default=0), max(ext, default=0), 1, 0, 0, 0, 0, 0, 0, 0, ng)
    t[b"maxp"] = struct.pack(">I14H", 0x10000, ng, max(g[2] for g in glyphs), max(g[3] for g in glyphs),
                             0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0)
    t[b"hmtx"] = b"".join(struct.pack(">Hh", a, l) for a, l in zip(adv, lsb))
    t[b"cmap"] = _cmap({ord(ch): gid[ch] for ch in chars})
    pairs = sorted((gid[a], gid[b], _r(k / SCALE)) for (a, b), k in font.kerning.items()
                   if a in gid and b in gid)
    if pairs:
        n = len(pairs)
        sr = 6 * (1 << (n.bit_length() - 1))
        sub = struct.pack(">4H", n, sr, n.bit_length() - 1, 6 * n - sr)
        sub += b"".join(struct.pack(">HHh", *p) for p in pairs)
        t[b"kern"] = struct.pack(">2H", 0, 1) + struct.pack(">3H", 0, 6 + len(sub), 1) + sub
    t[b"post"] = struct.pack(">IihhIIIII", 0x30000, 0, -_r(desc / 2), max(1, _r(UNITS_PER_EM / 20)),
                             0, 0, 0, 0, 0)
    avg = _r(sum(a for a, g in zip(adv, glyphs) if g[0]) / max(1, len(nonempty)))
    codes = [ord(c) for c in chars]
    fs_sel = (0x20 if font.bold else 0) | (0x01 if font.italic else 0) or 0x40
    t[b"OS/2"] = struct.pack(
        ">HhHHHhhhhhhhhhhh10s4I4sHHHhhhHHII hhHHH".replace(" ", ""),
        4, avg, 700 if font.bold else 400, 5, 0,
        UNITS_PER_EM * 13 // 20, UNITS_PER_EM * 12 // 20, 0, UNITS_PER_EM * 3 // 40,
        UNITS_PER_EM * 13 // 20, UNITS_PER_EM * 12 // 20, 0, UNITS_PER_EM * 7 // 20,
        max(1, UNITS_PER_EM // 20), UNITS_PER_EM * 5 // 20, 0,
        b"\0" * 10, 3, 0, 0, 0, b"NONE", fs_sel | 0x80, min(codes), min(max(codes), 0xFFFF),
        asc, -desc, gap, max(asc, ymax), max(desc, -ymin), 1, 0,
        0, 0, 0, 32, 0)
    ps = "".join(c for c in f"{family}-{style}" if 33 <= ord(c) < 127 and c not in "[](){}<>/%")
    t[b"name"] = _name_table({1: family, 2: style, 3: f"{family} {style} (Brutal Legend gfx)",
                              4: family if style == "Regular" else f"{family} {style}",
                              5: "Version 1.000", 6: ps})

    tags = sorted(t)
    n = len(tags)
    sr = 16 * (1 << (n.bit_length() - 1))
    head = struct.pack(">IHHHH", 0x10000, n, sr, n.bit_length() - 1, 16 * n - sr)
    off = 12 + 16 * n
    dirs, body = b"", b""
    for tag in tags:
        d = t[tag]
        dirs += struct.pack(">4sIII", tag, _checksum(d), off + len(body), len(d))
        body += d + b"\0" * (-len(d) % 4)
    out = bytearray(head + dirs + body)
    adj = (0xB1B0AFBA - _checksum(bytes(out))) & 0xFFFFFFFF
    hoff = off + sum(len(t[x]) + (-len(t[x]) % 4) for x in tags[:tags.index(b"head")])
    struct.pack_into(">I", out, hoff + 8, adj)
    return bytes(out)
