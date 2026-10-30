"""Build Blender data from Brutal Legend resources."""

from __future__ import annotations

import os

import bpy
from mathutils import Matrix, Vector

from .Brutal import material as bmat
from .Brutal import mesh as bmesh_fmt
from .Brutal import rig as brig
from .Brutal import texture as btex
from .Brutal.library import Library

# Game space is Y-up right-handed, characters facing +Z (proven on a01_avatar: eyes at +Z,
# Lf_* bones at +X). Rotating +90 deg about X gives Blender's Z-up with characters facing -Y.
AXIS = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
AXIS_INV = AXIS.inverted()


def conv(v):
    return (v[0], -v[2], v[1])


def short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- textures

def load_texture(lib: Library, path: str, cache: str, non_color=False):
    name = short(path)
    img = bpy.data.images.get(name)
    if img and img.get("bl_path") == path:
        return img
    data = lib.get(f"{path}.Texture")
    if data is None:
        return None
    out = os.path.join(cache, *path.split("/")) + ".dds"
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(btex.dds(data))
    img = bpy.data.images.load(out, check_existing=True)
    img.name = name
    img["bl_path"] = path
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


# ---------------------------------------------------------------- materials

def _tex_node(nt, img, x, y, label):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = img
    n.label = label
    n.location = (x, y)
    return n


