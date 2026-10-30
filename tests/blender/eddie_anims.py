"""Eddie with every animation of his rig, browsable from the sidebar list.

blender -b --factory-startup --python tests/blender/eddie_anims.py -- OUT.blend [OWN|ALL] [WORDS...]
"""
import sys
import time
from importlib import import_module

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out, scope = argv[0], (argv[1] if len(argv) > 1 else "ALL")
match = " ".join(argv[2:])
addon_utils.enable("bl_ext.user_default.brutal_legend", default_set=True)
pkg = "bl_ext.user_default.brutal_legend"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
sc = bpy.context.scene
bpy.ops.brutal_legend.import_resource("EXEC_DEFAULT", path="characters/bipeds/a01_avatar/rig/a01_avatar",
                                      type="Mesh")
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
bpy.context.view_layer.objects.active = arm

t = time.time()
bpy.ops.brutal_legend.import_rig_anims("EXEC_DEFAULT", scope=scope, match=match)
acts = [a for a in bpy.data.actions if a.get("bl_rig_hash") == arm["bl_rig_hash"]]
keys = sum(len(fc.keyframe_points) for a in bpy.data.actions for l in a.layers for s in l.strips
           for cb in s.channelbags for fc in cb.fcurves)
print(f"CLIPS {len(acts)} keys={keys} {time.time() - t:.0f}s", flush=True)

gs = import_module(pkg + ".gameshader")
lib = import_module(pkg).library()
gs.apply_weather(sc, lib, "environments/climates/aisland/day", 90.0)
d = Vector(sc["bl_sun_dir"]); d.y = -abs(d.y) - 0.3; d.z = max(d.z, 0.4)
sc["bl_sun_dir"] = tuple(d.normalized())
gs.aim_sun(sc)
sc.render.engine = "BLENDER_EEVEE"
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.location = (2.2, -4.2, 1.4)
cam.rotation_euler = (Vector((0, 0, 0.95)) - cam.location).to_track_quat("-Z", "Y").to_euler()

idle = next((i for i, a in enumerate(bpy.data.actions) if a.name == "action_walk_forward"), None)
if idle is None:
    idle = next(i for i, a in enumerate(bpy.data.actions) if a.get("bl_rig_hash"))
sc.bl_action_index = idle  # update callback plays it
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
print("SAVED", out, bpy.data.actions[idle].name, flush=True)
