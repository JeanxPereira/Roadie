"""Texture resources. Record header part = 0x24 bytes, data part = u32 size + a complete DDS.

    0x08  u32 engine format (9 DXT1, 11 DXT5, ...)
    0x10  u32 width
    0x14  u32 height
    0x1C  u32 mip count
    0x20  'rtxT'
    0x24  u32 DDS size          <- data part starts here
    0x28  'DDS ' ...

Normal maps are DXT5nm: X in alpha, Y in green, Z rebuilt. lighting/textures/rsalights/* use a
different 0xB0-byte header and are baked light data, not DDS.
"""

import struct

HEADER_SIZE = 0x24


def dds(d: bytes) -> bytes:
    if d[0x20:0x24] != b"rtxT" or d[0x28:0x2C] != b"DDS ":
        raise ValueError("not a Texture")
    (n,) = struct.unpack_from("<I", d, 0x24)
    if 0x28 + n != len(d):
        raise ValueError(f"DDS size {n} vs payload {len(d) - 0x28}")
    return d[0x28:]


def info(d: bytes) -> dict:
    fmt, _, w, h, _, mips = struct.unpack_from("<6I", d, 0x08)
    return {"format": fmt, "width": w, "height": h, "mips": mips}
