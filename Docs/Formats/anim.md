# AnimResource (skeletal animation)

Decoder: `Blender/BrutalLegend/Brutal/anim.py`. Gate: `Tests/corpus_anim.py`. Addresses are `BrutalLegend.exe`
(Steam build); every function named below was renamed in the IDA database
(`.evidence/ida/BrutalLegend.exe.i64`) — the original `sub_` address is given with each name.

Corpus: 15,866 AnimResource entries (RgB_Ctsn, RgB_Faction, RgB_Mission and the DLC bundles).
All 15,866 use codec 1 (CompressedSkeletalAnimation); codec 0 does not occur.

## 1. Outer resource

Read by `AnimResource_Deserialize` (sub_40E2D0). Little-endian.

| Offset | Type | Field | Source |
|---|---|---|---|
| 0x00 | u32 | codec: 0 → `UncompressedSkelAnim_Create` (sub_418900), 1 → `CompressedSkelAnim_Create` (sub_414480) | `AnimCodec_Create` sub_4131E0 |
| 0x04 | u64 | rig hash, equals `Rig.hash` (all 15,866 match a rig in the corpus) | sub_40E2D0 (byte-swapped by `ByteSwap64` sub_41D930 on big-endian streams) |
| 0x0C | u8 | B = bone track count | sub_40E2D0 |
| 0x0D | u8 | F = float track count | sub_40E2D0 |
| 0x0E | u8[B] | `bone_map`: track → rig bone | sub_40E2D0 (object +16) |
| | u8[F] | `float_map`: float track → rig flex (morph channel) | sub_40E2D0 (object +24) |
| | f32 | (frame_count − 1) / fps — observed, not used by the sampler | object +32 |
| | f32 | its inverse — observed | object +36 |
| | f32[3] | **unknown** (often zero; looks like a displacement, unverified) | object +40 |
| | u32, u32 | **unknown** (object +52, +56) | |
| | u32 n, n × 8 bytes | **unknown** array; values look like (f32, f32) pairs in [0, 1] (time ranges?) — unverified | `sub_40FAF0` resize, object +72 |
| | `'vena'` u32 len, char[len] | event text (e.g. `[]`), parsed by `TextInputDataStream` | tag 0x616e6576 checked by sub_45F430; read by sub_45F1B0; parsed by sub_410E30 |
| | `'mina'` | end of the CPU header | tag 0x616e696d, sub_45F430 |
| | blob | codec data, to the end of the entry | |

The blob is exactly the DFPF record's *data part*: `header_size` of the bundle record equals the
offset just past `'mina'` (gate check). `CompressedSkelAnim_Create` takes the stream's data buffer
as the blob, rejects it if smaller than 0x60 or than the blob's own `min size`, and rebases the
chunk offsets (adds the blob address to each). `CSA_Serialize` (sub_414390, vtable +0x28) undoes
the rebase before writing and redoes it after.

## 2. Compressed blob header

All offsets from the blob start; read by `CSA_Sample` (sub_419C10), `CSA_DecodeChunk`
(sub_419500), `CSA_FindChunk` (sub_419490), `CSA_SampleRootMotion` (sub_419D30).

