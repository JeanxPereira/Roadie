# Shaders (`win/shaders/*.fxo`) and the material/lighting math

Decoder: `brutal/shaders.py`. Gate: `tests/corpus_shaders.py`. Disassembly dump:
`python tools/shaders/disasm.py [container ...]` writes
`.evidence/shaders/<container>/<index>_<stage>_<first technique>.asm` plus `techniques.txt`
(technique -> VS file, PS file, render state). Every asm citation below uses those file names.

Legend: **[read]** = transcribed directly from the asm; **[inferred]** = deduced from names,
statistics or consistency, not proven; **[open]** = needs the exe (IDA) or a runtime capture.

---

## 1. Container format (`'bsfd'` v3)

Twelve `Blob` resources in `00Startup`: `win/shaders/{mesh,hair,light,sky,quadterrain,ambmesh,
custom,particle,shadow,image,debug,workspace}.fxo.Blob`. Little-endian.

| Offset | Field |
|---|---|
| 0x00 | magic `bsfd` |
| 0x04 | version = 3 |
| 0x08 | T technique count |
| 0x0C | S sampler-state count |
| 0x10 | P parameter count |
| 0x14 | BV vertex-shader constant bindings |
| 0x18 | BP pixel-shader constant bindings |
| 0x1C | BS sampler bindings |
| 0x20 | NV vertex shader count |
| 0x24 | NP pixel shader count |
| 0x28 | meta section size |
| 0x2C | bytecode section size (multiple of 16) |
| 0x30 | 0 |

`0x34 + meta + bytecode == file size`. The meta section is, in order:

| Array | Record |
|---|---|
| S x 40 | sampler state: u32 name, 9 x u32 engine state. [0..2] filter enums, [3] 0, [4..6] address enums, [7] 0x03010000 or 0x03040000 (the 4 appears on material samplers - anisotropy? [inferred]), [8] flags: bit0 set on Albedo/Layer/Detail/Gloss/EnvironmentCubemap, 0 on RSALight/Ramp/Glow/shadow maps, 0x100 on Normal1/2 (bit0 = SRGBTexture? [inferred]) |
| P x 12 | parameter: u32 name, u8 kind (0 bool, 1 float, 2 sampler), u8 register count, u16 unknown (one value per container), i32 -1 |
| (NV+NP) x 20 | shader: u32 bytecode offset, u32 0, u32 first constant binding (into its stage's array), u16 first sampler binding, u16 sampler mask (bit N = sN bound; gate-checked), u8 constant-binding count, u8 sampler-binding count, u16 0. VS first, then PS. |
| (BV+BP+BS) x 8 | binding: u16 parameter index, u16 register, i32 -1. Three consecutive arrays: VS constants, PS constants, samplers. |
| T x 148 | technique: u32 name, u16 VS index, u16 PS index (each within its stage), 35 x i32 render state |
| strings | NUL-terminated names (techniques, parameters, samplers), NUL-padded to 4 |

Shader size = next shader's offset - offset; the last shader's size is not stored, so its token
stream is walked and the remainder (< 16 bytes) is NUL padding. Bytecode = plain D3D9 SM3
(`vs_3_0` 0xFFFE0300 / `ps_3_0` 0xFFFF0300) with the CTAB comment (so D3DDisassemble prints
names). Parameter names are offsets into the same string table.

Render state (indices into the 35): [6] SrcBlend, [7] DestBlend (D3DBLEND: 2/1 opaque,
5/6 SRCALPHA/INVSRCALPHA on `_Trn`), [9] ColorWriteEnable (15, or 7 on `_Trn`), [3] = 1 only
on `_Trn` (AlphaBlendEnable [inferred]), [2] = 1 on `_Bin`/`_Trn`, [34] 2 static / 4 skinned /
-1 (vertex format id? [inferred]). The rest is constant across mesh.fxo and left raw.

Gate output (`python tests/corpus_shaders.py`):

```
mesh          4732884 B  techniques  1989  vs  117  ps  776  samplers  22  params  93  bindings  31303  bases 1
hair           413284 B  techniques   162  vs    9  ps   82  samplers  25  params  68  bindings   2184  bases 3
light           39780 B  techniques    20  vs   11  ps   14  samplers  22  params  43  bindings    247  bases 10
sky              4580 B  techniques     2  vs    1  ps    2  samplers  10  params  18  bindings     23  bases 1
quadterrain    319828 B  techniques   147  vs   31  ps   74  samplers  27  params  70  bindings   2466  bases 9
ambmesh         57876 B  techniques    34  vs    8  ps   14  samplers  22  params  34  bindings    242  bases 1
custom          62820 B  techniques    22  vs   20  ps   14  samplers  22  params  49  bindings    346  bases 14
particle       363540 B  techniques   234  vs   50  ps  118  samplers  22  params  56  bindings   2123  bases 34
shadow          23220 B  techniques    10  vs    5  ps    9  samplers  11  params  23  bindings     66  bases 10
image           40948 B  techniques    36  vs    8  ps   33  samplers  26  params  53  bindings    163  bases 36
debug            8068 B  techniques    11  vs    6  ps    4  samplers   0  params  13  bindings     31  bases 8
workspace       63140 B  techniques    22  vs   19  ps   14  samplers  22  params  82  bindings    355  bases 17
materials resolved to an existing technique: 2748/2748
rsa gradients decoded: 16, weathers evaluated: 146
ALL 12 CONTAINERS PARSE, ALL MATERIALS RESOLVE
```

(Earlier "1552 ps / 234 vs" counts came from scanning for version tokens: each stream's CTAB
repeats its version token, so a scan counts every shader twice.)

---

## 2. Choosing a variant: technique names

There is no separate flag table: the technique **name** is the key. mesh.fxo holds 1989
techniques, all `RenderMesh[_Flag...]`, flags 3 letters, sorted alphabetically. The engine
builds the name per draw from the material and draw context; the importer should do the same and
look it up with `Container.technique(name)`. Flag meanings (from the code each flag adds):

The third column was the pre-IDA guess; the exact engine conditions are in section 6.3.

| Flag | What the code shows | Material key that likely drives it |
|---|---|---|
| `Nm1`, `Nm2` | samples g_samNormal1 / g_samNormal2 [read] | Normal1Texture / Normal2Texture [inferred] |
| `La1`, `La2` | samples g_samLayer1 / g_samLayer2 [read] | Layer1Texture / Layer2Texture [inferred] |
| `Lat` | per-layer runtime switch alpha-decal vs linear-light via g_vLayerBlendFloats [read] | any Layer?Blend = kLBM_LinearLightDecal [inferred] |
| `Spc` | sun specular + g_samGloss [read] | GlossTexture / SpecularIntensity > 0 [open] |
| `Env` | g_samEnvironmentCubemap reflection (also samples Gloss) [read] | EnvironmentMapTexture / EnvironmentMapIntensity > 0 [open] |
| `Det` | g_samDetail, final-colour multiplier [read] | DetailTexture [inferred] |
| `Glw` | g_samGlow: incandescence + translucence split [read] | IncandescenceTexture and/or TranslucenceTexture [open] |
| `Bin` | `texkill` at albedo alpha 0.5 [read] | BlendMode kBLEND_BinaryAlpha [inferred] |
| `Trn` | alpha-blended forward pass, own shadow-map lookup, no MRT normal [read] | BlendMode kBLEND_Alpha / Transparency < 1 [inferred] |
| `Dec` | like `Trn` but no shadow-map lookup [read] | decals [inferred] |
| `Shr` | screen-space g_samShadowOverlay (x = sun shadow, y = sky occlusion) [read] | draw context (shadow receive) |
| `Flg` | VS wind sway; **PS drops the COLOR1 tint** [read] | foliage meshes [open] |
| `Fld` | VS leaf/branch flutter (g_vLeafParams, g_vBranchParams, g_fWorldTime) [read] | foliage detail [open] |
| `Skn`, `Rgd` | skinned (g_avSkinningMatrices) / rigid-skinned VS [read] | mesh vertex format |
| `Pnt`, `Prj` | forward point / projected lights; only exist together with `Trn` [read] | draw context |
| `Dep`, `DpC`, `Shc`, `Shd` | depth-only / shadow-caster passes (no colour) [read] | draw context |
| `Blm` | bloom-buffer pass (Albedo, Detail, g_vBufferStrengths) [read] | InkBloomStrength / LightBloomStrength [inferred] |
| `Dbg` | debug view (g_eMaterialDebugType) | ignore |

For an importer: the opaque look of a RenderMesh material is the technique
`RenderMesh_[Det_][Env_][Glw_][La1_][La2_][Lat_][Nm1_][Nm2_]Shr[_Spc]` (plus `Bin`/`Trn`), and
every term below is switched by those flags. Opaque point/projected lights are deferred
(light.fxo, reading oC1), not in these shaders.

hair.fxo: `RenderHair[_Bin][_Dbg][_Edg][_Nm1][_Pnt][_Prj][_Skn][_Trn]` (+ RenderFur,
RenderFurNormals). `Edg` changes no shader code (RenderHair and RenderHair_Edg have identical
VS/PS asm), only render state [read].

---

## 3. Spaces and vertex streams (RenderMesh VS)

VS 0040 (`RenderMesh`, `RenderMesh_Shr`), 0002 (`Nm1`), 0003 (full) [read]:

| VS input | Use |
|---|---|
| POSITION, NORMAL, TANGENT (Nm variants) | transformed by g_mModelToCamWorld (camera-relative world: world rotation, translated so the camera is at the origin; fog adds g_vCameraPosition.y to get world height) |
| COLOR0 (D3DCOLOR: .r = byte 2, .g = byte 1, .b = byte 0, .a = byte 3; `brutal.mesh` color0 is already RGBA in this order) | **.r = Layer1 mask, .g = Layer2 mask** (weight = 1 - channel), **.a = AO + tangent sign**, .b unused by mesh (hair: comb direction) |
| COLOR1 | **.rgb = albedo tint** (multiplied in the PS), **.a = alpha multiplier** on `_Trn`; on `Flg` foliage .r/.g are wind weights and the tint is not applied |
| TEXCOORD0 (float4) | .xy = UV0, .zw = UV1 |

```hlsl
// VS 0002 / 0003
s      = 2*COLOR0.a - 1;
o6.w   = sign(s);                                    // tangent handedness
AO     = (g_vOcclusionStrength.x != 0) ? abs(s) : 1; // o1.zw  (so AO = |2a-1|)
o1.xy  = (1 - COLOR0.rg) * g_vLayerFloats.xy;        // layer vertex weights
o2     = float4(COLOR1.rgb, 1);
o3     = TEXCOORD0 * g_vMapTilingVertex.x;           // albedo UV0 (.xy) / UV1 (.zw)
uvN1   = (g_vSecondUVVertex.x != 0 ? UV1 : UV0) * g_vMapTilingVertex.z;   // o7.xy
uvN2   = (g_vSecondUVVertex.y != 0 ? UV1 : UV0) * g_vMapTilingVertex.w;   // o7.zw
uvGl   = (g_vSecondUVVertex.z != 0 ? UV1 : UV0) * g_vMapTilingVertex.y;   // o8.xy (gloss)
P      = mul(pos, g_mModelToCamWorld);               // o0 (camera at origin)
d      = min(length(P), g_vFogRange.y);
fogD   = 1 - min(exp((g_vFogRange.x - d) * g_vFogRange.w), 1);
h      = saturate((g_vFogHeightFade.y - (P.y + g_vCameraPosition.y)) * g_vFogHeightFade.z);
fog    = fogD * (g_vFogHeightFade.w + h*(1 - g_vFogHeightFade.w));       // o5.w
```

Excerpt (0002): `mad r0.x, v3.w, c12.x, c12.y` / `add o6.w, -r0.z, r0.y` /
`mad o1.zw, r0.y, r0.x, c12.z` / `add r0.xy, c12.z, -v3` / `mul o1.xy, r0, c110` /
`mad o2, v4.xyzx, c13.xxxy, c13.yyyx`.

---

## 4. RenderMesh pixel shader, term by term

### 4.1 Default opaque: `RenderMesh_Shr` (PS 0655; `RenderMesh` = PS 0158 is the same minus shadows)

```hlsl
albedo = tex2D(g_samAlbedo, uv0).rgb * g_vDiffuseColor * COLOR1.rgb;        // [read]
N      = normalize(faceSign * vertexNormal);                                 // see note
sun    = saturate(dot(N, g_vSunLightDir.xyz)) * g_vSunLightDiffuseColor * shadow.x;
sky    = tex2D(g_samRSALight, float2(0.5 - 0.5*N.y + g_vRSALightOffset.x,
                                     g_vRSALightOffset.y)).rgb
         * g_vSkyLightDiffuseColor * shadow.y;
light  = sun + sky + g_vGlowColor.w;                                         // constant self-illum
V      = normalize(-P);                                                       // to the camera
rim    = saturate((1 - saturate(dot(N, V))) * g_vRimLightConstants.y + g_vRimLightConstants.x)
         * (1 - g_fRimLightShadowFactor * (1 - shadow.x));
light += g_vRimLightColor * rim;
color  = albedo * light * AO;
color  = lerp(color, g_vFogColor, fog);
oC0    = float4(color * g_vScreenTargetExpand.y, 1);
// shadow = tex2D(g_samShadowOverlay, (vPos + 0.5) * g_vScreenSize.zw)  (Shr only; 1 otherwise)
```

Excerpts (0655): `texld r0, v3, s3` / `mul r0.xyz, r0, c113` / `mul r0.xyz, r0, v2`;
`dp3_sat r0.w, r2, c11` / `mul r1.xzw, r0.w, c111.xyyz`; `mad r0.w, r2.y, r1.y, c10.x`
(r1.y = -0.5) / `add r3.x, r0.w, c1.x` / `mov r3.y, c10.y` / `texld r3, r3, s0` /
`mul r3.xyz, r3, c112`; `texld r4, r4, s2` / `mul r3.xyz, r3, r4.y` /
`mad r1.xyz, r1.xzww, r4.x, r3`; `add r1.xyz, r1, c115.w`; `dp3_sat r1.w, r2, -r3` /
`add r1.w, -r1.w, c2.x` / `mad_sat r1.w, r1.w, c117.y, c117.x` / `mad r1.xyz, c116, r0.w, r1`;
`mul r0.xyz, r0, r1` / `mul r1.xyz, r0, v1.z` / `mad r0.xyz, r0, -v1.z, c110` /
`mad r0.xyz, v4.w, r0, r1` / `mul oC0.xyz, r0, c108.y` / `mov oC0.w, c2.x`.

Notes:
- **No specular at all without `Spc`/`Env`** [read]. The base look is Lambert sun + a sky term
  indexed by world-up N.y + rim + constant g_vGlowColor.w, times albedo, times vertex AO.
- Face sign [read]: `s = vFace >= 0 ? 1 : -1; N = normalize(-s * v4)`. With the engine's
  right-handed projection the visible faces rasterise as D3D back faces (vFace < 0), so N = the
  vertex normal on the visible side and is flipped on the reverse side of double-sided
  geometry [inferred]. Blender does this by itself.
- Sky ("RSA") term [read]: a 2D texture row g_vRSALightOffset.y, column 0.5 - 0.5*N.y + offset.x,
  i.e. a ramp from straight-up (u = off.x) to straight-down (u = off.x + 1). The textures are
  `lighting/textures/rsalights/*_rsa.Texture` (non-DDS, 0xB0 header, per weather) [inferred].
  For Blender: a colour ramp on world-Z of the normal, scaled by the weather sky colour.
- oC1 is an MRT for deferred lights: oC1.xy = view-space normal (dot with g_vCameraRight/Up) *
  0.5 + 0.5, oC1.z = luma(albedo)*AO, oC1.w = floor(3.999*g_vSpecularConstants.y)*0.25098 +
  luma(gloss*g_vSpecularColor)*AO*0.247 [read]. Irrelevant for a Blender material.

### 4.2 `Spc`: sun specular (PS 0309 `RenderMesh_Shr_Spc`)

```hlsl
gloss  = tex2D(g_samGloss, uvGl).r;                       // only the red channel
specCol= gloss * g_vSpecularColor;
R      = reflect(-V, N);                                  // camera ray reflected
RdotL  = dot(g_vSunLightDir.xyz, R);
phong  = (RdotL > 1e-5) ? pow(RdotL, g_vSpecularConstants.x) : 0;    // Phong, not Blinn
spec   = phong * g_vSunLightSpecularColor * (1 - g_vSunLightDir.w * (1 - shadow.x))
         * specCol;
f      = 1 - saturate(dot(N, V));
fres   = lerp(1, f*f*f*f*f, g_vSpecularConstants.z);      // only ever attenuates
color  = albedo * light * AO + spec * fres * AO;
```

Excerpts (0309): `texld r3, v5, s8` / `mul r3.yzw, r3.x, c115.xxyz`; `dp3 r0.w, r1, r2` /
`add r0.w, r0.w, r0.w` / `mad r3.yzw, r2.xxyz, -r0.w, r1.xxyz`; `dp3 r1.x, c11, r3.yzww` /
`log r1.x, r1.x` / `cmp r1.x, r1.y, c0.w, r1.x` / `mul r1.x, r1.x, c116.x` / `exp r1.x, r1.x` /
`mul r1.xyz, r1.x, c112`; `mad r1.w, c11.w, -r4.x, c11.w`; `mul r1.w, r0.w, r0.w` /
`mul r1.w, r1.w, r1.w` / `mad r1.w, r0.w, r1.w, c3.y` / `mad r1.w, c116.z, r1.w, r3.x`;
`mad r0.xyz, r0, v1.z, r1`.

The spec is not energy-normalised and is not multiplied by albedo; its peak is
g_vSunLightSpecularColor * g_vSpecularColor * gloss.r. g_vSunLightDir.w is the sun shadow
strength for specular.

### 4.3 `Nm1` / `Nm2`: normals (PS 0381 `RenderMesh_Nm1_Shr`, PS 0662 full)

```hlsl
T  = normalize(tangent);  sgn = tangent.w (= sign(2*COLOR0.a-1));   // VS o6
Ng = normalize(-faceSign * vertexNormal);
B  = normalize(cross(vertexNormal, T));                   // raw normal, not face-flipped
n1 = tex2D(g_samNormal1, uvN1).ag * 2 - 1;                // DXT5nm: x = alpha, y = green, no flip
n2 = tex2D(g_samNormal2, uvN2).ag * 2 - 1;
k1 = g_vMapScaleFloats.x * (g_vLayerFloats.z != 0 ? w1 : 1);   // Normal1UseLayerAlpha
k2 = g_vMapScaleFloats.y * (g_vLayerFloats.w != 0 ? w2 : 1);   // Normal2UseLayerAlpha
xy = n1*k1 + n2*k2;                                       // additive (derivative-style) blend
z  = sqrt(1 - saturate(dot(xy, xy)));
N  = normalize(z*Ng + (xy.x*sgn)*T + xy.y*B);
```

Excerpts (0662): `texld r4, v6.zwzw, s5` / `mad r1.zw, r4.xywy, c2.x, c2.y` (alpha, green);
`texld r4, v6, s4` / `mad r3.yz, r4.xwyw, c2.x, c2.y`; `mad r1.xy, r3.yzzw, r1.x, r1.yzzw`;
`mul r1.z, r1.x, v5.w` (sign on X); `mul r3.yzw, r4.xyzx, v4.xzxy` /
`mad r3.yzw, v4.xyzx, r4.xzxy, -r3` (cross(N,T)); `dp2add_sat r1.x, r1, r1, c0.z` /
`rsq`/`rcp` (z); `abs r1.xy, c123.zwzw` / `cmp r1.xy, -r1, c0.x, r4.zwzw` /
`mul r1.xy, r1, c120` (scales).

Handedness is applied to the **tangent (X) term**, the bitangent is always cross(N, T)
[read]. Blender's Normal Map node instead uses B = sign * cross(N, T) with the stored X
unchanged; the two agree only when sign = +1 (see open questions). The game also normalises
the combined vector, then uses it for everything (sun, sky N.y, rim, specular, env).

### 4.4 `La1` / `La2` / `Lat`: layers (PS 0885 alpha-decal, PS 0132 `Lat`)

```hlsl
base = tex2D(g_samAlbedo, uv0).rgb * g_vDiffuseColor;
uvL1 = (g_vSecondUVPixel.z != 0 ? uv1 : uv0) * g_vMapTilingPixel.x;   // uv already * MapTilingVertex.x
uvL2 = (g_vSecondUVPixel.w != 0 ? uv1 : uv0) * g_vMapTilingPixel.y;
L1 = tex2D(g_samLayer1, uvL1);  L2 = tex2D(g_samLayer2, uvL2);
w1 = L1.a * (1 - COLOR0.r) * g_vLayerFloats.x;            // texture alpha x vertex mask x strength
w2 = L2.a * (1 - COLOR0.g) * g_vLayerFloats.y;
// AlphaDecal (g_vLayerBlendFloats.n == 0, and always without Lat):
c = lerp(base, L1.rgb, w1);
// LinearLightDecal (g_vLayerBlendFloats.n != 0, Lat only):
c = saturate(base + w1 * (2*L1.rgb - 1));
// same for layer 2 on top of c
albedo = c * COLOR1.rgb;
// specular mask from layers (multiplies gloss.r, i.e. spec AND env):
a = g_vLayerSpecularFloats.x*w1 + g_vLayerSpecularFloats.z*w2;
b = g_vLayerSpecularFloats.y*w1*luma(L1.rgb) + g_vLayerSpecularFloats.w*w2*luma(L2.rgb);
specMask = lerp(1, b, a);           // luma = dot(rgb, (0.3, 0.59, 0.11))
```

Excerpts (0662, alpha-decal): `mad r0.xyz, r0, -c116, r4` / `mul r4.zw, r5.xyxy, v1.xyxy` /
`mad r0.xyz, r4.z, r0, r1` / `lrp r1.xyz, r4.w, r3, r0`; `mul r4.xy, r0.wxzw, c124.ywzw` /
`dp2add r0.x, r4, r4.zwzw, c0.y` / `dp2add r1.z, c124.xzzw, r4.zwzw, r3.z` /
`mad r0.x, r1.z, r0.x, c0.x` / ... `mul r0.x, r0.x, r1.x` (x gloss.r).
Excerpts (0132, `Lat`): `abs r0.xy, c122`; `mad r5.xyz, r3, c2.x, c2.y` /
`mad_sat r1.xyz, r5, r0.z, r1` / `cmp r1.xyz, -r0.x, r4, r1`; `mad r4.xyz, r2, c2.x, c2.y` /
`mad_sat r4.xyz, r4, r0.w, r1` / `lrp r5.xyz, r0.w, r2, r1` / `cmp r1.xyz, -r0.y, r5, r4`.

Vertex-colour meaning, therefore: **COLOR0.r = 1 hides Layer1, 0 shows it; COLOR0.g likewise
for Layer2** [read]. The tint COLOR1.rgb applies after layering.

### 4.5 `Env`: environment cubemap (PS 0739 `Env_Nm1`, PS 0662 full)

```hlsl
E    = texCUBE(g_samEnvironmentCubemap, reflect(-V, N));
env  = (E.rgb / E.a) * g_vEnvironmentMapColor          // alpha-divided HDR (e.g. the DXT5
       * (1 - g_fEnvironmentMapShadowFactor * (1 - shadow.x));   // airbrushchromehdr_env)
// with Spc:  refl = (spec + env)  ; without Spc: refl = env      (spec already has SpecularColor)
refl = (spec_without_gloss + env) * gloss.r * specMask * fres * AO;
color = albedo * light * AO + refl;
```

Excerpts (0662): `texld r4, r1, s1` / `rcp r1.y, r4.w` / `mul r2.yzw, r1.y, r4.xxyz` /
`mul r2.yzw, r2, c114.xxyz` / `mad r1.y, c115.x, -r7.x, c115.x` / `add r1.yz, -r1, c0.x` /
`mul r2.yzw, r1.y, r2` / `mad r1.xyz, r1, c117, r2.yzww` / `mul r1.xyz, r0.x, r1` (gloss x
specMask) / `mad r0.x, c118.z, r0.x, r3.x` / `mul r1.xyz, r0.x, r1` / `mul r1.xyz, r1, v1.z` /
`mad r0.xyz, r0.yzww, v1.z, r1`.

Env is **not** multiplied by albedo or g_vSpecularColor; it is masked by gloss.r and the same
Fresnel factor as the spec. `Env` always samples g_samGloss (even without `Spc`) [read].

### 4.6 `Glw`: glow map (incandescence + translucence) (PS 0451 `Glw_Nm1`, PS 0662)

```hlsl
G     = tex2D(g_samGlow, g_vSecondUVPixel.y != 0 ? uv1 : uv0).r;   // no extra tiling
back  = saturate(dot(-N, g_vSunLightDir.xyz));
skyB  = tex2D(g_samRSALight, float2(0.5 + 0.5*N.y + g_vRSALightOffset.x, g_vRSALightOffset.y)).rgb;
trans = (1 - G) * g_vGlowColor.rgb * (back * g_vSunLightDiffuseColor * shadow.x
                                     + skyB * g_vSkyLightDiffuseColor);
light = sun + sky + trans + G * g_vGlowColor.w + rim;       // replaces the constant + GlowColor.w
```

Excerpts (0662): `texld r6, r2, s2` / `add r2.y, -r6.x, c0.x` / `mul r2.yzw, r2.y, c119.xxyz` /
`mul r3.yzw, r1.w, r2` (r1.w = `dp3_sat r1.w, -r4, c11`) / `mul r2.yzw, r2, r5.xxyz` (RSA at
the mirrored column) / `mul r2.yzw, r2, c113.xxyz` / `mul r3.yzw, r3, c111.xyz` /
`mad r2.yzw, r3, r7.x, r2` / `mad r2.yzw, r6.x, c119.w, r2` / `add r1.xyz, r1, r2.yzww`.

Both incandescence and translucence end up inside `light`, so **both are multiplied by albedo**
(self-illumination tinted by the diffuse colour, not an additive emission) [read]. Without
`Glw` there is no translucence and incandescence is the uniform g_vGlowColor.w.

### 4.7 `Det`: detail map (PS 0662)

```hlsl
D      = tex2D(g_samDetail, (g_vSecondUVPixel.x != 0 ? uv1 : uv0) * g_vMapTilingPixel.z).r;
detail = (0.5 + (D - 0.5) * g_vMapScaleFloats.z) * 1.9921875;     // 255/128: 2x-multiply
color  = (albedo*light*AO + refl) * detail;                         // before fog
```

Excerpts: `mul r2.xy, r2.zwzw, c122.z` / `texld r2, r2, s9` / `add r2.x, r2.x, c2.w` /
`mad r2.x, c120.z, r2.x, r3.z` / `mul r2.x, r2.x, c3.w` / `mul r1.xyz, r2.x, r0` /
`mad r0.xyz, r0, -r2.x, c110`.

### 4.8 `Bin`, `Trn`: alpha (PS 0734 `Bin_Shr`, PS 0886 `Shr_Spc_Trn`)

```hlsl
// Bin: clip(albedoTex.a - 0.5);  oC0.a = (albedoTex.a >= g_vTransparencyFloats.z) ? g_vTransparencyFloats.x : 0
// Trn: oC0.a = max(albedoTex.a, g_vTransparencyFloats.y) * g_vTransparencyFloats.x * COLOR1.a
//      blend SrcAlpha / InvSrcAlpha, colour write RGB, same lighting with a shadow-map
//      lookup (g_samShadowMapAtlas, g_amViewToShadowTexture) instead of the overlay.
```

Excerpts: 0734 `add r1, r0.w, c2.z` (-0.5) / `texkill r1` / `add r0.w, r0.w, -c116.z` /
`cmp oC0.w, r0.w, c116.x, r1.w`; 0886 `max r1.x, r0.w, c135.y` / `mul r0.w, r1.x, c135.x` /
`mul oC0.w, r0.w, v2.w`. Colour is not premultiplied.

### 4.9 Complete opaque formula (PS 0662 `RenderMesh_Det_Env_Glw_La1_La2_Nm1_Nm2_Shr_Spc`)

```hlsl
albedo = layered(tex(Albedo)*g_vDiffuseColor, Layer1, Layer2) * COLOR1.rgb;
N      = normal-mapped (4.3);  V = normalize(-P);  L = g_vSunLightDir.xyz
light  = sat(N.L)*SunDiffuse*sh.x + RSA(up)*SkyDiffuse*sh.y
       + (1-G)*GlowColor.rgb*(sat(-N.L)*SunDiffuse*sh.x + RSA(down)*SkyDiffuse) + G*GlowColor.w
       + RimColor * sat((1-sat(N.V))*Rim.y + Rim.x) * (1 - RimShadowFactor*(1-sh.x));
spec   = pow(R.L, SpecConst.x)*SunSpecColor*(1-L.w*(1-sh.x)) * g_vSpecularColor;
env    = (E.rgb/E.a)*EnvColor*(1 - EnvShadowFactor*(1-sh.x));
refl   = (spec + env) * gloss.r * specMask * lerp(1,(1-sat(N.V))^5, SpecConst.z);
color  = (albedo*light*AO + refl*AO) * detail;
out    = lerp(color, FogColor, fog) * g_vScreenTargetExpand.y;   alpha 1
```

### 4.10 Output encoding, gamma

- oC0 = linear radiance * g_vScreenTargetExpand.y. The final composite (image.fxo
  `ImageAddToneMapLDR`, PS 0012) reads it back * g_vScreenTargetExpand.x, adds bloom, applies
  g_fExpOverWhitePoint (exposure) and `pow(c, g_GammaExponent)` [read]. So .y/.x is a range
  encode/decode pair to ignore in Blender, and the scene is lit **in linear space** [inferred:
  Bink video is de-gamma'd with pow 2.2 before compositing, `BinkDegamma` PS def c3.z = 2.2].
- Sampler-state flag bit0 is set on Albedo/Layer/Detail/Gloss/EnvironmentCubemap and clear on
  Normal/RSALight/Ramp/Glow: consistent with SRGBTexture on colour maps [inferred]. Blender:
  albedo/layer/detail/env as sRGB; normal, glow, ramps as Non-Color. Gloss is flagged like a
  colour map [inferred; open].
- No tonemap curve in the material shaders; the luma weights (0.3, 0.59, 0.11) are only used for
  masks and the MRT.

---

## 5. RenderHair (PS 0040 `RenderHair`, PS 0012 `RenderHair_Nm1`, VS 0005/0006)

VS [read]: same AO/tangent-sign packing in COLOR0.a; **COLOR0.b packs a 2D comb direction**:
`d = -(2*frac(COLOR0.b*{1,16}) - 1)`, `Nc = normalize(T*d.x + cross(N,T)*d.y + N)`, used as
the "hair normal" when g_vOcclusionStrength.y != 0 (else the vertex normal); g_vOcclusionStrength.z
!= 0 adds a reflection-vector occlusion term (o6.y, unused by these PS). COLOR1 passes through
whole (rgba). UVs are not tiled in the VS.

```hlsl
Nn   = normal-mapped as RenderMesh (Nm1 only; uv choice g_vSecondUVVertex.x/y, tiling
       g_vMapTilingVertex.z/w, scales g_vMapScaleFloats.x/y; z from Normal1 alone)
Nh   = normalize(Nn + normalize(faceSign*Nc));            // shading normal for diffuse
NdL  = dot(Nh, L);
diffL= (saturate(NdL)*g_vSunLightDiffuseColor
        + RSA(0.5 - 0.5*Nh.y + off.x, off.y)*g_vSkyLightDiffuseColor) * shadow.x;   // sky also uses .x
NdV  = dot(Nn, V);  NnL = dot(Nn, L);
uvR  = float2(1 - (0.5 + 0.49*NdL), 1 - (0.5 + 0.49*NdV));
R1   = tex2D(g_samRamp1, uvR);  R2 = tex2D(g_samRamp2, uvR);
A    = tex2D(g_samAlbedo, uv0 * g_vMapTilingPixel.z);     // r = diffuse, g = spec, b = glow mask
diff = diffL * (g_vDiffuseColor*g_vDiffuseColor) * R1.rgb * A.r;      // DiffuseColor squared
glowC= (g_bAdditiveUseSpec > 0 ? R2.rgb : R1.rgb) * saturate(1 - R1.a)
       * g_vMapTilingVertex.x * A.b * g_vGlowColor.rgb * g_vSkyLightDiffuseColor;
cosD = sqrt(1-NdV*NdV)*sqrt(1-NnL*NnL) + NdV*NnL;          // cos(thetaV - thetaL) about Nn
spec = pow(cosD, g_vSpecularConstants.x) * g_vSunLightSpecularColor
       * (1 - g_vSunLightDir.w*(1-shadow.x)) * R2.rgb * g_vSpecularColor
       * lerp(1, (1-saturate(NdV))^5, g_vSpecularConstants.z) * A.g*1.9921875 * AO;
color= (diff*AO + glowC) * COLOR1.rgb + spec;
out  = lerp(color, g_vFogColor, fog) * g_vScreenTargetExpand.y;  oC1 = (0.5,0.5,0,0)
```

Excerpts (0012): `mul r4.xyz, c112, c112` / `mul r4.xyz, r1, r4` / `mul r2.zw, c120.z, v2.xyxy` /
`texld r5, r2.zwzw, s3` / `mul r4.xyz, r4, r5.x`; `mad r0.x, r0.x, c1.x, c1.y` (0.49, 0.5) /
`add r3.x, -r0.x, c2.x`; `mad r1.x, r2.x, c1.x, c1.y` / `add r3.y, -r1.x, c2.x` /
`texld r1, r3, s10` / `texld r3, r3, s11`; `add_sat r1.w, -r1.w, c2.x` /
`cmp r1.xyz, -c117.x, r1, r3` / `mul r1.w, r1.w, c119.x` / `mul r1.w, r5.z, r1.w`;
`mul r1.x, r2.x, r2.y` / `mad r1.yz, r2.xyxw, -r2.xyxw, c2.x` / `rsq`/`rcp` /
`mad r1.x, r1.y, r1.z, r1.x` / `log`/`mul c114.x`/`exp` / `mul r1.xyz, r1, r3` /
`mul r1.xyz, r1, c113` / `mul r2.z, r5.y, c0.w`; `mad r0.xyz, r0, v5.x, r1` /
`mad r0.xyz, r0, v1, r1`.

So hair colour comes from the **Ramp1 texture** (a 2D LUT over wrapped N.L and N.V), not from
the albedo texture, which is a 3-channel mask; spec colour comes from Ramp2. Alpha: `Bin` =
`texkill(A.a - 0.5)`, `Trn` = `max(A.a, TF.y) * TF.x * COLOR1.a` (PS 0072, 0060) [read].

---

## 6. Engine-side constants (from BrutalLegend.exe)

Everything in this section was read in the IDA database (functions renamed there, addresses
below). Implemented in `brutal/shaders.py`: `material_constants(props, damage=0.0, ...)`,
`weather_constants(weather, elevation=90, sun_rsa=None)`, `resolve_options`, `sun_direction`,
`specular_bucket`; RSA gradients in `brutal/rsalight.py`. Gate: `tests/corpus_shaders.py`
resolves **2748/2748** materials to a technique that exists (RenderMesh/RenderHair through the
full option logic, static and skinned; the other shaders by base name).

`g(c)` below = `pow(c, 2.2)` per component: `ShaderColorVec3_Gamma` 0x65D8C0 /
`ShaderColorVec4_Gamma` 0x65D950 apply it to every colour constant when the renderer's
linear-lighting byte is set (effect object +333). The same mode makes the final
`g_GammaExponent = 1 / lerp(1.2, 3.2, t)` (`Gamma_SetFromBrightness` 0x652E80, t = 0.5 at the
default brightness -> 1/2.2; the non-linear branch gives 1/lerp(0.5, 1.5, t) = 1.0). Together
with Bink "Degamma" and the texture `EnableGamma` build flag this is the linear pipeline;
where +333 is written was not found [open, linear assumed].

### 6.1 Material object (reflection, `Material_RegisterAttributes` 0x6635A0)

Keys map to fields of the runtime Material (byte offsets): Transparency +0, Incandescence +4,
Layer1Strength +8, Layer2Strength +12, DiffuseColor +48, SpecularColor +60, SpecularIntensity
+72, flags u16 +84, textures +88..+132 (Diffuse, Gloss, Translucence, Incandescence, Normal1,
Normal2, Detail, Layer1, Layer2, EnvironmentMap, Ramp1, Ramp2), 1/Roughness +136, bucket/8 +140,
Fresnel +144, Roughness +148, SunlightStrength +152, EnvironmentMapColor +156,
EnvironmentMapIntensity +168, RimLightColor +172, RimLightIntensity +184, RimLightWidth +188,
TranslucenceColor +192, TranslucenceIntensity +204, Layer1/2 Specular Strength/Intensity
+208..+220, Layer1Blend +224, Layer2Blend +225, BlendMode +226, tilings +228..+252 (Diffuse,
Gloss, Normal1, Normal2, Layer1, Layer2, Detail), Normal1/2Scale +256/+260, DetailScale +264,
SceneImageStrength / LightBloomStrength / InkBloomStrength +268..+276, SecondUV floats +308..+332
(Normal1, Normal2, Gloss, Detail, glow, Layer1, Layer2), DepthPrepassThreshold +336.

Setters with side effects: `Material_SetRoughness` 0x666A20 (stores 1/max(r,1e-5) and the
bucket), `Material_SetTranslucenceIntensity` 0x666AE0 (flag 0x40 = intensity != 0),
`Material_SetTransparency` 0x6669D0 (flag 0x20 = value < 1), `Material_SetShader` 0x666830
(flag 0x80 = RenderMesh, 0x100 = RenderHair, 0x2000 = either, 0x800 = hair/fur),
`Material_SetBlendMode` 0x666990. Enums: BlendMode Default 0, Opaque 1, BinaryAlpha 2, Alpha 3,
Additive 4, Multiply 5, Subtractive 6, Min 8 (0x6751D0); kLBM_AlphaDecal 0, LinearLightDecal 1
(0x661B10).

### 6.2 Per-draw constants (`Material_SetShaderConstants` 0x65C4B0)

`a4` = LOD fade (1 at full detail), `inst` = optional per-instance parameters (see 6.4).
`S` = render context (scene lighting, 6.5). Stored copies (used for the technique choice, 6.3)
zero any component with |x| < 0.001 (0x65DA40 / 0x65DAF0).

```
k                       = log2(next_pow2(int(1/max(Roughness,1e-5)))), clamped 0..7   (0x666A20, 0x675670)
g_vSpecularConstants    = (1/max(Roughness,1e-5), k/8, Fresnel, Roughness)
g_vDiffuseColor         = g(DiffuseColor * inst[0..2])
g_vSpecularColor        = g(SpecularColor * SpecularIntensity * inst[3..5])
g_vGlowColor            = (g(TranslucenceColor * TranslucenceIntensity), Incandescence + inst[6])
g_vMapScaleFloats       = (Normal1Scale, Normal2Scale, DetailScale)
g_vLayerFloats          = (Layer1Strength*inst[9], Layer2Strength*inst[10],
                           Normal1UseLayerAlpha, Normal2UseLayerAlpha)
   RenderMesh only (flag 0x80): a missing Normal1/Normal2/Detail/Layer1/Layer2 texture zeroes
   its scale/strength; then strength = max(strength, 0.001) if NormalNUseLayerAlpha.
g_vLayerBlendFloats     = (min(Layer1Blend==LinearLight ? 1:0, L1), min(.., L2), 0)
g_vLayerSpecularFloats  = (Layer1SpecularStrength, Layer1SpecularIntensity,
                           Layer2SpecularStrength, Layer2SpecularIntensity)
g_vMapTilingVertex      = (DiffuseTiling, GlossTiling, Normal1Tiling, Normal2Tiling)
g_vMapTilingPixel       = RenderMesh: (Layer1Tiling, Layer2Tiling, DetailTiling) / DiffuseTiling
                          RenderHair: (Layer1Tiling, Layer2Tiling, DetailTiling)
g_vSecondUVVertex       = (Normal1SecondUV, Normal2SecondUV, GlossSecondUV)
g_vSecondUVPixel        = (DetailSecondUV, glowSecondUV, Layer1SecondUV, Layer2SecondUV)
   glowSecondUV = TranslucenceSecondUV if TranslucenceIntensity != 0 else IncandescenceSeconduV
g_vTransparencyFloats   = (Transparency * inst[7], textureAlpha ? 0 : 1, 0.5)
g_bTextureAlpha         = BlendMode >= Alpha and SceneImageStrength > 0     (0x665BA0 bit 2)
g_bBinaryAlpha          = BlendMode == BinaryAlpha
g_vBufferStrengths      = (SceneImageStrength, LightBloomStrength, InkBloomStrength)
g_vEnvironmentMapColor  = g(EnvironmentMapColor * EnvironmentMapIntensity *
                            (material has EnvironmentMapTexture ? S.envColorOwn : S.envColorScene))
g_vRimLightColor        = g(RimLightColor * S.rimColor * RimLightIntensity)
w = RimLightWidth * S.rimWidth;  inv = (w < 1e-5) ? 1 : 1/w
g_vRimLightConstants    = (-(1-w)*inv, inv, w)      =>  rim = saturate(1 - (N.V)/w)
g_vSunLightDiffuseColor = g(S.sun * SunlightStrength * SPEC_NORM[0])       SPEC_NORM[0] = 0.0853055
g_vSunLightSpecularColor= g(S.sunSpec * SunlightStrength * SPEC_NORM[k])
g_vFogColor             = g(S.fogColor)   (not updated for Additive/Multiply/Subtractive)
g_vOcclusionStrength    = (1, 1, 1) every frame (Weather_SetFrameConstants 0x6F31C0)
```

`SPEC_NORM` (exe 0xE8061C) = 0.0853, 0.1080, 0.1425, 0.1915, 0.2561, 0.3329, 0.4088, 0.4618, the
same 8 floats that open `simplesun_rsa` (6.6). So a sun of Intensity 12 gives about 1.0 x Color
diffuse, and the specular peak grows with the exponent bucket. The deferred point lights decode
the bucket from oC1.w as exponent 1/(0.5 - 0.15*floor(4*k/8)).

Textures bound (0x65C4B0, defaults from `Renderer_LoadCommonTextures` 0x64FBE0 via
`RenderContext_Init` 0x65A4C0):

| Sampler | Texture | Empty slot |
|---|---|---|
| g_samAlbedo | DiffuseTexture | Renderer/Textures/Common/White |
| g_samGloss | GlossTexture | White |
| g_samNormal1 / 2 | Normal1/2Texture | Default_Norm |
| g_samDetail, g_samLayer1/2 | Detail / Layer1 / Layer2 | Gray |
| **g_samGlow** | **TranslucenceTexture if TranslucenceIntensity != 0, else IncandescenceTexture** | Black (translucence) / White (incandescence) |
| g_samEnvironmentCubemap | EnvironmentMapTexture | the Weather's EnvironmentMap (context +148) |

So with no glow texture, translucence covers the whole surface (G = 0) and incandescence is
uniform (G = 1), matching the no-`Glw` shader.

### 6.3 Technique selection (`ShaderOptions_SelectTechnique` 0x66D760, rules 0x66F1D0)

Option bits are the alphabetical flags (table at 0xF7A6EC: Bin 0, Blm 1, Dbg 2, Dec 3, Det 4,
Dep 5, DpC 6, Edg 7, Env 8, ...). RenderMesh (case 0) requests, from the stored constants:

| Flag | Requested when |
|---|---|
| Bin | g_bBinaryAlpha (BlendMode == BinaryAlpha) |
| Det | MapScaleFloats.z != 0 (DetailTexture and DetailScale) |
| Env | EnvironmentMapColor != 0 (EnvironmentMapIntensity * colours) |
| Glw | GlowColor.rgb != 0 (TranslucenceIntensity*Color) or (Incandescence != 0 and g_samGlow is not the White default) |
| La1 / La2 | LayerFloats.x / .y != 0 |
| Lat | LayerBlendFloats != 0 (a LinearLight layer with strength) |
| Nm1 / Nm2 | MapScaleFloats.x / .y != 0 (texture present) |
| Spc | SpecularColor != 0 (SpecularColor * SpecularIntensity) |
| Trn | Transparency < 1, or g_bTextureAlpha and not Bin |
| Shr, Skn, Rgd, Flg, Fld, Dec, Pnt, Prj, Blm, Dep, DpC, Shc, Shd, Dbg | draw context (shadow receive, skinned mesh, foliage, pass) |

RenderHair (case 14): Bin; **Edg** when g_samGlow is a real texture (not White/Black); **Nm1**
when Normal1Scale and Normal2Scale are both != 0 (no texture check for hair); Pnt/Prj with Trn;
Skn; Trn as above.

Then each requested option switches on/off other options (records built in
`ShaderOptions_Register` 0x66F1D0, closed transitively by `ShaderOptions_CloseMasks`
0x671850), final = on & ~off, looked up exactly (`ShaderOptions_Lookup` 0x66E770):

```
RenderMesh  Det -> La2, Nm2        Env -> Nm1 (off Dec)     Glw -> Nm1 (off Dec)
            La1 -> Shr             La2 -> La1               Lat -> La2, Nm2, Spc
            Nm1 -> Shr             Nm2 -> Nm1               Spc -> Shr      Trn -> Spc
            Dec -> Nm1, Shr, Trn   Fld -> Flg, Nm1          Flg off Dec, Skn
            Pnt/Prj -> Nm2, Trn    Rgd -> Skn               Bin off Dec
            Blm/Dbg/Dep -> Det La1 La2 Lat Nm1 Nm2 Shr Spc (+ their off sets), DpC/Shc -> Dep, Shd -> Shc
RenderHair  Pnt/Prj -> Trn
```

This is why, for example, a material with only an env map renders with `Env_Nm1_Shr_Spc`: the
extra terms run with zero weight / Default_Norm / Gray layers.

### 6.4 Per-instance parameters, blood damage

`inst` is the draw instance's parameter block (`RenderList_DrawMeshes` 0x65AD10 passes
`[instance+0x30]`): [0..2] diffuse multiplier, [3..5] specular multiplier, [6] incandescence
add, [7] transparency multiplier, [8] pass mask, **[9] Layer1Strength multiplier, [10]
Layer2Strength multiplier**, [11..18] custom vectors. `CoRenderMesh_ctor` 0x571C10 initialises
the component's two layer scales (+368, +372) to 1.0. The health component, when its
**HasDamageTexture** is set (entity property, not a Material key), writes every update
(`Health_UpdateDamageTexture` 0x84CCC0, also 0x84AE00) into the render object's +372:

```
damage = saturate(1 - (health/maxHealth - R.x) / (R.y - R.x))     (Health_GetDamageTextureAmount 0x850190)
         R = DamageTextureDisplayRange (default (0, 1)); 0 when gore is disabled
```

So an undamaged character has Layer2 multiplier 0 (the `characters/textures/blooddamage`
layer, Layer2Strength 6, is invisible) and it ramps in as health drops; with
AccessoriesShowDamage the same value goes to attached accessories. Layer1 (chest hair,
rough skin) is not scaled (stays 1.0). That +372 is the block's [10] is [inferred] from the
matching defaults and the single writer; the formula itself is [read].
`material_constants(..., damage=0.0, has_damage_texture=None)` applies the multiplier to
materials whose Layer2Texture is `blooddamage` (heuristic for "entity has HasDamageTexture");
pass `has_damage_texture=False` for props.

### 6.5 Scene constants from the Weather (`Weather_SetLightConstants` 0x6F4850,
`Weather_SetFogConstants` 0x6F6040)

