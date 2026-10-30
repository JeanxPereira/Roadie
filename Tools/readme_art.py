"""README art, generated from the game install (needs Pillow): the banner and section headers set
in the game's own UI fonts (glyph outlines from `Data/UI/Fonts/Opt/EnglishFonts.gfx`, drawn as SVG
paths) and the faction emblems from the front-end movie's textures, used as alpha masks.

    python Tools/readme_art.py      writes Docs/Images/banner.svg, pipeline.svg, progress.svg and h-*.svg

These few files are the one exception to "extracted data stays out of git" (CLAUDE.md rule 4):
fan use of Double Fine's lettering and emblems for this README, regenerated, never hand-edited.
"""
import base64
import io
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from Brutal import gfx, paths, texture  # noqa: E402
from Brutal.library import Library  # noqa: E402

OUT = os.path.join(ROOT, "Docs", "Images")
# Palette: stage black, bone, blood, ember, steel.
BLACK, PLATE, BONE, BLOOD, EMBER, STEEL = "#0b0a0a", "#141212", "#e9dcc0", "#b3261e", "#e0731c", "#8d8a86"

HEADERS = {
    "name": "The name",
    "how": "How a piece is made",
    "progress": "Progress",
    "build": "Build",
    "use": "Use",
    "ui": "The UI",
    "where": "Where to look",
}


def fonts():
    with open(os.path.join(paths.game_dir(), "Data", "UI", "Fonts", "Opt", "EnglishFonts.gfx"), "rb") as f:
        return {ft.name: ft for ft in gfx.fonts(gfx.parse(f.read()))}


def emblem(lib, name, size):
    """A front-end texture as a PNG data URI, to be used as an SVG luminance mask."""
    im = Image.open(io.BytesIO(texture.dds(lib.read(f"ui/flash/frontend/{name}.Texture")))).convert("RGBA")
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    # Luminance x alpha as a grey mask: keeps the drawing inside a silhouette (the horns' fingers).
    from PIL import ImageChops
    a = ImageChops.multiply(im.convert("L"), im.getchannel("A"))
    mask = Image.merge("RGBA", (a, a, a, a))
    buf = io.BytesIO()
    mask.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), im.size


def write(name, svg):
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    print(f"{name}: {len(svg) // 1024} KB")


def banner(f, lib):
    W, H = 1280, 400
    title, tw, _ = gfx.text_svg(f["Schreibweise"], "Roadie", 150)
    words = ["MODELS", "RIGS", "MATERIALS", "ANIMATION", "LIGHT", "UI"]
    sets = [gfx.text_svg(f["TG_Condensed"], w, 30) for w in words]
    gap = 46
    x = (W - sum(w for _, w, _ in sets) - gap * (len(sets) - 1)) / 2
    sub = []
    for k, (d, w, _) in enumerate(sets):
        sub.append(f'<path transform="translate({x:.1f},240)" d="{d}" fill="{BLOOD}"/>')
        x += w
        if k < len(sets) - 1:
            sub.append(f'<path d="M{x + gap / 2:.1f} 251l5 5-5 5-5-5z" fill="{EMBER}"/>')
            x += gap
    line, lw, _ = gfx.text_svg(f["TG_Menu"], "out of Brütal Legend, into Blender 5.2", 24)
    emb = []
    for i, (n, cx) in enumerate(zip(("faction-a", "faction-b", "faction-d"), (W / 2 - 120, W / 2, W / 2 + 120))):
        uri, (w, h) = emblem(lib, n, 96)
        s = 60 / max(w, h)
        emb.append(f'<mask id="m{i}"><image href="{uri}" x="{cx - w * s / 2:.1f}" y="{350 - h * s / 2:.1f}" '
                   f'width="{w * s:.1f}" height="{h * s:.1f}"/></mask>'
                   f'<rect width="{W}" height="{H}" fill="{STEEL}" mask="url(#m{i})"/>')
    horns, (hw, hh) = emblem(lib, "horns", 160)
    hs = 250 / max(hw, hh)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Roadie: models, rigs, materials, animation, light and UI out of Brütal Legend, into Blender 5.2">
