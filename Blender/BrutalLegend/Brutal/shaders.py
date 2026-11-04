"""Shader containers: `win/shaders/<name>.fxo` Blob resources in the 00Startup bundle.

Magic on disk is 'bsfd' (b"bsfd"; the u32 reads 0x64667362). Little-endian throughout.
Every container is laid out as: header, meta section, bytecode section. Gate:
Tests/corpus_shaders.py (every byte of all 12 containers accounted for, every shader's token
stream ends with END 0x0000FFFF exactly at its declared size).

Header (13 x u32, 0x34 bytes):
    0x00  magic 'bsfd'
    0x04  version (3)
    0x08  technique count            (T)
    0x0C  sampler-state count        (S)
    0x10  parameter count            (P)
    0x14  VS constant-binding count  (BV)
    0x18  PS constant-binding count  (BP)
    0x1C  sampler-binding count      (BS)
    0x20  vertex shader count        (NV)
    0x24  pixel shader count         (NP)
    0x28  meta section size          (everything between the header and the bytecode)
    0x2C  bytecode section size
    0x30  0

Meta section, in order (all names are offsets into the string table, which ends the section):
    S x 40  sampler state:  u32 name, 9 x u32 state (engine enums, see SamplerState)
    P x 12  parameter:      u32 name, u8 kind (0 bool, 1 float, 2 sampler), u8 registers,
                            u16 unknown (one value per container, e.g. 57 in mesh; image.fxo
                            has one outlier), i32 -1
    (NV+NP) x 20  shader:   u32 bytecode offset, u32 0, u32 first constant binding (index
                            into its stage's constant-binding array), u16 first sampler
                            binding, u16 sampler mask (bit N set = register sN bound),
                            u8 constant-binding count, u8 sampler-binding count, u16 0.
                            The NV vertex shaders come first, then the NP pixel shaders.
                            A shader's size is the next shader's offset; the last one's size
                            is not stored (its token stream is walked; the bytecode section
                            is then NUL-padded to a multiple of 16).
    (BV+BP+BS) x 8  binding: u16 parameter index, u16 register (cN / sN), i32 -1.
                            Three consecutive arrays: BV vertex-shader constants, BP pixel-
                            shader constants, BS sampler bindings (all stages). Shaders take
                            contiguous, consecutive runs of them.
    T x 148  technique:     u32 name, u16 VS index (0..NV-1), u16 PS index (0..NP-1),
                            35 x i32 render state (D3D9 enum values where recognisable:
                            [6]/[7] SrcBlend/DestBlend, [9] colour write mask; the rest is
                            kept raw)
    string table            NUL-terminated names, padded with NULs to a multiple of 4.

A technique name is '<Base>[_<Flag>...]' with 3-letter feature flags in alphabetical order,
e.g. 'RenderMesh_Env_Nm1_Shr_Spc'. The engine builds that name from the material and draw
context; the importer chooses a variant by building the same name (Docs/Formats/shaders.md).

Engine-side constants (material_constants, weather_constants, resolve_options) follow
Material_SetShaderConstants 0x65C4B0, ShaderOptions_SelectTechnique 0x66D760 and
Weather_SetLightConstants 0x6F4850; every Material resolves to an existing technique (gate).

Bytecode section: D3D9 SM3 token streams (vs_3_0 0xFFFE0300 / ps_3_0 0xFFFF0300), each with
its CTAB comment block, back to back.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"bsfd"
HEADER = struct.Struct("<13I")
VS_3_0 = 0xFFFE0300
PS_3_0 = 0xFFFF0300
END = 0x0000FFFF

CONTAINERS = ("mesh", "hair", "light", "sky", "quadterrain", "ambmesh", "custom", "particle",
              "shadow", "image", "debug", "workspace")


def resource_path(name: str) -> str:
    return f"win/shaders/{name}.fxo.Blob"


@dataclass
class SamplerState:
    name: str
    state: tuple  # 9 raw u32: [0..2] filter enums, [3] 0, [4..6] address enums, [7], [8] flags


@dataclass
class Parameter:
    name: str
    kind: int  # 0 bool, 1 float, 2 sampler
    registers: int
    unknown: int


@dataclass
class Binding:
    param: int
    register: int


@dataclass
class Shader:
    index: int
    stage: str  # "vs" or "ps"
    offset: int  # within the bytecode section
    size: int
    sampler_mask: int  # bit N = sN used (gate-checked against the bindings)
    constants: list[Binding] = field(default_factory=list)
    samplers: list[Binding] = field(default_factory=list)
    bytecode: bytes = b""


@dataclass
class Technique:
    name: str
    vs: int  # index into Container.vertex_shaders
    ps: int  # index into Container.pixel_shaders
    state: tuple  # 35 raw i32 render-state values

    @property
    def base(self) -> str:
        return self.name.split("_", 1)[0]

    @property
    def flags(self) -> tuple[str, ...]:
        return tuple(self.name.split("_")[1:])


@dataclass
class Container:
    samplers: list[SamplerState]
    parameters: list[Parameter]
    shaders: list[Shader]
    techniques: list[Technique]
    nv: int

    @property
    def vertex_shaders(self) -> list[Shader]:
        return self.shaders[:self.nv]

    @property
    def pixel_shaders(self) -> list[Shader]:
        return self.shaders[self.nv:]

    def technique(self, name: str) -> Technique | None:
        for t in self.techniques:
            if t.name == name:
                return t
        return None

    def shaders_of(self, t: Technique) -> tuple[Shader, Shader]:
        return self.shaders[t.vs], self.shaders[self.nv + t.ps]


def token_length(d: bytes, o: int) -> int:
    """Byte length of the SM3 token stream at d[o:], END token included."""
    p = o + 4
    while True:
        (t,) = struct.unpack_from("<I", d, p)
        if t == END:
            return p + 4 - o
        if t & 0xFFFF == 0xFFFE:  # comment: length in DWORDs in bits 16..30
            p += 4 + 4 * ((t >> 16) & 0x7FFF)
        else:  # SM2+ instruction: operand DWORD count in bits 24..27
            p += 4 + 4 * ((t >> 24) & 0xF)


def _cstr(d: bytes, o: int) -> str:
    return d[o:d.index(b"\0", o)].decode("ascii")


def parse(d: bytes) -> Container:
    """Parse a whole container; raises ValueError on any byte not accounted for."""
    h = HEADER.unpack_from(d, 0)
    if d[:4] != MAGIC or h[1] != 3 or h[12] != 0:
        raise ValueError("not a bsfd v3 container")
    nt, ns, np_, bv, bp, bs, nv, nps, meta_size, code_size = h[2:12]
    if HEADER.size + meta_size + code_size != len(d):
        raise ValueError("section sizes do not cover the file")
    o = HEADER.size
    raw_samp = [struct.unpack_from("<10I", d, o + 40 * i) for i in range(ns)]
    o += 40 * ns
    raw_par = [struct.unpack_from("<IBBHi", d, o + 12 * i) for i in range(np_)]
    o += 12 * np_
    nsh = nv + nps
    raw_sh = [struct.unpack_from("<5I", d, o + 20 * i) for i in range(nsh)]
    o += 20 * nsh
    nb = sum((r[4] & 0xFF) + ((r[4] >> 8) & 0xFF) for r in raw_sh)
    if nb != bv + bp + bs:
        raise ValueError("binding counts disagree with the header")
    raw_bind = [struct.unpack_from("<HHi", d, o + 8 * i) for i in range(nb)]
    o += 8 * nb
    raw_tech = [struct.unpack_from("<IHH35i", d, o + 148 * i) for i in range(nt)]
    o += 148 * nt
    strings = o
    meta_end = HEADER.size + meta_size
    if strings > meta_end:
        raise ValueError("records overrun the meta section")
    table = d[strings:meta_end]
    if len(table) % 4 or (table and table[-1] != 0):
        raise ValueError("string table not NUL-terminated / 4-aligned")

    used = []  # (offset, length) of every string referenced, to prove the table is covered

    def name(off: int) -> str:
        s = _cstr(d, strings + off)
        used.append((off, len(s) + 1))
        return s

    samplers = [SamplerState(name(r[0]), r[1:]) for r in raw_samp]
    params = []
    for r in raw_par:
        if r[4] != -1 or r[1] > 2:
            raise ValueError(f"unexpected parameter record {r}")
        params.append(Parameter(name(r[0]), r[1], r[2], r[3]))
    code = HEADER.size + meta_size
    if code_size % 16:
        raise ValueError("bytecode section size not a multiple of 16")
    vs_const, ps_const, samp = raw_bind[:bv], raw_bind[bv:bv + bp], raw_bind[bv + bp:]
    for b in raw_bind:
        if b[2] != -1 or b[0] >= np_:
            raise ValueError(f"unexpected binding {b}")
    shaders = []
    next_c = [0, 0]  # running constant-binding index per stage (vs, ps)
    next_s = 0
    for i, r in enumerate(raw_sh):
        off, zero, cfirst, sword, counts = r
        nc, nsmp = counts & 0xFF, (counts >> 8) & 0xFF
        sfirst, sampler_mask = sword & 0xFFFF, sword >> 16
        stage = 0 if i < nv else 1
        if zero != 0 or counts >> 16 or cfirst != next_c[stage] or sfirst != next_s:
            raise ValueError(f"unexpected shader record {i}: {r}")
        next_c[stage] += nc
        next_s += nsmp
        if i + 1 < nsh:
            end = raw_sh[i + 1][0]
        else:  # the last shader's size is not stored: walk its tokens, rest is NUL padding
            end = off + token_length(d, code + off)
            if any(d[code + end:code + code_size]) or code_size - end >= 16:
                raise ValueError("bytecode section tail is not padding")
        sh = Shader(i, "vs" if i < nv else "ps", off, end - off, sampler_mask,
                    [Binding(*b[:2]) for b in (vs_const, ps_const)[stage][cfirst:cfirst + nc]],
                    [Binding(*b[:2]) for b in samp[sfirst:sfirst + nsmp]])
        sh.bytecode = d[code + off:code + end]
        ver = struct.unpack_from("<I", sh.bytecode, 0)[0] if len(sh.bytecode) >= 4 else 0
        if ver != (VS_3_0 if i < nv else PS_3_0):
            raise ValueError(f"shader {i}: version token {ver:#x}")
        if (struct.unpack_from("<I", sh.bytecode, len(sh.bytecode) - 4)[0] != END
                or token_length(sh.bytecode, 0) != len(sh.bytecode)):
            raise ValueError(f"shader {i}: token stream does not end with END at its size")
        if sum(1 << b.register for b in sh.samplers) != sampler_mask:
            raise ValueError(f"shader {i}: sampler mask disagrees with its bindings")
        shaders.append(sh)
    if raw_sh and raw_sh[0][0] != 0:
        raise ValueError("bytecode section does not start with shader 0")
    if next_c != [bv, bp] or next_s != bs:
        raise ValueError("binding split disagrees with the header")
    techs = []
    for r in raw_tech:
        if r[1] >= nv or r[2] >= nps:
            raise ValueError(f"technique shader index out of range {r[:3]}")
        techs.append(Technique(name(r[0]), r[1], r[2], r[3:]))
    # Every byte of the string table must be a referenced string or trailing NUL padding.
    covered = bytearray(len(table))
    for off, n in used:
        covered[off:off + n] = b"\1" * n
    for i, c in enumerate(covered):
        if not c and table[i] != 0:
            raise ValueError(f"string table byte {i:#x} not referenced")
    return Container(samplers, params, shaders, techs, nv)


def load(library, name: str) -> Container:
    return parse(library.read(resource_path(name)))


# ---------------------------------------------------------------------------------------------
# Engine-side constants (Docs/Formats/shaders.md, "Engine-side constants"). Every formula names
# the BrutalLegend.exe function it was read from.
# ---------------------------------------------------------------------------------------------

import math  # noqa: E402

# exe 0xE8061C: specular normalisation per exponent bucket (identical to the first 8 floats of
# lighting/textures/rsalights/simplesun_rsa). [0] also scales the sun diffuse colour.
SPEC_NORM = (0.0853055, 0.108038, 0.142544, 0.191474, 0.256055, 0.332851, 0.408758, 0.461755)
BLEND_MODES = {"kBLEND_Default": 0, "kBLEND_Opaque": 1, "kBLEND_BinaryAlpha": 2, "kBLEND_Alpha": 3,
               "kBLEND_Additive": 4, "kBLEND_Multiply": 5, "kBLEND_Subtractive": 6,
               "kBLEND_Min": 8}  # sub_6751D0
# Default textures bound when a slot is empty (sub_64FBE0 loads them, sub_65A4C0 copies them to
# the render context, sub_65C4B0 picks them).
WHITE = "Renderer/Textures/Common/White"
BLACK = "Renderer/Textures/Common/Black"
GRAY = "Renderer/Textures/Common/Gray"
DEFAULT_NORM = "Renderer/Textures/Common/Default_Norm"
_EPS = 0.001  # sub_65DA40 / sub_65DAF0: stored copies drop components with |x| < 0.001


def _tex(p, k):
    v = p.get(k)
    return v if isinstance(v, str) and v else None


def _vec(p, k, n=3, default=1.0):
    v = p.get(k)
    if isinstance(v, (tuple, list)):
        return tuple(float(x) for x in v[:n])
    return (default,) * n


def _f(p, k, default=0.0):
    v = p.get(k)
    return float(v) if isinstance(v, (int, float)) else default


def _b(p, k):
    return 1.0 if _f(p, k) != 0.0 else 0.0


def gamma(c, linear=True):
    """sub_65D8C0 / sub_65D950: colours are raised to 2.2 when the renderer runs linear."""
    return tuple(max(x, 0.0) ** 2.2 for x in c) if linear else tuple(c)


def _nz(v):
    return any(abs(x) >= _EPS for x in v)


def specular_bucket(roughness: float) -> int:
    """sub_666A20 (Roughness setter) + sub_675670: k = log2(next_pow2(int(1/r))), clamped 0..7."""
    e = 1.0 / max(roughness, 1e-5)
    n = int(e)
    p = 1 if n <= 1 else 1 << (n - 1).bit_length()
    return min(max(p, 1), 128).bit_length() - 1


NEUTRAL_SCENE = {  # render-context lighting when no Weather is given (all multipliers 1)
    "sun": (1.0, 1.0, 1.0), "sun_spec": (1.0, 1.0, 1.0), "sky": (1.0, 1.0, 1.0),
    "env_color_scene": (1.0, 1.0, 1.0), "env_color_material": (1.0, 1.0, 1.0),
    "rim_color": (1.0, 1.0, 1.0), "rim_width": 1.0, "fog_color": (0.0, 0.0, 0.0),
    "spec_norm": SPEC_NORM, "environment_map": None,
}


def _is_blood(path):
    return bool(path) and path.rsplit("/", 1)[-1] == "blooddamage"


# Technique option rules, sub_66F1D0 (one record per option): option -> (options it switches on,
# options it switches off). sub_66D760 ORs the 'on' masks of every requested option (each record
# starts with its own bit, sub_66E8B0), removes the union of the 'off' masks, and looks the
# result up exactly (sub_66E770). Not transitive: only requested options contribute masks.
OPTION_RULES = {
    "RenderMesh": {
        "Bin": ((), ("Dec",)),
        "Blm": (("Det", "La1", "La2", "Lat", "Nm1", "Nm2", "Shr", "Spc"),
                ("Bin", "Dbg", "Dec", "Env", "Glw", "Pnt", "Prj", "Trn")),
        "Dbg": (("Det", "La1", "La2", "Lat", "Nm1", "Nm2", "Shr", "Spc"), ("Env", "Pnt", "Prj")),
        "Dec": (("Nm1", "Shr", "Trn"), ()),
        "Dep": (("Det", "La1", "La2", "Lat", "Nm1", "Nm2", "Shr", "Spc"),
                ("Blm", "Dbg", "Dec", "Env", "Glw", "Trn")),
        "DpC": (("Dep",), ()),
        "Det": (("La2", "Nm2"), ()),
        "Env": (("Nm1",), ("Dec",)),
        "Flg": ((), ("Dec", "Skn")),
        "Fld": (("Flg", "Nm1"), ()),
        "Glw": (("Nm1",), ("Dec",)),
        "La1": (("Shr",), ()),
        "La2": (("La1",), ()),
        "Lat": (("La2", "Nm2", "Spc"), ()),
        "Nm1": (("Shr",), ()),
        "Nm2": (("Nm1",), ()),
        "Pnt": (("Nm2", "Trn"), ()),
        "Prj": (("Nm2", "Trn"), ()),
        "Rgd": (("Skn",), ()),
        "Shc": (("Dep",), ()),
        "Shd": (("Shc",), ()),
        "Spc": (("Shr",), ()),
        "Trn": (("Spc",), ()),
    },
    "RenderHair": {
        "Pnt": (("Trn",), ()),
        "Prj": (("Trn",), ()),
    },
}


def resolve_options(shader: str, requested) -> tuple:
    """Final technique flag set from the requested options (sub_66D760 tail)."""
    rules = OPTION_RULES.get(shader, {})
    on, off = set(), set()
    todo = list(requested)
    while todo:  # closure over implied options
        f = todo.pop()
        if f in on:
            continue
        on.add(f)
        en, dis = rules.get(f, ((), ()))
        todo.extend(en)
        off.update(dis)
    return tuple(sorted(on - off))


def material_constants(props: dict, damage: float = 0.0, has_damage_texture: bool | None = None,
                       scene: dict | None = None, skinned: bool = False, rigid: bool = False,
                       shadow_receive: bool = True, foliage: bool = False,
                       linear: bool = True) -> dict:
    """Technique name + every material-driven shader constant, as sub_65C4B0 (constants),
    sub_665BA0 (flags) and sub_66D760 (technique options) compute them for one draw.

    damage: the per-instance Layer2 multiplier. sub_65C4B0 multiplies Layer2Strength by the
    instance parameter [10] (Layer1Strength by [9]). The render object's layer-2 scale
    (CoRenderMesh +372) defaults to 1.0 (sub_571C10); an entity whose health component has
    HasDamageTexture overwrites it every frame with
    clamp(1 - (health/maxHealth - R.x) / (R.y - R.x), 0, 1), R = DamageTextureDisplayRange
    (default (0, 1)): 0 at full health (sub_850190, stored by sub_84CCC0 / sub_84AE00).
    Layer1's multiplier stays 1.0.
    has_damage_texture: whether that applies here. It is an entity (health component) setting,
    not a Material key; None = assume it exactly when Layer2Texture is the shared
    characters/textures/blooddamage (heuristic), otherwise Layer2 keeps multiplier 1.
    scene: weather_constants(...) output (render-context colours); None = neutral white light.
    """
    sc = dict(NEUTRAL_SCENE)
    if scene:
        sc.update(scene)
    p = props
    shader = p.get("ShaderName") or "RenderMesh"
    is_mesh, is_hair = shader == "RenderMesh", shader == "RenderHair"   # sub_666830 type 0 / 14
    blend = BLEND_MODES.get(p.get("BlendMode"), 0)

    def g(c):
        return gamma(c, linear)

    tex = {k: _tex(p, k) for k in ("DiffuseTexture", "GlossTexture", "TranslucenceTexture",
                                    "IncandescenceTexture", "Normal1Texture", "Normal2Texture",
                                    "DetailTexture", "Layer1Texture", "Layer2Texture",
                                    "EnvironmentMapTexture", "Ramp1Texture", "Ramp2Texture")}
    if has_damage_texture is None:
        has_damage_texture = _is_blood(tex["Layer2Texture"])
    l1_mult = 1.0
    l2_mult = float(damage) if has_damage_texture else 1.0

    transparency = _f(p, "Transparency", 1.0)
    trans_int = _f(p, "TranslucenceIntensity")
    incand = _f(p, "Incandescence")
    # g_samGlow: Translucence texture when TranslucenceIntensity != 0 (flag 0x40, sub_666AE0),
    # else Incandescence texture; an empty slot binds Black / White (sub_65C4B0).
    if trans_int != 0.0:
        glow_tex, glow_default = tex["TranslucenceTexture"], BLACK
        glow_second = _b(p, "TranslucenceSecondUV")
    else:
        glow_tex, glow_default = tex["IncandescenceTexture"], WHITE
        glow_second = _b(p, "IncandescenceSeconduV")

    n1s, n2s = _f(p, "Normal1Scale", 1.0), _f(p, "Normal2Scale", 1.0)
    dets = _f(p, "DetailScale", 1.0)
    l1s = _f(p, "Layer1Strength") * l1_mult
    l2s = _f(p, "Layer2Strength") * l2_mult
    n1la, n2la = _b(p, "Normal1UseLayerAlpha"), _b(p, "Normal2UseLayerAlpha")
    if is_mesh:  # material flag 0x80 (RenderMesh only): a missing texture zeroes its scale
        n1s = n1s if tex["Normal1Texture"] else 0.0
        n2s = n2s if tex["Normal2Texture"] else 0.0
        dets = dets if tex["DetailTexture"] else 0.0
        l1s = l1s if tex["Layer1Texture"] else 0.0
        l2s = l2s if tex["Layer2Texture"] else 0.0
        l1s = max(l1s, 0.001 if n1la else 0.0)
        l2s = max(l2s, 0.001 if n2la else 0.0)

    dt = _f(p, "DiffuseTiling", 1.0)
    pix = (_f(p, "Layer1Tiling", 1.0), _f(p, "Layer2Tiling", 1.0), _f(p, "DetailTiling", 1.0))
    if is_mesh:  # the shader's UV already carries DiffuseTiling (g_vMapTilingVertex.x)
        pix = tuple(x / dt for x in pix)

    rough = _f(p, "Roughness", 0.3)
    k = specular_bucket(rough)
    env_base = sc["env_color_material"] if tex["EnvironmentMapTexture"] else sc["env_color_scene"]
    env_i = _f(p, "EnvironmentMapIntensity")
    env_col = g(tuple(c * e * env_i for c, e in zip(_vec(p, "EnvironmentMapColor"), env_base)))
    w = _f(p, "RimLightWidth", 1.0) * sc["rim_width"]
    inv = 1.0 if w - 1e-5 < 0.0 else 1.0 / w
    rim_i = _f(p, "RimLightIntensity")
    sun_s = _f(p, "SunlightStrength", 1.0)
    norm = sc.get("spec_norm") or SPEC_NORM
    spec_col = g(tuple(x * _f(p, "SpecularIntensity") for x in _vec(p, "SpecularColor")))
    glow_rgb = g(tuple(x * trans_int for x in _vec(p, "TranslucenceColor")))
    # sub_665BA0 bit 2 (g_bTextureAlpha): BlendMode >= Alpha and SceneImageStrength > 0
    texture_alpha = blend >= 3 and _f(p, "SceneImageStrength", 1.0) > 1e-5 and transparency > 1e-5
    lb1 = 1.0 if p.get("Layer1Blend") == "kLBM_LinearLightDecal" else 0.0
    lb2 = 1.0 if p.get("Layer2Blend") == "kLBM_LinearLightDecal" else 0.0

    c = {
        "g_vDiffuseColor": g(_vec(p, "DiffuseColor")),
        "g_vSpecularColor": spec_col,
        "g_vSpecularConstants": (1.0 / max(rough, 1e-5), k * 0.125, _f(p, "Fresnel"), rough),
        "g_vGlowColor": glow_rgb + (incand,),
        "g_vMapScaleFloats": (n1s, n2s, dets),
        "g_vMapTilingVertex": (dt, _f(p, "GlossTiling", 1.0), _f(p, "Normal1Tiling", 1.0),
                               _f(p, "Normal2Tiling", 1.0)),
        "g_vMapTilingPixel": pix,
        "g_vSecondUVVertex": (_b(p, "Normal1SecondUV"), _b(p, "Normal2SecondUV"),
                              _b(p, "GlossSecondUV")),
        "g_vSecondUVPixel": (_b(p, "DetailSecondUV"), glow_second, _b(p, "Layer1SecondUV"),
                             _b(p, "Layer2SecondUV")),
        "g_vLayerFloats": (l1s, l2s, n1la, n2la),
        "g_vLayerBlendFloats": (min(lb1, l1s), min(lb2, l2s), 0.0),
        "g_vLayerSpecularFloats": (_f(p, "Layer1SpecularStrength"), _f(p, "Layer1SpecularIntensity"),
                                   _f(p, "Layer2SpecularStrength"), _f(p, "Layer2SpecularIntensity")),
        "g_vTransparencyFloats": (transparency, 0.0 if texture_alpha else 1.0, 0.5),
        "g_bTextureAlpha": texture_alpha,
        "g_bBinaryAlpha": blend == 2,
        "g_vBufferStrengths": (_f(p, "SceneImageStrength", 1.0), _f(p, "LightBloomStrength"),
                               _f(p, "InkBloomStrength")),
        "g_vEnvironmentMapColor": env_col,
        "g_vRimLightColor": g(tuple(a * b * rim_i for a, b in
                                    zip(_vec(p, "RimLightColor"), sc["rim_color"]))),
        "g_vRimLightConstants": (-(1.0 - w) * inv, inv, w),
        "g_vSunLightDiffuseColor": g(tuple(x * sun_s * norm[0] for x in sc["sun"])),
        "g_vSunLightSpecularColor": g(tuple(x * sun_s * norm[k] for x in sc["sun_spec"])),
        "g_vFogColor": (0.0, 0.0, 0.0) if blend in (4, 5, 6) else g(sc["fog_color"]),
        "g_bAdditiveUseSpec": _b(p, "AdditiveUseSpec") != 0.0,
        "g_vOcclusionStrength": (1.0, 1.0, 1.0),  # sub_6F31C0: constant (1,1,1) every frame
    }
    samplers = {
        "g_samAlbedo": tex["DiffuseTexture"] or WHITE,
        "g_samGloss": tex["GlossTexture"] or WHITE,
        "g_samNormal1": tex["Normal1Texture"] or DEFAULT_NORM,
        "g_samNormal2": tex["Normal2Texture"] or DEFAULT_NORM,
        "g_samDetail": tex["DetailTexture"] or GRAY,
        "g_samLayer1": tex["Layer1Texture"] or GRAY,
        "g_samLayer2": tex["Layer2Texture"] or GRAY,
        "g_samGlow": glow_tex or glow_default,
        "g_samEnvironmentCubemap": tex["EnvironmentMapTexture"] or sc.get("environment_map"),
        "g_samRamp1": tex["Ramp1Texture"] or WHITE,
        "g_samRamp2": tex["Ramp2Texture"] or WHITE,
    }

    # Technique options, sub_66D760: each flag tests the stored (|x| >= 0.001) constant.
    trn = transparency < 1.0 or (texture_alpha and blend != 2)
    glow_bound = glow_tex or glow_default
    flags = set()
    if is_hair:  # sub_66D760 case 14
        if blend == 2:
            flags.add("Bin")
        if glow_bound not in (WHITE, BLACK):
            flags.add("Edg")
        if abs(n1s) >= _EPS and abs(n2s) >= _EPS:
            flags.add("Nm1")
        if skinned:
            flags.add("Skn")
        if trn:
            flags.add("Trn")
    else:  # sub_66D760 case 0 (RenderMesh)
        checks = {
            "Bin": blend == 2,
            "Det": abs(dets) >= _EPS,
            "Env": _nz(env_col),
            "Glw": _nz(glow_rgb) or (abs(incand) >= _EPS and glow_bound != WHITE),
            "Flg": foliage,
            "La1": abs(l1s) >= _EPS,
            "La2": abs(l2s) >= _EPS,
            "Lat": _nz(c["g_vLayerBlendFloats"]),
            "Nm1": abs(n1s) >= _EPS,
            "Nm2": abs(n2s) >= _EPS,
            "Shr": shadow_receive,
            "Skn": skinned,
            "Rgd": skinned and rigid,
            "Spc": _nz(spec_col),
            "Trn": trn,
        }
        flags = {f for f, on in checks.items() if on}
    final = resolve_options(shader, flags)
    name = "_".join((shader,) + final)
    return {"technique": name, "requested": tuple(sorted(flags)), "flags": final, "constants": c,
            "samplers": samplers, "specular_bucket": k, "layer2_multiplier": l2_mult}


def sun_direction(declination: float, rotation: float, elevation: float = 90.0) -> tuple:
    """g_vSunLightDir.xyz in game space (Y up), sub_6F4850 + sub_4F4350:
    M = Rx(elevation) * Rz(declination) * Ry(rotation) (row vectors, sub_685570 / sub_6856F0 /
    sub_685630), dir = -row2(M). elevation is the time-of-day angle (sub_4F78F0:
    seconds * 360 / 86400 - 90, folded into [40, 140]); 90 = noon."""
    se, ce = math.sin(math.radians(elevation)), math.cos(math.radians(elevation))
    sd, cd = math.sin(math.radians(declination)), math.cos(math.radians(declination))
    sr, cr = math.sin(math.radians(rotation)), math.cos(math.radians(rotation))
    return (-(se * sd * cr + ce * sr), se * cd, se * sd * sr - ce * cr)


def weather_constants(props: dict, elevation: float = 90.0, sun_rsa=None,
                      linear: bool = True) -> dict:
    """Render-context lighting from a Weather (Brutal.textobj dict), sub_6F4850 / sub_6F6040.
    Returns the raw context colours (pass as material_constants(scene=...)) and the per-frame
    constants. sun_rsa: rsalight.RSA of SunLight.Gradient (its 8 floats replace SPEC_NORM).
    Two unidentified multipliers (WeatherState +640, a global light scale on sun, sky and fog;
    render context +116, a sky scale) are taken as 1."""
    p = props
    sun = p.get("SunLight") or {}
    sky = p.get("SkyLight") or {}
    post = p.get("PostSettings") or {}
    fog = p.get("FogSettings") or {}
    sun_raw = tuple(x * _f(sun, "Intensity", 1.0) * _f(post, "SunStrengthMultiplier", 1.0)
                    for x in _vec(sun, "Color"))
    sky_raw = tuple(x * _f(sky, "Intensity", 1.0) * _f(post, "SkyStrengthMultiplier", 1.0)
                    for x in _vec(sky, "Color"))
    fr = _vec(fog, "FogRange", 2, 0.0)
    fh = _vec(fog, "FogHeightFade", 2, 0.0)
    d = sun_direction(_f(p, "SunDeclination", 30.0), _f(p, "SunRotation", -90.0), elevation)
    return {
        "sun": sun_raw,
        "sun_spec": tuple(x * _f(sun, "SpecularIntensity", 1.0) for x in sun_raw),
        "sky": sky_raw,
        "env_color_scene": tuple(x * _f(p, "EnvironmentMapIntensity", 1.0)
                                 for x in _vec(p, "EnvironmentMapColor")),
        "env_color_material": tuple(x * _f(p, "AverageEnvironmentIntensity", 1.0)
                                    for x in _vec(p, "AverageEnvironmentColor")),
        "rim_color": tuple(x * _f(p, "RimLightIntensity", 1.0) for x in _vec(p, "RimLightColor")),
        "rim_width": _f(p, "RimLightWidth", 1.0),
        "fog_color": tuple(x * _f(fog, "FogBrightness", 1.0) for x in _vec(fog, "FogColor")),
        "spec_norm": tuple(sun_rsa.spec_norm) if sun_rsa is not None else SPEC_NORM,
        "environment_map": _tex(p, "EnvironmentMap"),
        "rsa_gradient": _tex(sky, "Gradient"),
        "sun_rsa_gradient": _tex(sun, "Gradient"),
        "constants": {
            "g_vSunLightDir": d + (_f(sun, "SpecularShadowFactor", 1.0),),
            "g_vSkyLightDiffuseColor": gamma(sky_raw, linear),
            "g_vRSALightOffset": (1.0 / 512.0, 1.0 / 16.0),
            "g_fEnvironmentMapShadowFactor": _f(p, "EnvironmentMapShadowFactor"),
            "g_fRimLightShadowFactor": _f(p, "RimLightShadowFactor"),
            "g_vFogRange": (fr[0], fr[1], 1.0 / (fr[1] - fr[0]) if fr[1] > fr[0] else 0.0,
                            _f(fog, "FogDensity")),
            "g_vFogHeightFade": (fh[0], fh[1], 1.0 / (fh[1] - fh[0]) if fh[1] > fh[0] else 0.0,
                                 _f(fog, "FogHeightMinDensity")),
            "g_vOcclusionStrength": (1.0, 1.0, 1.0),
            "g_GammaExponent": 1.0 / 2.2 if linear else 1.0,
        },
    }
