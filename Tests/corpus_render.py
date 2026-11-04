"""Corpus gate for the movie renderer (`Blender/BrutalLegend/Brutal/gfxsvg.py`) and the pixel helpers (`Blender/BrutalLegend/Brutal/image.py`).

- every character and control tag of every movie, root and nested sprites, decodes to exactly its
  tag length: DefineShape/2/3/4, DefineMorphShape/2, DefineEditText, PlaceObject2/3 (up to clip
  actions); every fill style's edges of every shape (and morph at ratio 0 and 65535) join into
  closed contours;
- every movie renders frame 0 and every root frame label without exception and without an
  unresolved reference: every placed character id, bitmap fill id (imports included), font and
  external image Texture resolves; the SVG is well-formed XML and every `url(#..)` / `href="#.."`
  names an element of the document;
- one movie (Pause) renders with embedded images: every data URI is a PNG whose IHDR size is the
  `<image>` size;
- BC1/BC3 decoding is bit-exact on synthetic blocks (4-colour, 3-colour + transparent, 8- and
  6-level alpha); the PNG writer re-reads (signature, chunk CRCs, IHDR, inflated rows = input);
  with ImageMagick (`magick`) on PATH, a sample of UI textures decodes within 2 levels of it.
"""
import base64
import collections
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Blender", "BrutalLegend"))
from Brutal import gfx, gfxsvg, image, texture
from Brutal.library import Library

L = Library()
bad = collections.Counter()
ex = {}


def fail(k, name):
    bad[k] += 1
    ex.setdefault(k, name)


# ---------------------------------------------------------------- tag decoding over the corpus

movies = sorted(e.name for b, e in L.entries("Blob") if e.name.endswith(".gfx"))
decoded = collections.Counter()
contours = open_contours = 0
facts = collections.Counter()
for mv in movies:
    m = gfx.parse(L.read(mv + ".Blob"))
    dic = gfx.dictionary(m)
    imported = {cid for _, names in gfx.imports(m) for cid in names.values()}
    tags = list(m.tags)
    for t in m.tags:
        if t.code == 39:
            tags += gfx.sprite(t).tags
    for t in tags:
        try:
            if t.code in gfx.SHAPE_TAGS:
                s, n = gfx.shape(t)
                shapes = [s]
            elif t.code in (46, 84):
                ms, n = gfx.morph_shape(t)
                shapes = [gfx.morph_at(ms, 0), gfx.morph_at(ms, 65535)]
            elif t.code == 37:
                _, n = gfx.edit_text(t)
                shapes = []
            elif t.code in (26, 70):
                o, n = gfx.place(t)
                if o.clip_actions:
                    n = len(t.data)
                shapes = []
            else:
                continue
        except Exception as x:
            fail(f"{t.name} raises {type(x).__name__}: {x}", mv)
            continue
        decoded[t.name] += 1
        if t.code in (26, 70):
            facts.update(f"filter {gfx.FILTER_NAMES[f[0]]}" for f in o.filters or [])
            facts.update([f"blend {gfx.BLEND_MODES[o.blend]}"] if o.blend not in (None, 0, 1) else [])
            facts.update(["clip depth"] if o.clip_depth else [])
            facts.update(["clip actions"] if o.clip_actions else [])
        for s in shapes[:1] if t.code in gfx.SHAPE_TAGS else []:
            for fills, _, edges in s.groups:
                used = {i for e in edges for i in e[:2] if i}
                for i, f in enumerate(fills, 1):
                    facts[f"fill {f['type']}"] += 1
                    if f["type"] != "bitmap":
                        continue
                    d = dic.get(f["id"])
                    if d is not None and d.code == 1001:
                        facts["bitmap fill -> external image"] += 1
                    elif f["id"] in imported:
                        facts["bitmap fill -> imported image"] += 1
                    elif f["id"] == 0xFFFF and i not in used:
                        facts["bitmap fill 65535, never selected"] += 1
                    else:
                        fail("bitmap fill names no image", f"{mv} shape {s.id} bitmap {f['id']}")
        if n != len(t.data):
            fail(f"{t.name} decodes {n} of {len(t.data)} bytes", mv)
        for s in shapes:
            for _, _, cs in gfxsvg.Renderer._shape_fills(s.groups):
                contours += len(cs)
                open_contours += sum(1 for _, closed in cs if not closed)
