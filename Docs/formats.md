# Brutal Legend PC file formats

Every fact here is proven by a corpus gate (`python check.py`) over the whole Steam install
(`Win/Packs`, 20 bundles, 71,095 resources), or marked as an assumption. IDA addresses refer to
`BrutalLegend.exe` (Steam build, 13,180,928 bytes, x86, no DRM wrapper). Where a tag is used by two
functions they are a serializer pair; which one reads and which writes is not pinned yet.

| Resource | Count | Decoder | Gate | IDA |
|---|---:|---|---|---|
| Bundle `.~h`/`.~p` (DFPF v5) | 20 | `Brutal/dfpf.py` | `Tests/corpus_dfpf.py`: 71,095/71,095 unpack to header+data | — |
| Mesh | 7,711 | `Brutal/mesh.py` | `Tests/corpus_mesh.py`: 7,711/7,711 byte-exact, parsed header = record header | `hsem`/`lrtm` sub_64C5C0, sub_64C860; `tsbs` sub_64D0A0, sub_64D6B0; `BVXD` sub_66A5E0, sub_66A720 |
| Rig | 302 | `Brutal/rig.py` | `Tests/corpus_rig_tex.py`: 302/302, parents precede children, 301 mesh↔rig palettes in range | — |
| Texture | 10,672 | `Brutal/texture.py` | 10,656 DDS byte-exact; 16 `rsalights` are another subtype | `rtxT` sub_64E170 |
| Material | 2,748 | `Brutal/material.py` | `Tests/corpus_material.py`: 2,748 parse, 11,247/11,247 texture refs resolve | — |
| Text objects (69 types: MeshSet, Weather, LevelData, Cutscene, …) | 11,678 | `Brutal/textobj.py` | `Tests/corpus_textobj.py`: 11,678/11,678 parse | — |
| UI movie (`.gfx`, Scaleform) + DUIMovie | 80 + 79 | `Brutal/gfx.py` | `Tests/corpus_gfx.py`: 80 parse to their length, bundle = disk, 1,664/1,664 external images resolve, FontMap fonts exist | see [ui.md](Formats/ui.md) |
| UI movie content (shapes, morphs, edit texts, placements, sprites) → SVG | 80 | `Brutal/gfx.py`, `Brutal/gfxsvg.py`, `Brutal/image.py` | `Tests/corpus_render.py`: 43,059 character/placement tags decode to their length, 9,409/9,409 fill contours close, 480 renders (frame 0 + 160 labels, sprites unsettled and settled) with every character, bitmap, font and texture resolved; BC1/BC3 within 1 level of ImageMagick | see [ui.md](Formats/ui.md) §13 |
| UI fonts (DefineFont3) → TrueType | 3 shared + 42 embedded | `Brutal/ttf.py` | `Tests/corpus_ttf.py`: checksums, loca, cmap, hmtx, kern re-read; every contour round-trips to the source outline | — |
| AnimResource | 15,866 | `Brutal/anim.py` | `Tests/corpus_anim.py`: 15,866 parse, 34,370 chunks / 618,660 sections close, 9.86M quaternions unit | see [anim.md](Formats/anim.md) |

## DFPF bundles (`Win/Packs/*.~h` + `*.~p`)

`.~h` holds the directory, `.~p` the payloads. Integers in the directory are big-endian even on PC.

```
0x00 'dfpf'   0x04 u8 version = 5
0x08 u64 type table offset      0x10 u64 name directory offset
0x18 u32 type count             0x1C u32 name directory size     0x20 u32 file count
0x38 u64 record table offset    (16-byte records)
type table: { u32 len; char name[len]; u8 unknown[12] } * type count
```

Record bitfields (16 bytes, read as big-endian words):