def dxt5nm_group():
    """DXT5nm decode: X in alpha, Y in green, Z rebuilt as sqrt(1 - x^2 - y^2)."""
    g = bpy.data.node_groups.get("BL DXT5nm")
    if g:
        return g
    g = bpy.data.node_groups.new("BL DXT5nm", "ShaderNodeTree")
    g.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
    g.interface.new_socket("Alpha", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    n, ln = g.nodes, g.links
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    sep = n.new("ShaderNodeSeparateColor")
    ln.new(gi.outputs["Color"], sep.inputs["Color"])
    xy = n.new("ShaderNodeCombineXYZ")
    ln.new(gi.outputs["Alpha"], xy.inputs["X"])
    ln.new(sep.outputs["Green"], xy.inputs["Y"])
    v = n.new("ShaderNodeVectorMath")  # [0,1] -> [-1,1]
    v.operation = "MULTIPLY_ADD"
    v.inputs[1].default_value = (2, 2, 0)
    v.inputs[2].default_value = (-1, -1, 0)
    ln.new(xy.outputs[0], v.inputs[0])
    dot = n.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    ln.new(v.outputs[0], dot.inputs[0])
    ln.new(v.outputs[0], dot.inputs[1])
    z = n.new("ShaderNodeMath")
    z.operation = "SUBTRACT"
    z.use_clamp = True
    z.inputs[0].default_value = 1
    ln.new(dot.outputs["Value"], z.inputs[1])
    sq = n.new("ShaderNodeMath")
    sq.operation = "SQRT"
    ln.new(z.outputs[0], sq.inputs[0])
    sep2 = n.new("ShaderNodeSeparateXYZ")
    ln.new(v.outputs[0], sep2.inputs[0])
    out = n.new("ShaderNodeCombineXYZ")
    ln.new(sep2.outputs["X"], out.inputs["X"])
    ln.new(sep2.outputs["Y"], out.inputs["Y"])
    ln.new(sq.outputs[0], out.inputs["Z"])
    back = n.new("ShaderNodeVectorMath")  # [-1,1] -> [0,1]
    back.operation = "MULTIPLY_ADD"
    back.inputs[1].default_value = (0.5, 0.5, 0.5)
    back.inputs[2].default_value = (0.5, 0.5, 0.5)
    ln.new(out.outputs[0], back.inputs[0])
    ln.new(back.outputs[0], go.inputs["Color"])
    return g


def build_material(lib: Library, path: str, cache: str, opts) -> bpy.types.Material:
    name = short(path)
    mat = bpy.data.materials.get(name)
    if mat and mat.get("bl_path") == path:
        return mat
    mat = bpy.data.materials.new(name)
    mat["bl_path"] = path
    data = lib.get(f"{path}.Material")
    if data is None:
        return mat
    p = bmat.parse(data)
    for k, v in p.items():  # keep the raw engine parameters on the material
        if isinstance(v, (int, float, str)):
            mat[f"bl_{k}"] = v
    if not opts.textures:
        return mat

    if getattr(opts, "shading", "GAME") == "GAME":
        from . import gamemat

        def tex(tpath, non_color):
            return load_texture(lib, tpath, cache, non_color=non_color)

        def uv_for(second, tiling, x, y):
            uvn = mat.node_tree.nodes.new("ShaderNodeUVMap")
            uvn.uv_map = "UV1" if second else "UV0"
            uvn.location = (x - 200, y)
            if tiling == 1:
                return uvn.outputs["UV"]
            m = mat.node_tree.nodes.new("ShaderNodeMapping")
            m.location = (x, y)
            m.inputs["Scale"].default_value = (tiling, tiling, 1)
            mat.node_tree.links.new(uvn.outputs["UV"], m.inputs["Vector"])
            return m.outputs["Vector"]

        return gamemat.build(mat, p, tex, uv_for)

    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    uv_main = nt.nodes.new("ShaderNodeUVMap")
    uv_main.uv_map = "UV0"
    uv_main.location = (-1200, 0)

    def tiled(img, tiling, x, y, label):
        n = _tex_node(nt, img, x, y, label)
        if tiling and tiling != 1:
            m = nt.nodes.new("ShaderNodeMapping")
            m.location = (x - 220, y)
            m.inputs["Scale"].default_value = (tiling, tiling, 1)
            nt.links.new(uv_main.outputs["UV"], m.inputs["Vector"])
            nt.links.new(m.outputs["Vector"], n.inputs["Vector"])
        else:
            nt.links.new(uv_main.outputs["UV"], n.inputs["Vector"])
        return n

    color = p.get("DiffuseColor", (1, 1, 1))
    bsdf.inputs["Base Color"].default_value = (*color[:3], 1)
    if isinstance(p.get("Roughness"), float):
        bsdf.inputs["Roughness"].default_value = p["Roughness"]

    diff = p.get("DiffuseTexture")
    img = load_texture(lib, diff, cache) if diff else None
    if img:
        t = tiled(img, p.get("DiffuseTiling", 1), -600, 300, "Diffuse")
        base = t.outputs["Color"]
        ramp = p.get("Ramp1Texture")
        rimg = load_texture(lib, ramp, cache) if ramp and p.get("ShaderName") == "RenderHair" else None
        if rimg:
            # RenderHair: the diffuse map is a grey index into a colour ramp; its alpha cuts the cards
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            sep.location = (-380, 500)
            nt.links.new(base, sep.inputs["Color"])
            uv = nt.nodes.new("ShaderNodeCombineXYZ")
            uv.location = (-200, 500)
            uv.inputs["Y"].default_value = 0.5
            nt.links.new(sep.outputs["Red"], uv.inputs["X"])
            r = _tex_node(nt, rimg, -20, 500, "Ramp1")
            r.extension = "EXTEND"
            nt.links.new(uv.outputs["Vector"], r.inputs["Vector"])
            base = r.outputs["Color"]
            nt.links.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
            mat.surface_render_method = "DITHERED"
        if color[:3] != (1, 1, 1):
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1
            mix.inputs["B"].default_value = (*color[:3], 1)
            mix.location = (-300, 300)
            nt.links.new(base, mix.inputs["A"])
            base = mix.outputs["Result"]
        nt.links.new(base, bsdf.inputs["Base Color"])
        if p.get("BlendMode") in ("kBLEND_Alpha", "kBLEND_BinaryAlpha"):
            alpha = t.outputs["Alpha"]
            if p.get("BlendMode") == "kBLEND_BinaryAlpha":
                cut = nt.nodes.new("ShaderNodeMath")
                cut.operation = "GREATER_THAN"
                cut.inputs[1].default_value = 0.5
                cut.location = (-300, 100)
                nt.links.new(alpha, cut.inputs[0])
                alpha = cut.outputs[0]
            nt.links.new(alpha, bsdf.inputs["Alpha"])

    nrm = p.get("Normal1Texture")
    img = load_texture(lib, nrm, cache, non_color=True) if nrm else None
    if img:
        t = tiled(img, p.get("Normal1Tiling", 1), -900, -300, "Normal1")
        dec = nt.nodes.new("ShaderNodeGroup")
        dec.node_tree = dxt5nm_group()
        dec.location = (-560, -300)
        nt.links.new(t.outputs["Color"], dec.inputs["Color"])
        nt.links.new(t.outputs["Alpha"], dec.inputs["Alpha"])
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UV0"
        nm.location = (-300, -300)
        nm.inputs["Strength"].default_value = float(p.get("Normal1Scale", 1) or 1)
        nt.links.new(dec.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])

    gloss = p.get("GlossTexture")
    img = load_texture(lib, gloss, cache, non_color=True) if gloss else None
    if img:
        t = tiled(img, p.get("GlossTiling", 1), -900, 0, "Gloss")
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1
        inv.location = (-300, 0)
        nt.links.new(t.outputs["Color"], inv.inputs[1])
        nt.links.new(inv.outputs[0], bsdf.inputs["Roughness"])

    inc = p.get("IncandescenceTexture")
    img = load_texture(lib, inc, cache) if inc else None
    if img:
        t = tiled(img, 1, -900, -600, "Incandescence")
        nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = max(1.0, float(p.get("Incandescence", 1) or 1))

    # Layer textures are blended in-engine by a vertex color channel that is not pinned down yet:
    # load them so they are at hand, but leave them unwired.
    for i, slot in enumerate(("Layer1Texture", "Layer2Texture", "DetailTexture")):
        lp = p.get(slot)
        img = load_texture(lib, lp, cache) if lp else None
        if img:
            tiled(img, p.get(slot.replace("Texture", "Tiling"), 1), -1600, 400 - 300 * i, slot)

    # Interim specular until the game's shader is transcribed (Docs/Formats/shaders.md):
    # the engine's highlights are much weaker than Principled's defaults.
    bsdf.inputs["Specular IOR Level"].default_value = 0.25 * float(p.get("SpecularIntensity", 1) or 0)

    mat.use_backface_culling = not p.get("DoubleSided")
    _blend_mode(mat, bsdf, p.get("BlendMode"))
    return mat


