"""Corpus gate for the TrueType export (`Blender/BrutalLegend/Brutal/ttf.py`).

Every DefineFont3 of the shared font movie named by FlashConfig (Schreibweise, TG_Menu,
TG_Condensed) is exported and re-read by an independent strict parser:

- table directory: sorted tags, 4-aligned offsets inside the file, every table checksum, whole-file
  checksum 0xB1B0AFBA (head.checkSumAdjustment), head magic;
- maxp.numGlyphs = hhea.numberOfHMetrics = loca entries - 1; loca monotonic, last = len(glyf);
  maxp maxPoints / maxContours equal the true maxima;
- cmap format 4 maps exactly the font's characters, each to a glyph whose outline round-trips:
  same contour count, and every contour equals the source subpath (points / 10, y flipped, rounded,
  closing point dropped) as a cyclic sequence, forward or reversed, with the same on/off-curve flags;
- every glyph's stored bbox is the bbox of its points; head bbox is the union;
- hmtx advance = layout advance / 10, lsb = xMin; kern format 0 holds exactly the layout pairs
  whose two characters are in the font, sorted, value / 10;
- contour direction: under the non-zero rule each contour's winding sum equals its parity
  (filled outer, holes cut) — checked by the signed area of each contour against its nesting;
- when fontTools is installed, it also decompiles every table (extra validator only);
- the same checks run on every DefineFont3 with glyphs and layout embedded in the other movies.
"""
import collections
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Blender", "BrutalLegend"))
from Brutal import gfx, textobj, ttf
from Brutal.library import Library

L = Library()
cfg = textobj.parse(next(b.read(e) for b, e in L.entries("FlashConfig")))
movie = gfx.parse(L.read(cfg["FontMapping"][0]["SharedFontFile"].lower() + ".Blob"))
fonts = gfx.fonts(movie)
problems = []


def bad(font, msg):
    problems.append(f"{font}: {msg}")


def r(v):
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def expected(subpaths):
    out = []
    for sp in subpaths:
        if len(sp) < 2:
            continue
        pts = []
        for op in sp:
            if op[0] == "Q":
                pts.append((r(op[1] / 10), r(-op[2] / 10), False))
            pts.append((r(op[-2] / 10), r(-op[-1] / 10), True))
        if pts[-1] == pts[0]:
            pts.pop()
        out.append(pts)
    return out


def cyc_eq(a, b):
    if len(a) != len(b):
        return False
    n = len(a)
    for seq in (b, [b[0]] + b[1:][::-1]):
        for s in range(n):
            if all(a[i] == seq[(i + s) % n] for i in range(n)):
                return True
    return False


def checksum(b):
    b += b"\0" * (-len(b) % 4)
    return sum(struct.unpack(f">{len(b) // 4}I", b)) & 0xFFFFFFFF


def parse_glyph(g):
    if not g:
        return [], None
    nc, *bbox = struct.unpack_from(">h4h", g)
    ends = struct.unpack_from(f">{nc}H", g, 10)
    p = 10 + 2 * nc
    ilen = struct.unpack_from(">H", g, p)[0]
    p += 2 + ilen
    n = ends[-1] + 1
    flags = []
    while len(flags) < n:
        f = g[p]
        p += 1
        flags.append(f)
        if f & 8:
            flags += [f] * g[p]
            p += 1
    coords = []
    for short, same in ((2, 0x10), (4, 0x20)):
        v, vals = 0, []
        for f in flags:
            if f & short:
                d = g[p]
                p += 1
                v += d if f & same else -d
            elif not f & same:
                v += struct.unpack_from(">h", g, p)[0]
                p += 2
            vals.append(v)
        coords.append(vals)
    pts = [(x, y, bool(f & 1)) for x, y, f in zip(coords[0], coords[1], flags)]
    cs, s = [], 0
    for e in ends:
        cs.append(pts[s:e + 1])
        s = e + 1
    return cs, tuple(bbox)


def area(c):
    return sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1] for i in range(len(c))) / 2


