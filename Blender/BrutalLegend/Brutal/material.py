"""Material resources: u32 text length, then '1Material{Key=Value;...}'.

Values: numbers, <x,y,z[,w]> vectors, @resource/path references ('@' alone = none),
[a,b,...] arrays, and kEnum identifiers.
"""

from __future__ import annotations

import re
import struct

_BODY = re.compile(r"(\w+)\{(.*)\}", re.S)


def _value(v: str):
    v = v.strip()
    if v.startswith("@"):
        return v[1:] or None
    if v.startswith("<") and v.endswith(">"):
        return tuple(float(x) for x in v[1:-1].split(","))
    if v.startswith("[") and v.endswith("]"):
        return [_value(x) for x in v[1:-1].split(",") if x.strip()]
    try:
        return float(v)
    except ValueError:
        return v


def parse(d: bytes) -> dict:
    (n,) = struct.unpack_from("<I", d, 0)
    text = d[4:4 + n].decode("latin-1")
    m = _BODY.search(text)
    if not m:
        raise ValueError("not a Material")
    props = {"_class": m.group(1)}
    for item in m.group(2).split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            props[k.strip()] = _value(v)
    return props


TEXTURE_SLOTS = (
    "DiffuseTexture", "Normal1Texture", "Normal2Texture", "GlossTexture", "Layer1Texture",
    "Layer2Texture", "DetailTexture", "IncandescenceTexture", "TranslucenceTexture",
    "EnvironmentMapTexture", "Ramp1Texture", "Ramp2Texture",
)
