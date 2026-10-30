"""Materials that reproduce the game's shaders (RenderMesh / RenderHair), per
Docs/Formats/shaders.md. The lighting itself lives in the 'BL RenderMesh' group (gameshader.py);
this module builds the per-material inputs exactly as the pixel shaders form them:
albedo + layers + vertex tint, DXT5nm normals, gloss, glow, detail, alpha.

Vertex colours are FLOAT_COLOR attributes holding the raw D3DCOLOR bytes / 255:
Color0 = (layer1 mask, layer2 mask, hair comb, AO + tangent sign), Color1 = (tint rgb, alpha).
"""

from __future__ import annotations

from . import gameshader


def engine_constants(p: dict, damage: float = 0.0) -> dict:
    """Per-material inputs of the 'BL RenderMesh' group, from the engine's own constant setup
    (Brutal.shaders.material_constants = Material_SetShaderConstants, sub_65C4B0)."""
    from .Brutal import shaders
    mc = shaders.material_constants(p, damage=damage)
    k = mc["constants"]
    flags = set(mc["flags"])
    ss = float(p.get("SunlightStrength", 1.0) or 0.0)
    spec_norm = shaders.SPEC_NORM[mc["specular_bucket"]]
    spc = "Spc" in flags
    return {
        "flags": flags,
        "technique": mc["technique"],
        "samplers": mc["samplers"],
        "diffuse": tuple(k["g_vDiffuseColor"]),
        "layers": tuple(k["g_vLayerFloats"]),
        "layer_blend": tuple(k["g_vLayerBlendFloats"]),
        "map_scale": tuple(k["g_vMapScaleFloats"]),
        "sun_scale": gameshader.g((ss,))[0],
        "spec_color": tuple(c * gameshader.g((ss * spec_norm,))[0] for c in k["g_vSpecularColor"]) if spc else (0, 0, 0),
        "spec_exponent": k["g_vSpecularConstants"][0],
        "spec_fresnel": k["g_vSpecularConstants"][2],
        "gloss_used": spc or "Env" in flags,
        "rim_color": gameshader.g(tuple(c * float(p.get("RimLightIntensity", 1.0) or 0.0)
                                        for c in tuple(p.get("RimLightColor", (1, 1, 1)))[:3])),
        "rim_width": float(p.get("RimLightWidth", 1.0) or 1.0),
        "glow_w": k["g_vGlowColor"][3],
        "glow_rgb": tuple(k["g_vGlowColor"][:3]),
        "additive_use_spec": bool(k.get("g_bAdditiveUseSpec")),
        "transparency": tuple(k["g_vTransparencyFloats"]),
    }