if open_contours:
    fail(f"{open_contours} fill contours do not close", "")

# ---------------------------------------------------------------- rendering

REF = re.compile(r'url\(#([^)]+)\)|href="#([^"]+)"')


def check_svg(svg, name):
    try:
        ET.fromstring(svg)
    except ET.ParseError as x:
        fail(f"SVG not well-formed: {x}", name)
        return
    ids = set(re.findall(r' id="([^"]+)"', svg))
    for a, b in REF.findall(svg):
        if (a or b) not in ids:
            fail("SVG reference to a missing id", f"{name} #{a or b}")
            return


renders = 0
stats = collections.Counter()
for settle in (False, True):
    r = gfxsvg.Renderer(L, images="link", settle=settle)
    for mv in movies:
        labels = [None] + list(gfx.frame_labels(r.ctx(mv).movie.tags))
        for label in labels:
            name = f"{mv} [{label or 'frame 0'}{', settled' if settle else ''}]"
            try:
                svg = r.render(mv, label)
            except Exception as x:
                fail(f"render raises {type(x).__name__}: {str(x)[:60]}", name)
                continue
            renders += 1
            stats.update(r.stats)
            for p in r.problems:
                fail(re.sub(r"\d+", "N", p.split(": ", 1)[-1]), f"{name}: {p}")
            check_svg(svg, name)

# the shipped movies carry no clip layer (no PlaceObject with ClipDepth): a synthetic display list
# exercises the clipPath path (Pause shape 206 clips the edit text 207 placed above it)
pc = r.ctx("data/ui/pause/opt/pause.gfx")
r.reset()
clip = r.display_svg(pc, [gfx.Place(1, False, char=206, clip_depth=3), gfx.Place(2, False, char=207),
                          gfx.Place(4, False, char=207)])
clip_ok = re.fullmatch(r'<g clip-path="url\(#[^)]+\)"><use href="#[^"]+"/></g><use href="#[^"]+"/>', clip)
if not clip_ok or not any(d.startswith("<clipPath") and "<path " in d for d in r.defs):
    fail("synthetic clip layer", clip[:80])

