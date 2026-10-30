"""RSA light gradients: `lighting/textures/rsalights/*_rsa.Texture` (the RSALight.Gradient of a
Weather's SunLight / SkyLight). Gate: tests/corpus_shaders.py (all 16 decode).

Layout (little-endian):
    0x00  4 x u32 0
    0x10  u32 width (256), u32 height (16), u32 0, u32 mip count (2)
    0x20  bytes '_ASR' (u32 0x5253415F)
    0x24  8 x f32 specular normalisation, one per exponent bucket k = 0..7 (k from the material's
          Roughness, see shaders.specular_bucket). For lighting/textures/rsalights/simplesun_rsa
          these are exactly the exe's table at 0xE8061C that sub_65C4B0 multiplies the sun
          colours by ([0] for diffuse, [k] for specular).
    0x44  27 x f32: 9 red, 9 green, 9 blue coefficients (order-2 spherical harmonics, by the
          RSALight class's Red/Green/Blue float arrays; their use is not traced)
    0xB0  u32 DDS size, then a complete DDS: A8R8G8B8 (bytes B,G,R,A), width x height, 2 mips.

The image is a set of ramps over the world-up normal: u = 0.5 - 0.5*N.y (u = 0 straight up,
u = 1 straight down). Rows come in identical pairs: 8 distinct rows, one per specular bucket
(row 2k and 2k+1). The mesh shaders sample it at g_vRSALightOffset = (1/512, 1/16)
(sub_6F4850), i.e. rows 0/1 = bucket 0, the broad diffuse ramp.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

TAG = 0x5253415F  # bytes '_ASR'


@dataclass
class RSA:
    spec_norm: tuple  # 8 floats
    sh_red: tuple     # 9 floats each
    sh_green: tuple
    sh_blue: tuple
    width: int
    height: int
    rows: list        # height rows of width (r, g, b) floats in 0..1, mip 0

    def sample(self, u: float, v: float = 1.0 / 16.0) -> tuple:
        """Bilinear, clamped (texel centres at (i + 0.5) / size), like the D3D sampler."""
        def axis(t, n):
            x = min(max(t * n - 0.5, 0.0), n - 1.0)
            i = min(int(x), n - 2) if n > 1 else 0
            return i, x - i
        i, fu = axis(u, self.width)
        j, fv = axis(v, self.height)
        out = []
        for c in range(3):
            a = self.rows[j][i][c] * (1 - fu) + self.rows[j][i + 1][c] * fu
            b = self.rows[j + 1][i][c] * (1 - fu) + self.rows[j + 1][i + 1][c] * fu
            out.append(a * (1 - fv) + b * fv)
        return tuple(out)

    def ramp(self, bucket: int = 0) -> list:
        """The 256-entry (r, g, b) ramp of one bucket (rows 2k / 2k+1 are identical)."""
        return self.rows[2 * bucket]


def parse(d: bytes) -> RSA:
    w, h, _, mips = struct.unpack_from("<4I", d, 0x10)
    if struct.unpack_from("<I", d, 0x20)[0] != TAG:
        raise ValueError("not an RSA light gradient")
    f = struct.unpack_from("<35f", d, 0x24)
    (n,) = struct.unpack_from("<I", d, 0xB0)
    dds = d[0xB4:]
    if dds[:4] != b"DDS " or len(dds) != n:
        raise ValueError("bad embedded DDS")
    dh, dw = struct.unpack_from("<II", dds, 12)
    bits, rmask, gmask, bmask, amask = struct.unpack_from("<5I", dds, 88)
    if (dw, dh) != (w, h) or bits != 32 or (rmask, gmask, bmask) != (0xFF0000, 0xFF00, 0xFF):
        raise ValueError("unexpected RSA pixel format")
    size = sum(max(w >> m, 1) * max(h >> m, 1) * 4 for m in range(mips))
    if 128 + size != len(dds):
        raise ValueError("RSA mip chain does not fill the DDS")
    px = dds[128:]
    rows = []
    for y in range(h):
        row = px[y * w * 4:(y + 1) * w * 4]
        rows.append([(row[x * 4 + 2] / 255.0, row[x * 4 + 1] / 255.0, row[x * 4] / 255.0)
                     for x in range(w)])
    return RSA(f[:8], f[8:17], f[17:26], f[26:35], w, h, rows)