def _blend_mode(mat, bsdf, mode):
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    if mode == "kBLEND_Alpha":
        mat.surface_render_method = "BLENDED"
    elif mode == "kBLEND_BinaryAlpha":
        mat.surface_render_method = "DITHERED"
    elif mode in ("kBLEND_Additive", "kBLEND_Subtractive"):
        # colour is added to (subtracted from) what is behind: transparent + emission / tinted transparency
        mat.surface_render_method = "BLENDED"
        src = bsdf.inputs["Base Color"]
        col = src.links[0].from_socket if src.links else None
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        tr.location = (out.location.x - 200, out.location.y - 200)
        if mode == "kBLEND_Additive":
            em = nt.nodes.new("ShaderNodeEmission")
            em.location = (out.location.x - 200, out.location.y - 350)
            if col:
                nt.links.new(col, em.inputs["Color"])
            else:
                em.inputs["Color"].default_value = src.default_value
            add = nt.nodes.new("ShaderNodeAddShader")
            add.location = (out.location.x - 100, out.location.y - 250)
            nt.links.new(tr.outputs[0], add.inputs[0])
            nt.links.new(em.outputs[0], add.inputs[1])
            nt.links.new(add.outputs[0], out.inputs["Surface"])
        else:
            inv = nt.nodes.new("ShaderNodeInvert")
            inv.location = (out.location.x - 400, out.location.y - 200)
            if col:
                nt.links.new(col, inv.inputs["Color"])
            else:
                inv.inputs["Color"].default_value = src.default_value
            nt.links.new(inv.outputs[0], tr.inputs["Color"])
            nt.links.new(tr.outputs[0], out.inputs["Surface"])


# ---------------------------------------------------------------- skeleton

def build_armature(rig: brig.Rig, name: str, col) -> bpy.types.Object:
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    col.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    world = [AXIS @ Matrix([ib[0:4], ib[4:8], ib[8:12], ib[12:16]]).transposed().inverted() @ AXIS_INV
             for ib in rig.inverse_bind]
    bones = []
    for i, nm in enumerate(rig.names):
        eb = arm.edit_bones.new(nm)
        m = world[i]
        head = m.to_translation()
        kids = [j for j, p in enumerate(rig.parents) if p == i]
        length = (world[kids[0]].to_translation() - head).length if len(kids) == 1 else 0.05
        eb.head = head
        eb.tail = head + Vector((0, max(length, 0.01), 0))
        eb.matrix = m
        eb.length = max(length, 0.01)
        bones.append(eb)
    for i, p in enumerate(rig.parents):
        if p >= 0:
            bones[i].parent = bones[p]
    bpy.ops.object.mode_set(mode="OBJECT")
    obj["bl_rig_hash"] = f"{rig.hash:016x}"
    obj["bl_rest"] = [list(x) for m in world for x in m]  # exact rest, for animation import
    return obj


# ---------------------------------------------------------------- mesh