| Offset | Type | Field |
|---|---|---|
| 0x00 | char[4] | `dnap` (`'pand'` as a little-endian u32) |
| 0x04 | f32 | duration = frame_count / fps |
| 0x08 | f32 | fps (time × fps = frame, sub_419C10) |
| 0x0C | u16 | min blob size (sub_414480) |
| 0x0E | u16 | flags: 2 = root translation, 4 = root rotation (sub_419D30, sub_419AF0) |
| 0x10 | u16 | frame_count (frames 0 … frame_count − 1 are sampled) |
| 0x12 | u16 | bone track count (= B) |
| 0x14 | u16 | float track count (= F) |
| 0x16 | u16 | chunk count, including one closing key-only chunk (sub_414480, sub_419490) |
| 0x18 | u32 | **unknown** (high half is 64/32/16/8/4/0; probably the encoder's chunk length) |
| 0x1C | u8[4] | codec per stream: rotation, scale, translation, float (sub_419500) |
| 0x20 | u8, u8 | root rotation / root translation *disabled* when non-zero (sub_419AF0) |
| 0x22 | u16 | padding |
| 0x24 | f32[4] | **unknown** (always −7727.545 in the samples looked at) |
| 0x34 | u16[8] | track counts: (constant, animated) × (rotation, scale, translation, float) |
| 0x44 | u32 | chunk table, relative to 0x44: rows `{u32 unknown, u32 chunk offset}` (offset at row+4 is what the loader rebases) |
| 0x48 | u32 | frame table, self-relative: per chunk `{u16 first frame, u16 last local frame L}` |
| 0x4C | u32 | constant rotation values, self-relative |
| 0x50 | u32 | constant scale values, self-relative |
| 0x54 | u32 | constant translation values, self-relative |
| 0x58 | u32 | constant float values, self-relative |
| 0x5C | u32 | 0 |
| 0x60 | u16 lists | track indices: const rot, const scale, const trans, const float, animated rot, animated scale, animated trans, animated float. Rotation lists are padded to a multiple of 8 entries, the others to 4 (sub_419500). Padding entries hold the track count (out-of-range sentinel; the SIMD decoders process 4 tracks at a time and stop after the first index ≥ count − 1). |

Then (proven exact on every resource): the four constant tables, `count × value size` each, the
rotation table and any f32 table starting 16-aligned, f16 tables directly after the previous one;
the chunk table rows (16-aligned); the frame table directly after the rows; the first chunk
(16-aligned).

Indices in the lists are *track* indices (0…B−1 for bones, 0…F−1 for floats), not rig bones.

### Codecs and value encodings

| Stream | Codec byte | Bytes/value | Encoding | Const decoder | Animated decoder | Interpolation |
|---|---|---|---|---|---|---|
| rotation | 2 | 6 | 48-bit smallest-three quaternion | `CSA_ConstRot_Q48` sub_427B20 | `CSA_AnimRot_Q48` sub_427BD0 | slerp |
| rotation | 0 | 16 | f32 x, y, z, w | `CSA_ConstRot_F32` sub_41DBD0 | `CSA_AnimRot_F32` sub_4202D0 | slerp |
| scale, translation | 1 | 6 | f16 × 3 | `CSA_ConstVec3_F16` sub_423EB0 | `CSA_AnimVec3_F16` sub_4259C0 | lerp |
| scale, translation | 0 | 12 | f32 × 3 | `CSA_ConstVec3_F32` sub_41DAB0 | `CSA_AnimVec3_F32` sub_41ECA0 | lerp |
| float | 1 | 2 | f16 | `CSA_ConstFloat_F16` sub_423B50 | `CSA_AnimFloat_F16` sub_424410 | lerp |
| float | 0 | 4 | f32 | `CSA_ConstFloat_F32` sub_41DA10 | `CSA_AnimFloat_F32` sub_41DD10 | lerp |

Corpus mix (rot, scale, trans, float codec bytes): see the gate output; rotation codec 0 occurs in
17 clips, float codec 0 never.

**48-bit quaternion** (`Quat_FromSmallest3_48`, sub_6871E0). The 6 bytes are one big-endian
48-bit integer v (assembled byte by byte in sub_427B20/sub_427BD0):

```
a = ((v >> 32) & 0x7FFF)      b = ((v >> 17) & 0x7FFF)      c = ((v >> 2) & 0x7FFF)
s = v & 3                     bit 47 unused
each = (raw - 16383.5) * 4.31596891e-05        # flt_10123E8 = 23169.7676 / sqrt(2) (set by
                                               #   init_Quat48Bias sub_E02320), flt_F7C268
w = sqrt(1 - a² - b² - c²)                     # no clamp in the engine
out = table dword_E7EE08[s]: s=0 (w,a,b,c)  s=1 (a,w,b,c)  s=2 (a,b,w,c)  s=3 (a,b,c,w)
```

`out` is stored x, y, z, w (memory order; identity is (0, 0, 0, 1): sub_427BD0 pre-fills its
temporaries with 0, 0, 0, 1 and `Quat_Normalize` sub_401450 falls back to w = 1).

**f16** (SSE masks at F76CE0…F76D2C): `float_bits = sign<<16 | ((exp + 0x1C000) | mantissa) << 13`
with `exp = h & 0x7C00`, `mantissa = h & 0x3FF`. No zero/denormal/inf handling: 0x0000 decodes to
2⁻¹⁵ ≈ 3.05e-5, not 0. `Brutal.anim.half` reproduces this.

## 3. Chunks

`CSA_FindChunk` (sub_419490) binary-searches the frame table over rows 0 … count−2 (the closing
chunk is never selected). `CSA_Sample` (sub_419C10):

```
f      = max(0, time * fps)
chunk  = last row with first_frame <= int(f)
k      = int(f - first_frame);  frac = (f - first_frame) - floor(f - first_frame)
if k > L: k = L, frac = 1.0             # end of clip: lands on the next chunk's first key
```

A chunk covers local frames 0…L; local frame L+1 is the next chunk's first key, so chunk c
needs chunk c+1's first-key sections (chunk header word 16 = offset of the next chunk). Chunks are
contiguous: `first(c) + L(c) + 1 = first(c+1)`, and the closing chunk sits at frame_count − 1.

Chunk header: 18 u16 words h[0..17] (bytes 8, 9, 18, 19 are separate u8 sizes). h[17] = header size
(36; 48 in some clips with f32 rotations), h[16] = offset of the next chunk, h[15] = unknown (4/8/0). Sections follow in this order (the
order and the sums are from the pointer arithmetic in sub_419500 and `CSA_DecodeChunkRoot`
sub_419AF0):

| # | Size | Section |
|---|---|---|
| 1 | h[0] | first keys, animated rotations (frame 0) |
| 2 | h[1] | first keys, animated scales |
| 3 | h[2] | first keys, animated translations |
| 4 | h[3] | first keys, animated floats |
| 5 | u8 @8 | root rotation first key, f32 × 4 (16) |
| 6 | u8 @9 | root translation first key, f32 × 3 (12) |
| 7 | h[5] | keyframe masks, rotations |
| 8 | h[6] | masks, scales |
| 9 | h[7] | masks, translations |
| 10 | h[8] | masks, floats |
| 11 | u8 @18 | mask, root rotation |
| 12 | u8 @19 | mask, root translation |
| 13 | h[10] | key pool, rotations |
| 14 | h[11] | key pool, scales |
| 15 | h[12] | key pool, translations |
| 16 | h[13] | key pool, floats |
| 17 | h[14] | key pool, root rotation (f32 × 4 per key, `CSA_RootRot_F32` sub_4238C0) |
| 18 | rest | key pool, root translation (f32 × 3 per key, `CSA_RootTrans_F32` sub_4235E0) |

**Masks.** Each animated track owns L bits; tracks are packed back to back, MSB-first, starting at
the section's first byte (the decoders read 64-bit big-endian words through `ByteSwap64`
sub_41D930 at `ptr & ~7` with a bit offset of `8 * (ptr & 7)`). Bit i of a track (i = 0 is the
most significant) set ⇔ local frame i+1 is a key. Frame 0 always comes from the first-key section,
frame L+1 from the next chunk's first-key section.