re_ = gfxsvg.Renderer(L, images="embed")
svg = re_.render("pause")
check_svg(svg, "pause (embedded)")
pngs = 0
for w, h, uri in re.findall(r'<image id="[^"]+" width="(\d+)" height="(\d+)" preserveAspectRatio="none" '
                            r'href="data:image/png;base64,([^"]+)"', svg):
    d = base64.b64decode(uri)
    if d[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", d[16:24]) != (int(w), int(h)):
        fail("embedded PNG header / size", "pause")
    pngs += 1
if not pngs:
    fail("no embedded image in Pause", "pause")

# ---------------------------------------------------------------- BC1 / BC3 and PNG


def c565(r5, g6, b5):
    return (r5 << 11) | (g6 << 5) | b5


def expand(c):
    r5, g6, b5 = c >> 11, (c >> 5) & 63, c & 31  # bit replication
    return r5 << 3 | r5 >> 2, g6 << 2 | g6 >> 4, b5 << 3 | b5 >> 2


def synthetic():
    out = []
    for c0, c1, four in ((c565(31, 0, 0), c565(0, 0, 31), False), (c565(0, 0, 31), c565(31, 0, 0), False),
                         (c565(3, 40, 9), c565(17, 2, 30), False), (c565(0, 0, 31), c565(31, 0, 0), True)):
        a, b = expand(c0), expand(c1)
        if four or c0 > c1:
            pal = [a + (255,), b + (255,), tuple((2 * x + y + 1) // 3 for x, y in zip(a, b)) + (255,),
                   tuple((x + 2 * y + 1) // 3 for x, y in zip(a, b)) + (255,)]
        else:
            pal = [a + (255,), b + (255,), tuple((x + y + 1) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]
        idx = 0x1B4EE41B
        rows = image.color_block(struct.pack("<HHI", c0, c1, idx), four)
        want = [b"".join(bytes(pal[(idx >> (2 * (4 * r + i))) & 3]) for i in range(4)) for r in range(4)]
        out.append(rows == want)
    for a0, a1 in ((255, 0), (0, 255), (200, 13)):
        if a0 > a1:
            pal = [a0, a1] + [((7 - k) * a0 + k * a1 + 3) // 7 for k in range(1, 7)]
        else:
            pal = [a0, a1] + [((5 - k) * a0 + k * a1 + 2) // 5 for k in range(1, 5)] + [0, 255]
        bits = sum(((i * 5) % 8) << (3 * i) for i in range(16))
        rows = image.alpha_block(bytes((a0, a1)) + bits.to_bytes(6, "little"))
        want = [bytes(pal[(bits >> (3 * (4 * r + i))) & 7] for i in range(4)) for r in range(4)]
        out.append(rows == want)
    return out


if not all(synthetic()):
    fail("BC1/BC3 synthetic blocks", str(synthetic()))


def png_read(d):
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("signature")
    p, idat, ihdr = 8, b"", None
    while p < len(d):
        n = struct.unpack_from(">I", d, p)[0]
        t, body = d[p + 4:p + 8], d[p + 8:p + 8 + n]
        if struct.unpack_from(">I", d, p + 8 + n)[0] != zlib.crc32(t + body) & 0xFFFFFFFF:
            raise ValueError(f"crc {t}")
        if t == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif t == b"IDAT":
            idat += body
        p += 12 + n
    w, h = ihdr[:2]
    raw = zlib.decompress(idat)
    return w, h, b"".join(raw[y * (4 * w + 1) + 1:(y + 1) * (4 * w + 1)] for y in range(h))


tex = sorted(e.path for b, e in L.entries("Texture") if e.path.startswith("ui/flash/"))
sample = tex[::64] + ["ui/flash/map/worldmap1.Texture"]
magick = shutil.which("magick")
maxdiff, checked = 0, 0
tmp = tempfile.mkdtemp()
for t in sample:
    dds = texture.dds(L.read(t))
    w, h, px = image.dds_rgba(dds)
    if png_read(image.png(w, h, px)) != (w, h, px):
        fail("PNG does not re-read to its pixels", t)
    if magick:
        f = os.path.join(tmp, "t.dds")
        open(f, "wb").write(dds)
        ref = subprocess.run([magick, f, "-depth", "8", "rgba:-"], capture_output=True).stdout
        if len(ref) != len(px):
            fail("magick output size differs", t)
            continue
        maxdiff = max(maxdiff, max(abs(a - b) for a, b in zip(px[::7], ref[::7])))
        checked += 1
shutil.rmtree(tmp, ignore_errors=True)
if maxdiff > 2:
    fail(f"BC decode differs from ImageMagick by {maxdiff}", "")

print("decoded: " + ", ".join(f"{n} {k}" for k, n in sorted(decoded.items())))
print(f"fill contours closed {contours - open_contours}/{contours}")
print("corpus: " + ", ".join(f"{k} {n}" for k, n in sorted(facts.items())))
print(f"renders {renders} (frame 0 of {len(movies)} movies + every root label; sprites at frame 0, then settled), "
      f"{stats['placements']} placements, {stats['shapes']} shapes, {stats['sprites']} sprites, "
      f"{stats['text fields']} text fields ({stats['glyphs drawn']} glyphs), {stats['bitmap fills']} bitmap fills "
      f"({stats['imported bitmaps']} imported), {stats['clip layers']} clip layers in the corpus (synthetic clip layer ok)")
print("not rendered: " + (", ".join(f"{k.split('(', 1)[1][:-1]} x{n}" for k, n in sorted(stats.items())
                                     if k.startswith(("filters not", "blend modes not"))) or "none met"))
print(f"pause embedded {pngs} PNG images; BC1/BC3 synthetic ok; "
      + (f"ImageMagick agreement on {checked} textures, max diff {maxdiff}" if magick else "magick not on PATH, skipped"))
for k, n in bad.most_common(15):
    print(f"  {n:5} {k}  e.g. {ex[k]}")
print("ALL RENDER GATES PASS" if not bad else "RENDER GATE FAILS")
sys.exit(1 if bad else 0)
