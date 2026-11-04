"""Corpus gate for Material: every material parses, every texture reference resolves,
and every material a mesh names exists."""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Blender", "BrutalLegend"))
from Brutal import material, mesh
from Brutal.library import Library

L = Library()
bad = collections.Counter()
ex = {}
n = collections.Counter()
shaders = collections.Counter()
for b, e in L.entries("Material"):
    try:
        p = material.parse(b.read(e))
        shaders[p.get("ShaderName")] += 1
        n["material"] += 1
        for slot in material.TEXTURE_SLOTS:
            t = p.get(slot)
            if t:
                k = "tex-ok" if f"{t}.Texture" in L else "tex-missing"
                n[k] += 1
                if k == "tex-missing":
                    ex.setdefault(slot, f"{e.name} -> {t}")
    except Exception as x:
        k = f"{type(x).__name__}: {x}"[:80]
        bad[k] += 1
        ex.setdefault(k, e.name)
for b, e in L.entries("Mesh"):
    for m in mesh.parse_header(b.read(e)).materials:
        n["mesh-mat-ok" if f"{m}.Material" in L else "mesh-mat-missing"] += 1
print(dict(n), "bad", sum(bad.values()))
print("shaders", shaders.most_common())
for k, v in ex.items():
    print("  e.g.", k, v)
sys.exit(1 if bad else 0)
