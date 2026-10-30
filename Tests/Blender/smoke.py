"""Blender smoke test: import resources through the installed extension and render a check image.

blender -b --factory-startup --python Tests/Blender/smoke.py -- OUT.png PATH [PATH...]
"""
import sys
import time

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out, paths = argv[0], argv[1:]
ZOOM = float(paths.pop(0)[5:]) if paths and paths[0].startswith("zoom=") else 1.6
addon_utils.enable("bl_ext.user_default.brutal_legend", default_set=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

for p in paths:
    t = time.time()
    r = bpy.ops.brutal_legend.import_resource("EXEC_DEFAULT", path=p, type="Mesh")
    print("IMPORT", p, r, f"{time.time() - t:.1f}s")

for o in bpy.data.objects:
    extra = ""
    if o.type == "MESH":
        me = o.data
        extra = (f"v={len(me.vertices)} f={len(me.polygons)} mats={len(me.materials)} "
                 f"groups={len(o.vertex_groups)} keys={len(me.shape_keys.key_blocks) if me.shape_keys else 0}")
    elif o.type == "ARMATURE":
        extra = f"bones={len(o.data.bones)}"
    print("OBJ", o.name, o.type, [round(x, 3) for x in o.dimensions], extra)
for img in bpy.data.images:
    print("IMG", img.name, img.size[:], img.colorspace_settings.name)

# frame everything, render with the material preview look
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
FOCUS = [o for o in meshes]
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c, size = (lo + hi) / 2, max((hi - lo).length, 0.1)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
bpy.context.scene.collection.objects.link(cam)
cam.location = c + Vector((0.0, -ZOOM * size, 0.1 * size))
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
light = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
light.data.energy = 4
light.rotation_euler = (0.8, 0.2, 0.6)
bpy.context.scene.collection.objects.link(light)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = 768, 768
sc.world = sc.world or bpy.data.worlds.new("w")
sc.world.color = (0.25, 0.25, 0.28)
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("RENDER", out)
