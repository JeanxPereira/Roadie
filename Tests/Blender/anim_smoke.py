"""Animation smoke test: import a character, apply clips, render a frame strip per clip.

blender -b --factory-startup --python Tests/Blender/anim_smoke.py -- OUT_DIR MESH_PATH CLIP [CLIP...]
"""
import os
import sys
import time

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out_dir, mesh_path, clips = argv[0], argv[1], argv[2:]
addon_utils.enable("bl_ext.user_default.brutal_legend", default_set=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
bpy.ops.brutal_legend.import_resource("EXEC_DEFAULT", path=mesh_path, type="Mesh")
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = next(o for o in bpy.data.objects if o.type == "MESH")
arm.hide_render = True
sc = bpy.context.scene
sc.view_settings.view_transform = "Standard"
sc.world = sc.world or bpy.data.worlds.new("w")
sc.world.color = (0.4, 0.4, 0.42)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.rotation_euler = (1.0, 0, 0.5)
sun.data.energy = 4
sc.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
sc.render.resolution_x, sc.render.resolution_y = 360, 480
face = "--face" in os.environ.get("BL_SMOKE", "")

for clip in clips:
    for o in (arm, body):
        if o.animation_data:
            o.animation_data.action = None
    if body.data.shape_keys and body.data.shape_keys.animation_data:
        body.data.shape_keys.animation_data.action = None
    bpy.context.view_layer.objects.active = arm
    t = time.time()
    r = bpy.ops.brutal_legend.import_resource("EXEC_DEFAULT", path=clip, type="AnimResource")
    n = sc.frame_end
    print("ANIM", clip, r, f"frames={n}", f"{time.time() - t:.1f}s", flush=True)
    frames = sorted({1 + round(i * (n - 1) / 5) for i in range(6)})
    tiles = []
    for f in frames:
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = body.evaluated_get(dg)
        pts = [ev.matrix_world @ v.co for v in ev.data.vertices]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        if face:
            head = arm.matrix_world @ arm.pose.bones["Neck1"].tail
            c, d = head + Vector((0, 0, 0.12)), 0.55
            cam.location = c + Vector((0, -d, 0))
        else:
            c = (lo + hi) / 2
            cam.location = c + Vector((-2.2, -3.6, 0.3))
        cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(out_dir, f"anim_{os.path.basename(clip)}_{f:03d}.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        tiles.append(path)
    print("TILES", "|".join(tiles), flush=True)