class _B:
    """Tiny node-building helper."""

    def __init__(self, mat):
        self.mat = mat
        self.nt = mat.node_tree
        self.n, self.L = self.nt.nodes, self.nt.links

    def node(self, kind, x, y, **props):
        nd = self.n.new(kind)
        nd.location = (x, y)
        for k, v in props.items():
            setattr(nd, k, v)
        return nd

    def math(self, op, a, b=None, x=0, y=0, clamp=False, c=None):
        m = self.node("ShaderNodeMath", x, y, operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                self.L.new(v, m.inputs[i])
        return m.outputs[0]

    def mix(self, blend, fac, a, b, x=0, y=0, clamp=False):
        m = self.node("ShaderNodeMix", x, y, data_type="RGBA", blend_type=blend, clamp_result=clamp)
        for sock, v in (("Factor", fac), ("A", a), ("B", b)):
            if isinstance(v, (int, float)):
                m.inputs[sock].default_value = v
            elif isinstance(v, tuple):
                m.inputs[sock].default_value = (*v[:3], 1) if sock != "Factor" else v
            else:
                self.L.new(v, m.inputs[sock])
        return m.outputs["Result"]

    def sep(self, color, x, y):
        s = self.node("ShaderNodeSeparateColor", x, y)
        self.L.new(color, s.inputs[0])
        return s.outputs


def build(mat, p: dict, tex, uv_for, damage: float = 0.0):
    """tex(path, non_color) -> image or None; uv_for(second_uv_flag, tiling, x, y) -> vector socket."""
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    b = _B(mat)
    out = b.node("ShaderNodeOutputMaterial", 900, 0)
    c = engine_constants(p, damage)
    mat["bl_technique"] = c["technique"]
    c0 = b.sep(b.node("ShaderNodeVertexColor", -2200, -900, layer_name="Color0").outputs["Color"], -2000, -900)
    c0a = b.node("ShaderNodeVertexColor", -2200, -1100, layer_name="Color0").outputs["Alpha"]
    c1n = b.node("ShaderNodeVertexColor", -2200, -1250, layer_name="Color1")

    def sample(slot, second_key, tiling_key, x, y, non_color=False, tiling=None):
        path = p.get(slot)
        img = tex(path, non_color) if path else None
        if img is None:
            return None
        t = b.node("ShaderNodeTexImage", x, y, image=img, label=slot)
        uv = uv_for(bool(p.get(second_key)), tiling if tiling is not None else float(p.get(tiling_key, 1) or 1), x - 250, y)
        b.L.new(uv, t.inputs["Vector"])
        return t

    if p.get("ShaderName") == "RenderHair":
        return _hair(b, out, p, sample, c1n, c0a)

    # ---- albedo: tex * DiffuseColor, layers, * COLOR1.rgb   (PS 0662 / 0885 / 0132)
    dcol = c["diffuse"]  # g(DiffuseColor): linear
    diffuse_tiling = float(p.get("DiffuseTiling", 1) or 1)
    alb_t = sample("DiffuseTexture", None, None, -1500, 400, tiling=diffuse_tiling)
    base = b.mix("MULTIPLY", 1.0, alb_t.outputs["Color"], dcol, -1200, 400) if alb_t else None
    if base is None:
        rgb = b.node("ShaderNodeRGB", -1200, 400)
        rgb.outputs[0].default_value = (*dcol, 1)
        base = rgb.outputs[0]
    weights = []
    for i, mask in ((1, c0["Red"]), (2, c0["Green"])):
        strength = c["layers"][i - 1]  # Layer{i}Strength x runtime scale (Layer2: damage, 0 = clean)
        lt = sample(f"Layer{i}Texture", f"Layer{i}SecondUV", f"Layer{i}Tiling", -1500, 100 - 300 * i,
                    tiling=float(p.get(f"Layer{i}Tiling", 1) or 1))
        if lt is None or strength == 0:
            weights.append(None)
            continue
        inv = b.math("SUBTRACT", 1.0, mask, -1200, -100 * i)
        w = b.math("MULTIPLY", b.math("MULTIPLY", lt.outputs["Alpha"], inv, -1050, -100 * i), strength, -900, -100 * i)
        weights.append((w, lt))
        if c["layer_blend"][i - 1] != 0:
            # saturate(base + w * (2L - 1))
            two = b.node("ShaderNodeVectorMath", -1050, 50 - 300 * i, operation="MULTIPLY_ADD")
            two.inputs[1].default_value = (2, 2, 2)
            two.inputs[2].default_value = (-1, -1, -1)
            b.L.new(lt.outputs["Color"], two.inputs[0])
            sc = b.node("ShaderNodeVectorMath", -900, 50 - 300 * i, operation="SCALE")
            b.L.new(two.outputs[0], sc.inputs[0])
            b.L.new(w, sc.inputs["Scale"])
            base = b.mix("ADD", 1.0, base, sc.outputs[0], -750, 300 - 100 * i, clamp=True)
        else:
            base = b.mix("MIX", w, base, lt.outputs["Color"], -750, 300 - 100 * i)
    albedo = b.mix("MULTIPLY", 1.0, base, c1n.outputs["Color"], -550, 300)

    # ---- AO = |2*COLOR0.a - 1|
    ao = b.math("ABSOLUTE", b.math("MULTIPLY_ADD", c0a, 2.0, -1700, -1100, c=-1.0), None, -1500, -1100)

    # ---- normals: DXT5nm, xy = n1*k1 + n2*k2, z rebuilt (PS 0381 / 0662)
    normal = None
    xy = None
    for i in (1, 2):
        nt_ = sample(f"Normal{i}Texture", f"Normal{i}SecondUV", f"Normal{i}Tiling", -1500, -1400 - 300 * i,
                     non_color=True)
        if nt_ is None:
            continue
        k = c["map_scale"][i - 1]
        if k == 0:
            continue
        comb = b.node("ShaderNodeCombineXYZ", -1250, -1400 - 300 * i)
        b.L.new(nt_.outputs["Alpha"], comb.inputs["X"])
        b.L.new(b.sep(nt_.outputs["Color"], -1350, -1500 - 300 * i)["Green"], comb.inputs["Y"])
        v = b.node("ShaderNodeVectorMath", -1100, -1400 - 300 * i, operation="MULTIPLY_ADD")
        v.inputs[1].default_value = (2 * k, 2 * k, 0)
        v.inputs[2].default_value = (-k, -k, 0)
        b.L.new(comb.outputs[0], v.inputs[0])
        term = v.outputs[0]
        if p.get(f"Normal{i}UseLayerAlpha") and weights[i - 1]:
            s = b.node("ShaderNodeVectorMath", -950, -1400 - 300 * i, operation="SCALE")
            b.L.new(term, s.inputs[0])
            b.L.new(weights[i - 1][0], s.inputs["Scale"])
            term = s.outputs[0]
        if xy is None:
            xy = term
        else:
            add = b.node("ShaderNodeVectorMath", -800, -1600, operation="ADD")
            b.L.new(xy, add.inputs[0])
            b.L.new(term, add.inputs[1])
            xy = add.outputs[0]
    if xy is not None:
        dot = b.node("ShaderNodeVectorMath", -650, -1600, operation="DOT_PRODUCT")
        b.L.new(xy, dot.inputs[0])
        b.L.new(xy, dot.inputs[1])
        z = b.math("SQRT", b.math("SUBTRACT", 1.0, dot.outputs["Value"], -500, -1700, clamp=True), None, -350, -1700)
        sx = b.node("ShaderNodeSeparateXYZ", -500, -1550)
        b.L.new(xy, sx.inputs[0])
        cz = b.node("ShaderNodeCombineXYZ", -200, -1600)
        b.L.new(sx.outputs["X"], cz.inputs["X"])
        b.L.new(sx.outputs["Y"], cz.inputs["Y"])
        b.L.new(z, cz.inputs["Z"])
        back = b.node("ShaderNodeVectorMath", -50, -1600, operation="MULTIPLY_ADD")
        back.inputs[1].default_value = (0.5, 0.5, 0.5)
        back.inputs[2].default_value = (0.5, 0.5, 0.5)
        b.L.new(cz.outputs[0], back.inputs[0])
        nm = b.node("ShaderNodeNormalMap", 100, -1600, uv_map="UV0")
        b.L.new(back.outputs[0], nm.inputs["Color"])
        normal = nm.outputs["Normal"]

    g = b.node("ShaderNodeGroup", 600, 0)
    g.node_tree = gameshader.ensure_group()
    b.L.new(albedo, g.inputs["Albedo"])
    b.L.new(ao, g.inputs["AO"])
    if normal is not None:
        b.L.new(normal, g.inputs["Normal"])
    else:
        b.L.new(b.node("ShaderNodeNewGeometry", 300, -500).outputs["Normal"], g.inputs["Normal"])

    g.inputs["Sun Scale"].default_value = c["sun_scale"]
    g.inputs["Rim Color"].default_value = (*c["rim_color"], 1)
    g.inputs["Rim Width"].default_value = c["rim_width"]

    # ---- specular (Spc/Env): gloss.r masks spec and env; fresnel in the group
    if c["gloss_used"]:
        gt = sample("GlossTexture", "GlossSecondUV", "GlossTiling", -1500, -600, non_color=False)
        gloss = b.sep(gt.outputs["Color"], -1200, -600)["Red"] if gt else 1.0
        if isinstance(gloss, float):
            g.inputs["Gloss"].default_value = gloss
        else:
            b.L.new(gloss, g.inputs["Gloss"])
        g.inputs["Spec Color"].default_value = (*c["spec_color"], 1)
        g.inputs["Spec Exponent"].default_value = c["spec_exponent"]
        g.inputs["Spec Fresnel"].default_value = c["spec_fresnel"]
    else:
        g.inputs["Gloss"].default_value = 0.0

    # ---- glow (Glw): G = glow.r ; incandescence G * GlowColor.w   (translucence: see shaders.md)
    # ---- glow: light += G * GlowColor.w (Glw; G = g_samGlow.r), else the uniform GlowColor.w
    glow_path = c["samplers"].get("g_samGlow") or ""
    glow_t = None
    if "Glw" in c["flags"] and not glow_path.startswith("Renderer/"):
        img = tex(glow_path, True)
        if img is not None:
            glow_t = b.node("ShaderNodeTexImage", -1500, -2300, image=img, label="Glow")
            b.L.new(uv_for(False, 1.0, -1750, -2300), glow_t.inputs["Vector"])
    if glow_t is not None:
        gw = b.math("MULTIPLY", b.sep(glow_t.outputs["Color"], -1200, -2300)["Red"], c["glow_w"], -1000, -2300)
        b.L.new(gw, g.inputs["Glow"])
    else:
        g.inputs["Glow"].default_value = c["glow_w"] if "Glw" not in c["flags"] else 0.0

    # ---- alpha
    mode = p.get("BlendMode")
    shader = g.outputs["Shader"]
    if alb_t is not None and mode in ("kBLEND_Alpha", "kBLEND_BinaryAlpha"):
        a = alb_t.outputs["Alpha"]
        if mode == "kBLEND_BinaryAlpha":
            a = b.math("GREATER_THAN", a, 0.5, 300, 300)
            mat.surface_render_method = "DITHERED"
        else:
            a = b.math("MULTIPLY", a, c1n.outputs["Alpha"], 300, 300)
            mat.surface_render_method = "BLENDED"
        b.L.new(a, g.inputs["Alpha"])
    elif mode == "kBLEND_Additive":
        mat.surface_render_method = "BLENDED"
        em = b.node("ShaderNodeEmission", 600, -300)
        b.L.new(albedo, em.inputs["Color"])
        tr = b.node("ShaderNodeBsdfTransparent", 600, -450)
        add = b.node("ShaderNodeAddShader", 750, -350)
        b.L.new(tr.outputs[0], add.inputs[0])
        b.L.new(em.outputs[0], add.inputs[1])
        shader = add.outputs[0]

    # ---- detail: color * (0.5 + (D - 0.5) * DetailScale) * 1.9921875
    det = sample("DetailTexture", "DetailSecondUV", None, -1500, -2600,
                 tiling=float(p.get("DetailTiling", 1) or 1)) if "Det" in c["flags"] else None
    if det is not None:
        # applied as a multiplier on the emitted colour via a second emission factor
        f = b.math("MULTIPLY_ADD", b.math("SUBTRACT", b.sep(det.outputs["Color"], -1200, -2600)["Red"], 0.5,
                                          -1050, -2600), float(p.get("DetailScale", 1) or 1), -900, -2600, c=0.5)
        f = b.math("MULTIPLY", f, 1.9921875, -750, -2600)
        # multiply the albedo-lit part: equivalent for the opaque path (spec is not detail-free in the
        # game either: color = (albedo*light*AO + refl) * detail), so scale the final shader colour
        mul = b.node("ShaderNodeMix", 450, 200, data_type="RGBA", blend_type="MULTIPLY")
        mul.inputs["Factor"].default_value = 1
        b.L.new(albedo, mul.inputs["A"])
        b.L.new(f, mul.inputs["B"])
        b.L.new(mul.outputs["Result"], g.inputs["Albedo"])

    b.L.new(shader, out.inputs["Surface"])
    mat.use_backface_culling = not p.get("DoubleSided")
    return mat


def _hair(b, out, p, sample, c1n, c0a=None):
    """RenderHair, PS 0040 / 0012 (Docs/Formats/shaders.md §5):

        A     = tex(Albedo, uv0 * DetailTiling)           r = diffuse, g = spec, b = glow mask
        uvR   = (1 - (0.5 + 0.49 N.L), 1 - (0.5 + 0.49 N.V))  ramps are raw (sampler not sRGB)
        diff  = (sun + sky) * DiffuseColor^2 * Ramp1 * A.r
        glow  = (AdditiveUseSpec ? Ramp2 : Ramp1) * sat(1 - Ramp1.a) * DiffuseTiling * A.b * GlowColor.rgb * SkyDiffuse
        spec  = pow(cos(thetaV - thetaL), 1/Roughness) * SunSpec * Ramp2 * SpecColor * fresnel * A.g * 1.992 * AO
        color = (diff * AO + glow) * COLOR1.rgb + spec
    """
    L = b.L
    c = engine_constants(p)
    a_t = sample("DiffuseTexture", None, None, -1500, 400, tiling=float(p.get("DetailTiling", 1) or 1))
    geo = b.node("ShaderNodeNewGeometry", -1900, -200)
    N, V = geo.outputs["Normal"], geo.outputs["Incoming"]
    sun = b.node("ShaderNodeAttribute", -1900, -600, attribute_type="VIEW_LAYER", attribute_name="bl_sun_dir")

    def dot(x, y, px, py):
        d = b.node("ShaderNodeVectorMath", px, py, operation="DOT_PRODUCT")
        L.new(x, d.inputs[0])
        L.new(y, d.inputs[1])
        return d.outputs["Value"]
    ndl = dot(N, sun.outputs["Vector"], -1700, -300)
    ndv = dot(N, V, -1700, -450)
    u = b.math("SUBTRACT", 1.0, b.math("MULTIPLY_ADD", ndl, 0.49, -1500, -300, c=0.5), -1300, -300)
    # D3D v = 1 - (0.5 + 0.49 N.V) with v down; Blender images run bottom-up, so v flips back
    v = b.math("MULTIPLY_ADD", ndv, 0.49, -1300, -450, c=0.5)
    uv = b.node("ShaderNodeCombineXYZ", -1150, -350)
    L.new(u, uv.inputs["X"])
    L.new(v, uv.inputs["Y"])

    def ramp(slot, y):
        r = sample(slot, None, None, -1000, y, non_color=True, tiling=1.0) if p.get(slot) else None
        if r is not None:
            r.extension = "EXTEND"
            L.new(uv.outputs[0], r.inputs["Vector"])
        return r
    r1, r2 = ramp("Ramp1Texture", -250), ramp("Ramp2Texture", -600)
    A = b.sep(a_t.outputs["Color"], -1200, 400) if a_t is not None else None

    # ---- diffuse through the lighting group (sun Lambert * shadow + sky ramp), no rim on hair
    d2 = tuple(x * x for x in c["diffuse"])  # g_vDiffuseColor^2 (the shader squares it)
    g = b.node("ShaderNodeGroup", 400, 0)
    g.node_tree = gameshader.ensure_group()
    base = b.mix("MULTIPLY", 1.0, r1.outputs["Color"] if r1 is not None else (1, 1, 1), d2, -600, 200)
    if A is not None:
        base = b.mix("MULTIPLY", 1.0, base, A["Red"], -450, 200)
    base = b.mix("MULTIPLY", 1.0, base, c1n.outputs["Color"], -300, 200)
    L.new(base, g.inputs["Albedo"])
    L.new(N, g.inputs["Normal"])
    g.inputs["Gloss"].default_value = 0.0
    g.inputs["Sun Scale"].default_value = c["sun_scale"]
    g.inputs["Rim Color"].default_value = (0, 0, 0, 1)
    if c0a is not None:
        L.new(b.math("ABSOLUTE", b.math("MULTIPLY_ADD", c0a, 2.0, -500, -50, c=-1.0), None, -350, -50), g.inputs["AO"])

    extra = []
    # ---- glow
    gc = c["glow_rgb"]
    if A is not None and r1 is not None and any(gc):
        src = r2 if (c["additive_use_spec"] and r2 is not None) else r1
        k = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, r1.outputs["Alpha"], -700, -900, clamp=True),
                   float(p.get("DiffuseTiling", 1) or 1), -550, -900)
        k = b.math("MULTIPLY", k, A["Blue"], -400, -900)
        glow = b.mix("MULTIPLY", 1.0, src.outputs["Color"], k, -250, -850)
        glow = b.mix("MULTIPLY", 1.0, glow, gc, -100, -850)
        sky = b.node("ShaderNodeAttribute", -250, -1000, attribute_type="VIEW_LAYER", attribute_name="bl_sky_diffuse")
        glow = b.mix("MULTIPLY", 1.0, glow, sky.outputs["Color"], 50, -850)
        extra.append(b.mix("MULTIPLY", 1.0, glow, c1n.outputs["Color"], 200, -850))
    # ---- spec: cos(thetaV - thetaL) about N
    if A is not None and r2 is not None and any(c["spec_color"]):
        def sq1m(x, px, py):  # sqrt(1 - x^2)
            return b.math("SQRT", b.math("SUBTRACT", 1.0, b.math("MULTIPLY", x, x, px, py), px + 120, py, clamp=True),
                          None, px + 240, py)
        cosd = b.math("MULTIPLY_ADD", sq1m(ndv, -1100, -1200), sq1m(ndl, -1100, -1350), -700, -1250,
                      c=b.math("MULTIPLY", ndv, ndl, -850, -1450))
        pw = b.math("POWER", b.math("MAXIMUM", cosd, 0.0, -550, -1250), c["spec_exponent"], -400, -1250)
        f5 = b.math("POWER", b.math("SUBTRACT", 1.0, b.math("MAXIMUM", ndv, 0.0, -700, -1550), -550, -1550), 5.0, -400, -1550)
        fres = b.node("ShaderNodeMix", -250, -1550, data_type="FLOAT")
        fres.inputs["Factor"].default_value = c["spec_fresnel"]
        fres.inputs["A"].default_value = 1.0
        L.new(f5, fres.inputs["B"])
        k = b.math("MULTIPLY", b.math("MULTIPLY", pw, fres.outputs["Result"], -250, -1250), A["Green"], -100, -1250)
        k = b.math("MULTIPLY", k, 1.9921875, 50, -1250)
        sunspec = b.node("ShaderNodeAttribute", -100, -1400, attribute_type="VIEW_LAYER", attribute_name="bl_sun_specular")
        spec = b.mix("MULTIPLY", 1.0, sunspec.outputs["Color"], k, 200, -1250)
        spec = b.mix("MULTIPLY", 1.0, spec, r2.outputs["Color"], 350, -1250)
        extra.append(b.mix("MULTIPLY", 1.0, spec, c["spec_color"], 500, -1250))

    shader = g.outputs["Shader"]
    for i, e in enumerate(extra):
        em = b.node("ShaderNodeEmission", 600, -400 - 150 * i)
        L.new(e, em.inputs["Color"])
        add = b.node("ShaderNodeAddShader", 750, -300 - 150 * i)
        L.new(shader, add.inputs[0])
        L.new(em.outputs[0], add.inputs[1])
        shader = add.outputs[0]
    if a_t is not None:  # hair cards are cut by the mask's alpha (Bin: texkill(A.a - 0.5))
        b.mat.surface_render_method = "DITHERED"
        L.new(b.math("GREATER_THAN", a_t.outputs["Alpha"], 0.5, 200, 300), g.inputs["Alpha"])
    L.new(shader, out.inputs["Surface"])
    return b.mat
