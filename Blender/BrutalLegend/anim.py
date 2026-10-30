"""Apply an AnimResource to an imported armature (bone TRS) and its mesh (facial shape keys)."""

from __future__ import annotations

import bpy
from mathutils import Matrix, Quaternion

from .Brutal import anim as banim
from .Brutal import rig as brig
from .Brutal.library import Library
from .importer import AXIS, AXIS_INV, short


def _trs(q, t, s) -> Matrix:
    m = Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
    for i in range(3):
        for j in range(3):
            m[i][j] *= s[j]
    m.translation = t
    return m


def _channelbag(owner, action):
    from bpy_extras import anim_utils
    ad = owner.animation_data_create()
    ad.action = action
    if ad.action_slot is None:  # Blender 5.x layered actions: a fresh action has no slot
        ad.action_slot = action.slots.new(owner.id_type, owner.name)
    return anim_utils.action_ensure_channelbag_for_slot(action, ad.action_slot)


def _write(cb, path, index, group, values, start=1):
    if max(values) - min(values) < 1e-6:
        values = values[:1]  # constant channel: one key (most bones hold still in a clip)
    fc = cb.fcurves.find(path, index=index) or cb.fcurves.new(path, index=index, group_name=group)
    fc.keyframe_points.add(len(values))
    fc.keyframe_points.foreach_set("co", [c for f, v in enumerate(values) for c in (start + f, v)])
    for k in fc.keyframe_points:
        k.interpolation = "LINEAR"
    fc.update()


def _find_rig(lib: Library, rig_hash: int, hint: str | None = None):
    """(Rig, raw bytes) for a rig hash; tries the armature's own rig path first."""
    if hint and f"{hint}.Rig" in lib:
        d = lib.read(f"{hint}.Rig")
        r = brig.parse(d)
        if r.hash == rig_hash:
            return r, d
    for b, e in lib.entries("Rig"):
        d = b.read(e)
        r = brig.parse(d)
        if r.hash == rig_hash:
            return r, d
    return None, None


def label(path: str) -> str:
    """Action name: the clip name, prefixed by the scene/interaction it belongs to."""
    parts = path.split("/")
    i = parts.index("animations") if "animations" in parts else len(parts) - 1
    owner = parts[i - 1] if parts[0] == "interactions" else "/".join(parts[i + 1:-1])
    return f"{owner}/{parts[-1]}" if owner else parts[-1]


def rig_clips(lib: Library, rig_hash: int, own_only: bool = False, own_dir: str = "") -> list[str]:
    """Every AnimResource path whose header names this rig (hash at +4)."""
    import struct
    out = []
    for b, e in lib.entries("AnimResource"):
        if own_only and not e.name.startswith(own_dir):
            continue
        if struct.unpack_from("<Q", b.read(e), 4)[0] == rig_hash:
            out.append(e.name)
    return sorted(out)


def play(arm_obj, action) -> None:
    """Show one imported clip: body action on the armature, its face action on the shape keys."""
    pairs = [(arm_obj, action)] + [
        (c.data.shape_keys, bpy.data.actions.get(action.get(f"bl_face:{c.name}", "")))
        for c in arm_obj.children if c.type == "MESH" and c.data.shape_keys]
    for owner, act in pairs:
        ad = owner.animation_data_create()
        ad.action = act
        if act and act.slots:
            ad.action_slot = act.slots[0]
    sc = bpy.context.scene
    sc.render.fps = action.get("bl_fps", sc.render.fps)
    sc.frame_start, sc.frame_end = 1, max(1, int(action.frame_range[1]))
    sc.frame_set(1)