<defs>
<clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>
<radialGradient id="glow" cx="50%" cy="100%" r="70%"><stop offset="0" stop-color="{BLOOD}" stop-opacity=".55"/><stop offset="1" stop-color="{BLACK}" stop-opacity="0"/></radialGradient>
<linearGradient id="bone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff6e0"/><stop offset=".55" stop-color="{BONE}"/><stop offset="1" stop-color="#9c8f74"/></linearGradient>
<mask id="horns"><image href="{horns}" x="{W - 70 - hw * hs:.1f}" y="{(H - hh * hs) / 2:.1f}" width="{hw * hs:.1f}" height="{hh * hs:.1f}"/></mask>
<mask id="horns2"><image href="{horns}" transform="translate({W},0) scale(-1,1)" x="{W - 70 - hw * hs:.1f}" y="{(H - hh * hs) / 2:.1f}" width="{hw * hs:.1f}" height="{hh * hs:.1f}"/></mask>
</defs>
<g clip-path="url(#card)">
<rect width="{W}" height="{H}" fill="{BLACK}"/>
<rect width="{W}" height="{H}" fill="url(#glow)"/>
<rect width="{W}" height="{H}" fill="#1d1918" mask="url(#horns)"/>
<rect width="{W}" height="{H}" fill="#1d1918" mask="url(#horns2)"/>
<rect width="{W}" height="6" fill="{BLOOD}"/>
<path transform="translate({(W - tw) / 2:.1f},18)" d="{title}" fill="url(#bone)" stroke="{BLACK}" stroke-width="2"/>
{''.join(sub)}
<path transform="translate({(W - lw) / 2:.1f},284)" d="{line}" fill="{BONE}" opacity=".8"/>
{''.join(emb)}
</g>
</svg>
'''


def header(f, text):
    W, H = 1280, 64
    d, w, h = gfx.text_svg(f["TG_Menu"], text.upper(), 34)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{text}">
<rect width="{W}" height="{H}" rx="8" fill="{BLACK}"/>
<rect x="0" y="0" width="8" height="{H}" rx="4" fill="{BLOOD}"/>
<path transform="translate(32,{(H - h) / 2:.1f})" d="{d}" fill="{BONE}"/>
<rect x="{32 + w + 24:.1f}" y="{H / 2 - 1}" width="{W - 32 - w - 24 - 28:.1f}" height="2" fill="{BLOOD}" opacity=".6"/>
<path d="M{W - 28} {H / 2 - 7}l7 7-7 7-7-7z" fill="{EMBER}"/>
</svg>
'''


# Resource support, as Docs/assets.md states it (done = decoder + corpus gate).
PROGRESS = [
    ("done", ["DFPF bundles", "Mesh", "Rig", "Texture", "Material", "AnimResource", "Shaders", "Weather",
              "RSA light", "Text objects", "UI movies", "UI fonts"]),
    ("parse", ["MeshSet", "Outfit", "Stance", "LevelData", "TerrainMaterial", "Cutscene", "Climate",
               "StringTable"]),
    ("todo", ["Heightfield", "ObjectData", "Prototype", "CollisionShape", "Particles", "CameraPath",
              "Havok bodies", "Lua scripts"]),
]


