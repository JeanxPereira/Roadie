"""Corpus gate: every Mesh in every bundle must parse and its byte budget must close exactly.

Run: python tests/corpus_mesh.py [packs_dir]
"""
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brutal import mesh
from brutal.dfpf import Bundle
from brutal.paths import packs_dir

ok, bad = 0, collections.Counter()
morph_err, morph_n = 0.0, 0
examples = {}
for h in sorted(glob.glob(os.path.join(sys.argv[1] if len(sys.argv) > 1 else packs_dir(), "*.~h"))):
    with Bundle(h) as b:
        for e in b:
            if e.type != "Mesh":
                continue
            try:
                m = mesh.parse(b.read(e), geometry=False)
                if any(s.morph_frames for s in m.submeshes):
                    # Delta scale proof: normal + 2/32767 * dnormal must stay unit length.
                    g = mesh.parse(b.read(e))
                    for s in g.submeshes:
                        for fr in s.morph_frames:
                            for v, dn in zip(fr.vertices, fr.dnrm):
                                n = s.normals[v]
                                ln = sum((n[i] + dn[i]) ** 2 for i in range(3)) ** 0.5
                                morph_err += (ln - 1) ** 2
                                morph_n += 1
                assert m.header_size == e.header_size, f"parsed header {m.header_size} != record {e.header_size}"
                for s in m.submeshes:
                    assert s.material < len(m.materials), "material index out of range"
                    assert s.primitive in (mesh.PRIM_LIST, mesh.PRIM_STRIP), f"primitive {s.primitive}"
                ok += 1
            except Exception as ex:
                k = type(ex).__name__ + ": " + str(ex).split(" at ")[0][:60]
                bad[k] += 1
                examples.setdefault(k, e.name)
rms = (morph_err / max(morph_n, 1)) ** 0.5
print(f"meshes ok={ok} bad={sum(bad.values())}; morph normals |n+dn| rms-from-1 = {rms:.5f} over {morph_n} deltas")
if rms > 1e-3:
    bad["morph delta scale"] += 1
for k, n in bad.most_common():
    print(f"  {n:5} {k}  e.g. {examples[k]}")
sys.exit(1 if bad else 0)