def inside(px, py, poly):
    c, j = False, len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i][:2], poly[j][:2]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def check(font, data):
    name = font.name
    ver, n = struct.unpack_from(">IH", data)
    if ver != 0x10000:
        bad(name, "sfnt version")
    tables, prev = {}, b""
    for i in range(n):
        tag, cs, off, ln = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag <= prev or off % 4 or off + ln > len(data):
            bad(name, f"directory entry {tag}")
        prev = tag
        body = data[off:off + ln]
        if tag == b"head":
            body = body[:8] + b"\0\0\0\0" + body[12:]
        if checksum(body) != cs:
            bad(name, f"checksum {tag}")
        tables[tag] = data[off:off + ln]
    if checksum(data) != 0xB1B0AFBA:
        bad(name, "whole-file checksum")
    head = struct.unpack(">HHiIIHHqqhhhhHHhhh", tables[b"head"])
    if head[4] != 0x5F0F3CF5 or head[6] != 2048 or head[16] != 1:
        bad(name, "head magic / unitsPerEm / loca format")
    ng = struct.unpack_from(">H", tables[b"maxp"], 4)[0]
    maxpts, maxcont = struct.unpack_from(">HH", tables[b"maxp"], 6)
    hhea = struct.unpack(">HHhhhHhhhhhhhhhhhH", tables[b"hhea"])
    if hhea[-1] != ng:
        bad(name, "numberOfHMetrics != numGlyphs")
    if (hhea[2], hhea[3], hhea[4]) != (r(font.ascent / 10), -r(font.descent / 10), r(font.leading / 10)):
        bad(name, "hhea metrics")
    loca = struct.unpack(f">{len(tables[b'loca']) // 4}I", tables[b"loca"])
    if len(loca) != ng + 1 or any(b < a for a, b in zip(loca, loca[1:])) or loca[-1] != len(tables[b"glyf"]):
        bad(name, "loca")
    glyphs = [parse_glyph(tables[b"glyf"][loca[i]:loca[i + 1]]) for i in range(ng)]
    if max(sum(len(c) for c in g[0]) for g in glyphs) != maxpts or max(len(g[0]) for g in glyphs) != maxcont:
        bad(name, "maxp maxima")
    allp = [p for g in glyphs for c in g[0] for p in c]
    if head[9:13] != (min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp)):
        bad(name, "head bbox")
    # cmap format 4 (platform 3/1)
    cm = tables[b"cmap"]
    nsub = struct.unpack_from(">H", cm, 2)[0]
    off = next(o for i in range(nsub) for (pl, en, o) in [struct.unpack_from(">HHI", cm, 4 + 8 * i)] if (pl, en) == (3, 1))
    fmt, _, _, sx2 = struct.unpack_from(">4H", cm, off)
    segs = sx2 // 2
    p = off + 14
    ends = struct.unpack_from(f">{segs}H", cm, p)
    starts = struct.unpack_from(f">{segs}H", cm, p + sx2 + 2)
    deltas = struct.unpack_from(f">{segs}h", cm, p + 2 * sx2 + 2)
    ros = struct.unpack_from(f">{segs}H", cm, p + 3 * sx2 + 2)
    cmap = {}
    for s, e, dl, ro in zip(starts, ends, deltas, ros):
        if ro:
            bad(name, "idRangeOffset used")
        for c in range(s, e + 1):
            if c != 0xFFFF:
                cmap[c] = (c + dl) & 0xFFFF
    if fmt != 4 or set(cmap) != {ord(c) for c in font.glyphs}:
        bad(name, "cmap covers a different character set")
    hm = [struct.unpack_from(">Hh", tables[b"hmtx"], 4 * i) for i in range(ng)]
    gchar = {}
    for ch, sp in font.glyphs.items():
        g = cmap.get(ord(ch))
        if g is None:
            continue
        gchar[g] = ch
        cs, bbox = glyphs[g]
        exp = expected(sp)
        if len(cs) != len(exp):
            bad(name, f"U+{ord(ch):04X} contour count {len(cs)} vs {len(exp)}")
            continue
        left = list(exp)
        for c in cs:
            hit = next((i for i, e in enumerate(left) if cyc_eq(e, c)), None)
            if hit is None:
                bad(name, f"U+{ord(ch):04X} contour does not round-trip")
                break
            left.pop(hit)
        pts = [p for c in cs for p in c]
        if pts and bbox != (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)):
            bad(name, f"U+{ord(ch):04X} glyph bbox")
        if hm[g] != (r(font.advance[ch] / 10), bbox[0] if pts else 0):
            bad(name, f"U+{ord(ch):04X} hmtx")
        for c in cs:  # non-zero rule: clockwise (negative area, y up) exactly at even nesting depth
            probe = next((q for q in c if q[2]), c[0])
            depth = sum(inside(probe[0] + 0.01, probe[1] + 0.013, o) for o in cs if o is not c)
            if (area(c) < 0) != (depth % 2 == 0):
                bad(name, f"U+{ord(ch):04X} contour direction")
    kern = tables.get(b"kern", b"")
    pairs = {}
    if kern:
        npairs = struct.unpack_from(">H", kern, 10)[0]
        raw = [struct.unpack_from(">HHh", kern, 18 + 6 * i) for i in range(npairs)]
        if raw != sorted(raw):
            bad(name, "kern pairs not sorted")
        pairs = {(gchar[a], gchar[b]): v for a, b, v in raw}
    want = {k: r(v / 10) for k, v in font.kerning.items() if k[0] in font.glyphs and k[1] in font.glyphs}
    if pairs != want:
        bad(name, "kern pairs differ from layout")
    return ng, len(pairs), len(font.kerning) - len(want)


try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

names = []
for f in fonts:
    d = ttf.build(f)
    ng, nk, dropped = check(f, d)
    names.append(f.name)
    print(f"{f.name:14} {len(d):7} bytes  {ng} glyphs  {nk} kern pairs ({dropped} pairs name a character the font lacks)")
    if TTFont:
        t = TTFont(io.BytesIO(d))
        for tag in t.keys():
            t[tag]
        t.save(io.BytesIO())
if sorted(names) != ["Schreibweise", "TG_Condensed", "TG_Menu"]:
    problems.append(f"shared fonts are {names}")

# the fonts embedded in single movies (DefineFont3 with glyphs and layout) take the same checks
embedded = collections.Counter()
for b, e in L.entries("Blob"):
    if e.name.endswith(".gfx") and not e.name.endswith("englishfonts.gfx"):
        for f in gfx.fonts(gfx.parse(b.read(e))):
            if f.glyphs and f.advance:
                d = ttf.build(f)
                check(f, d)
                if TTFont:
                    TTFont(io.BytesIO(d))["glyf"]
                embedded[f.name] += 1
print("embedded fonts: " + ", ".join(f"{k} x{n}" for k, n in sorted(embedded.items())))
print("fontTools cross-check:", "done" if TTFont else "not installed, skipped")
for p in problems[:15]:
    print("  ", p)
print("ALL TTF GATES PASS" if not problems else f"TTF GATE FAILS ({len(problems)})")
sys.exit(1 if problems else 0)
