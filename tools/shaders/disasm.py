"""Disassemble the shaders of a `.fxo` container with d3dcompiler_47's D3DDisassemble.

Windows only (ctypes + d3dcompiler_47.dll, present on any Windows 10/11).

    python tools/shaders/disasm.py                 all containers
    python tools/shaders/disasm.py mesh hair       some containers

Writes .evidence/shaders/<container>/<index>_<stage>_<technique>.asm, one per shader, where
<index> is the shader's index in the container (VS first, then PS) and <technique> is the
first technique that uses it. Also writes .evidence/shaders/<container>/techniques.txt
(technique -> VS/PS file) so a material's variant can be looked up quickly.
"""
from __future__ import annotations

import ctypes
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from brutal import shaders  # noqa: E402
from brutal.library import Library  # noqa: E402

_dc = None


def disassemble(code: bytes) -> str:
    """D3DDisassemble(code) -> text. ID3DBlob vtable: 2 Release, 3 GetBufferPointer, 4 GetBufferSize."""
    global _dc
    if _dc is None:
        _dc = ctypes.WinDLL("d3dcompiler_47.dll")
    blob = ctypes.c_void_p()
    hr = _dc.D3DDisassemble(code, len(code), 0, None, ctypes.byref(blob))
    if hr != 0:
        raise OSError(f"D3DDisassemble failed: {hr & 0xFFFFFFFF:#x}")
    vt = ctypes.cast(ctypes.cast(blob, ctypes.POINTER(ctypes.c_void_p))[0],
                     ctypes.POINTER(ctypes.c_void_p))
    ptr = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vt[3])(blob)
    size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vt[4])(blob)
    text = ctypes.string_at(ptr, size).decode("latin-1").rstrip("\0")
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])(blob)
    return text


def dump(c: shaders.Container, out: str) -> int:
    os.makedirs(out, exist_ok=True)
    first: dict[int, str] = {}
    for t in c.techniques:
        first.setdefault(t.vs, t.name)
        first.setdefault(c.nv + t.ps, t.name)
    names = {}
    for s in c.shaders:
        names[s.index] = f"{s.index:04d}_{s.stage}_{first.get(s.index, 'unused')}.asm"
        header = [f"// shader {s.index} ({s.stage}), {s.size} bytes at bytecode+{s.offset:#x}",
                  "// bound constants: " + ", ".join(
                      f"{c.parameters[b.param].name}=c{b.register}" for b in s.constants),
                  "// bound samplers:  " + ", ".join(
                      f"{c.parameters[b.param].name}=s{b.register}" for b in s.samplers), ""]
        with open(os.path.join(out, names[s.index]), "w", encoding="utf-8") as f:
            f.write("\n".join(header) + disassemble(s.bytecode))
    with open(os.path.join(out, "techniques.txt"), "w", encoding="utf-8") as f:
        for t in c.techniques:
            f.write(f"{t.name}\t{names[t.vs]}\t{names[c.nv + t.ps]}\tstate={list(t.state)}\n")
    return len(c.shaders)


def main(argv):
    lib = Library()
    for name in argv or shaders.CONTAINERS:
        c = shaders.load(lib, name)
        n = dump(c, os.path.join(ROOT, ".evidence", "shaders", name))
        print(f"{name}: {n} shaders, {len(c.techniques)} techniques")


if __name__ == "__main__":
    main(sys.argv[1:])