Weathers are blended into a WeatherState (`Weather_BlendState` 0x4F78F0); for one Weather:

```
S.sun          = SunLight.Color * SunLight.Intensity * PostSettings.SunStrengthMultiplier * G
S.sunSpec      = S.sun * SunLight.SpecularIntensity
S.sky          = SkyLight.Color * SkyLight.Intensity * PostSettings.SkyStrengthMultiplier * G
g_vSkyLightDiffuseColor = g(S.sky * S116)
S.envColorScene= EnvironmentMapColor * EnvironmentMapIntensity        (material without own cube)
S.envColorOwn  = AverageEnvironmentColor * AverageEnvironmentIntensity (material with own cube)
S.rimColor     = RimLightColor * RimLightIntensity ; S.rimWidth = RimLightWidth
g_fEnvironmentMapShadowFactor = EnvironmentMapShadowFactor ; g_fRimLightShadowFactor = RimLightShadowFactor
g_vSunLightDir = (-row2(Rx(e) * Rz(SunDeclination) * Ry(SunRotation)), SunLight.SpecularShadowFactor)
               = (-(se*sd*cr + ce*sr), se*cd, se*sd*sr - ce*cr, SSF)        (0x4F4350, 0x685570/0x6856F0/0x685630)
   e = time-of-day angle: seconds*360/86400 - 90, folded into [40, 140] (0x4F78F0); 90 = noon
g_vRSALightOffset = (1/512, 1/16)  (constant; row 0/1 of the RSA texture)
S.fogColor     = FogSettings.FogColor * FogBrightness * G
g_vFogRange    = (FogRange.x, FogRange.y, 1/(FogRange.y - FogRange.x), FogDensity)
g_vFogHeightFade = (FogHeightFade.x, .y, 1/(y - x), FogHeightMinDensity)
```