**Pools.** Track k's keys are `popcount(mask_k)` consecutive values (`Popcount64` sub_4193E0)
after the keys of tracks 0…k−1 of the same stream.

**Sampling a track at (k, frac)** (sub_427BD0 and its 4-wide siblings, all the same algebra):

```
P     = mask bits for frames 1..k        (mask & top-k-bits)
prev  = largest key frame <= k, or 0     (bsr on (P >> 1) | 1<<63, lowest set bit)
next  = smallest key frame >= k+1, or L+1
t     = (k - prev + frac) / (next - prev)        # flt_E83258[i] = i, flt_E8325C[i] = i + 1
from  = popcount(P) == 0 ? first_keys[track] : pool[popcount(P) - 1]
to    = popcount(P) <  popcount(mask) ? pool[popcount(P)] : next_chunk.first_keys[track]
value = rotation ? Quat_Slerp(from, to, t) : from + (to - from) * t
```

`Quat_Slerp` (sub_686F00): if dot < 0 negate `to`; if dot ≥ 0.999 `Quat_Nlerp` (sub_686980, lerp +
normalize); else `from·sin((1−t)θ) + to·sin(tθ)` with θ from `AcosDegrees` (sub_411890), then
`Quat_Normalize` (sub_401450). Equivalent to the textbook slerp.

