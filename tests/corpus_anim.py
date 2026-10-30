"""Corpus gate for AnimResource (brutal/anim.py). Full reference: docs/formats/anim.md.

    python tests/corpus_anim.py [--step N] [--sample-step M] [--only TEXT]

Every N-th AnimResource (default 1 = all, ~90 s) is parsed and every chunk decoded.
Enforced (exit 1 on any failure):
  1. layout: blob = bundle record data part; blob layout exact (index lists, constant
     tables, chunk table, frame table, first chunk); chunk sections hold what the decoder
     reads (masks exact, others < 16 bytes of padding); chunks 16-aligned and contiguous
     in frames; closing chunk = first-key sections only; list indices < track counts.
  2. every stored quaternion (constant, key, root key) has | |q| - 1 | < 1e-3.
  4. pose: a01 lip-sync clips at frame 0 within 3 cm of bind; a01 relaxed idles keep head
     and ankles at bind height; median frame-0 distance over a01's own clips < 0.3 m.
  5. bone_map / float_map indices inside the rig whose hash matches.
  6. mask timing: decoded key frames give a smoother root path than the mirrored order.
Reported: 3. continuity (rotation/translation change per frame between consecutive keys,
which is exact for the piecewise slerp/lerp curve; full per-frame sample() on every M-th
clip), float and root-motion ranges.
"""
import argparse
import collections
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brutal import anim, rig
from brutal.library import Library

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=int, default=1)
ap.add_argument("--sample-step", type=int, default=25)
ap.add_argument("--only", default="", help="restrict to resource paths containing this text")
args = ap.parse_args()

bad = collections.Counter()
ex = {}
n = collections.Counter()


def fail(kind, name, msg):
    k = f"{kind}: {msg}"
    bad[k] += 1
    ex.setdefault(k, name)


