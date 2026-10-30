"""The game's RenderMesh lighting, rebuilt as Blender nodes (EEVEE).

Transcribed from mesh.fxo PS 0662 and the engine constant setup (Docs/Formats/shaders.md §4, §6):

    light  = saturate(N.L) * SunDiffuse * shadow                    (Lambert, no wrap)
           + RSA(0.5 - 0.5 N.up + 1/512, 1/16) * SkyDiffuse          (sky ramp, Weather SkyLight.Gradient)
           + Glow                                                    (incandescence G * GlowColor.w)
           + RimColor * saturate(1 - N.V / w)                        (w = material x weather width)
    color  = albedo * light * AO
           + (pow(saturate(R.L), 1/Roughness) * SunSpecular * SpecColor + env) * gloss.r * fresnel * AO
    fresnel = lerp(1, (1 - N.V)^5, Fresnel)

Colours are linear (the engine raises every colour constant to 2.2 and outputs with 1/2.2;
Blender's 'Standard' view transform does the same encode). Scene-wide terms come from the
Weather and live in scene custom properties read by Attribute (View Layer) nodes; per-material
factors (SunlightStrength, the specular normalisation of the material's exponent bucket, rim
colour/width) are group inputs. The sun's shadow comes from the 'BL Sun' lamp through
Shader-to-RGB: with strength pi a white Diffuse BSDF returns exactly saturate(N.L) * shadow.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

GROUP = "BL RenderMesh"
SUN = "BL Sun"
RSA_IMAGE = "BL RSA Sky"
SUN_DIFFUSE_NORM = 0.0853055  # SPEC_NORM[0], exe 0xE8061C (sub_65C4B0)

SCENE_DEFAULTS = {
    "bl_sun_diffuse": (1.0, 0.95, 0.88),
    "bl_sun_specular": (1.0, 0.95, 0.88),
    "bl_sky_diffuse": (0.32, 0.36, 0.42),
    "bl_rim_color": (0.0, 0.0, 0.0),
    "bl_rim_width": 1.0,
    "bl_sun_dir": (0.35, -0.55, 0.76),  # towards the sun, Blender space
}


def g(c):
    """Engine linear-mode colour constant: pow(c, 2.2) (sub_65C4B0)."""
    return tuple(max(x, 0.0) ** 2.2 for x in c)


def game_to_blender(v):
    return (v[0], -v[2], v[1])


# ------------------------------------------------------------------ scene

def ensure_scene(scene):
    for k, v in SCENE_DEFAULTS.items():
        if k not in scene:
            scene[k] = v
    sun = bpy.data.objects.get(SUN)
    if sun is None:
        sun = bpy.data.objects.new(SUN, bpy.data.lights.new(SUN, "SUN"))
        scene.collection.objects.link(sun)
    sun.data.energy = math.pi
    sun.data.color = (1, 1, 1)
    sun.data.angle = math.radians(1.0)
    aim_sun(scene)
    _ensure_rsa_image()
    world = scene.world or bpy.data.worlds.new("BL World")
    scene.world = world
    world.use_nodes = True
    wn, wl = world.node_tree.nodes, world.node_tree.links
    bg = next(n for n in wn if n.type == "BACKGROUND" and n.name != "BL black")
    out = next(n for n in wn if n.type == "OUTPUT_WORLD")

    def get(name, kind):
        nd = wn.get(name) or wn.new(kind)
        nd.name = name
        return nd
    black = get("BL black", "ShaderNodeBackground")
    black.inputs["Color"].default_value = (0, 0, 0, 1)
    lp = get("BL camera-only", "ShaderNodeLightPath")
    mix = get("BL sky mix", "ShaderNodeMixShader")
    # the world only shows to the camera: lighting is entirely in the materials (+ the sun's shadow)
    wl.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    wl.new(black.outputs[0], mix.inputs[1])
    wl.new(bg.outputs[0], mix.inputs[2])
    wl.new(mix.outputs[0], out.inputs["Surface"])
    scene.view_settings.view_transform = "Standard"
    return sun


def aim_sun(scene):
    sun = bpy.data.objects.get(SUN)
    if sun is not None:
        d = Vector(scene["bl_sun_dir"]).normalized()
        sun.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()


def sync_sun_from_lamp(scene):
    """Rotating 'BL Sun' by hand moves the game's sun direction too."""
    sun = bpy.data.objects.get(SUN)
    if sun is None or "bl_sun_dir" not in scene:
        return
    d = sun.matrix_world.to_3x3() @ Vector((0, 0, 1))
    cur = Vector(scene["bl_sun_dir"])
    if (cur - d).length > 1e-5:
        scene["bl_sun_dir"] = tuple(d)


