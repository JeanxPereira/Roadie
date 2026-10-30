"""Pixels without numpy: DDS (DXT1 / DXT5, top mip) to RGBA, and a minimal PNG writer.

DDS: `'DDS '`, 124-byte header (height at +12, width at +16, pixel format flags at +80, FourCC
at +84), top mip at +128. Every UI texture (`ui/flash/*`, 1,664) is DXT1 or DXT5.

Block decoding follows the D3D BC1/BC3 definitions: RGB565 endpoints expanded by bit replication;
BC1 is 4-colour when `c0 > c1` (thirds) else 3-colour + transparent black; the BC3 colour block is
always 4-colour; BC3 alpha has 8 levels when `a0 > a1` (sevenths) else 6 levels + 0 and 255.
Interpolants round to nearest (`(2a + b + 1) // 3`, `(k a + (7-k) b + 3) // 7`), which may differ
by one step from a GPU's. Gate: `Tests/corpus_render.py` (bit-exact on synthetic blocks; against
ImageMagick's DDS decoder within 2 levels per channel when `magick` is available).
"""

from __future__ import annotations

import struct
import zlib

_ROWS = [(b & 3, (b >> 2) & 3, (b >> 4) & 3, b >> 6) for b in range(256)]
_AROWS = [(v & 7, (v >> 3) & 7, (v >> 6) & 7, (v >> 9) & 7) for v in range(4096)]


def _565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def color_block(blk: bytes, four: bool) -> list[bytes]:
    """8-byte BC1 colour block -> 4 rows of 16 RGBA bytes."""
    c0, c1, idx = struct.unpack("<HHI", blk)
    a, b = _565(c0), _565(c1)
    if four or c0 > c1:
        pal = [bytes((*a, 255)), bytes((*b, 255)),
               bytes((*((2 * x + y + 1) // 3 for x, y in zip(a, b)), 255)),
               bytes((*((x + 2 * y + 1) // 3 for x, y in zip(a, b)), 255))]
    else:
        pal = [bytes((*a, 255)), bytes((*b, 255)),
               bytes((*((x + y + 1) // 2 for x, y in zip(a, b)), 255)), b"\0\0\0\0"]
    out = []
    for r in range(4):
        i0, i1, i2, i3 = _ROWS[(idx >> (8 * r)) & 0xFF]
        out.append(pal[i0] + pal[i1] + pal[i2] + pal[i3])
    return out


def alpha_block(blk: bytes) -> list[bytes]:
    """8-byte BC3 alpha block -> 4 rows of 4 alpha bytes."""
    a0, a1 = blk[0], blk[1]
    bits = int.from_bytes(blk[2:8], "little")
    if a0 > a1:
        pal = [a0, a1] + [((7 - k) * a0 + k * a1 + 3) // 7 for k in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - k) * a0 + k * a1 + 2) // 5 for k in range(1, 5)] + [0, 255]
    out = []
    for r in range(4):
        i0, i1, i2, i3 = _AROWS[(bits >> (12 * r)) & 0xFFF]
        out.append(bytes((pal[i0], pal[i1], pal[i2], pal[i3])))
    return out


def dds_rgba(dds: bytes, width: int | None = None, height: int | None = None) -> tuple[int, int, bytes]:
    """Top mip of a DXT1/DXT5 DDS -> (w, h, RGBA bytes), cropped to width x height when given."""
    if dds[:4] != b"DDS ":
        raise ValueError("not a DDS")
    h, w = struct.unpack_from("<II", dds, 12)
    fourcc = dds[84:88]
    if fourcc not in (b"DXT1", b"DXT5"):
        raise ValueError(f"unsupported DDS format {fourcc!r}")
    dxt5 = fourcc == b"DXT5"
    bw, bh = (w + 3) // 4, (h + 3) // 4
    stride = w * 4
    rgba = bytearray(stride * bh * 4)
    alpha = bytearray(w * bh * 4) if dxt5 else None
    p = 128
    ccache, acache = {}, {}
    bs = 16 if dxt5 else 8
    for by in range(bh):
        for bx in range(bw):
            if dxt5:
                ab = dds[p:p + 8]
                rows = acache.get(ab)
                if rows is None:
                    rows = acache[ab] = alpha_block(ab)
                ncol = min(4, w - bx * 4)
                for r in range(4):
                    o = (by * 4 + r) * w + bx * 4
                    alpha[o:o + ncol] = rows[r][:ncol]
                cb = dds[p + 8:p + 16]
            else:
                cb = dds[p:p + 8]
            rows = ccache.get(cb)
            if rows is None:
                rows = ccache[cb] = color_block(cb, dxt5)
            ncol = min(4, w - bx * 4) * 4
            for r in range(4):
                o = (by * 4 + r) * stride + bx * 16
                rgba[o:o + ncol] = rows[r][:ncol]
            p += bs
    if dxt5:
        rgba[3::4] = alpha
    width, height = width or w, height or h
    if (width, height) != (w, h):
        rgba = b"".join(rgba[y * stride:y * stride + width * 4] for y in range(height))
    return width, height, bytes(rgba[:width * height * 4])


def png(w: int, h: int, rgba: bytes, level: int = 6) -> bytes:
    """RGBA8 -> PNG (filter 0 on every row)."""
    stride = w * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))
