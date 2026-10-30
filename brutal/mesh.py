"""Mesh resources (`.Mesh` entries in RgS_* bundles).

One entry = header ('hsem') followed by the GPU blob (all vertex buffers, then
all index buffers, submesh by submesh). Little-endian.

    0x00  'hsem'
    0x08  bounding sphere / boxes / mip constants (floats)
    0x50  'lrtm'  u32 material count, then {u32 len, char name[len]} each
          u32 submesh count, then per submesh:
            'tsbs' u32 material index, u32 ?
            'BVXD' u32 vertex count, u16 vertex format, u32 morph frame count
                   [morph block]
            'BIXD' u32 0, u32 index count, u32 primitive (2 list, 3 strip)
                   u8 bone palette count, u8 palette[count]
                   56 bytes: misc + local bbox
          u16 bone (0xFFFF none; set on rigged meshes), u16 last morph frame (0xFFFF none)
          GPU blob: per submesh, vertex buffer then u16 index buffer

Morph block, per frame: u32 n, n * {u32 vertex, s16 dpos[3], s16 dnrm[3], s16 dtan[4]},
then u16 order[frames], u16 last, u32 name length (incl. NUL), name.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FMT_STATIC = 0x200   # 40 bytes, half floats
FMT_SKINNED = 0x400  # 48 bytes, half floats + 4 bone indices/weights

STRIDE = {FMT_STATIC: 40, FMT_SKINNED: 48}

PRIM_LIST = 2
PRIM_STRIP = 3


@dataclass
class MorphFrame:
    vertices: list[int]
    dpos: list[tuple[float, float, float]]
    dnrm: list[tuple[float, float, float]]


@dataclass
class Submesh:
    material: int
    vertex_count: int
    vertex_format: int
    index_count: int
    primitive: int
    bone_palette: list[int]
    morph_frames: list[MorphFrame] = field(default_factory=list)
    morph_order: list[int] = field(default_factory=list)
    morph_last: int = 0xFFFF
    morph_name: str = ""
    # decoded geometry
    positions: list = field(default_factory=list)
    normals: list = field(default_factory=list)
    uv0: list = field(default_factory=list)
    uv1: list = field(default_factory=list)
    color0: list = field(default_factory=list)
    color1: list = field(default_factory=list)
    bone_indices: list = field(default_factory=list)
    bone_weights: list = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    def triangles(self) -> list[tuple[int, int, int]]:
        ix = self.indices
        if self.primitive == PRIM_LIST:
            return [(ix[i], ix[i + 1], ix[i + 2]) for i in range(0, len(ix) - 2, 3)]
        tris = []
        for i in range(len(ix) - 2):
            a, b, c = ix[i], ix[i + 1], ix[i + 2]
            if a == b or b == c or a == c:
                continue  # degenerate stitch
            tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
        return tris


@dataclass
class Mesh:
    materials: list[str]
    submeshes: list[Submesh]
    header_size: int
    bone: int | None = None


class FormatError(ValueError):
    pass


def _tag(d: bytes, o: int, tag: bytes) -> int:
    if d[o:o + 4] != tag:
        raise FormatError(f"expected {tag!r} at {o:#x}, got {d[o:o + 4]!r}")
    return o + 4


def _read_morphs(d: bytes, o: int, frames: int, sm: Submesh) -> int:
    # 2/32767: proven -- with it, normal + dnormal is unit length (rms 1e-4) on every morph
    # in the corpus (tests/corpus_mesh.py); 1/32767 or 4/32767 miss by 300x+.
    s = 2.0 / 32767.0
    for _ in range(frames):
        (n,) = struct.unpack_from("<I", d, o)
        o += 4
        vids, dp, dn = [], [], []
        for v, px, py, pz, nx, ny, nz, *_tan in struct.iter_unpack("<I10h", d[o:o + 24 * n]):
            vids.append(v)
            dp.append((px * s, py * s, pz * s))
            dn.append((nx * s, ny * s, nz * s))
        sm.morph_frames.append(MorphFrame(vids, dp, dn))
        o += 24 * n
    sm.morph_order = list(struct.unpack_from(f"<{frames}H", d, o))
    o += 2 * frames
    (sm.morph_last,) = struct.unpack_from("<H", d, o)
    o += 2
    (ln,) = struct.unpack_from("<I", d, o)
    sm.morph_name = d[o + 4:o + 4 + ln].rstrip(b"\0").decode("latin-1")
    return o + 4 + ln


def parse_header(d: bytes) -> Mesh:
    _tag(d, 0, b"hsem")
    o = _tag(d, 0x50, b"lrtm")
    (mc,) = struct.unpack_from("<I", d, o)
    o += 4
    mats = []
    for _ in range(mc):
        (ln,) = struct.unpack_from("<I", d, o)
        mats.append(d[o + 4:o + 4 + ln].rstrip(b"\0").decode("latin-1"))
        o += 4 + ln
    (sc,) = struct.unpack_from("<I", d, o)
    o += 4
    subs = []
    for _ in range(sc):
        o = _tag(d, o, b"tsbs")
        mat, _unk = struct.unpack_from("<II", d, o)
        o = _tag(d, o + 8, b"BVXD")
        vc, vf, frames = struct.unpack_from("<IHI", d, o)
        o += 10
        if vf not in STRIDE:
            raise FormatError(f"unknown vertex format {vf:#x}")
        sm = Submesh(mat, vc, vf, 0, 0, [])
        if frames:
            o = _read_morphs(d, o, frames, sm)
        o = _tag(d, o, b"BIXD")
        _z, ic, prim, nb = struct.unpack_from("<IIIB", d, o)
        o += 13
        sm.index_count, sm.primitive = ic, prim
        sm.bone_palette = list(d[o:o + nb])
        o += nb + 56
        subs.append(sm)
    bone, last_morph = struct.unpack_from("<HH", d, o)
    expect = max((s.morph_last for s in subs if s.morph_frames), default=0xFFFF)
    if last_morph != expect:
        raise FormatError(f"trailer morph index {last_morph:#x}, submeshes say {expect:#x}")
    return Mesh(mats, subs, o + 4, None if bone == 0xFFFF else bone)


def _h4(b: bytes, o: int):
    return struct.unpack_from("<4e", b, o)


def parse(d: bytes, geometry: bool = True) -> Mesh:
    m = parse_header(d)
    blob = sum(s.vertex_count * STRIDE[s.vertex_format] + s.index_count * 2 for s in m.submeshes)
    if m.header_size + blob != len(d):
        raise FormatError(f"header {m.header_size} + blob {blob} != {len(d)}")
    if not geometry:
        return m
    o = m.header_size
    for s in m.submeshes:
        st = STRIDE[s.vertex_format]
        vb = d[o:o + s.vertex_count * st]
        o += len(vb)
        for v in range(s.vertex_count):
            p = v * st
            if s.vertex_format == FMT_SKINNED:
                s.bone_indices.append(tuple(vb[p:p + 4]))
                s.bone_weights.append(tuple(x / 255.0 for x in vb[p + 4:p + 8]))
                s.positions.append(_h4(vb, p + 8)[:3])
                s.uv0.append(struct.unpack_from("<2e", vb, p + 16))
                s.uv1.append(struct.unpack_from("<2e", vb, p + 20))
                s.normals.append(_h4(vb, p + 24)[:3])
                c = p + 40
            else:
                s.positions.append(_h4(vb, p)[:3])
                s.normals.append(_h4(vb, p + 8)[:3])
                s.uv0.append(struct.unpack_from("<2e", vb, p + 24))
                s.uv1.append(struct.unpack_from("<2e", vb, p + 28))
                c = p + 32
            # stored BGRA
            s.color0.append((vb[c + 2] / 255, vb[c + 1] / 255, vb[c] / 255, vb[c + 3] / 255))
            s.color1.append((vb[c + 6] / 255, vb[c + 5] / 255, vb[c + 4] / 255, vb[c + 7] / 255))
        s.indices = list(struct.unpack_from(f"<{s.index_count}H", d, o))
        o += s.index_count * 2
    return m
