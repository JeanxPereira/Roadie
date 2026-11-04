"""Render one frame of a Scaleform movie (`Blender/BrutalLegend/Brutal/gfx.py`) to SVG, from the bundles alone.

What is drawn, in SWF terms (coordinates stay in twips; the root `viewBox` is the movie's frame
RECT and the pixel size is RECT / 20):

- the root display list after frame 0 (or after the frame holding a `FrameLabel`), PlaceObject2/3
  and RemoveObject2 played in order; every nested DefineSprite shows its own first frame, or with
  `settle` the first frame whose script holds a stop (`gfx.stop_frame`, a heuristic);
- depth order, placement matrices, colour transforms (alpha-only ones as `opacity`, others as an
  `feColorMatrix` in sRGB), blend modes multiply / screen / lighten / darken / difference /
  overlay / hardlight / add (`mix-blend-mode`, add = `plus-lighter`);
- clip layers (`ClipDepth`): the clip character's fill geometry, flattened through nested sprites
  and text, becomes an SVG `clipPath` over depths (depth, ClipDepth];
- DefineShape/2/3/4: per style group, every fill style's edges (fill1 forward, fill0 reversed)
  joined into closed contours and filled even-odd (non-zero for DefineShape4 with the winding
  flag), then the line styles (width >= 1 px, caps/joins of LINESTYLE2, fill-styled lines);
  solid, linear, radial and focal gradients (`gradientUnits=userSpaceOnUse`, the +-16384 twip
  gradient square through the fill matrix, pad/reflect/repeat), bitmap fills as `pattern`s of the
  external image (pixel space through the fill matrix), the image possibly imported;
- DefineMorphShape/2 interpolated at the placement ratio;
- DefineExternalImage: the Texture found through the movie's `DUIMovie` by the lower-cased stem of
  the file name, decoded (DXT1/DXT5, `Blender/BrutalLegend/Brutal/image.py`) and embedded as a PNG data URI, cropped to
  the image size; also placed directly when an image is a display-list character;
- ImportAssets2: `gfxfontlib.swf` names resolve through `FlashConfig.FontMap` to the shared font
  movie; `Shared/ControllerIcons.swf` resolves to `PhysicalInputIcons.gfx` (the game's file-opener
  remap), any other `Shared/X.swf` to `Data/UI/X/Opt/X.gfx`; the export name gives the id there;
- DefineEditText: initial text (HTML subset: p align, br, font face/size/color/letterSpacing/kerning,
  textformat leading/indent/margins, li) set in DefineFont3 glyph outlines. Fonts: the movie's own
  DefineFont3 when it has glyphs; a glyph-less font or an HTML face by name, through FontMap for
  `$` aliases, in the shared font movie. Layout: 2 px gutter, first baseline at gutter + ascent,
  line step ascent + descent + leading, alignment per line, word wrap at spaces for WordWrap
  fields (2 px gutter and line metrics are Flash Player conventions: assumption for Scaleform).
  Line codes (`*XXXX`) are drawn as their keys, unwrapped; Border draws a white box, black frame;
- Glow and DropShadow filters (outer, not knockout) as SVG blur filters: stdDeviation = blur px / 2
  (assumption for Flash's box blur), strength scales the alpha, quality ignored.

Not rendered: ActionScript (DoAction/DoInitAction, clip actions, variables, `gotoAndStop` in frame
scripts: whatever a script shows, hides, moves or fills in at run time is absent; sprites do not
advance with the root when a label is rendered), Glow/DropShadow inner and knockout variants and
the other filters (Blur, Bevel, GradientGlow/Bevel, Convolution, ColorMatrix), blend modes
subtract/invert/alpha/erase, gradient interpolation mode 1 (linear RGB), CacheAsBitmap, device
fonts without outlines, `img` tags inside HTML text, the translator's markup (`/alias/`) and line
code lookup, TextField auto-size growth, and line strokes in clip geometry.
"""

from __future__ import annotations

import base64
import html.parser
import math
import struct
from xml.sax.saxutils import quoteattr

from . import gfx, image, texture, textobj

GUTTER = 40  # 2 px text field gutter, twips


