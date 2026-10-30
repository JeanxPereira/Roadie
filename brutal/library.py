"""All bundles of an install, addressed by resource path ('name.Type')."""
from __future__ import annotations

import glob
import os

from .dfpf import Bundle, Entry
from .paths import packs_dir


class Library:
    def __init__(self, packs: str | None = None):
        self.bundles = [Bundle(h) for h in sorted(glob.glob(os.path.join(packs or packs_dir(), "*.~h")))]
        self._index: dict[str, tuple[Bundle, Entry]] = {}
        for b in self.bundles:
            for e in b:
                self._index.setdefault(e.path.lower(), (b, e))

    def __contains__(self, path: str) -> bool:
        return path.lower() in self._index

    def entries(self, type: str | None = None):
        for b, e in self._index.values():
            if type is None or e.type == type:
                yield b, e

    def read(self, path: str) -> bytes:
        b, e = self._index[path.lower().replace("\\", "/")]
        return b.read(e)

    def get(self, path: str) -> bytes | None:
        try:
            return self.read(path)
        except KeyError:
            return None

    def close(self):
        for b in self.bundles:
            b.close()
