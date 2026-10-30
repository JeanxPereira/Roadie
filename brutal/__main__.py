"""Command-line explorer for Brutal Legend bundles.

    python -m brutal types                         resource types and counts across all bundles
    python -m brutal ls [GLOB] [-t TYPE]           list resources (fnmatch on 'name.Type')
    python -m brutal info PATH                     what a resource contains (mesh/rig/texture/material)
    python -m brutal extract GLOB -o DIR [--convert]
                                                   write resources to DIR; --convert turns textures
                                                   into .dds and materials into .txt

Game folder: BL_GAME_DIR (default Steam path in brutal/paths.py).
"""

import argparse
import collections
import fnmatch
import os
import sys

from . import material, mesh, rig, texture
from .library import Library


def cmd_types(lib, a):
    c = collections.Counter(e.type for _, e in lib.entries())
    for t, n in c.most_common():
        print(f"{n:7} {t}")


def _match(lib, pattern, type_):
    pat = (pattern or "*").lower()
    for b, e in lib.entries(type_):
        if fnmatch.fnmatch(e.path.lower(), pat) or fnmatch.fnmatch(e.name.lower(), pat):
            yield b, e


def cmd_ls(lib, a):
    for b, e in _match(lib, a.pattern, a.type):
        print(f"{b.name:14} {e.usize:9} {e.path}")


def cmd_info(lib, a):
    path = a.path
    d = lib.read(path)
    kind = path.rsplit(".", 1)[-1]
    if kind == "Mesh":
        m = mesh.parse(d, geometry=False)
        print(f"materials: {len(m.materials)}")
        for i, n in enumerate(m.materials):
            print(f"  [{i}] {n}")
        for i, s in enumerate(m.submeshes):
            fmt = {mesh.FMT_STATIC: "static", mesh.FMT_SKINNED: "skinned"}[s.vertex_format]
            prim = {mesh.PRIM_LIST: "list", mesh.PRIM_STRIP: "strip"}[s.primitive]
            morph = f" morphs={len(s.morph_frames)} ({s.morph_name})" if s.morph_frames else ""
            print(f"  sub {i}: mat={s.material} {fmt} v={s.vertex_count} i={s.index_count} {prim} "
                  f"bones={len(s.bone_palette)}{morph}")
    elif kind == "Rig":
        r = rig.parse(d)
        print(f"hash {r.hash:016x}  bones {r.bone_count}  flexes {len(r.flex_names)}")
        for i, (n, p) in enumerate(zip(r.names, r.parents)):
            print(f"  {i:3} {n:32} parent {p}")
    elif kind == "Texture":
        print(texture.info(d))
    elif kind == "Material":
        for k, v in material.parse(d).items():
            print(f"  {k} = {v}")
    else:
        print(f"{len(d)} bytes; no decoder for {kind}")


def cmd_extract(lib, a):
    n = 0
    for b, e in _match(lib, a.pattern, a.type):
        d = b.read(e)
        out = os.path.join(a.out, *e.path.split("/"))
        if a.convert and e.type == "Texture":
            try:
                d, out = texture.dds(d), out[:-len(".Texture")] + ".dds"
            except ValueError:
                pass
        elif a.convert and e.type == "Material":
            d = d[4:4 + int.from_bytes(d[:4], "little")].replace(b";", b";\n")
            out += ".txt"
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(d)
        n += 1
    print(f"{n} files -> {a.out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m brutal", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("types").set_defaults(fn=cmd_types)
    p = sub.add_parser("ls")
    p.add_argument("pattern", nargs="?")
    p.add_argument("-t", "--type")
    p.set_defaults(fn=cmd_ls)
    p = sub.add_parser("info")
    p.add_argument("path")
    p.set_defaults(fn=cmd_info)
    p = sub.add_parser("extract")
    p.add_argument("pattern")
    p.add_argument("-t", "--type")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--convert", action="store_true")
    p.set_defaults(fn=cmd_extract)
    a = ap.parse_args(argv)
    lib = Library()
    try:
        a.fn(lib, a)
    finally:
        lib.close()


if __name__ == "__main__":
    sys.exit(main())