G (WeatherState +640, multiplies sun, sky and fog) and S116 (render context +116, sky) are
runtime scales whose source was not identified [open; 1 assumed]. With the shader's fog code
this gives fog = (1 - exp((x - min(dist, y)) * density)) * (minDensity + h*(1 - minDensity)).
Game space is Y-up; Blender (x, -z, y).

### 6.6 RSA light gradients (`brutal/rsalight.py`)

`lighting/textures/rsalights/*_rsa.Texture` (16): 0x10 width 256, height 16, mips 2; 0x20 bytes
`_ASR`; 0x24 8 floats = specular normalisation per bucket (simplesun's equal the exe table);
0x44 27 floats = 9 red, 9 green, 9 blue (RSALight's Red/Green/Blue arrays, SH-like; use not
traced); 0xB0 u32 size + DDS A8R8G8B8 256x16. Rows come in identical pairs: 8 ramps, one per
bucket; u = 0.5 - 0.5*N.y (0 = facing up, 1 = facing down). Example (blueskywithwarmbounce):
up = (213,221,255)/255 bluish, down = (105,73,64)/255 warm bounce. g_samRSALight =
the Weather's SkyLight.Gradient [inferred from the name and the SkyLightDiffuseColor product];
sampled linear (sampler flag 0). For Blender: an RGB ramp on world-Z of the normal from row 0,
times g_vSkyLightDiffuseColor.

---

## 7. What this means for the look

- Diffuse = Lambert sun (no wrap, no half-lambert) + a sky ramp on world-up N.y + rim + constant
  self-illumination, all multiplied by albedo and by **vertex AO = |2*COLOR0.a - 1|**.
- Specular = classic Phong on the reflection vector, sun only, gloss.r-masked, attenuated by a
  Fresnel that can only reduce it (lerp(1, (1-N.V)^5, Fresnel)). With Fresnel 0.5 facing
  surfaces keep half.
- Reflection: only with `Env`; scaled by g_vEnvironmentMapColor (most materials Intensity 0,
  else 0.1/0.5/1), by gloss.r and the same Fresnel. By default reflections are weak or absent;
  there is no implicit sky reflection on plain RenderMesh.
- No PBR energy conservation anywhere; nothing is Principled-BSDF-like.

---

## 8. Open questions

1. Where the renderer's linear-lighting byte (effect +333, which makes every colour constant
   pow 2.2 and GammaExponent 1/2.2) is set; linear is assumed (all evidence points that way).
