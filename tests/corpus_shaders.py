"""Corpus gate for the shader containers (win/shaders/*.fxo, 'bsfd' v3).

Every container parses completely: header + meta + bytecode sizes cover the file, every record
array fits, every string-table byte is a referenced name or NUL padding, binding runs are
contiguous and match the header split, every sampler mask matches its bindings, every shader's
token stream walks to END 0x0000FFFF exactly at its declared size, and the bytecode tail is
padding only. The gate also proves it bites: a few corruptions must be rejected.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brutal import material, rsalight, shaders, textobj  # noqa: E402
from brutal.library import Library  # noqa: E402

L = Library()
failed = []
data = {}
for name in shaders.CONTAINERS:
    path = shaders.resource_path(name)
    if path not in L:
        failed.append(f"{name}: missing")
        continue
    d = data[name] = L.read(path)
    try:
        c = shaders.parse(d)
    except Exception as x:
        failed.append(f"{name}: {type(x).__name__}: {x}")
        continue
    bases = sorted({t.base for t in c.techniques})
    print(f"{name:12s} {len(d):8d} B  techniques {len(c.techniques):5d}  vs {len(c.vertex_shaders):4d}"
          f"  ps {len(c.pixel_shaders):4d}  samplers {len(c.samplers):3d}  params {len(c.parameters):3d}"
          f"  bindings {sum(len(s.constants) + len(s.samplers) for s in c.shaders):6d}"
          f"  bases {len(bases)}")

# The gate must bite: each corruption below has to raise.
d = data.get("sky")
if d:
    h = shaders.HEADER.unpack_from(d, 0)
    meta_end = shaders.HEADER.size + h[10]
    vs0_end = struct.unpack_from("<I", d, shaders.HEADER.size + 40 * h[3] + 12 * h[4] + 20)[0]
    cases = {
        "END token of shader 0": (meta_end + vs0_end - 4, b"\0\0\0\0"),
        "technique count + 1": (8, struct.pack("<I", h[2] + 1)),
        "string table padding byte": (meta_end - 1, b"Z"),
        "shader 1 offset": (shaders.HEADER.size + 40 * h[3] + 12 * h[4] + 20, struct.pack("<I", vs0_end + 4)),
    }
    for what, (off, patch) in cases.items():
        bad = bytearray(d)
        bad[off:off + len(patch)] = patch
        try:
            shaders.parse(bytes(bad))
            failed.append(f"gate does not bite: {what}")
        except Exception:
            pass

# Every Material resolves to a technique that exists (RenderMesh / RenderHair through
# shaders.material_constants, static and skinned; other shaders by their base technique name).
parsed = {n: shaders.parse(d) for n, d in data.items() if n in ("mesh", "hair")}
names = {n: {t.name for t in c.techniques} for n, c in parsed.items()}
bases = set()
for n, d in data.items():
    try:
        bases |= {t.base for t in shaders.parse(d).techniques}
    except Exception:
        pass
mat_ok = mat_n = 0
unresolved = {}
for b, e in L.entries("Material"):
    p = material.parse(b.read(e))
    s = p.get("ShaderName")
    mat_n += 1
    if s in ("RenderMesh", "RenderHair"):
        cont = names.get("mesh" if s == "RenderMesh" else "hair", set())
        good = True
        for skinned in (False, True):
            t = shaders.material_constants(p, skinned=skinned)["technique"]
            if t not in cont:
                good = False
                unresolved.setdefault(t, e.name)
    else:
        good = s in bases
        if not good:
            unresolved.setdefault(str(s), e.name)
    mat_ok += good
print(f"materials resolved to an existing technique: {mat_ok}/{mat_n}")
for t, n in list(unresolved.items())[:10]:
    print("  unresolved", t, "e.g.", n)
if mat_ok != mat_n:
    failed.append(f"{mat_n - mat_ok} materials do not resolve")

# RSA light gradients and Weathers.
rsa_n = 0
for b, e in L.entries("Texture"):
    if "/rsalights/" in e.path:
        try:
            r = rsalight.parse(b.read(e))
            assert len(r.rows) == r.height and all(r.rows[2 * i] == r.rows[2 * i + 1] for i in range(8))
            rsa_n += 1
        except Exception as x:
            failed.append(f"rsa {e.name}: {x}")
w_n = 0
for b, e in L.entries("Weather"):
    try:
        shaders.weather_constants(textobj.parse(b.read(e)))
        w_n += 1
    except Exception as x:
        failed.append(f"weather {e.name}: {type(x).__name__}: {x}")
print(f"rsa gradients decoded: {rsa_n}, weathers evaluated: {w_n}")
if rsa_n == 0 or w_n == 0:
    failed.append("no RSA gradients / weathers found")

print("FAIL: " + "; ".join(failed) if failed else f"ALL {len(data)} CONTAINERS PARSE, ALL MATERIALS RESOLVE")
sys.exit(1 if failed else 0)
