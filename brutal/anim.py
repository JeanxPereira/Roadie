"""Skeletal animations (`.AnimResource` entries in RgB_* bundles). Little-endian.

Full reference with IDA addresses: docs/formats/anim.md. Function names below are the
names given in the IDA database (original sub_ address in brackets).

Outer resource, read by AnimResource_Deserialize [sub_40E2D0]:

    0x00  u32 codec: 0 UncompressedSkelAnim_Create [sub_418900] (not in the corpus),
          1 CompressedSkelAnim_Create [sub_414480] (all 15,866 resources)
    0x04  u64 rig hash (== Rig.hash)
    0x0C  u8 bone track count B, u8 float track count F
    0x0E  u8 bone_map[B]   track -> rig bone index
          u8 float_map[F]  float track -> rig flex (morph channel) index
          f32 (frame_count-1)/fps, f32 its inverse, f32[3], u32, u32 -- copied verbatim;
          the sampler never reads them (meaning of the last five unverified)
          u32 n, n * {f32, f32} (unverified; looks like normalized time ranges)
          'vena' u32 len, char events[len]  (text, parsed by TextInputDataStream)
          'mina'
          codec blob = the bundle record's data part (record header_size ends at 'mina')

Compressed blob ('pand' as a LE u32), all offsets from blob start; CSA_Sample [sub_419C10],
CSA_FindChunk [sub_419490], CSA_DecodeChunk [sub_419500]:

    +0x00 'dnap'           +0x04 f32 duration     +0x08 f32 fps
    +0x0C u16 min size     +0x0E u16 flags (2 = root translation, 4 = root rotation)
    +0x10 u16 frame count  +0x12 u16 bone tracks  +0x14 u16 float tracks
    +0x16 u16 chunk count (incl. one trailing key-only chunk)
    +0x18 u32 ?            +0x1C u8 codec per stream: rotation, scale, translation, float
    +0x20 u8 root-rot disable, u8 root-trans disable, u16 pad, f32[4] ?
    +0x34 u16 constant/animated track counts: rot c,a  scale c,a  trans c,a  float c,a
    +0x44 u32 -> chunk table   (relative to +0x44; 8-byte rows {u32 ?, u32 chunk offset})
    +0x48 u32 -> frame table   (self-relative; u16 start frame, u16 last local frame)
    +0x4C/+0x50/+0x54/+0x58 u32 -> constant values rot/scale/trans/float (self-relative)
    +0x60 u16 track index lists, in order: const rot (pad 8), const scale, const trans,
          const float (pad 4), animated rot (pad 8), animated scale, trans, float (pad 4)
          then the constant tables (rotation and f32 tables 16-aligned), the chunk table
          (16-aligned), the frame table, the chunks (16-aligned)

Chunk (one per row of the chunk table), header of u16 words h[0..17]:

    h[17] header size (36, or 48), h[16] offset of the next chunk; sizes below carry
    < 16 bytes of encoder padding (masks are exact); CSA_DecodeChunkRoot [sub_419AF0]
    then, in this order, sections of size:
      h[0] rot first keys   h[1] scale first keys   h[2] trans first keys   h[3] float first keys
      u8@8 root rot first key (f32 x4)   u8@9 root trans first key (f32 x3)
      h[5] rot masks   h[6] scale masks   h[7] trans masks   h[8] float masks
      u8@18 root rot mask   u8@19 root trans mask
      h[10] rot keys   h[11] scale keys   h[12] trans keys   h[13] float keys
      h[14] root rot keys (f32 x4), then root trans keys (f32 x3) to the chunk end

A chunk covers local frames 0..L (L = frame table 'last'); local frame L+1 is the
first key of the next chunk. Each animated track has an L-bit keyframe mask (bit
stream MSB-first, tracks packed back to back): bit i set = local frame i+1 is a key.
Frame 0 comes from the 'first keys' section, frame L+1 from the next chunk's.
Keys of track k sit in the key pool after the keys of tracks 0..k-1.

Value encodings (codec byte -> bytes per value):
    rotation 2: 48-bit big-endian smallest-three quaternion (Quat_FromSmallest3_48
                [sub_6871E0]); 0: f32 x4 (x, y, z, w)
    scale/trans 1: f16 x3 (engine's no-denormal conversion);              0: f32 x3
    float 1: f16;  0: f32
Rotations are slerped (Quat_Slerp [sub_686F00]), everything else lerped. Sampling
track (k, frac): prev = last key frame <= k, next = first key frame > k,
t = (k - prev + frac) / (next - prev).

Pose slot layout (48 bytes per track) is translation(+0), rotation(+16, xyzw),
scale(+32). Stored values are absolute parent-relative local TRS. Components the clip
does not store keep the rig's local rest pose, which Anim_SamplePoseLayers [sub_4338C0]
copies in before sampling (see rest_pose()). Root motion (flags) is a separate
transform: CSA_SampleRootMotion [sub_419D30], see Anim.root_motion().
"""

