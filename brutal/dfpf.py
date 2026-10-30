"""DFPF v5 bundles: Brutal Legend's `.~h` (header) + `.~p` (payload) pairs.

Layout (big-endian on PC too — the magic is stored as 'dfpf'):
    0x00  'dfpf'
    0x04  u8   version (5)
    0x08  u64  type table offset
    0x10  u64  name directory offset
    0x18  u32  type count
    0x1C  u32  name directory size
    0x20  u32  file count
    0x38  u64  file record table offset (16 bytes per record)

Record bitfields (16 bytes, big-endian). Base: the DoubleFine Explorer V5 reader
(uDFExplorer_PAKManager), corrected here: its "uncompressed size" is only the data part.
    bytes 0..3  BE u32 >> 8              data size (24 bits)
    bytes 3..6  BE u32 >> 11             name offset (21 bits)
    bytes 4..7  (BE u32 >> 1) & 0x3FFFF  header size (18 bits) -- the CPU-side part that
                                         precedes the data; unpacked = header + data
    bytes 8..11 BE u32 >> 3              payload offset (29 bits)
    bytes 11..14 (BE u32 << 5) >> 9      stored size (23 bits)
    bytes 14..17 ((BE u32 << 4) >> 24) >> 1  type index
    byte 15 & 15                         compression: 4 raw, 8 zlib, 12 xmem
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"dfpf"
RECORD_SIZE = 16

COMP_RAW = 4
COMP_ZLIB = 8
COMP_XMEM = 12


@dataclass
class Entry:
    index: int
    name: str
    type: str
    offset: int
    size: int
    usize: int          # data part
    header_size: int    # CPU header part, stored before the data
    compression: int

    @property
    def unpacked_size(self) -> int:
        return self.header_size + self.usize

    @property
    def path(self) -> str:
        """Name with the resource type appended, as the game addresses it."""
        return f"{self.name}.{self.type}"


def _be32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _cstr(b: bytes, o: int) -> str:
    end = b.index(b"\0", o)
    return b[o:end].decode("latin-1")


class Bundle:
    def __init__(self, header_path: str):
        if header_path.endswith(".~p"):
            header_path = header_path[:-3] + ".~h"
        self.header_path = header_path
        self.payload_path = header_path[:-3] + ".~p"
        with open(header_path, "rb") as f:
            self._h = f.read()
        if self._h[:4] != MAGIC:
            raise ValueError(f"{header_path}: not a DFPF bundle")
        self.version = self._h[4]
        if self.version != 5:
            raise ValueError(f"{header_path}: DFPF v{self.version} unsupported (Brutal Legend is v5)")
        self.entries = self._parse()
        self._by_path = {e.path.lower(): e for e in self.entries}
        self._payload = None

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.header_path))[0]

    def _parse(self) -> list[Entry]:
        h = self._h
        type_off, name_off = struct.unpack_from(">QQ", h, 0x08)
        type_count, _name_size, count = struct.unpack_from(">III", h, 0x18)
        rec_off = struct.unpack_from(">Q", h, 0x38)[0]

        types = []
        o = type_off
        for _ in range(type_count):
            n = _be32(h, o)
            types.append(h[o + 4:o + 4 + n].decode("latin-1").strip().rstrip("\0"))
            o += 4 + n + 12

        out = []
        for i in range(count):
            r = rec_off + i * RECORD_SIZE
            usize = _be32(h, r) >> 8
            name_rel = _be32(h, r + 3) >> 11
            hsize = (_be32(h, r + 4) >> 1) & 0x3FFFF
            offset = _be32(h, r + 8) >> 3
            size = ((_be32(h, r + 11) << 5) & 0xFFFFFFFF) >> 9
            tidx = ((((_be32(h, r + 14) << 4) & 0xFFFFFFFF) >> 24) >> 1)
            comp = h[r + 15] & 15
            out.append(Entry(i, _cstr(h, name_off + name_rel), types[tidx],
                             offset, size, usize, hsize, comp))
        return out

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def find(self, path: str) -> Entry | None:
        return self._by_path.get(path.lower().replace("\\", "/"))

    def read(self, entry: Entry | str) -> bytes:
        if isinstance(entry, str):
            e = self.find(entry)
            if e is None:
                raise KeyError(entry)
            entry = e
        if self._payload is None:
            self._payload = open(self.payload_path, "rb")
        self._payload.seek(entry.offset)
        raw = self._payload.read(entry.size)
        if entry.compression == COMP_ZLIB:
            return zlib.decompress(raw, bufsize=entry.unpacked_size)
        if entry.compression == COMP_XMEM:
            raise NotImplementedError("XMemCompress payloads only appear in Xbox 360 bundles")
        return raw

    def close(self):
        if self._payload:
            self._payload.close()
            self._payload = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