**Padding.** Section sizes are explicit; several sections carry < 16 bytes of slack beyond what the
decoder reads (first.rot/scale/trans/float, keys.rot/scale/trans/float, root masks, chunk tail).
The encoder's padding rule was not derived (no aligned-address rule fits); the gate bounds it:
mask sections exact, every other section `needed ≤ stored < needed + 16`.

## 4. The pose the engine builds

The pose slot is 48 bytes per bone track: **translation f32×4 (+0), rotation quaternion x,y,z,w
(+16), scale f32×4 (+32)**. Evidence: `CSA_DecodeChunk` writes the rotation stream to slot+16,
the stream with counts at +0x38/+0x3A (here "scale") to slot+32, the one at +0x3C/+0x3E
("translation") to slot+0; `Transform_SetIdentity` (sub_411A40) writes (0,0,0,0)(0,0,0,1)(1,1,1,1);
and the data agrees (avatar wing bones carry a constant 0.01 in the +32 stream — wings hidden — and
`Root` carries a ≈0.86 m height in the +0 stream).

`Anim_SamplePoseLayers` (sub_4338C0) copies, for every track, the default slot of its rig bone
(`slot[track] = default[bone_map[track]]`) and then calls `CSA_Sample`, which overwrites only the
components the clip stores (constant tables, then animated tracks, per stream: rotation, scale,
translation, float). **Components not stored keep the default**, and the default is the rig's local
rest pose: the Rig resource's `offsets[4]` table (48 bytes per bone in the same slot layout).
Composing that table through the rig parents reproduces the bind pose of the inverse bind matrices
to 1.8e-6 m (max over 212 avatar bones). So the clip stores **absolute parent-relative local
TRS**, not deltas from the bind pose; only *missing* components fall back to the rest pose.
`Brutal.anim.rest_pose(rig_bytes)` reads that table; pass it to `Anim.sample(frame, rest)`.

Floats (flex weights) start at 0 (memset in sub_4338C0); several layers are merged by keeping the
value with the larger |weight × value| (sub_4338C0). Observed range −1…2.

Hierarchy convention (verified on the rest pose only): column vectors, `R_world = R_parent ·
R_local`, `p_world = p_parent + R_parent · S_parent · t_local` (scale inherited, as the 0.01 wing
scale collapsing the wing chains shows).

### Root motion

`CSA_SampleRootMotion` (sub_419D30) samples a separate transform (identity from sub_411A40) when
flags & 6 and the disable byte at blob+0x20/+0x21 is 0, through `CSA_DecodeChunkRoot` (sub_419AF0):
one track each, f32 values, same mask/pool/first-key scheme. `CSA_RootMotionDelta` (sub_414250,
vtable +0x1C) differences two samples. It is not part of the bone pose; `Anim.root_motion(frame)`
returns it.

## 5. API (`Blender/BrutalLegend/Brutal/anim.py`)

```python
a = anim.parse(data)                 # Anim: rig_hash, fps, frame_count, duration, bone_map, float_map, events
bones, floats = a.sample(frame)      # bones[i] = (quat_xyzw, t_xyz, s_xyz) local, game space; floats[j]
bones, floats = a.sample(frame, anim.rest_pose(rig_bytes))   # engine-exact defaults
a.animated                           # per track: (rotation, translation, scale) stored?
a.root_motion(frame)                 # (quat_xyzw, t_xyz) or None
```

`frame` may be fractional (the engine samples time × fps). Frame `frame_count − 1` is the last
sampled frame; `duration = frame_count / fps`.

## 5b. Notes for the Blender side

- Space: game space is Y-up, right-handed, metres (avatar head at y ≈ 1.84 in the bind pose; left
  bones at +x). Per the project rule convert positions `(x, y, z) → (x, −z, y)`; the same proper
  rotation applied to a quaternion `(x, y, z, w)` gives Blender `Quaternion((w, x, −z, y))`.
- Quaternions come out of `sample()` as x, y, z, w (engine memory order; identity (0,0,0,1)).
- Values are absolute parent-relative local TRS, not offsets from the bind pose. A Blender pose
  bone's `matrix_basis` is relative to its rest (edit) bone, so the per-frame basis is
  `rest_local⁻¹ · anim_local`, with `rest_local` from `rest_pose()` (or from the inverse bind
  matrices: `bind_parent · inverse_bind_child`, which agree to 1.8e-6 m).
