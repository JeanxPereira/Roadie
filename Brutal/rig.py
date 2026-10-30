"""Rig resources (`.Rig` entries in RgB_* bundles). Little-endian.

    0x00  u32 0
    0x04  u64 rig hash (AnimResource carries the same hash at +4)
    0x0C  u32 name blob size
    0x10  u32 bone count
    0x14  u32 parent array capacity (padded; entries past bone count are filler)
    0x18  u32 flex (morph channel) count
    0x4C  u32 offsets[8], relative to 0x70
    0x6C  ' gir'
    0x70  names: bone_count NUL strings, then flex_count NUL strings
          offsets[1]: s16 parent[capacity]  (-1 = root; first bone_count valid)
          offsets[5]: float inverse_bind[bone_count][4][4], row-major, translation in the last row
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

BASE = 0x70


@dataclass
class Rig:
    hash: int
    names: list[str]
    parents: list[int]
    flex_names: list[str]
    inverse_bind: list[tuple[float, ...]]  # 16 floats per bone

    @property
    def bone_count(self) -> int:
        return len(self.inverse_bind)


def parse(d: bytes) -> Rig:
    if d[0x6C:0x70] != b"gir ":
        raise ValueError("not a Rig")
    (h,) = struct.unpack_from("<Q", d, 4)
    bones, _capacity, flexes = struct.unpack_from("<III", d, 0x10)
    offs = struct.unpack_from("<8I", d, 0x4C)
    strings, o = [], BASE
    for _ in range(bones + flexes):
        end = d.index(b"\0", o)
        strings.append(d[o:end].decode("latin-1"))
        o = end + 1
    parents = list(struct.unpack_from(f"<{bones}h", d, BASE + offs[1]))
    mats = [struct.unpack_from("<16f", d, BASE + offs[5] + 64 * i) for i in range(bones)]
    return Rig(h, strings[:bones], parents, strings[bones:], mats)