def progress(f):
    W, cols, tw, th, gx, gy = 1280, 6, 196, 46, 12, 12
    style = {"done": (BLOOD, BLOOD, BONE), "parse": (PLATE, EMBER, BONE), "todo": (PLATE, "#2a2523", STEEL)}
    out, y = [], 28
    for state, names in PROGRESS:
        lab, lw, lh = gfx.text_svg(f["TG_Menu"], {"done": "DECODED + GATED", "parse": "PARSED",
                                                    "todo": "NOT YET"}[state], 18)
        out.append(f'<path transform="translate(28,{y})" d="{lab}" fill="{style[state][1] if state != "todo" else STEEL}"/>')
        y += lh + 10
        for i, n in enumerate(names):
            x, yy = 28 + (i % cols) * (tw + gx), y + (i // cols) * (th + gy)
            fill, stroke, ink = style[state]
            d, w, h = gfx.text_svg(f["TG_Condensed"], n.upper(), 21)
            out.append(f'<rect x="{x}" y="{yy}" width="{tw}" height="{th}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
                       f'<path transform="translate({x + (tw - w) / 2:.1f},{yy + (th - h) / 2:.1f})" d="{d}" fill="{ink}"/>')
        y += ((len(names) + cols - 1) // cols) * (th + gy) + 18
    H = y + 6
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Resource support: '
            + "; ".join(f"{s}: {', '.join(n)}" for s, n in PROGRESS) + '">'
            f'<rect width="{W}" height="{H}" rx="14" fill="{BLACK}"/>' + "".join(out) + "</svg>\n")


# The pipeline figure: sources -> decoders -> what is built on them.
NODES = {  # key: (x, y, w, h, accent, title, lines)
    "packs": (40, 60, 300, 120, EMBER, "Win/Packs + Data/UI", ["20 DFPF bundles • 71,095 resources", "80 Scaleform movies"]),
    "exe": (40, 240, 300, 120, BLOOD, "BrutalLegend.exe", ["IDA 9.4 headless", "decomp • imm • vtable • rename"]),
    "brutal": (450, 120, 330, 180, BONE, "Brutal/  (stdlib)", ["dfpf • mesh • rig • texture", "material • anim • shaders",
                                                               "rsalight • textobj • gfx"]),
    "gates": (900, 20, 340, 100, BLOOD, "Corpus gates", ["check.py: the exit code is the verdict"]),
    "cli": (900, 150, 340, 100, STEEL, "python -m Brutal", ["types • ls • info • extract"]),
    "blender": (900, 280, 340, 120, EMBER, "Roadie for Blender 5.2", ["mesh • rig • game shading", "weather • animation"]),
}
EDGES = [("packs", "brutal"), ("exe", "brutal"), ("brutal", "gates"), ("brutal", "cli"), ("brutal", "blender")]


def pipeline(f):
    W, H = 1280, 420
    out = []
    for x, y, w, h, accent, title, lines in NODES.values():
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PLATE}" stroke="#2a2523" stroke-width="1.5"/>'
                   f'<rect x="{x}" y="{y}" width="{w}" height="6" rx="3" fill="{accent}"/>')
        d, tw, th = gfx.text_svg(f["TG_Menu"], title, 22)
        out.append(f'<path transform="translate({x + 20},{y + 20})" d="{d}" fill="{accent if accent != STEEL else BONE}"/>')
        yy = y + 20 + th + 10
        for ln in lines:
            d, lw, lh = gfx.text_svg(f["TG_Condensed"], ln, 20)
            out.append(f'<path transform="translate({x + 20},{yy:.1f})" d="{d}" fill="{STEEL}"/>')
            yy += lh + 4
    for a, b in EDGES:
        ax, ay, aw, ah = NODES[a][:4]
        bx, by, bw, bh = NODES[b][:4]
        x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx - 8, by + bh / 2
        if b == "brutal":
            y2 = by + bh * (0.33 if a == "packs" else 0.67)
        else:
            y1 = ay + ah * {"gates": 0.3, "cli": 0.5, "blender": 0.7}[b]
        mx = (x1 + x2) / 2
        out.append(f'<path d="M{x1} {y1:.1f}H{mx:.1f}V{y2:.1f}H{x2}" fill="none" stroke="{EMBER}" stroke-width="2" '
                   f'stroke-opacity=".75" marker-end="url(#arrow)"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Pipeline: game bundles and '
            f'the executable feed the Brutal/ decoders, which feed the corpus gates, the command line and the Blender extension">'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
            f'<path d="M0 0L10 5L0 10z" fill="{EMBER}"/></marker>'
            f'<radialGradient id="pglow" cx="50%" cy="50%" r="60%"><stop offset="0" stop-color="{BLOOD}" stop-opacity=".18"/>'
            f'<stop offset="1" stop-color="{BLACK}" stop-opacity="0"/></radialGradient></defs>'
            f'<rect width="{W}" height="{H}" rx="14" fill="{BLACK}"/><rect width="{W}" height="{H}" rx="14" fill="url(#pglow)"/>'
            + "".join(out) + "</svg>\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    f, lib = fonts(), Library()
    write("banner.svg", banner(f, lib))
    write("progress.svg", progress(f))
    write("pipeline.svg", pipeline(f))
    for k, t in HEADERS.items():
        write(f"h-{k}.svg", header(f, t))


if __name__ == "__main__":
    main()