def _ensure_rsa_image():
    img = bpy.data.images.get(RSA_IMAGE)
    if img is None:
        img = bpy.data.images.new(RSA_IMAGE, 256, 16, alpha=False, float_buffer=True)
        img.pixels.foreach_set([0.5] * (256 * 16 * 4))
        img.colorspace_settings.name = "Non-Color"  # sampler flag clear: raw values (shaders.md §4.10)
        img.use_fake_user = True
    return img


def set_rsa(rsa):
    """Upload a decoded rsalight.RSA into the sky ramp image (rows top-down -> Blender bottom-up)."""
    img = _ensure_rsa_image()
    if img.size[0] != rsa.width or img.size[1] != rsa.height:
        img.scale(rsa.width, rsa.height)
    px = []
    for row in reversed(rsa.rows):
        for r, gg, b in row:
            px += (r, gg, b, 1.0)
    img.pixels.foreach_set(px)
    img.update()


def apply_weather(scene, lib, path: str, elevation: float = 90.0):
    """Weather -> scene lighting, per Weather_SetLightConstants (sub_6F4850)."""
    from .Brutal import rsalight, shaders, textobj
    w = textobj.parse(lib.read(f"{path}.Weather"))
    wc = shaders.weather_constants(w, elevation=elevation)
    ensure_scene(scene)
    scene["bl_sun_diffuse"] = g(tuple(x * SUN_DIFFUSE_NORM for x in wc["sun"]))
    scene["bl_sun_specular"] = g(wc["sun_spec"])  # x material g(SunlightStrength x SPEC_NORM[k])
    scene["bl_sky_diffuse"] = g(wc["sky"])
    scene["bl_rim_color"] = g(wc["rim_color"])
    scene["bl_rim_width"] = wc["rim_width"]
    scene["bl_sun_dir"] = game_to_blender(wc["constants"]["g_vSunLightDir"][:3])
    scene["bl_weather"] = path
    grad = wc.get("rsa_gradient")
    if grad and f"{grad}.Texture" in lib:
        set_rsa(rsalight.parse(lib.read(f"{grad}.Texture")))
    fog = wc["fog_color"]
    bg = next(n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND" and n.name != "BL black")
    bg.inputs["Color"].default_value = (*g(fog), 1)
    aim_sun(scene)
    return wc


# ------------------------------------------------------------------ group

def _attr(nodes, name, x, y):
    a = nodes.new("ShaderNodeAttribute")
    a.attribute_type = "VIEW_LAYER"
    a.attribute_name = name
    a.location = (x, y)
    return a


INPUTS = (
    ("Albedo", "NodeSocketColor", (0.8, 0.8, 0.8, 1)),
    ("Alpha", "NodeSocketFloat", 1.0),
    ("Normal", "NodeSocketVector", None),
    ("AO", "NodeSocketFloat", 1.0),
    ("Sun Scale", "NodeSocketFloat", 1.0),       # g(SunlightStrength)
    ("Gloss", "NodeSocketFloat", 0.0),            # gloss.r * layer spec mask (0 = no Spc/Env)
    ("Spec Color", "NodeSocketColor", (0, 0, 0, 1)),   # g(SpecularColor*SpecularIntensity) * g(SunlightStrength*SPEC_NORM[k])
    ("Spec Exponent", "NodeSocketFloat", 2.5),   # 1 / Roughness
    ("Spec Fresnel", "NodeSocketFloat", 0.5),
    ("Env", "NodeSocketColor", (0, 0, 0, 1)),
    ("Rim Color", "NodeSocketColor", (1, 1, 1, 1)),    # g(RimLightColor * RimLightIntensity)
    ("Rim Width", "NodeSocketFloat", 1.0),       # material RimLightWidth (x weather width)
    ("Glow", "NodeSocketFloat", 0.0),            # G * Incandescence
)


def ensure_group():
    g_ = bpy.data.node_groups.get(GROUP)
    if g_ and g_.get("bl_version") == 2:
        return g_
    if g_:
        bpy.data.node_groups.remove(g_)
    g_ = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    g_["bl_version"] = 2
    for name, kind, default in INPUTS:
        s = g_.interface.new_socket(name, in_out="INPUT", socket_type=kind)
        if default is not None:
            s.default_value = default
    g_.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    n, L = g_.nodes, g_.links
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    gi.location, go.location = (-1600, 0), (1100, 0)

    def node(kind, x, y, **kw):
        nd = n.new(kind)
        nd.location = (x, y)
        for k, v in kw.items():
            setattr(nd, k, v)
        return nd

    def link(a, b):
        L.new(a, b)

    def math_(op, a, b=None, x=0, y=0, clamp=False, c=None):
        m = node("ShaderNodeMath", x, y, operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                link(v, m.inputs[i])
        return m.outputs[0]

    def vec(op, a, b=None, x=0, y=0):
        m = node("ShaderNodeVectorMath", x, y, operation=op)
        link(a, m.inputs[0])
        if b is not None:
            link(b, m.inputs[1])
        return m

    def col(op, a, b, x=0, y=0):
        m = node("ShaderNodeMix", x, y, data_type="RGBA", blend_type=op)
        m.inputs["Factor"].default_value = 1
        for sock, v in (("A", a), ("B", b)):
            if isinstance(v, (int, float)):
                m.inputs[sock].default_value = (v, v, v, 1)
            else:
                link(v, m.inputs[sock])
        return m.outputs["Result"]

    N = vec("NORMALIZE", gi.outputs["Normal"], None, -1350, -300).outputs[0]
    geo = node("ShaderNodeNewGeometry", -1600, -500)
    V = geo.outputs["Incoming"]
    sun_dir = _attr(n, "bl_sun_dir", -1350, -800).outputs["Vector"]

    # sun: saturate(N.L) * shadow (Blender sun, strength pi) * SunDiffuse * g(SunlightStrength)
    dif = node("ShaderNodeBsdfDiffuse", -1100, 600)
    dif.inputs["Color"].default_value = (1, 1, 1, 1)
    link(N, dif.inputs["Normal"])
    s2rgb = node("ShaderNodeShaderToRGB", -900, 600)
    link(dif.outputs[0], s2rgb.inputs[0])
    sun_term = col("MULTIPLY", s2rgb.outputs["Color"], _attr(n, "bl_sun_diffuse", -900, 450).outputs["Color"], -650, 550)
    sun_term = col("MULTIPLY", sun_term, gi.outputs["Sun Scale"], -450, 550)

    # sky: RSA(0.5 - 0.5*N.up + 1/512, 1/16) * SkyDiffuse
    sep = node("ShaderNodeSeparateXYZ", -1100, 300)
    link(N, sep.inputs[0])
    u = math_("MULTIPLY_ADD", sep.outputs["Z"], -0.5, -900, 300, c=0.5 + 1.0 / 512.0)
    uv = node("ShaderNodeCombineXYZ", -750, 300)
    link(u, uv.inputs["X"])
    uv.inputs["Y"].default_value = 1.0 - 1.0 / 16.0  # Blender images are bottom-up
    rsa = node("ShaderNodeTexImage", -600, 300, image=_ensure_rsa_image(), extension="EXTEND",
               interpolation="Linear")
    link(uv.outputs[0], rsa.inputs["Vector"])
    sky_term = col("MULTIPLY", rsa.outputs["Color"], _attr(n, "bl_sky_diffuse", -600, 100).outputs["Color"], -350, 300)

    # rim: RimColor(weather) * RimColor(material) * saturate(1 - N.V / w), w = mat x weather width
    ndv = vec("DOT_PRODUCT", N, V, -1100, 0).outputs["Value"]
    ndv_s = math_("MAXIMUM", ndv, 0.0, -950, 0)
    w = math_("MULTIPLY", gi.outputs["Rim Width"], _attr(n, "bl_rim_width", -1100, -150).outputs["Fac"], -950, -150)
    rim_k = math_("SUBTRACT", 1.0, math_("DIVIDE", ndv_s, w, -800, -50), -650, -50, clamp=True)
    rim = col("MULTIPLY", _attr(n, "bl_rim_color", -650, 100).outputs["Color"], gi.outputs["Rim Color"], -500, 50)
    rim = col("MULTIPLY", rim, rim_k, -350, 0)

    glow = node("ShaderNodeCombineColor", -350, -150)
    for ch in ("Red", "Green", "Blue"):
        link(gi.outputs["Glow"], glow.inputs[ch])
    light = col("ADD", sun_term, sky_term, -150, 450)
    light = col("ADD", light, rim, 0, 300)
    light = col("ADD", light, glow.outputs[0], 150, 200)
    ao = node("ShaderNodeCombineColor", 150, 0)
    for ch in ("Red", "Green", "Blue"):
        link(gi.outputs["AO"], ao.inputs[ch])
    color = col("MULTIPLY", col("MULTIPLY", gi.outputs["Albedo"], light, 300, 200), ao.outputs[0], 450, 150)

    # spec: pow(saturate(R.L), exp) * SunSpecular * SpecColor (+ env) * gloss * fresnel * AO
    negv = vec("SCALE", V, None, -1350, -1000)
    negv.inputs["Scale"].default_value = -1.0
    refl = vec("REFLECT", negv.outputs[0], N, -1150, -1000)
    rdl = math_("MAXIMUM", vec("DOT_PRODUCT", refl.outputs[0], sun_dir, -950, -1000).outputs["Value"], 0.0, -800, -1000)
    pw = math_("POWER", rdl, gi.outputs["Spec Exponent"], -650, -1000)
    shadow = node("ShaderNodeSeparateColor", -800, -850)
    link(s2rgb.outputs["Color"], shadow.inputs[0])
    lit = math_("GREATER_THAN", shadow.outputs["Red"], 1e-4, -650, -850)
    pw = math_("MULTIPLY", pw, lit, -500, -950)
    one_m = math_("SUBTRACT", 1.0, ndv_s, -950, -1200)
    f5 = math_("POWER", one_m, 5.0, -800, -1200)
    fres = node("ShaderNodeMix", -650, -1200, data_type="FLOAT")
    link(gi.outputs["Spec Fresnel"], fres.inputs["Factor"])
    fres.inputs["A"].default_value = 1.0
    link(f5, fres.inputs["B"])
    spec = col("MULTIPLY", _attr(n, "bl_sun_specular", -500, -750).outputs["Color"], pw, -350, -900)
    spec = col("MULTIPLY", spec, gi.outputs["Spec Color"], -200, -900)
    spec = col("ADD", spec, gi.outputs["Env"], -50, -900)
    mask = math_("MULTIPLY", math_("MULTIPLY", gi.outputs["Gloss"], fres.outputs["Result"], -350, -1150),
                 gi.outputs["AO"], -200, -1150)
    spec = col("MULTIPLY", spec, mask, 100, -900)
    total = col("ADD", color, spec, 650, 0)

    em = node("ShaderNodeEmission", 800, -150)
    link(total, em.inputs["Color"])
    tr = node("ShaderNodeBsdfTransparent", 800, -300)
    mix = node("ShaderNodeMixShader", 950, -150)
    link(gi.outputs["Alpha"], mix.inputs[0])
    link(tr.outputs[0], mix.inputs[1])
    link(em.outputs[0], mix.inputs[2])
    link(mix.outputs[0], go.inputs["Shader"])
    return g_