- Components a clip does not store must come from `rest_pose()` — pass it to `sample()`; with
  `rest=None` they come back as identity, which is wrong for translations (most bones have no
  translation track at all).
- Scale is inherited by children (wings of the avatar are hidden with scale 0.01 on the wing root).
  Some clips park prop bones far away (e.g. `Lf_Prop` at 19.5 km, `XBow_Bolt` at 1.8e8) or carry
  garbage translations on hidden bones (22 clips with a translation key > 1e5).
- Root motion is a separate transform (not baked in the `Root` bone track); apply it to the
  armature object if wanted.
- Frames: `frame_count` frames 0 … frame_count−1 at `fps` (30 in the samples); looping clips repeat
  frame 0 as the last frame.

## 6. Gate (`Tests/corpus_anim.py`)

1. every resource parses; blob = record data part; blob layout exact (lists, constant tables,
   chunk table, frame table, first chunk); chunk sections close (masks exact, other sections
   < 16 bytes of slack, closing chunk = first-key sections only, ≤ 15 trailing bytes); chunk
   starts 16-aligned; frame table contiguous and spanning 0…frame_count−1; duration × fps =
   frame_count; every list index < its track count;
2. every stored quaternion (constant, key, root key) has ‖q‖ within 1e-3 of 1;
3. per-frame rotation/translation change between consecutive keys (exact for the decoded curve),
   and full per-frame `sample()` on every 25th clip;
4. a01_avatar clips: frame 0 composed through the rig vs bind positions;
5. bone_map < rig bones, float_map < rig flexes (rig matched by hash);
6. mask timing: root-motion path smoothness, decoded vs mirrored bit order.

The gate bites (checked by monkeypatching the decoder in a scratch run): a wrong smallest-three
component order, conjugated or w-first quaternions, or swapped scale/translation slots fail the
pose checks; a mirrored mask bit order fails the timing check; a byte-shifted quaternion read
fails the norm check; wrong section sizes fail the layout checks.

Enforced: all of 1, 2, 5; pose: a01 lip-sync clips within 3 cm of bind at frame 0 (body at
rest), a01 `relaxed_idle_*` head within 5 cm and ankles within 3 cm of bind height, median
frame-0 distance over `characters/bipeds/a01_avatar/animations` < 0.3 m; timing: the decoded
key frames give a smoother root-motion path than the mirrored bit order. Continuity (3) is
reported, not enforced (cutscene cuts and prop teleports are real 180° / km jumps).

## 7. Renamed functions

| Address | Name |
|---|---|
| 0x40E2D0 | AnimResource_Deserialize |
| 0x4131E0 | AnimCodec_Create |
| 0x418900 | UncompressedSkelAnim_Create (codec 0, unused by the corpus) |
| 0x414480 | CompressedSkelAnim_Create |
| 0x414390 | CSA_Serialize (vtable +0x28) |
| 0x4141F0 | CSA_SampleBones (vtable +0x14) |
| 0x414220 | CSA_SampleFloats (vtable +0x18) |
| 0x414250 | CSA_RootMotionDelta (vtable +0x1C) |
| 0x419C10 | CSA_Sample |
| 0x419490 | CSA_FindChunk |
| 0x419460 | CSA_Floorf |
| 0x419500 | CSA_DecodeChunk |
| 0x427B20 | CSA_ConstRot_Q48 |
| 0x427BD0 | CSA_AnimRot_Q48 |
| 0x41DBD0 | CSA_ConstRot_F32 |
| 0x4202D0 | CSA_AnimRot_F32 |
| 0x41DAB0 | CSA_ConstVec3_F32 |
| 0x41ECA0 | CSA_AnimVec3_F32 |
| 0x423EB0 | CSA_ConstVec3_F16 |
| 0x4259C0 | CSA_AnimVec3_F16 |
| 0x41DA10 | CSA_ConstFloat_F32 |
| 0x41DD10 | CSA_AnimFloat_F32 |
| 0x423B50 | CSA_ConstFloat_F16 |
| 0x424410 | CSA_AnimFloat_F16 |
| 0x419D30 | CSA_SampleRootMotion |
| 0x419AF0 | CSA_DecodeChunkRoot |
| 0x4238C0 | CSA_RootRot_F32 |
| 0x4235E0 | CSA_RootTrans_F32 |
| 0x6871E0 | Quat_FromSmallest3_48 |
| 0x686F00 | Quat_Slerp |
| 0x686980 | Quat_Nlerp |
| 0x401450 | Quat_Normalize |
| 0x411890 | AcosDegrees |
| 0x4193E0 | Popcount64 |
| 0x41D930 | ByteSwap64 |
| 0x411A40 | Transform_SetIdentity |
| 0x4338C0 | Anim_SamplePoseLayers |
| 0xE02320 | init_Quat48Bias |