def qangle(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.degrees(math.acos(min(1.0, d)))


def pct(v, ps=(50, 90, 99, 99.9, 100)):
    if not v:
        return "n/a"
    v = sorted(v)
    return " ".join(f"p{p}={v[min(len(v) - 1, int(len(v) * p / 100))]:.4g}" for p in ps)


# ---- pose helpers (column-vector convention; checked: rest pose -> bind pose exactly)
def qmat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def world_positions(parents, local):
    R, P = [None] * len(parents), [None] * len(parents)
    for i, (q, t, s) in enumerate(local):
        m = qmat(q)
        m = [[m[r][c] * s[c] for c in range(3)] for r in range(3)]
        p = parents[i]
        if p < 0:
            R[i], P[i] = m, list(t)
        else:
            R[i] = [[sum(R[p][r][k] * m[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
            P[i] = [P[p][r] + sum(R[p][r][k] * t[k] for k in range(3)) for r in range(3)]
    return P


def inv4(m):
    a = [list(m[i * 4:i * 4 + 4]) + [float(i == j) for j in range(4)] for i in range(4)]
    for c in range(4):
        p = max(range(c, 4), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        f = a[c][c]
        a[c] = [x / f for x in a[c]]
        for r in range(4):
            if r != c:
                g = a[r][c]
                a[r] = [x - g * y for x, y in zip(a[r], a[c])]
    return [row[4:] for row in a]


t0 = time.time()
L = Library()
rigs = {}
for b, e in L.entries("Rig"):
    d = b.read(e)
    try:
        r = rig.parse(d)
        rigs.setdefault(r.hash, (e.path, r, d))
    except Exception:
        pass

rot_step, trans_step, sample_rot, sample_trans = [], [], [], []
codec_mix = collections.Counter()
pose_rows = []
float_vals, root_t = [], []
jerk = [0.0, 0.0]  # root path second differences: decoded vs mirrored mask bit order
huge_t = set()  # clips with a translation key beyond 1e5 units (garbage in the shipped data)
worst_rot = worst_trans = (0.0, "")
avatar = rigs.get(next((h for h, (p, _, _) in rigs.items() if p.endswith("a01_avatar.Rig")), None))
avatar_bind = [inv4(m)[3][:3] for m in avatar[1].inverse_bind] if avatar else None

entries = sorted(L.entries("AnimResource"), key=lambda be: be[1].path)
for ai, (b, e) in enumerate(entries):
    if ai % args.step or args.only not in e.path:
        continue
    name = e.path
    data = b.read(e)
    try:
        a = anim.parse(data)
    except Exception as x:
        fail("parse", name, f"{type(x).__name__}: {str(x)[:60]}")
        continue
    n["anim"] += 1
    if e.header_size != len(data) - len(a._blob):
        fail("layout", name, "'dnap' blob is not exactly the bundle record's data part")
    codec_mix[a.codecs] += 1
    if a.flags & (anim.FLAG_ROOT_ROT | anim.FLAG_ROOT_TRANS):
        n["root motion"] += 1
    blob = a._blob
    if a.chunk_starts[0] != 0 or a.chunk_starts[-1] + a._chunk_last[-1] != a.frame_count - 1:
        fail("frames", name, "frame table does not span 0..frame_count-1")
    if abs(a.duration * a.fps - a.frame_count) > 0.01:
        fail("frames", name, "duration*fps != frame_count")
    for ci in range(len(a.chunk_starts) - 1):
        if a.chunk_starts[ci] + a._chunk_last[ci] + 1 != a.chunk_starts[ci + 1]:
            fail("frames", name, "chunks not contiguous")
    # 1a. blob layout, exact: index lists, the four constant tables (count * value size;
    # rotation and f32 tables start 16-aligned, f16 tables follow directly), the chunk
    # table rows (16-aligned), the frame table, then the first chunk (16-aligned)
    o = 0x60
    pads = (8, 4, 4, 4, 8, 4, 4, 4)
    for k, lst in enumerate(a.const_lists + a.anim_lists):
        o += 2 * (-(-len(lst) // pads[k]) * pads[k])
    for st in range(4):
        p0 = anim._rel(blob, 0x4C + 4 * st)
        if st == anim.ROT or a.codecs[st] == 0:  # quaternion and f32 tables are 16-aligned
            o = (o + 15) & ~15
        if p0 != o:
            fail("layout", name, f"constant table {st} at {p0:#x}, expected {o:#x}")
        o = p0 + anim.VALUE_SIZE[st].get(a.codecs[st], 0) * len(a.const_lists[st])
    rows = anim._rel(blob, 0x44)  # {u32 ?, u32 chunk offset} rows
    if rows != (o + 15) & ~15:
        fail("layout", name, f"chunk table at {rows:#x}, constants end {o:#x}")
    if anim._rel(blob, 0x48) != rows + 8 * len(a._chunk_offs):
        fail("layout", name, "frame table does not follow the chunk table")
    ftab_end = anim._rel(blob, 0x48) + 4 * len(a._chunk_offs)
    if not 0 <= a._chunk_offs[0] - ftab_end < 16:
        fail("layout", name, f"first chunk at {a._chunk_offs[0]:#x}, frame table ends {ftab_end:#x}")
    for st in range(3):
        for idx in a.const_lists[st] + a.anim_lists[st]:
            if idx >= len(a.bone_map):
                fail("layout", name, "bone track index >= track count")
    for idx in a.const_lists[3] + a.anim_lists[3]:
        if idx >= len(a.float_map):
            fail("layout", name, "float track index >= float track count")
    # 5. maps vs rig
    rg = rigs.get(a.rig_hash)
    if rg is None:
        n["rig not in corpus"] += 1
    else:
        n["rig matched"] += 1
        if a.bone_map and max(a.bone_map) >= rg[1].bone_count:
            fail("map", name, "bone_map index >= rig bones")
        if a.float_map and max(a.float_map) >= len(rg[1].flex_names):
            fail("map", name, "float_map index >= rig flexes")
    # 2. constant quaternions
    for q in a.const_values[anim.ROT]:
        n["quat"] += 1
        if abs(math.sqrt(sum(c * c for c in q)) - 1.0) > 1e-3:
            fail("quat", name, "constant |q| off by > 1e-3")
    # 1.-3. per chunk
    try:
        for ci, p in enumerate(a._chunk_offs):
            if p % 16:
                fail("layout", name, "chunk not 16-aligned")
            if ci == len(a._chunk_offs) - 1:
                sec = anim.chunk_sections(blob, p)
                o = sec["first.rot"][0]
                for st, nm in enumerate(anim._NAMES):
                    need = anim.VALUE_SIZE[st].get(a.codecs[st], 0) * len(a.anim_lists[st])
                    have = sec["first." + nm][1]
                    if not need <= have < need + 16:
                        fail("layout", name, f"closing chunk first.{nm} {have} vs {need}")
                    o += have
                o += 16 * bool(a.flags & anim.FLAG_ROOT_ROT) + 12 * bool(a.flags & anim.FLAG_ROOT_TRANS)
                if not 0 <= len(blob) - o < 16:
                    fail("layout", name, f"closing chunk leaves {len(blob) - o} bytes")
                continue
            n["chunk"] += 1
            for sname, have, need in anim.chunk_layout(a, ci):
                n["section"] += 1
                exact = sname.startswith("mask.") and not sname.startswith("mask.root")
                if have < need or have - need >= (1 if exact else 16):
                    fail("layout", name, f"{sname} stored {have} needs {need}")
            c = a.chunk(ci)
            for st, tracks in enumerate(c.tracks):
                for tr in tracks:
                    n["track-chunk"] += 1
                    if st == anim.ROT:
                        for q in tr.values:
                            n["quat"] += 1
                            if abs(math.sqrt(sum(x * x for x in q)) - 1.0) > 1e-3:
                                fail("quat", name, "key |q| off by > 1e-3")
                    for i in range(len(tr.frames) - 1):
                        df = tr.frames[i + 1] - tr.frames[i]
                        if st == anim.ROT:
                            s = qangle(tr.values[i], tr.values[i + 1]) / df
                            rot_step.append(s)
                            if s > worst_rot[0]:
                                worst_rot = (s, f"{name} chunk {ci}")
                        elif st == anim.TRANS:
                            if max(abs(x) for x in tr.values[i]) > 1e5:
                                huge_t.add(name)
                            s = math.dist(tr.values[i], tr.values[i + 1]) / df
                            trans_step.append(s)
                            if s > worst_trans[0]:
                                worst_trans = (s, f"{name} chunk {ci}")
            if c.root_trans and len(c.root_trans.frames) > 3:
                # mask timing: the decoded key frames must give a smoother root path than the
                # mirrored bit order would (same values, frames L+1-f)
                fr = c.root_trans.frames
                mirrored = [0] + sorted(c.last + 1 - x for x in fr[1:-1]) + [c.last + 1]
                for which, frames in ((0, fr), (1, mirrored)):
                    tr = anim.Track(frames, c.root_trans.values)
                    pts = [anim.Anim._interp(tr, f, 0.0, False) for f in range(c.last + 1)]
                    pts.append(tr.values[-1])
                    jerk[which] += sum(math.dist([2 * y - x - z for x, y, z in zip(pts[f - 1], pts[f], pts[f + 1])],
                                                 (0, 0, 0)) for f in range(1, len(pts) - 1))
            if c.root_rot:
                for q in c.root_rot.values:
                    n["quat"] += 1
                    if abs(math.sqrt(sum(x * x for x in q)) - 1.0) > 1e-3:
                        fail("quat", name, "root key |q| off by > 1e-3")
    except Exception as x:
        fail("decode", name, f"{type(x).__name__}: {str(x)[:60]}")
        continue
    # 3b. full per-frame sampling on a subset
    if ai % args.sample_step == 0:
        n["sampled clips"] += 1
        prev = None
        for f in range(a.frame_count):
            bones, floats = a.sample(f)
            n["sampled frames"] += 1
            float_vals.extend(floats)
            rm = a.root_motion(f)
            if rm is not None:
                root_t.append(math.dist(rm[1], (0.0, 0.0, 0.0)))
            if prev is not None:
                for (q0, t0_, _), (q1, t1, _) in zip(prev, bones):
                    sample_rot.append(qangle(q0, q1))
                    sample_trans.append(math.dist(t0_, t1))
            prev = bones
    # 4. pose sanity on the avatar
    if avatar and a.rig_hash == avatar[1].hash:
        rest = anim.rest_pose(avatar[2])
        bones, _ = a.sample(0, rest)
        local = list(rest)
        for i, bone in enumerate(a.bone_map):
            local[bone] = bones[i]
        P = world_positions(avatar[1].parents, local)
        d = [math.dist(x, y) for x, y in zip(P, avatar_bind)]
        core = [x for x, nm in zip(d, avatar[1].names) if "Wing" not in nm and "Prop" not in nm]
        pose_rows.append((sum(core) / len(core), max(core), name))
        # enforced: lip-sync clips hold the body at the rest pose -> bind pose within 3 cm
        # (observed <= 1.5 cm); standing idles keep head and ankles at bind height
        if "/a01_avatar/animations/lipsync/" in name and max(core) > 0.03:
            fail("pose", name, f"lip-sync frame 0 off bind by {max(core):.3f} m")
        if name.startswith("characters/bipeds/a01_avatar/animations/relaxed_idle_"):
            nm = avatar[1].names
            for bone_name, tol in (("Head", 0.05), ("Lf_Ankle", 0.03), ("Rt_Ankle", 0.03)):
                j = nm.index(bone_name)
                if abs(P[j][1] - avatar_bind[j][1]) > tol:
                    fail("pose", name, f"idle {bone_name} height off bind by > {tol} m")
    a._cache.clear()

print(f"{time.time() - t0:.0f}s", dict(n))
print("codecs (rot, scale, trans, float):", dict(codec_mix))
print("rotation deg/frame between keys:", pct(rot_step), f"(n={len(rot_step)})")
print("  worst:", f"{worst_rot[0]:.3g}", worst_rot[1])
print("  share > 30 deg/frame:", f"{sum(s > 30 for s in rot_step) / max(1, len(rot_step)):.2e}")
print("translation units/frame between keys:", pct(trans_step), f"(n={len(trans_step)})")
print("  worst:", f"{worst_trans[0]:.3g}", worst_trans[1])
print(f"  clips with a translation key > 1e5 units: {len(huge_t)}", sorted(huge_t)[:5])
print("sample() rotation deg/frame:", pct(sample_rot))
print("sample() translation units/frame:", pct(sample_trans))
print("sample() float track values:", pct(float_vals, (0, 1, 50, 99, 100)))
print("root motion |translation|:", pct(root_t, (0, 50, 99, 100)))
if pose_rows:
    pose_rows.sort()
    print(f"a01_avatar frame-0 pose vs bind ({len(pose_rows)} clips), mean/max metres per clip "
          "(wing and prop bones excluded: clips park them with scale 0.01 / far away):")
    print("  mean of means", f"{sum(r[0] for r in pose_rows) / len(pose_rows):.3f}",
          " median clip mean", f"{pose_rows[len(pose_rows) // 2][0]:.3f}")
    for r in pose_rows[:3] + pose_rows[-3:]:
        print(f"  {r[0]:.3f} {r[1]:.3f} {r[2]}")
    for r in pose_rows:
        if "idle" in r[2] and "/animations/" in r[2] and r[2].startswith("characters/"):
            print(f"  idle: {r[0]:.3f} {r[1]:.3f} {r[2]}")
print(f"root path jerk, decoded mask order {jerk[0]:.4g} vs mirrored {jerk[1]:.4g}")
if jerk[0] >= jerk[1]:
    fail("timing", "root motion", "mirrored mask bit order gives a smoother root path")
own = sorted(r[0] for r in pose_rows if r[2].startswith("characters/bipeds/a01_avatar/animations/"))
if own:
    med = own[len(own) // 2]
    print(f"  median clip mean over characters/bipeds/a01_avatar/animations ({len(own)} clips): {med:.3f} m")
    if med > 0.3:  # observed 0.187; a wrong quaternion component order gives ~1 m
        fail("pose", "a01_avatar", f"median frame-0 distance to bind {med:.3f} m > 0.3 m")
print("bad", sum(bad.values()))
for k, c in bad.most_common():
    print(f"  {c:5} {k}  e.g. {ex[k]}")
sys.exit(1 if bad else 0)
