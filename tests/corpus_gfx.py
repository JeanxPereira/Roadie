"""Corpus gate for the UI movies (`brutal/gfx.py`).

- every `.gfx` Blob in the bundles parses; its tag stream ends with End exactly at the header length
  and the bundle copy is byte-identical to `Data/UI/.../Opt/*.gfx` on disk;
- every DUIMovie names an existing movie, and every DefineExternalImage of that movie resolves to a
  Texture the DUIMovie lists, by the lower-cased stem of its file name (`SD_guide.dds`,
  `Chapters_I12.dds`), whose size is the image's rounded up to the 4-pixel DXT block;
- the shared font movie named by FlashConfig decodes its DefineFont3 glyphs and every FontMap
  target (`$Menu` -> TG_Menu ...) is one of its fonts.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brutal import gfx, paths, texture, textobj
from brutal.library import Library

L = Library()
bad = collections.Counter()
ex = {}


def fail(k, name):
    bad[k] += 1
    ex.setdefault(k, name)


movies = {}
for b, e in L.entries("Blob"):
    if not e.name.endswith(".gfx"):
        continue
    d = b.read(e)
    try:
        m = gfx.parse(d)
        if m.end != m.length or m.tags[-1].code != 0:
            fail("tag stream does not end at header length", e.name)
        disk = os.path.join(paths.game_dir(), e.name)
        if not os.path.exists(disk):
            disk = next((os.path.join(r, f) for r, _, fs in os.walk(os.path.join(paths.game_dir(), "Data"))
                         for f in fs if os.path.join(r, f).lower().replace("\\", "/").endswith(e.name)), None)
        if disk is None or open(disk, "rb").read() != d:
            fail("bundle copy differs from disk", e.name)
        movies[e.name] = m
    except Exception as x:
        fail(f"{type(x).__name__}: {str(x)[:60]}", e.name)

tags = collections.Counter(t.code for m in movies.values() for t in m.tags)
images = resolved = 0
for b, e in L.entries("DUIMovie"):
    o = textobj.parse(b.read(e))
    m = movies.get(o["FlashFile"].lower())
    if m is None:
        fail("DUIMovie names a missing movie", e.name)
        continue
    listed = {t.rsplit("/", 1)[-1].lower(): t for t in o["Textures"]}
    for im in gfx.external_images(m):
        images += 1
        t = listed.get(im.file_name.rsplit(".", 1)[0].lower())
        if t is None or f"{t}.Texture" not in L:
            fail("external image not resolved", f"{e.name} #{im.id} {im.export_name}")
            continue
        info = texture.info(L.read(f"{t}.Texture"))
        if (info["width"], info["height"]) != ((im.width + 3) & ~3, (im.height + 3) & ~3):
            fail("external image size differs from texture", f"{t} {im.width}x{im.height}")
            continue
        resolved += 1

cfg = textobj.parse(next(b.read(e) for b, e in L.entries("FlashConfig")))
glyphs = 0
for fm in cfg["FontMapping"]:
    fm_movie = movies.get(fm["SharedFontFile"].lower())
    fonts = {f.name: f for f in gfx.fonts(fm_movie)} if fm_movie else {}
    glyphs += sum(len(f.glyphs) for f in fonts.values())
    for alias, target in ((k, v) for k, v in fm["FontMap"].items() if not k.startswith("_")):
        if target[0] not in fonts:
            fail("FontMap target not in the shared font movie", f"{alias} -> {target[0]}")

print(f"movies {len(movies)} parse, {sum(tags.values())} tags in {len(tags)} kinds")
print(f"external images resolved {resolved}/{images}; shared fonts: {glyphs} glyphs")
for k, n in bad.most_common(15):
    print(f"  {n:5} {k}  e.g. {ex[k]}")
print("ALL GFX GATES PASS" if not bad else "GFX GATE FAILS")
sys.exit(1 if bad else 0)