## 8. Gate results (full corpus)

`python Tests/corpus_anim.py` (all 15,866 resources, every chunk decoded; full per-frame
`sample()` on every 25th clip), 82 s, **bad 0**:

- 15,866/15,866 parse; 34,370 chunks, 618,660 sections close; 1,173,413 track×chunk decodes;
  15,866/15,866 rig hashes match a Rig; all bone_map/float_map indices in range.
- Codec mix (rot, scale, trans, float): (2,1,1,1) 11,541; (2,1,0,1) 3,821; (2,0,0,1) 314;
  (2,0,1,1) 173; (0,0,0,1) 10; (0,1,0,1) 4; (0,1,1,1) 3. Root motion in 7,761 clips.
- 9,857,285 stored quaternions, all with ‖q‖ within 1e-3 of 1.
- Rotation change between consecutive keys, deg/frame: p50 1.40, p90 10.2, p99 49.7,
  p99.9 176, max 180; 1.9 % above 30°/frame (keys are dense exactly where motion is fast). The
  180° steps are exact half-turns about one axis on single frames (cutscene cuts, e.g.
  `ihsh_13` a15_chopper2 track 2 frame 9→10), not decoder noise. Per-frame `sample()`:
  p50 0, p90 0.31, p99 9.97, p99.9 47.5, max 180.
- Translation change between keys: p50 0.045, p99 4.1 units/frame; 22 clips carry translation
  keys beyond 1e5 (parked or garbage prop bones, e.g. `XBow_Bolt` at 1.8e8 in `rfhb_0x`,
  noise up to 1e13 on four hidden bones of `a04_extractorconstruction1/action_build01`).
- Float tracks: −1 … 2 (p1 −0.57, p99 0.985). Root motion |t| up to 319 (cutscene placement).
- Chunk boundaries are seamless (e.g. `dlc_action_pound_cntr`, 15 chunks: max step at each
  boundary equals the neighbouring steps, 0.3–1.5°); looping clips end exactly on frame 0.
- Pose, a01_avatar (1,907 clips on its rig, wing/prop bones excluded): median of per-clip mean
  distance to bind 0.317 m over all, **0.187 m** over the 340 `characters/bipeds/a01_avatar/
  animations` clips; lip-sync clips 0.000–0.015 m; `relaxed_idle_*` 0.196 m mean / 0.69 m max
  (arms out of the T-pose), head at 1.82 m vs bind 1.84, ankles at the bind height 0.15 m.
- Mask timing: root path jerk 2.24e4 decoded vs 3.09e4 with the mirrored bit order.

## 9. Open questions

- Outer header: f32[3] at object +40, u32 at +52/+56 and the n × 8-byte array — never read by the
  sampler; meaning unverified.
- Blob +0x18 u32, +0x24 f32[4], chunk-table row word 0 (high half looks like a byte size larger
  than the chunk), chunk header h[15] — not read by the sampler.
- The encoder's section padding rule (bounded < 16 bytes, not derived).
- Codec 0 (`UncompressedSkelAnim_Create` sub_418900) is not in the corpus and not implemented
  (`parse` raises `NotImplementedError`).
- The 4-wide decoders (sub_4202D0 etc.) run on 4 tracks per iteration and read past the last real
  track; with the padded index lists the extra writes go to the sentinel slot. The Python decoder
  only decodes real tracks. sub_4202D0's vectorised slerp may use an approximation of acos/sin;
  the Python side uses exact slerp (difference is float rounding, not semantics).
- How sub_436C70 blends layers into the final pose and how skinning consumes it was not traced.