from __future__ import annotations

import bisect
import math
import struct
from dataclasses import dataclass, field

TAG_VENA = b"vena"
TAG_MINA = b"mina"
TAG_PAND = b"dnap"

# stream ids, in the order the engine decodes them (sub_419500)
ROT, SCALE, TRANS, FLOAT = 0, 1, 2, 3

# bytes per value, by stream and codec byte
VALUE_SIZE = {ROT: {2: 6, 0: 16}, SCALE: {1: 6, 0: 12}, TRANS: {1: 6, 0: 12}, FLOAT: {1: 2, 0: 4}}

FLAG_ROOT_TRANS = 2
FLAG_ROOT_ROT = 4

IDENTITY = ((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

_Q48_SCALE = 4.31596891e-05     # flt_F7C268 = sqrt(0.5) / 16383.5
_Q48_BIAS = 16383.5             # flt_10123E8 = 23169.7676 / sqrt(2), set by init_Quat48Bias
# dword_E7EE08: for selector s, output component i takes [a, b, c, w][_Q48_ORDER[s][i]]
_Q48_ORDER = ((3, 0, 1, 2), (0, 3, 1, 2), (0, 1, 3, 2), (0, 1, 2, 3))


def half(h: int) -> float:
    """f16 -> float as the engine does it (SSE masks at F76CE0): no zero/denormal/inf
    special case, so 0x0000 decodes to 2**-15."""
    bits = ((h & 0x8000) << 16) | ((((h & 0x7C00) + 0x1C000) | (h & 0x3FF)) << 13)
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def quat48(b: bytes, o: int) -> tuple[float, float, float, float]:
    """Quat_FromSmallest3_48 [sub_6871E0]: 48-bit big-endian smallest-three -> (x, y, z, w)."""
    v = int.from_bytes(b[o:o + 6], "big")
    a = ((v >> 32) & 0x7FFF) - _Q48_BIAS
    c1 = ((v >> 17) & 0x7FFF) - _Q48_BIAS
    c2 = ((v >> 2) & 0x7FFF) - _Q48_BIAS
    a, c1, c2 = a * _Q48_SCALE, c1 * _Q48_SCALE, c2 * _Q48_SCALE
    r = 1.0 - a * a - c1 * c1 - c2 * c2
    comps = (a, c1, c2, math.sqrt(r) if r > 0.0 else 0.0)  # engine: fsqrt (NaN if r < 0)
    order = _Q48_ORDER[v & 3]
    return (comps[order[0]], comps[order[1]], comps[order[2]], comps[order[3]])


def _value(stream: int, codec: int, b: bytes, o: int):
    if stream == ROT:
        return quat48(b, o) if codec == 2 else struct.unpack_from("<4f", b, o)
    if stream == FLOAT:
        return half(struct.unpack_from("<H", b, o)[0]) if codec == 1 else struct.unpack_from("<f", b, o)[0]
    if codec == 1:
        return tuple(half(h) for h in struct.unpack_from("<3H", b, o))
    return struct.unpack_from("<3f", b, o)


def normalize(q):
    """Quat_Normalize [sub_401450] (length < 1e-5 -> identity)."""
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if n - 1e-5 < 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    w = max(-1.0, min(1.0, q[3] / n))
    return (q[0] / n, q[1] / n, q[2] / n, w)


def slerp(a, b, t):
    """Quat_Slerp [sub_686F00]: shortest arc; Quat_Nlerp [sub_686980] when |dot| >= 0.999."""
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if d < 0.0:
        b, d = (-b[0], -b[1], -b[2], -b[3]), -d
    if d >= 0.999:
        return normalize(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(min(1.0, d))
    sa, sb = math.sin((1.0 - t) * th), math.sin(t * th)
    return normalize(tuple(x * sa + y * sb for x, y in zip(a, b)))


def lerp(a, b, t):
    if isinstance(a, float):
        return a + (b - a) * t
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _popcount(x: int) -> int:
    return bin(x).count("1")


@dataclass
class Track:
    """One animated track inside one chunk: key local frames and their values."""
    frames: list[int]
    values: list


@dataclass
class Chunk:
    start: int
    last: int                 # local frames 0..last; last+1 is the next chunk's first key
    tracks: list[list[Track]]  # per stream, per animated track
    root_rot: Track | None = None
    root_trans: Track | None = None


@dataclass
class Anim:
    rig_hash: int
    fps: float
    frame_count: int
    duration: float
    bone_map: list[int]
    float_map: list[int]
    events: str
    flags: int = 0
    codecs: tuple = (2, 1, 1, 1)
    const_lists: list = field(default_factory=list)   # per stream: track indices
    const_values: list = field(default_factory=list)  # per stream: values
    anim_lists: list = field(default_factory=list)    # per stream: track indices
    chunk_starts: list = field(default_factory=list)
    _blob: bytes = b""
    _chunk_offs: list = field(default_factory=list)
    _chunk_last: list = field(default_factory=list)
    _cache: dict = field(default_factory=dict)
    # outer header fields the sampler never reads (see module docstring); kept raw
    header: dict = field(default_factory=dict)

    # -- sampling -----------------------------------------------------------

    def chunk(self, ci: int) -> Chunk:
        c = self._cache.get(ci)
        if c is None:
            c = self._cache[ci] = _decode_chunk(self, ci)
        return c

    def _locate(self, frame: float) -> tuple[int, int, float]:
        """CSA_Sample + CSA_FindChunk: chunk, local key index and fraction for a frame."""
        f = max(0.0, float(frame))
        lo, hi = 0, len(self.chunk_starts) - 1
        while lo + 1 < hi:
            mid = (lo + hi) >> 1
            if int(f) >= self.chunk_starts[mid]:
                lo = mid
            else:
                hi = mid
        local = f - self.chunk_starts[lo]
        k, frac = int(local), local - math.floor(local)
        if k > self._chunk_last[lo]:
            k, frac = self._chunk_last[lo], 1.0
        return lo, k, frac

    @staticmethod
    def _interp(tr: Track, k: int, frac: float, rot: bool):
        i = bisect.bisect_right(tr.frames, k) - 1
        f0, f1 = tr.frames[i], tr.frames[i + 1]
        t = (k - f0 + frac) / (f1 - f0)
        return (slerp if rot else lerp)(tr.values[i], tr.values[i + 1], t)

    def sample(self, frame, rest=None) -> tuple[list[tuple], list[float]]:
        """returns (bones, floats). bones[i] = (quat_xyzw, translation_xyz, scale_xyz) LOCAL
        (parent-relative), in GAME space, for track i; floats[j] = value of float track j.

        Components the clip does not store keep `rest[bone_map[i]]` (a list indexed by rig
        bone, e.g. rest_pose(rig_bytes)) -- exactly what the engine pre-fills -- or the
        identity when `rest` is None (see `animated` for which components are stored)."""
        ci, k, frac = self._locate(frame)
        c = self.chunk(ci)
        n = len(self.bone_map)
        slots = []
        for i in range(n):
            if rest is not None and self.bone_map[i] < len(rest):
                q, t, s = rest[self.bone_map[i]]
                slots.append([tuple(q), tuple(t), tuple(s)])
            else:
                slots.append([IDENTITY[0], IDENTITY[1], IDENTITY[2]])
        floats = [0.0] * len(self.float_map)
        comp = {ROT: 0, TRANS: 1, SCALE: 2}
        for st in (ROT, SCALE, TRANS, FLOAT):
            for idx, v in zip(self.const_lists[st], self.const_values[st]):
                self._put(slots, floats, st, comp, idx, v)
            for idx, tr in zip(self.anim_lists[st], c.tracks[st]):
                self._put(slots, floats, st, comp, idx, self._interp(tr, k, frac, st == ROT))
        return [tuple(s) for s in slots], floats

    @staticmethod
    def _put(slots, floats, st, comp, idx, v):
        if st == FLOAT:
            if idx < len(floats):
                floats[idx] = v
        elif idx < len(slots):
            slots[idx][comp[st]] = tuple(v[:4] if st == ROT else v[:3])

    def root_motion(self, frame):
        """CSA_SampleRootMotion: root motion (quat_xyzw, translation_xyz) for the frame, or
        None when the clip has none; a missing half is the identity (Transform_SetIdentity)."""
        if not self.flags & (FLAG_ROOT_ROT | FLAG_ROOT_TRANS):
            return None
        ci, k, frac = self._locate(frame)
        c = self.chunk(ci)
        q, t = IDENTITY[0], IDENTITY[1]
        if c.root_rot is not None:
            q = self._interp(c.root_rot, k, frac, True)
        if c.root_trans is not None:
            t = self._interp(c.root_trans, k, frac, False)
        return q, t

    @property
    def animated(self) -> list[tuple[bool, bool, bool]]:
        """per bone track: (rotation, translation, scale) stored in the clip."""
        have = [[False, False, False] for _ in self.bone_map]
        for st, j in ((ROT, 0), (TRANS, 1), (SCALE, 2)):
            for idx in self.const_lists[st] + self.anim_lists[st]:
                if idx < len(have):
                    have[idx][j] = True
        return [tuple(h) for h in have]


# -- parsing -------------------------------------------------------------------

def parse(data: bytes) -> Anim:
    codec = struct.unpack_from("<I", data, 0)[0]
    (rig_hash,) = struct.unpack_from("<Q", data, 4)
    nb, nf = data[12], data[13]
    o = 14
    bone_map = list(data[o:o + nb]); o += nb
    float_map = list(data[o:o + nf]); o += nf
    f = struct.unpack_from("<5f2I", data, o)
    o += 4 + 4 + 12 + 4 + 4
    (n,) = struct.unpack_from("<I", data, o)
    header = {"last_time": f[0], "inv_last_time": f[1], "vec3": f[2:5], "u52": f[5], "u56": f[6],
              "pairs": [struct.unpack_from("<2f", data, o + 4 + 8 * i) for i in range(n)]}
    o += 4 + 8 * n
    if data[o:o + 4] != TAG_VENA:
        raise ValueError(f"no 'vena' tag at {o:#x}")
    (ln,) = struct.unpack_from("<I", data, o + 4)
    events = data[o + 8:o + 8 + ln].split(b"\0", 1)[0].decode("latin-1")
    o += 8 + ln
    if data[o:o + 4] != TAG_MINA:
        raise ValueError(f"no 'mina' tag at {o:#x}")
    blob = data[o + 4:]
    if codec != 1:
        raise NotImplementedError(f"codec {codec} (UncompressedSkeletalAnimation) not in corpus")
    a = _parse_blob(blob, rig_hash, bone_map, float_map, events)
    a.header = header
    return a


def _rel(b: bytes, at: int, base: int | None = None) -> int:
    return (at if base is None else base) + struct.unpack_from("<I", b, at)[0]


def _parse_blob(b, rig_hash, bone_map, float_map, events) -> Anim:
    if b[:4] != TAG_PAND:
        raise ValueError("no 'pand' blob")
    duration, fps = struct.unpack_from("<2f", b, 4)
    _minsize, flags, frames, nbt, nft, nchunks = struct.unpack_from("<6H", b, 12)
    if nbt != len(bone_map) or nft != len(float_map):
        raise ValueError(f"track counts {nbt}/{nft} != maps {len(bone_map)}/{len(float_map)}")
    codecs = tuple(b[28:32])
    counts = struct.unpack_from("<8H", b, 52)          # (const, animated) x rot, scale, trans, float
    const_n = counts[0::2]
    anim_n = counts[1::2]
    for st, cd in enumerate(codecs):
        if cd not in VALUE_SIZE[st] and (const_n[st] or anim_n[st]):
            raise ValueError(f"stream {st} codec {cd} unknown")
    # index lists (CSA_DecodeChunk prologue)
    o = 0x60
    lists = []
    for nn, pad in zip(const_n + anim_n, (8, 4, 4, 4, 8, 4, 4, 4)):
        lists.append(list(struct.unpack_from(f"<{nn}H", b, o)))
        o += 2 * ((nn + pad - 1) // pad * pad)
    const_lists, anim_lists = lists[:4], lists[4:]
    # constant values (CSA_Const{Rot_Q48,Rot_F32,Vec3_F16,Vec3_F32,Float_F16,Float_F32})
    const_values = []
    for st in range(4):
        p = _rel(b, 0x4C + 4 * st)
        sz = VALUE_SIZE[st].get(codecs[st], 0)
        const_values.append([_value(st, codecs[st], b, p + sz * i) for i in range(const_n[st])])
    tab = _rel(b, 0x44, 0x48)
    offs = [struct.unpack_from("<I", b, tab + 8 * i)[0] for i in range(nchunks)]
    ftab = _rel(b, 0x48)
    fr = [struct.unpack_from("<2H", b, ftab + 4 * i) for i in range(nchunks)]
    return Anim(rig_hash, fps, frames, duration, bone_map, float_map, events, flags, codecs,
                const_lists, const_values, anim_lists, [s for s, _ in fr], b, offs, [l for _, l in fr])


def chunk_sections(b: bytes, p: int) -> dict[str, tuple[int, int]]:
    """Section name -> (offset, size) for the chunk at blob offset p (CSA_DecodeChunk,
    CSA_DecodeChunkRoot)."""
    h = struct.unpack_from("<18H", b, p)
    sizes = [("first.rot", h[0]), ("first.scale", h[1]), ("first.trans", h[2]), ("first.float", h[3]),
             ("first.root_rot", h[4] & 0xFF), ("first.root_trans", h[4] >> 8),
             ("mask.rot", h[5]), ("mask.scale", h[6]), ("mask.trans", h[7]), ("mask.float", h[8]),
             ("mask.root_rot", h[9] & 0xFF), ("mask.root_trans", h[9] >> 8),
             ("keys.rot", h[10]), ("keys.scale", h[11]), ("keys.trans", h[12]), ("keys.float", h[13]),
             ("keys.root_rot", h[14])]
    out, o = {}, p + h[17]
    for name, sz in sizes:
        out[name] = (o, sz)
        o += sz
    out["keys.root_trans"] = (o, None)  # size not stored: 12 * key count
    out["next"] = (p + h[16], None)
    return out


def _masks(b: bytes, off: int, ntracks: int, nbits: int) -> list[int]:
    """L-bit masks, MSB-first, packed back to back from byte `off` (read as big-endian u64s
    through ByteSwap64)."""
    nbytes = (ntracks * nbits + 7) // 8
    v = int.from_bytes(b[off:off + nbytes], "big")
    total = nbytes * 8
    full = (1 << nbits) - 1
    return [(v >> (total - (k + 1) * nbits)) & full for k in range(ntracks)]


def _key_frames(mask: int, nbits: int) -> list[int]:
    return [i + 1 for i in range(nbits) if mask >> (nbits - 1 - i) & 1]


_NAMES = ("rot", "scale", "trans", "float")


def _decode_chunk(a: Anim, ci: int) -> Chunk:
    b = a._blob
    if ci + 1 >= len(a._chunk_offs):
        raise IndexError("the last chunk only holds the closing keys")
    p, pn = a._chunk_offs[ci], a._chunk_offs[ci + 1]
    last = a._chunk_last[ci]
    sec, nsec = chunk_sections(b, p), chunk_sections(b, pn)
    if sec["next"][0] != pn:
        raise ValueError(f"chunk {ci}: next offset {sec['next'][0]:#x} != table {pn:#x}")
    tracks = []
    for st, nm in enumerate(_NAMES):
        n = len(a.anim_lists[st])
        if not n:
            tracks.append([])
            continue
        cd = a.codecs[st]
        sz = VALUE_SIZE[st][cd]
        first, nfirst = sec["first." + nm][0], nsec["first." + nm][0]
        pool = sec["keys." + nm][0]
        out = []
        for k, m in enumerate(_masks(b, sec["mask." + nm][0], n, last)):
            kf = _key_frames(m, last)
            vals = [_value(st, cd, b, first + sz * k)]
            vals += [_value(st, cd, b, pool + sz * j) for j in range(len(kf))]
            vals.append(_value(st, cd, b, nfirst + sz * k))
            pool += sz * len(kf)
            out.append(Track([0] + kf + [last + 1], vals))
        tracks.append(out)
    c = Chunk(a.chunk_starts[ci], last, tracks)
    if a.flags & FLAG_ROOT_ROT and b[0x20] == 0:
        (m,) = _masks(b, sec["mask.root_rot"][0], 1, last)
        kf = _key_frames(m, last)
        pool = sec["keys.root_rot"][0]
        vals = [struct.unpack_from("<4f", b, sec["first.root_rot"][0])]
        vals += [struct.unpack_from("<4f", b, pool + 16 * j) for j in range(len(kf))]
        vals.append(struct.unpack_from("<4f", b, nsec["first.root_rot"][0]))
        c.root_rot = Track([0] + kf + [last + 1], vals)
    if a.flags & FLAG_ROOT_TRANS and b[0x21] == 0:
        (m,) = _masks(b, sec["mask.root_trans"][0], 1, last)
        kf = _key_frames(m, last)
        pool = sec["keys.root_trans"][0]
        vals = [struct.unpack_from("<3f", b, sec["first.root_trans"][0])]
        vals += [struct.unpack_from("<3f", b, pool + 12 * j) for j in range(len(kf))]
        vals.append(struct.unpack_from("<3f", b, nsec["first.root_trans"][0]))
        c.root_trans = Track([0] + kf + [last + 1], vals)
    return c


def chunk_layout(a: Anim, ci: int) -> list[tuple[str, int, int]]:
    """(section, stored size, bytes the decoder reads) for chunk ci; used by the corpus gate."""
    b = a._blob
    p = a._chunk_offs[ci]
    last = a._chunk_last[ci]
    sec = chunk_sections(b, p)
    rows = []
    for st, nm in enumerate(_NAMES):
        n = len(a.anim_lists[st])
        sz = VALUE_SIZE[st].get(a.codecs[st], 0)
        keys = sum(_popcount(m) for m in _masks(b, sec["mask." + nm][0], n, last)) if n and last else 0
        rows.append(("first." + nm, sec["first." + nm][1], sz * n))
        rows.append(("mask." + nm, sec["mask." + nm][1], (n * last + 7) // 8))
        rows.append(("keys." + nm, sec["keys." + nm][1], sz * keys))
    rr = bool(a.flags & FLAG_ROOT_ROT)
    rt = bool(a.flags & FLAG_ROOT_TRANS)
    rows.append(("first.root_rot", sec["first.root_rot"][1], 16 * rr))
    rows.append(("first.root_trans", sec["first.root_trans"][1], 12 * rt))
    rows.append(("mask.root_rot", sec["mask.root_rot"][1], (last + 7) // 8 * rr))
    rows.append(("mask.root_trans", sec["mask.root_trans"][1], (last + 7) // 8 * rt))
    krr = _popcount(_masks(b, sec["mask.root_rot"][0], 1, last)[0]) if rr and last else 0
    krt = _popcount(_masks(b, sec["mask.root_trans"][0], 1, last)[0]) if rt and last else 0
    rows.append(("keys.root_rot", sec["keys.root_rot"][1], 16 * krr))
    end = sec["next"][0] if ci + 1 < len(a._chunk_offs) else len(b)
    rows.append(("keys.root_trans", end - sec["keys.root_trans"][0], 12 * krt))
    return rows


# -- rig rest pose ---------------------------------------------------------------

def rest_pose(rig_data: bytes) -> list[tuple]:
    """Local rest pose per rig bone, (quat_xyzw, translation_xyz, scale_xyz), from the Rig
    resource's offsets[4] table (48 bytes per bone: translation f32x4, rotation f32x4,
    scale f32x4 -- the same slot layout as the animation pose; sub_4338C0 copies it into
    the pose before sampling)."""
    bones = struct.unpack_from("<I", rig_data, 0x10)[0]
    base = 0x70 + struct.unpack_from("<8I", rig_data, 0x4C)[4]
    out = []
    for i in range(bones):
        v = struct.unpack_from("<12f", rig_data, base + 48 * i)
        out.append((v[4:8], v[0:3], v[8:11]))
    return out