| Bits | Field |
|---|---|
| `BE32(+0) >> 8` | data size (24 bits) |
| `BE32(+3) >> 11` | name offset into the directory (21 bits) |
| `(BE32(+4) >> 1) & 0x3FFFF` | **header size** (18 bits) |
| `BE32(+8) >> 3` | payload offset in `.~p` |
| `(BE32(+11) << 5) >> 9` | stored size |
| `((BE32(+14) << 4) >> 24) >> 1` | type index |
| `byte(+15) & 15` | compression: 4 raw, 8 zlib, 12 XMemCompress (Xbox only) |

**Correction to DoubleFine Explorer:** the field it calls "uncompressed size" is only the *data*
part. Every resource unpacks to `header_size + data_size`; the header part is the CPU-side
description the engine parses, the data part is the bulk (vertex buffers, DDS, keyframes). This is
the `.header` / data split that the old Noesis script expected as two files. Proven on all 71,095
entries.

## Mesh

Header part (= record `header_size`, proven on all meshes), little-endian:

```
0x00 'hsem'  0x04 u32 0
0x08 bounding sphere, boxes, mip constants (floats)
0x50 'lrtm' u32 material count, { u32 len; char path[len] }   material paths, no extension
     u32 submesh count, per submesh:
       'tsbs' u32 material index, u32 ?
       'BVXD' u32 vertex count, u16 vertex format, u32 morph frame count, [morph block]
       'BIXD' u32 0, u32 index count, u32 primitive (2 list, 3 strip)
              u8 bone palette count, u8 palette[count], 56 bytes misc + local bounds
     u16 attach bone (0xFFFF none), u16 last morph index (0xFFFF none; = morph block 'last')
```

Morph block per frame: `u32 n`, then `n × { u32 vertex; s16 dpos[3]; s16 dnrm[3]; s16 dtan[4] }`;
after all frames `u16 order[frames]` (flex channel per frame, indexes `Rig.flex_names`),
`u16 last`, `u32 len`, `name` (e.g. `LOD0_FaceShape`). Delta scale is **2/32767, proven**: with it,
`normal + dnormal` is unit length on all 128,331 morph deltas in the corpus (rms 1.3e-4); 1/32767
or 4/32767 miss by 300× or more. The submesh reader (sub_64D6B0) stores the 24-byte deltas raw;
`order[f]` is the rig flex channel of frame `f` (proven: `Lf_`/`Rt_` shapes move +X/−X vertices
in 32/32 sided frames, the inverse mapping only 10/32). Animation float tracks drive these
channels with weights in about [−0.6, 1].

Correction to the layout above, from sub_64D6B0: the u32 after the material index is the
**number of vertex streams** (`BVXD` blocks, always 1 on PC).

Data part: per submesh, vertex buffer then `u16` index buffer.

| Format | Stride | Layout |
|---|---:|---|
| `0x200` static | 40 | pos half4 (w = 1), normal half4, tangent half4, uv0 half2, uv1 half2, color0 BGRA8, color1 BGRA8 |
| `0x400` skinned | 48 | bone index u8×4 (into the submesh palette), weight u8×4, pos half4, uv0 half2, uv1 half2, normal half4, tangent half4, color0, color1 |

Only these two formats exist on PC (survey of every `BVXD`). Strips: odd triangles flip, repeated
indices are stitches.

Space: **Y-up, right-handed, characters face +Z** — proven on `a01_avatar` (eyes at +Z, `Lf_*`
bones at +X) and by the winding check: with the rotation `(x, y, z) → (x, −z, y)` into Blender,
34,413 of 34,436 faces agree with the game's own stored normals.

## Rig

```
0x00 u32 0     0x04 u64 rig hash (AnimResource +4 carries the same hash)
0x0C u32 name blob size   0x10 u32 bone count   0x14 u32 parent array capacity (padded)
0x18 u32 flex count       0x4C u32 offsets[8], relative to 0x70     0x6C ' gir'
0x70 names: bone_count NUL strings, then flex_count NUL strings ("LOD0_FaceShape:LOD0_BS_JawOpenShape")
offsets[1]: s16 parent[capacity]   (-1 root; entries past bone_count are filler)
offsets[5]: f32 inverse_bind[bone_count][16]  row-major, translation in the last row (D3D style)
```