def build_mesh(lib: Library, path: str, opts, col, cache: str):
    if getattr(opts, "shading", "GAME") == "GAME":
        from . import gameshader
        gameshader.ensure_scene(bpy.context.scene)
    m = bmesh_fmt.parse(lib.read(f"{path}.Mesh"))
    rig = None
    rig_data = lib.get(f"{path}.Rig")
    if rig_data and opts.skeleton:
        rig = brig.parse(rig_data)

    # 'nomaterial' is the engine's magenta/yellow missing-material checker (misc_defaultmat);
    # its submeshes are helper geometry. Keep their vertices (morph/weight indexing), drop faces.
    hidden = set()
    if getattr(opts, "skip_nomaterial", True):
        hidden = {i for i, mp in enumerate(m.materials) if mp.endswith("/nomaterial")}
    verts, normals, uv0, uv1, c0, c1, faces, face_mat = [], [], [], [], [], [], [], []
    weights = []  # per vertex: [(bone, w), ...]
    for s in m.submeshes:
        base = len(verts)
        verts += [conv(p) for p in s.positions]
        normals += [conv(n) for n in s.normals]
        uv0 += s.uv0
        uv1 += s.uv1
        c0 += s.color0
        c1 += s.color1
        if s.bone_indices:
            for bi, bw in zip(s.bone_indices, s.bone_weights):
                weights.append([(s.bone_palette[i], w) for i, w in zip(bi, bw)
                                if w > 0 and i < len(s.bone_palette)])
        else:
            weights += [[] for _ in s.positions]
        if s.material in hidden:
            continue
        for a, b, c in s.triangles():
            faces.append((base + a, base + b, base + c))
            face_mat.append(s.material)

    name = short(path)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.polygons.foreach_set("material_index", face_mat)
    me.polygons.foreach_set("use_smooth", [True] * len(faces))
    for layer, data in (("UV0", uv0), ("UV1", uv1)):
        uvl = me.uv_layers.new(name=layer)
        for poly in me.polygons:
            for li in poly.loop_indices:
                u, v = data[me.loops[li].vertex_index]
                uvl.data[li].uv = (u, 1.0 - v)
    for layer, data in (("Color0", c0), ("Color1", c1)):
        # FLOAT_COLOR keeps the raw byte/255 values: these are masks, AO and tints, not sRGB colours
        ca = me.color_attributes.new(layer, "FLOAT_COLOR", "POINT")
        ca.data.foreach_set("color", [x for c in data for x in c])
    me.validate(clean_customdata=False)
    me.update()
    me.normals_split_custom_set_from_vertices(normals)

    for mp in m.materials:
        me.materials.append(build_material(lib, mp, cache, opts) if opts.materials else None)

    obj = bpy.data.objects.new(name, me)
    col.objects.link(obj)
    obj["bl_path"] = path

    if opts.morphs and any(s.morph_frames for s in m.submeshes):
        obj.shape_key_add(name="Basis", from_mix=False)
        base = 0
        for s in m.submeshes:
            for fi, fr in enumerate(s.morph_frames):
                flex = s.morph_order[fi] if fi < len(s.morph_order) else fi
                kname = rig.flex_names[flex].split(":")[-1] if rig and flex < len(rig.flex_names) else f"Frame_{fi}"
                sk = obj.shape_key_add(name=kname, from_mix=False)
                sk.value = 0.0  # Blender 5.x creates keys at 1.0: the face would wear every shape
                sk.slider_min, sk.slider_max = -1.0, 1.0  # anim float tracks go negative (to -0.56)
                for v, d in zip(fr.vertices, fr.dpos):
                    co = sk.data[base + v].co
                    dd = conv(d)
                    sk.data[base + v].co = (co[0] + dd[0], co[1] + dd[1], co[2] + dd[2])
            base += s.vertex_count

    arm_obj = None
    if rig:
        arm_obj = build_armature(rig, name + "_rig", col)
        arm_obj["bl_path"] = path
        for nm in rig.names:
            obj.vertex_groups.new(name=nm)
        for vi, ws in enumerate(weights):
            for bone, w in ws:
                obj.vertex_groups[bone].add([vi], w, "ADD")
        mod = obj.modifiers.new("Armature", "ARMATURE")
        mod.object = arm_obj
        obj.parent = arm_obj
    elif m.bone is not None:
        obj["bl_attach_bone"] = m.bone
    if hidden:
        _drop_loose_verts(me)
    return obj, arm_obj


def _drop_loose_verts(me):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)  # keeps shape-key layers, vertex groups and attributes
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
