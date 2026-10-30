"""Corpus gate for Rig and Texture, plus the Mesh<->Rig contract:
every rigged mesh's bone palette must index inside its rig's bones."""
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Brutal import mesh, rig, texture
from Brutal.dfpf import Bundle
from Brutal.paths import packs_dir

bad = collections.Counter()
ex = {}
rigs = {}
n = collections.Counter()


def fail(kind, name, e):
    k = f"{kind}: {type(e).__name__}: {str(e)[:70]}"
    bad[k] += 1
    ex.setdefault(k, name)


bundles = [Bundle(h) for h in sorted(glob.glob(os.path.join(packs_dir(), "*.~h")))]
for b in bundles:
    for e in b:
        if e.type == "Rig":
            try:
                r = rig.parse(b.read(e))
                assert all(-1 <= p < i for i, p in enumerate(r.parents)), "parent not before child"
                assert r.bone_count <= len(r.names)
                rigs[e.name] = r
                n["rig"] += 1
            except Exception as x:
                fail("rig", e.name, x)
        elif e.type == "Texture":
            if e.name.startswith("lighting/textures/rsalights/"):
                continue  # baked light data, not a DDS texture
            try:
                texture.dds(b.read(e))
                n["texture"] += 1
            except Exception as x:
                fail("texture", e.name, x)
for b in bundles:
    for e in b:
        if e.type == "Mesh" and e.name in rigs:
            m = mesh.parse_header(b.read(e))
            r = rigs[e.name]
            top = max((max(s.bone_palette, default=-1) for s in m.submeshes), default=-1)
            try:
                assert top < r.bone_count, f"palette index {top} >= {r.bone_count} bones"
                n["mesh~rig"] += 1
            except Exception as x:
                fail("mesh~rig", e.name, x)
print(dict(n), "bad", sum(bad.values()))
for k, c in bad.most_common():
    print(f"  {c:5} {k}  e.g. {ex[k]}")
sys.exit(1 if bad else 0)
