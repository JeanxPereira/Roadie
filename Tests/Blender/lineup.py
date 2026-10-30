"""Import every main character mesh into a labelled grid, save a .blend, render previews.

blender -b --factory-startup --python Tests/Blender/lineup.py -- OUT_DIR
"""
import math
import os
import re
import sys
import time
import traceback

import addon_utils
import bpy
from mathutils import Vector

out_dir = sys.argv[sys.argv.index("--") + 1]
mod = addon_utils.enable("bl_ext.user_default.brutal_legend", default_set=True)
lib = sys.modules["bl_ext.user_default.brutal_legend"].library()
names = sorted({e.name for _b, e in lib.entries("Mesh")
                if re.match(r"characters/(bipeds|others|quadrupeds)/[^/]+/rig/[^/]+$", e.name)
                and not re.search(r"_lod\d$", e.name) and e.name.split("/")[2] == e.name.split("/")[-1]})
CAST = ["b01_avatar", "a01_avatar", "a20_lita", "a21_lars", "a09_girl", "l01_lionwhyte", "d01_avatar",
        "a02_headbanger", "a03_crossbowgirl", "a10_tophat", "b20_reaper", "d24_maiden"]
names.sort(key=lambda n: (n.split("/")[-1] not in CAST, CAST.index(n.split("/")[-1]) if n.split("/")[-1] in CAST else 0, n))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
scene = bpy.context.scene
cast_col = bpy.data.collections.new("Cast")
scene.collection.children.link(cast_col)

ok, failed, placed = 0, [], []
for path in names:
    name = path.split("/")[-1]
    col = bpy.data.collections.new(name)
    (cast_col if name in CAST else scene.collection).children.link(col)
    t = time.time()
    try:
        bpy.ops.brutal_legend.import_resource("EXEC_DEFAULT", path=path, type="Mesh")
    except Exception:
        failed.append((path, traceback.format_exc().splitlines()[-1]))
        continue
    new = [o for o in bpy.data.objects if not o.get("_placed")]
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        col.objects.link(o)
        o["_placed"] = True
    meshes = [o for o in new if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    if not pts:
        failed.append((path, "no mesh"))
        continue
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    placed.append((name, [o for o in new if o.parent is None], lo, hi, col))
    ok += 1
    print(f"OK {path} {time.time() - t:.1f}s", flush=True)

# rows by size: the cast first, then people, big creatures, giants; each row behind the last
def size_class(item):
    name, _, lo, hi, _ = item
    h = hi.z - lo.z
    return 0 if name in CAST else 1 if h < 3 else 2 if h < 9 else 3

y = 0.0
for cls in range(4):
    row = [it for it in placed if size_class(it) == cls]
    if cls == 0:
        row.sort(key=lambda it: CAST.index(it[0]))
    else:
        row.sort(key=lambda it: it[3].z - it[2].z)
    depth = max((it[3].y - it[2].y for it in row), default=0)
    gap = 0.4 if cls < 2 else 1.5
    x = -sum(min(it[3].x - it[2].x, 12) + gap for it in row) / 2
    for name, roots, lo, hi, col in row:
        w = hi.x - lo.x
        for o in roots:
            o.location.x += x - lo.x + max(0.0, (min(w, 12) - w) / 2)
            o.location.y += y - lo.y
        label = bpy.data.objects.new(f"label_{name}", bpy.data.curves.new(name, "FONT"))
        label.data.body = name
        label.data.size = 0.12 if cls < 2 else 0.5
        label.location = (x, y - 0.3, 0)
        col.objects.link(label)
        x += min(w, 12) + gap
    y += depth + (2 if cls < 2 else 6)

print(f"IMPORTED {ok}/{len(names)}")
for p, err in failed:
    print("FAIL", p, err)

for o in bpy.data.objects:
    if o.type == "ARMATURE":
        o.hide_render = True
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "characters.blend"))

# lighting and previews
from importlib import import_module
gs = import_module("bl_ext.user_default.brutal_legend.gameshader")
gs.apply_weather(scene, lib, "environments/climates/aisland/day", 90.0)
d = Vector(scene["bl_sun_dir"]); d.y = -abs(d.y) - 0.3; d.z = max(d.z, 0.4)  # light the fronts
scene["bl_sun_dir"] = tuple(d.normalized())
gs.aim_sun(scene)
scene.render.engine = "BLENDER_EEVEE"
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
scene.collection.objects.link(cam)
scene.camera = cam


def shoot(objs, path, res, height_bias=0.45, dist=1.25):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (lo + hi) / 2
    span = max(hi.x - lo.x, (hi.z - lo.z) * res[0] / res[1])
    cam.data.lens = 50
    d = span * dist
    cam.location = c + Vector((0, -d, (hi.z - lo.z) * height_bias * 0.3))
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("RENDER", path)


cast_objs = [o for c in cast_col.children for o in c.objects]
others = [o for o in bpy.data.objects if o.type in ("MESH", "FONT") and o not in cast_objs]
for o in others:
    o.hide_render = True
shoot(cast_objs, os.path.join(out_dir, "cast.png"), (1800, 700))
for o in others:
    o.hide_render = False
allm = [o for o in bpy.data.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in allm for c in o.bound_box]
c = Vector((sum(p.x for p in pts), sum(p.y for p in pts), 0)) / len(pts)
cam.data.lens = 35
cam.location = (c.x + 30, -45, 28)
cam.rotation_euler = (Vector((c.x, 15, 3)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.render.resolution_x, scene.render.resolution_y = 1800, 1000
scene.render.filepath = os.path.join(out_dir, "all.png")
bpy.ops.render.render(write_still=True)
print("RENDER all")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "characters.blend"))