Header part = `0x70` on all 302 rigs. offsets[0], [2], [3], [4] are not decoded yet.

## Texture

Header part `0x24`: `+0x08` engine format (9 DXT1, 11 DXT5), `+0x10` width, `+0x14` height,
`+0x1C` mips, `+0x20` `'rtxT'`. Data part: `u32 size` + a complete DDS file. Normal maps are
**DXT5nm** (X in alpha, Y in green, R = B = 0; measured on the avatar maps). Green-channel
convention (DirectX vs OpenGL) is **not verified** yet.

## Material

`u32 length` + text `1Material{Key=Value;...}`. Values: numbers, `<x,y,z>` vectors, `@path`
texture references (`@` alone = none), `[a,b]` arrays, `kEnum` names. 25 shader families
(`ShaderName`), `RenderMesh` is 2,528 of 2,748. Main keys: `DiffuseTexture`, `Normal1Texture`,
`Normal2Texture`, `GlossTexture`, `Layer1Texture`/`Layer2Texture` (+ `…Blend`, `…Tiling`),
`DetailTexture`, `IncandescenceTexture`, `Ramp1Texture`/`Ramp2Texture` (hair), `DiffuseColor`,
`Roughness`, `Fresnel`, `BlendMode`, `DoubleSided`.

`RenderHair`: the diffuse map is a grey index sampled into `Ramp1Texture`, its alpha cuts the hair
cards (reading from the textures; shader not disassembled). Layer blending is driven by a vertex
color channel that is **not pinned yet**, so the Blender importer loads layer textures but leaves
them unwired.

## UI movies (Scaleform GFx)

`DUIMovie` (text object): `FlashFile=Data/UI/<Screen>/Opt/<Screen>.gfx; Textures=[@ui/flash/...]`.
The `.gfx` is on disk and also in the bundles as a `Blob` at the lower-cased path, byte-identical
(gate). Header `'GFX'`/`'CFX'` (zlib after byte 8), version 8, u32 uncompressed length; SWF 8 tag
stream ending with End exactly at that length (CFX bodies carry zero padding after it).
Scaleform tags: 1000 ExporterInfo, 1001 DefineExternalImage (`u16 id, u16 format, u16 w, u16 h,
str8 export name, str8 file name`). Every external image is a Texture listed by the DUIMovie, found
by the lower-cased stem of its file name; the texture is the image size rounded up to 4 (DXT
blocks). Fonts: `FlashConfig.FontMapping[].SharedFontFile` = `Data/UI/Fonts/Opt/EnglishFonts.gfx`,
three DefineFont3 (Schreibweise, TG_Menu, TG_Condensed; 159 glyphs, em = 1024 × 20, layout and
kerning present); `FontMap` maps the names movies import from `gfxfontlib.swf` (`$Fancy`, `$Menu`,
`$Condensed`) to them. Engine side: [formats/ui.md](Formats/ui.md).

Movie content is standard SWF 8 (layouts in the `Brutal/gfx.py` docstring): DefineShape 1–4,
DefineMorphShape 1–2, DefineEditText, DefineSprite, PlaceObject2/3, RemoveObject2, FrameLabel.
The corpus uses only solid and bitmap fills (no gradients), Glow and DropShadow filters, blend
modes multiply / add / screen, and no clip layer. A bitmap fill names either a DefineExternalImage
of the movie, an id imported from `Shared/ControllerIcons.swf` (an external image of
`PhysicalInputIcons.gfx`), or 65535 in a style no edge selects (gate: `Tests/corpus_render.py`).
`Brutal/gfxsvg.py` renders a root frame to SVG and `Brutal/ttf.py` writes a DefineFont3 as a
TrueType font; what each covers and leaves out: [formats/ui.md §13](Formats/ui.md).