def _n(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _mat(m) -> str:
    a, b, c, d, e, f = m
    return f"matrix({_n(round(a, 5))} {_n(round(b, 5))} {_n(round(c, 5))} {_n(round(d, 5))} {_n(e)} {_n(f)})"


def _mul(m, n):
    """m after n (n applied first)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c[:3])


def _xml_text(s: str) -> str:
    return "".join(ch for ch in s if ch in "\t\n" or ord(ch) >= 32)


class Ctx:
    """One loaded movie: dictionary, images, exports/imports."""

    def __init__(self, r: "Renderer", path: str, key: str):
        self.path, self.key = path, key
        self.movie = gfx.parse(r.lib.read(path + ".Blob"))
        self.dict = gfx.dictionary(self.movie)
        self.exports = gfx.exports(self.movie)
        self.imports = {cid: (url, name) for url, names in gfx.imports(self.movie) for name, cid in names.items()}
        info = next((t for t in self.movie.tags if t.code == 1000), None)
        self.prefix = ""
        if info is not None:
            p = 8 if struct.unpack_from("<H", info.data)[0] >= 0x10A else 4
            self.prefix = gfx._str8(info.data, p)[0]
        self.textures = r.duimovie_textures.get(path, {})
        self.cache: dict = {}


class _Html(html.parser.HTMLParser):
    """Flash HTML subset -> paragraphs [(para fmt, [(text, run fmt)])]."""

    def __init__(self, base: dict):
        super().__init__(convert_charrefs=True)
        self.stack = [dict(base)]
        self.paras = [(dict(base), [])]

    def _new_para(self):
        if self.paras[-1][1] or True:
            self.paras.append((dict(self.stack[-1]), []))

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs}
        f = dict(self.stack[-1])
        if tag == "p":
            if a.get("align"):
                f["align"] = {"left": 0, "right": 1, "center": 2, "justify": 3}.get(a["align"].lower(), 0)
            self.stack.append(f)
            if self.paras[-1][1]:
                self._new_para()
            else:
                self.paras[-1] = (dict(f), self.paras[-1][1])
            return
        if tag == "br":
            self._new_para()
            return
        if tag == "font":
            if a.get("face"):
                f["face"] = a["face"]
            if a.get("size"):
                try:
                    s = a["size"]
                    f["size"] = (f["size"] + float(s) * 20) if s[0] in "+-" else float(s) * 20
                except ValueError:
                    pass
            if a.get("color") and a["color"].startswith("#") and len(a["color"]) == 7:
                v = int(a["color"][1:], 16)
                f["color"] = (v >> 16, (v >> 8) & 255, v & 255, f["color"][3])
            if a.get("letterspacing"):
                f["spacing"] = float(a["letterspacing"]) * 20
            if a.get("kerning"):
                f["kerning"] = a["kerning"] not in ("0", "false")
        elif tag == "textformat":
            for k, key in (("leading", "leading"), ("indent", "indent"), ("leftmargin", "left"),
                           ("rightmargin", "right")):
                if a.get(k):
                    f[key] = float(a[k]) * 20
            if self.paras[-1][1] == []:
                self.paras[-1] = (dict(f), [])
        elif tag == "li":
            self._new_para()
            self.paras[-1][1].append(("• ", dict(f)))
        if tag not in ("img",):
            self.stack.append(f)

    def handle_endtag(self, tag):
        if tag in ("p", "font", "b", "i", "u", "a", "textformat", "li", "span") and len(self.stack) > 1:
            self.stack.pop()
        if tag in ("p", "li"):
            self._new_para()

    def handle_data(self, data):
        if data:
            self.paras[-1][1].append((data, dict(self.stack[-1])))


class Renderer:
    def __init__(self, lib, images: str = "embed", settle: bool = False):
        """images: 'embed' (PNG data URIs), 'link' (href = texture resource path, nothing decoded),
        'none' (no image data; bitmap fills become grey). settle: nested sprites show the frame
        they stop on (`gfx.stop_frame`) instead of their first frame."""
        self.lib, self.images, self.settle = lib, images, settle
        self.duimovie_textures: dict[str, dict[str, str]] = {}
        for b, e in lib.entries("DUIMovie"):
            o = textobj.parse(b.read(e))
            self.duimovie_textures[o["FlashFile"].lower()] = {
                t.rsplit("/", 1)[-1].lower(): t.lstrip("@") for t in o["Textures"]}
        cfg = textobj.parse(next(b.read(e) for b, e in lib.entries("FlashConfig")))
        fm = cfg["FontMapping"][int(cfg["FontIndexMap"][0])]
        self.font_map = {k: v[0] for k, v in fm["FontMap"].items() if not k.startswith("_")}
        self.font_movie = fm["SharedFontFile"].lower()
        self.ctxs: dict[str, Ctx] = {}
        self._shared_fonts = None
        self.png_cache: dict[str, bytes] = {}
        self.reset()

    def reset(self):
        self.defs: list[str] = []
        self.ids: set[str] = set()
        self.problems: list[str] = []
        self.stats: dict[str, int] = {}
        self.font_keys: dict[int, str] = {}
        self._stack: list = []
        for c in self.ctxs.values():  # SVG defs are per document
            c.cache = {k: v for k, v in c.cache.items() if k[0] == "font"}

    def _stat(self, k: str, n: int = 1):
        self.stats[k] = self.stats.get(k, 0) + n

    def _problem(self, msg: str):
        self.problems.append(msg)

    def ctx(self, path: str) -> Ctx:
        path = path.lower()
        if path not in self.ctxs:
            self.ctxs[path] = Ctx(self, path, f"m{len(self.ctxs)}")
        return self.ctxs[path]

    # ------------------------------------------------------------ fonts

    def shared_fonts(self) -> dict[str, gfx.Font]:
        if self._shared_fonts is None:
            self._shared_fonts = {f.name: f for f in gfx.fonts(self.ctx(self.font_movie).movie)}
        return self._shared_fonts

    def font_by_name(self, ctx: Ctx, name: str) -> gfx.Font | None:
        name = self.font_map.get(name, name)
        sf = self.shared_fonts()
        if name in sf:
            return sf[name]
        for cid, t in ctx.dict.items():
            if t.code == 75:
                f = self._font(ctx, cid)
                if f.name == name and f.glyphs:
                    return f
        return None

    def _font(self, ctx: Ctx, cid: int) -> gfx.Font:
        k = ("font", cid)
        if k not in ctx.cache:
            ctx.cache[k] = gfx.font(ctx.dict[cid])
        return ctx.cache[k]

    def font_by_id(self, ctx: Ctx, cid: int) -> gfx.Font | None:
        if cid in ctx.imports:
            url, name = ctx.imports[cid]
            if url.lower() == "gfxfontlib.swf":
                return self.font_by_name(ctx, name)
            tctx, tid = self.resolve_import(ctx, cid)
            return self.font_by_id(tctx, tid) if tctx else None
        t = ctx.dict.get(cid)
        if t is None or t.code != 75:
            return None
        f = self._font(ctx, cid)
        if f.glyphs:
            return f
        return self.font_by_name(ctx, f.name)

    # ------------------------------------------------------------ resolution

    def resolve_import(self, ctx: Ctx, cid: int):
        url, name = ctx.imports[cid]
        base = url.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if base.lower() == "controllericons":
            base = "PhysicalInputIcons"
        path = f"data/ui/{base}/opt/{base}.gfx".lower()
        if path + ".blob" not in self.lib:
            self._problem(f"{ctx.path}: import {url} has no movie")
            return None, None
        t = self.ctx(path)
        if name not in t.exports:
            self._problem(f"{ctx.path}: import {name} not exported by {path}")
            return None, None
        return t, t.exports[name]

    def lookup(self, ctx: Ctx, cid: int):
        """(ctx, tag) defining a character, following imports; (None, None) when unresolved."""
        seen = 0
        while cid not in ctx.dict and cid in ctx.imports and seen < 4:
            if ctx.imports[cid][0].lower() == "gfxfontlib.swf":
                return ctx, None
            ctx, cid = self.resolve_import(ctx, cid)
            if ctx is None:
                return None, None
            seen += 1
        t = ctx.dict.get(cid)
        return (ctx, t) if t is not None else (None, None)

    # ------------------------------------------------------------ images

    def image_def(self, ctx: Ctx, cid: int) -> tuple[str, int, int] | None:
        """id of an <image> def for an external image character, with its size."""
        k = ("img", cid)
        if k in ctx.cache:
            return ctx.cache[k]
        src, t = self.lookup(ctx, cid)  # bitmap fills may name an imported image
        if t is None or t.code != 1001:
            self._problem(f"{ctx.path}: bitmap {cid} is not an external image")
            ctx.cache[k] = None
            return None
        if src is not ctx:
            ctx.cache[k] = self.image_def(src, struct.unpack_from("<H", t.data)[0])
            self._stat("imported bitmaps")
            return ctx.cache[k]
        im = gfx.external_image(t)
        stem = im.file_name.rsplit(".", 1)[0].lower()
        tex = ctx.textures.get(stem) or f"ui/flash/{ctx.prefix.lower()}/{stem}"
        if f"{tex}.Texture" not in self.lib:
            self._problem(f"{ctx.path}: image {cid} {im.file_name} -> {tex}.Texture missing")
            ctx.cache[k] = None
            return None
        did = f"{ctx.key}i{cid}"
        if self.images == "embed":
            if tex not in self.png_cache:
                w, h, px = image.dds_rgba(texture.dds(self.lib.read(f"{tex}.Texture")), im.width, im.height)
                self.png_cache[tex] = image.png(w, h, px)
            href = "data:image/png;base64," + base64.b64encode(self.png_cache[tex]).decode()
            self._stat("images embedded")
        elif self.images == "link":
            href = f"{tex}.Texture"
        else:
            href = None
        if href is None:
            self.defs.append(f'<rect id="{did}" width="{im.width}" height="{im.height}" fill="#808080"/>')
        else:
            self.defs.append(f'<image id="{did}" width="{im.width}" height="{im.height}" '
                             f'preserveAspectRatio="none" href={quoteattr(href)}/>')
        self.ids.add(did)
        ctx.cache[k] = (did, im.width, im.height)
        return ctx.cache[k]

    # ------------------------------------------------------------ paints

    def _paint(self, ctx: Ctx, f: dict, pid: str) -> tuple[str, float]:
        """fill style -> (paint, opacity)."""
        t = f["type"]
        if t == "solid":
            return _hex(f["color"]), f["color"][3] / 255
        if t in ("linear", "radial", "focal"):
            stops = "".join(f'<stop offset="{_n(round(r / 255, 4))}" stop-color="{_hex(c)}" '
                            f'stop-opacity="{_n(round(c[3] / 255, 4))}"/>' for r, c in f["stops"])
            spread = {0: "pad", 1: "reflect", 2: "repeat"}.get(f["spread"], "pad")
            if f["interp"]:
                self._stat("gradient linearRGB interpolation (drawn as sRGB)")
            if t == "linear":
                el = (f'<linearGradient id="{pid}" gradientUnits="userSpaceOnUse" x1="-16384" y1="0" '
                      f'x2="16384" y2="0" spreadMethod="{spread}" gradientTransform="{_mat(f["matrix"])}">'
                      f'{stops}</linearGradient>')
            else:
                fx = _n(f["focal"] * 16384)
                el = (f'<radialGradient id="{pid}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="16384" '
                      f'fx="{fx}" fy="0" spreadMethod="{spread}" gradientTransform="{_mat(f["matrix"])}">'
                      f'{stops}</radialGradient>')
            self.defs.append(el)
            self.ids.add(pid)
            self._stat("gradient fills")
            return f"url(#{pid})", 1.0
        if t == "bitmap":
            if f["id"] == 0xFFFF:
                return "none", 1.0
            img = self.image_def(ctx, f["id"])
            if img is None:
                return "#ff00ff", 1.0
            did, w, h = img
            style = "" if f["smooth"] else ' style="image-rendering:pixelated"'
            self.defs.append(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{w}" height="{h}" '
                             f'patternTransform="{_mat(f["matrix"])}"><use href="#{did}"{style}/></pattern>')
            self.ids.add(pid)
            self._stat("bitmap fills")
            return f"url(#{pid})", 1.0
        raise ValueError(t)

    # ------------------------------------------------------------ shapes

    @staticmethod
    def _contours(edges: list) -> list[tuple[str, bool]]:
        """Directed edges (x0, y0, cx, cy, x1, y1) -> [(path data, closed)]."""
        key = lambda x, y: (round(x, 1), round(y, 1))
        by_start: dict = {}
        for i, e in enumerate(edges):
            by_start.setdefault(key(e[0], e[1]), []).append(i)
        used = [False] * len(edges)
        out = []
        for i, e in enumerate(edges):
            if used[i]:
                continue
            used[i] = True
            start = key(e[0], e[1])
            seq = [e]
            end = key(e[4], e[5])
            while end != start:
                nxt = next((j for j in by_start.get(end, ()) if not used[j]), None)
                if nxt is None:
                    break
                used[nxt] = True
                seq.append(edges[nxt])
                end = key(edges[nxt][4], edges[nxt][5])
            d = [f"M{_n(e[0])} {_n(e[1])}"]
            for s in seq:
                if s[2] is None:
                    d.append(f"L{_n(s[4])} {_n(s[5])}")
                else:
                    d.append(f"Q{_n(s[2])} {_n(s[3])} {_n(s[4])} {_n(s[5])}")
            closed = end == start
            if closed:
                d.append("Z")
            out.append(("".join(d), closed))
        return out

    @staticmethod
    def _shape_fills(groups) -> list:
        """[(group index, style index, contours)] for the fill styles."""
        out = []
        for gi, (fills, lines, edges) in enumerate(groups):
            per: dict[int, list] = {}
            for f0, f1, ln, x0, y0, cx, cy, x1, y1 in edges:
                if f1:
                    per.setdefault(f1, []).append((x0, y0, cx, cy, x1, y1))
                if f0:
                    per.setdefault(f0, []).append((x1, y1, cx, cy, x0, y0))
            for si in sorted(per):
                out.append((gi, si, Renderer._contours(per[si])))
        return out

    def shape_svg(self, ctx: Ctx, s: gfx.Shape, sid: str) -> str:
        parts = []
        fills_by_group: dict[int, list] = {}
        for gi, si, cs in self._shape_fills(s.groups):
            fills_by_group.setdefault(gi, []).append((si, cs))
            self._stat("open fill contours", sum(1 for _, closed in cs if not closed))
        rule = "nonzero" if s.nonzero else "evenodd"
        for gi, (fills, lines, edges) in enumerate(s.groups):
            for si, cs in fills_by_group.get(gi, []):
                if si > len(fills):
                    self._problem(f"{ctx.path}: shape {s.id} fill index {si} > {len(fills)}")
                    continue
                paint, op = self._paint(ctx, fills[si - 1], f"{sid}f{gi}_{si}")
                if paint == "none":
                    continue
                opa = f' fill-opacity="{_n(round(op, 3))}"' if op < 1 else ""
                parts.append(f'<path fill="{paint}"{opa} fill-rule="{rule}" d="{"".join(d for d, _ in cs)}"/>')
            per: dict[int, list] = {}
            for e in edges:
                if e[2]:
                    per.setdefault(e[2], []).append(e)
            for li in sorted(per):
                if li > len(lines):
                    self._problem(f"{ctx.path}: shape {s.id} line index {li} > {len(lines)}")
                    continue
                ln = lines[li - 1]
                d, last = [], None
                for e in per[li]:
                    if last != (e[3], e[4]):
                        d.append(f"M{_n(e[3])} {_n(e[4])}")
                    d.append(f"L{_n(e[7])} {_n(e[8])}" if e[5] is None else
                             f"Q{_n(e[5])} {_n(e[6])} {_n(e[7])} {_n(e[8])}")
                    last = (e[7], e[8])
                if ln.get("fill"):
                    paint, op = self._paint(ctx, ln["fill"], f"{sid}l{gi}_{li}")
                else:
                    paint, op = _hex(ln["color"]), ln["color"][3] / 255
                cap = {0: "round", 1: "butt", 2: "square"}[ln["cap"]]
                join = {0: "round", 1: "bevel", 2: "miter"}[ln["join"]]
                opa = f' stroke-opacity="{_n(round(op, 3))}"' if op < 1 else ""
                parts.append(f'<path fill="none" stroke="{paint}"{opa} stroke-width="{_n(max(20, ln["width"]))}" '
                             f'stroke-linecap="{cap}" stroke-linejoin="{join}" '
                             f'stroke-miterlimit="{_n(max(1, ln["miter"]))}" d="{"".join(d)}"/>')
                self._stat("line styles")
        return "".join(parts)

    def clip_geometry(self, ctx: Ctx, cid: int, ratio: int, m, depth: int = 0) -> list[str]:
        """Fill geometry of a character as <path> elements in the parent space (for clipPath)."""
        if depth > 32:
            return []
        c, t = self.lookup(ctx, cid)
        if t is None:
            return []
        if t.code in gfx.SHAPE_TAGS or t.code in (46, 84):
            s = gfx.shape(t)[0] if t.code in gfx.SHAPE_TAGS else gfx.morph_at(gfx.morph_shape(t)[0], ratio or 0)
            d = "".join(d for _, _, cs in self._shape_fills(s.groups) for d, _ in cs)
            return [f'<path clip-rule="evenodd" transform="{_mat(m)}" d="{d}"/>'] if d else []
        if t.code == 39:
            out = []
            for p in self._display(c, gfx.sprite(t).tags):
                out += self.clip_geometry(c, p.char, p.ratio, _mul(m, p.matrix or gfx.IDENTITY), depth + 1)
            return out
        if t.code == 37:
            return [f'<path transform="{_mat(_mul(m, gm))}" d="{d}"/>' for gm, d in self._text_glyphs(c, t)]
        if t.code == 1001:
            im = gfx.external_image(t)
            return [f'<path transform="{_mat(m)}" d="M0 0H{im.width * 20}V{im.height * 20}H0Z"/>']
        return []

    # ------------------------------------------------------------ text

    def _layout(self, ctx: Ctx, et: gfx.EditText):
        """Edit text -> list of (font, scale, x, y, char, color) glyph placements and a description."""
        base_font = self.font_by_id(ctx, et.font_id) if et.font_id is not None else None
        if et.font_id is not None and base_font is None:
            if et.font_class:
                base_font = self.font_by_name(ctx, et.font_class)
        base = {"font": base_font, "face": None, "size": float(et.height), "color": et.color,
                "align": et.align, "leading": float(et.leading), "indent": float(et.indent),
                "left": float(et.left), "right": float(et.right), "spacing": 0.0, "kerning": False}
        if et.html:
            p = _Html(base)
            try:
                p.feed(et.text)
                p.close()
            except Exception:
                self._problem(f"{ctx.path}: edit text {et.id} HTML does not parse")
            paras = [x for x in p.paras]
            while len(paras) > 1 and not paras[-1][1]:
                paras.pop()
        else:
            paras = [(dict(base), [(line, dict(base))]) for line in et.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        x0, x1, y0, y1 = et.bounds  # RECT order: xmin, xmax, ymin, ymax
        width = x1 - x0 - 2 * GUTTER
        out = []
        y = y0 + GUTTER
        for pf, runs in paras:
            chars = []
            for text, rf in runs:
                f = rf["font"]
                if rf.get("face"):
                    f = self.font_by_name(ctx, rf["face"]) or f
                    if f is None:
                        self._problem(f"{ctx.path}: edit text {et.id} face {rf['face']} unresolved")
                if f is None:
                    if text.strip():
                        self._problem(f"{ctx.path}: edit text {et.id} has no font")
                    continue
                for ch in text:
                    chars.append((ch, f, rf))
            # break into lines
            lines, cur, cw = [], [], 0.0
            avail = width - pf["left"] - pf["right"]
            # a paragraph that is only a line-code key stays on one line (its text is unknown here)
            wrap = et.word_wrap and not "".join(c[0] for c in chars).strip().startswith("*")
            first_indent = pf["indent"]

            def adv(ch, f, rf, prev):
                sc = rf["size"] / gfx.Font.EM
                a = f.advance.get(ch, gfx.Font.EM // 4 if ch == " " else 0) * sc + rf["spacing"]
                if rf["kerning"] and prev is not None:
                    a += f.kerning.get((prev, ch), 0) * sc
                return a

            prev = None
            for item in chars:
                ch, f, rf = item
                if ch == "\n":
                    lines.append(cur)
                    cur, cw, prev = [], 0.0, None
                    continue
                a = adv(ch, f, rf, prev)
                lim = avail - (first_indent if not lines else 0)
                if wrap and cur and cw + a > lim and ch != " ":
                    sp = max((i for i, c in enumerate(cur) if c[0] == " "), default=-1)
                    if sp > 0:
                        lines.append(cur[:sp])
                        cur = cur[sp + 1:]
                    else:
                        lines.append(cur)
                        cur = []
                    cw, prev = 0.0, None
                    for c in cur:
                        cw += adv(c[0], c[1], c[2], prev)
                        prev = c[0]
                cur.append(item)
                cw += a
                prev = ch
            lines.append(cur)
            for li, line in enumerate(lines):
                fonts = [(c[1], c[2]["size"]) for c in line] or [(pf["font"] or base_font, pf["size"])]
                fonts = [(f, s) for f, s in fonts if f is not None]
                if not fonts:
                    y += pf["size"]
                    continue
                asc = max(f.ascent * s / gfx.Font.EM for f, s in fonts)
                desc = max(f.descent * s / gfx.Font.EM for f, s in fonts)
                w, prev = 0.0, None
                for ch, f, rf in line:
                    w += adv(ch, f, rf, prev)
                    prev = ch
                ind = pf["indent"] if li == 0 else 0
                al = pf["align"]
                if al == 1:
                    x = x0 + GUTTER + width - pf["right"] - w
                elif al == 2:
                    x = x0 + GUTTER + pf["left"] + ind + (avail - ind - w) / 2
                else:
                    x = x0 + GUTTER + pf["left"] + ind
                base_y = y + asc
                prev = None
                for ch, f, rf in line:
                    sc = rf["size"] / gfx.Font.EM
                    if rf["kerning"] and prev is not None:
                        x += f.kerning.get((prev, ch), 0) * sc
                    if f.glyphs.get(ch):
                        out.append((f, sc, x, base_y, ch, rf["color"]))
                    elif ch not in " \t " and ch not in f.glyphs:
                        self._stat("characters without a glyph")
                    x += f.advance.get(ch, gfx.Font.EM // 4 if ch == " " else 0) * sc + rf["spacing"]
                    prev = ch
                y += asc + desc + pf["leading"]
        return out

    def _glyph_id(self, f: gfx.Font, ch: str) -> str:
        fk = self.font_keys.setdefault(id(f), f"F{len(self.font_keys)}")
        gid = f"{fk}u{ord(ch):x}"
        if gid not in self.ids:
            self.defs.append(f'<path id="{gid}" d="{gfx.path_d(f.glyphs[ch])}"/>')
            self.ids.add(gid)
        return gid

    def _text_glyphs(self, ctx: Ctx, t) -> list:
        et, _ = gfx.edit_text(t)
        return [((sc, 0, 0, sc, x, y), gfx.path_d(f.glyphs[ch]))
                for f, sc, x, y, ch, _c in self._layout(ctx, et)]

    def text_svg(self, ctx: Ctx, t) -> str:
        et, _ = gfx.edit_text(t)
        parts = []
        if et.border:
            x0, x1, y0, y1 = et.bounds  # RECT order: xmin, xmax, ymin, ymax
            parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="#fff" '
                         f'stroke="#000" stroke-width="20"/>')
        glyphs = self._layout(ctx, et)
        for f, sc, x, y, ch, col in glyphs:
            gid = self._glyph_id(f, ch)
            op = f' fill-opacity="{_n(round(col[3] / 255, 3))}"' if col[3] < 255 else ""
            parts.append(f'<use href="#{gid}" fill="{_hex(col)}"{op} '
                         f'transform="matrix({_n(round(sc, 6))} 0 0 {_n(round(sc, 6))} {_n(round(x, 1))} {_n(round(y, 1))})"/>')
        self._stat("text fields")
        self._stat("glyphs drawn", len(glyphs))
        label = _xml_text(et.text)[:200]
        return f'<g data-text={quoteattr(label)} data-var={quoteattr(_xml_text(et.variable))}>{"".join(parts)}</g>'

    # ------------------------------------------------------------ characters and display lists

    def char_def(self, ctx: Ctx, cid: int, ratio: int | None) -> str | None:
        """id of a <g>/<image> def drawing a character in its own space; None when unresolved."""
        c, t = self.lookup(ctx, cid)
        if t is None:
            self._problem(f"{ctx.path}: character {cid} unresolved")
            return None
        cid = struct.unpack_from("<H", t.data)[0]
        morph = t.code in (46, 84)
        k = ("def", cid, ratio or 0) if morph else ("def", cid)
        if k in c.cache:
            return c.cache[k]
        did = f"{c.key}c{cid}" + (f"r{ratio or 0}" if morph else "")
        if did in self._stack:
            self._problem(f"{c.path}: character {cid} contains itself")
            return None
        self._stack.append(did)
        try:
            if t.code in gfx.SHAPE_TAGS:
                body = self.shape_svg(c, gfx.shape(t)[0], did)
                self._stat("shapes")
            elif morph:
                body = self.shape_svg(c, gfx.morph_at(gfx.morph_shape(t)[0], ratio or 0), did)
                self._stat("morph shapes")
            elif t.code == 39:
                body = self.display_svg(c, self._display(c, gfx.sprite(t).tags))
                self._stat("sprites")
            elif t.code == 37:
                body = self.text_svg(c, t)
            elif t.code == 1001:
                img = self.image_def(c, cid)
                body = f'<use href="#{img[0]}" transform="scale(20)"/>' if img else ""
                self._stat("bitmaps placed")
            else:
                self._problem(f"{c.path}: character {cid} is a {t.name}, not drawable")
                body = ""
        finally:
            self._stack.pop()
        self.defs.append(f'<g id="{did}">{body}</g>')
        self.ids.add(did)
        c.cache[k] = did
        return did

    def _display(self, ctx: Ctx, tags, frame: int | None = None) -> list[gfx.Place]:
        if frame is None:  # a sprite timeline
            frame = (gfx.stop_frame(tags) or 0) if self.settle else 0
        return [p for _, p in sorted(gfx.display_list(tags, frame).items())]

    def _cx_attrs(self, cx, key: str) -> tuple[str, bool]:
        """colour transform -> (attributes, visible)."""
        if cx is None:
            return "", True
        (mr, mg, mb, ma), (ar, ag, ab, aa) = cx
        if (mr, mg, mb, ar, ag, ab, aa) == (256, 256, 256, 0, 0, 0, 0):
            if ma >= 256:
                return "", True
            if ma <= 0:
                return "", False
            return f' opacity="{_n(round(ma / 256, 4))}"', True
        fid = f"x{mr}_{mg}_{mb}_{ma}_{ar}_{ag}_{ab}_{aa}".replace("-", "n")
        if fid not in self.ids:
            v = (f"{mr / 256:.4f} 0 0 0 {ar / 255:.4f} 0 {mg / 256:.4f} 0 0 {ag / 255:.4f} "
                 f"0 0 {mb / 256:.4f} 0 {ab / 255:.4f} 0 0 0 {ma / 256:.4f} {aa / 255:.4f}")
            comp = '<feComposite in2="SourceAlpha" operator="in"/>' if aa > 0 else ""
            self.defs.append(f'<filter id="{fid}" color-interpolation-filters="sRGB">'
                             f'<feColorMatrix type="matrix" values="{v}"/>{comp}</filter>')
            self.ids.add(fid)
        self._stat("colour transforms (filter)")
        return f' filter="url(#{fid})"', True

    def _filter_attr(self, filters) -> str:
        prims, n = [], 0
        for fid, body in filters or []:
            if fid in (0, 2):
                r, g, b, a = body[:4]
                bx, by = struct.unpack_from("<ii", body, 4)
                if fid == 0:
                    angle, dist = struct.unpack_from("<ii", body, 12)
                    strength, flags = struct.unpack_from("<HB", body, 20)
                else:
                    angle = dist = 0
                    strength, flags = struct.unpack_from("<HB", body, 12)
                if flags & 0xC0:  # inner or knockout
                    self._stat(f"filters not rendered ({gfx.FILTER_NAMES[fid]} inner/knockout)")
                    continue
                sdx, sdy = bx / 65536 * 10, by / 65536 * 10
                dx = dist / 65536 * 20 * math.cos(angle / 65536)
                dy = dist / 65536 * 20 * math.sin(angle / 65536)
                s = strength / 256
                prims.append(
                    f'<feGaussianBlur in="SourceAlpha" stdDeviation="{_n(round(sdx, 1))} {_n(round(sdy, 1))}" result="B{n}"/>'
                    f'<feOffset in="B{n}" dx="{_n(round(dx, 1))}" dy="{_n(round(dy, 1))}" result="O{n}"/>'
                    f'<feComponentTransfer in="O{n}" result="A{n}"><feFuncA type="linear" '
                    f'slope="{_n(round(s * a / 255, 3))}"/></feComponentTransfer>'
                    f'<feFlood flood-color="{_hex((r, g, b))}" result="C{n}"/>'
                    f'<feComposite in="C{n}" in2="A{n}" operator="in" result="F{n}"/>')
                n += 1
                self._stat(f"filters ({gfx.FILTER_NAMES[fid]})")
            else:
                self._stat(f"filters not rendered ({gfx.FILTER_NAMES.get(fid, fid)})")
        if not prims:
            return ""
        key = f"fl{abs(hash(tuple(prims))) % 10 ** 10}"
        if key not in self.ids:
            merge = "".join(f'<feMergeNode in="F{i}"/>' for i in range(n))
            self.defs.append(f'<filter id="{key}" x="-50%" y="-50%" width="200%" height="200%" '
                             f'color-interpolation-filters="sRGB">{"".join(prims)}'
                             f'<feMerge>{merge}<feMergeNode in="SourceGraphic"/></feMerge></filter>')
            self.ids.add(key)
        return f' filter="url(#{key})"'

    def place_svg(self, ctx: Ctx, p: gfx.Place) -> str:
        self._stat("placements")
        did = self.char_def(ctx, p.char, p.ratio)
        if did is None:
            return ""
        cx, visible = self._cx_attrs(p.cxform, did)
        if not visible:
            self._stat("objects hidden by alpha 0")
            return ""
        tr = f' transform="{_mat(p.matrix)}"' if p.matrix and p.matrix != gfx.IDENTITY else ""
        el = f'<use href="#{did}"{tr}/>'
        style = ""
        if p.blend not in (None, 0, 1):
            mode = gfx.BLEND_MODES.get(p.blend)
            css = {"multiply": "multiply", "screen": "screen", "lighten": "lighten", "darken": "darken",
                   "difference": "difference", "overlay": "overlay", "hardlight": "hard-light",
                   "add": "plus-lighter", "layer": None}.get(mode, "?")
            if css == "?":
                self._stat(f"blend modes not rendered ({mode})")
            elif css:
                style = f' style="mix-blend-mode:{css}"'
                self._stat(f"blend {mode}")
        fl = self._filter_attr(p.filters)
        if fl:
            el = f"<g{fl}>{el}</g>"
        if cx or style:
            el = f"<g{cx}{style}>{el}</g>"
        return el

    def display_svg(self, ctx: Ctx, items: list[gfx.Place]) -> str:
        out, i = [], 0
        while i < len(items):
            p = items[i]
            if p.clip_depth:
                j = i + 1
                while j < len(items) and items[j].depth <= p.clip_depth:
                    j += 1
                inner = self.display_svg(ctx, items[i + 1:j])
                geo = self.clip_geometry(ctx, p.char, p.ratio, p.matrix or gfx.IDENTITY)
                self._stat("clip layers")
                if inner:
                    cid = f"{ctx.key}k{len(self.ids)}"
                    self.defs.append(f'<clipPath id="{cid}">{"".join(geo)}</clipPath>')
                    self.ids.add(cid)
                    out.append(f'<g clip-path="url(#{cid})">{inner}</g>')
                i = j
                continue
            out.append(self.place_svg(ctx, p))
            i += 1
        return "".join(out)

    # ------------------------------------------------------------ entry point

    def render(self, movie: str, label: str | None = None, background: bool = False, frame: int = 0) -> str:
        """SVG of a root frame (0-based, default the first) of a movie (path or short name), or of
        the frame holding `label`."""
        self.reset()
        path = movie.lower()
        if not path.endswith(".gfx"):
            path = f"data/ui/{path}/opt/{path}.gfx"
        ctx = self.ctx(path)
        if label is not None:
            labels = gfx.frame_labels(ctx.movie.tags)
            if label not in labels:
                raise KeyError(f"no frame label {label!r}; labels: {', '.join(labels) or 'none'}")
            frame = labels[label]
        body = self.display_svg(ctx, self._display(ctx, ctx.movie.tags, frame))
        x0, x1, y0, y1 = ctx.movie.frame_size
        bg = ""
        if background:
            t = next((t for t in ctx.movie.tags if t.code == 9), None)
            if t is not None:
                bg = f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{_hex(t.data)}"/>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" '
                f'width="{_n((x1 - x0) / 20)}" height="{_n((y1 - y0) / 20)}">'
                f'<defs>{"".join(self.defs)}</defs>{bg}{body}</svg>')


def render(lib, movie: str, label: str | None = None, images: str = "embed", background: bool = False,
           frame: int = 0, settle: bool = False) -> str:
    return Renderer(lib, images, settle).render(movie, label, background, frame)