def apply(lib: Library, path: str, arm_obj, set_scene: bool = True) -> bpy.types.Action:
    a = banim.parse(lib.read(f"{path}.AnimResource"))
    want = arm_obj.get("bl_rig_hash")
    if want and int(want, 16) != a.rig_hash:
        raise ValueError(f"{short(path)} is for rig {a.rig_hash:016x}, armature is {want}")

    rig, rig_data = _find_rig(lib, a.rig_hash, arm_obj.get("bl_path"))
    if rig is None:
        raise ValueError(f"no rig with hash {a.rig_hash:016x}")
    # Components a clip doesn't store keep the rig's local rest pose (engine pre-fills it).
    rest = banim.rest_pose(rig_data)
    bones = arm_obj.data.bones
    # Rest pose in game space, per bone, from the armature itself.
    rest_world = {b.name: AXIS_INV @ b.matrix_local @ AXIS for b in bones}
    parent = {b.name: (b.parent.name if b.parent else None) for b in bones}

    def rest_local(n):
        p = parent[n]
        return rest_world[n] if p is None else rest_world[p].inverted() @ rest_world[n]

    tracks = [rig.names[i] if i < len(rig.names) and rig.names[i] in bones else None for i in a.bone_map]
    frames = [a.sample(f, rest) for f in range(a.frame_count)]

    action = bpy.data.actions.new(label(path))
    action.use_fake_user = True  # survives being unassigned while browsing clips
    cb = _channelbag(arm_obj, action)
    for ti, name in enumerate(tracks):
        if name is None:
            continue
        inv_rest = (AXIS @ rest_local(name) @ AXIS_INV).inverted()
        loc, rot, scl = [], [], []
        prev = None
        for bones_t, _ in frames:
            q, t, s = bones_t[ti]
            basis = inv_rest @ (AXIS @ _trs(q, t, s) @ AXIS_INV)
            l, r, sc = basis.decompose()
            if prev is not None and prev.dot(r) < 0:
                r.negate()  # keep the quaternion on one hemisphere so curves don't flip
            prev = r
            loc.append(l)
            rot.append(r)
            scl.append(sc)
        pb = f'pose.bones["{name}"]'
        for i in range(3):
            _write(cb, f"{pb}.location", i, name, [v[i] for v in loc])
            _write(cb, f"{pb}.scale", i, name, [v[i] for v in scl])
        for i in range(4):
            _write(cb, f"{pb}.rotation_quaternion", i, name, [v[i] for v in rot])
        arm_obj.pose.bones[name].rotation_mode = "QUATERNION"

    # Bones the clip doesn't carry sit at rest, keyed, so every action is a whole pose on its own
    # (switching clips or stacking them in the NLA never leaves a previous clip's pose behind).
    driven = set(filter(None, tracks))
    for pb in arm_obj.pose.bones:
        if pb.name in driven:
            continue
        p = f'pose.bones["{pb.name}"]'
        for i, v in enumerate((0.0, 0.0, 0.0)):
            _write(cb, f"{p}.location", i, pb.name, [v])
        for i, v in enumerate((1.0, 1.0, 1.0)):
            _write(cb, f"{p}.scale", i, pb.name, [v])
        for i, v in enumerate((1.0, 0.0, 0.0, 0.0)):
            _write(cb, f"{p}.rotation_quaternion", i, pb.name, [v])
        pb.rotation_mode = "QUATERNION"

    # Float tracks drive the face's shape keys (named after the rig's flex channels); the shapes
    # a clip doesn't drive are keyed at 0 (the engine memsets floats before sampling).
    for child in arm_obj.children:
        keys = child.data.shape_keys if child.type == "MESH" else None
        if not keys:
            continue
        kact = bpy.data.actions.new(f"{action.name}_face")
        kact.use_fake_user = True
        action[f"bl_face:{child.name}"] = kact.name
        kcb = _channelbag(keys, kact)
        done = set()
        for j, flex in enumerate(a.float_map):
            if flex >= len(rig.flex_names):
                continue
            kname = rig.flex_names[flex].split(":")[-1]
            if kname in keys.key_blocks and kname not in done:
                done.add(kname)
                _write(kcb, f'key_blocks["{kname}"].value', 0, "Face", [fl[j] for _, fl in frames])
        for kb in keys.key_blocks[1:]:
            if kb.name not in done:
                _write(kcb, f'key_blocks["{kb.name}"].value', 0, "Face", [0.0])

    action["bl_path"] = path
    action["bl_rig_hash"] = f"{a.rig_hash:016x}"
    action["bl_fps"] = round(a.fps)
    action.use_frame_range = True
    action.frame_start, action.frame_end = 1, max(2, a.frame_count)
    if set_scene:
        sc = bpy.context.scene
        sc.render.fps = round(a.fps)
        sc.frame_start, sc.frame_end = 1, a.frame_count
    action["bl_events"] = a.events
    return action