2. WeatherState +640 (global scale on sun/sky/fog) and render context +116 (sky scale): source
   not identified, taken as 1. The time-of-day elevation is game-clock driven (pass it in).
3. HasDamageTexture is an entity/health-component property; the Material does not say whether
   its entity has it (heuristic: Layer2Texture == blooddamage). The +372 <-> inst[10] link is
   inferred.
4. g_samRSALight = SkyLight.Gradient is inferred; the RSA Red/Green/Blue (SH) arrays and the
   SunLight gradient image are not used by the mesh shaders that were read.
5. Tangent sign convention vs Blender: the game puts the handedness on the X (tangent) term and
   uses B = cross(N, T); Blender puts it on B. Check against a mirrored mesh. The 8 bytes after
   the normal in the static vertex (+16) and skinned vertex (+32), unparsed by `brutal/mesh.py`,
   are presumably the TANGENT input [inferred].
6. Sampler flag bit0 = SRGBTexture is inferred (it is also set on ScreenNormal/ScreenImage).
7. g_vMapTilingVertex.x (DiffuseTiling) multiplies the hair glow term, and hair albedo uses
   g_vMapTilingPixel.z (DetailTiling) - read from the code, purpose unclear.
8. Render state fields other than [3], [6], [7], [9]; fog colour for Additive/Multiply/
   Subtractive materials (left unchanged by the engine; 0 assumed).
