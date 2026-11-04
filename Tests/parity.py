"""Parity gate: the extension's Python decoder (Blender/BrutalLegend/Brutal, stdlib only) and the
C++ module (`roadie digest`) must agree on every record and every texture, field by field.

Both sides write the same UTF-8 lines, tab-separated, sorted by their bytes:

    R <path> <compression> <headerSize> <dataSize>                                  every record
    T <path> <engineFormat> <width> <height> <mips> <len(dds)> <crc32(dds) 8 hex>   every DDS texture
                                                                                    (rsalights are not DDS: no T line)

A one-field divergence in either decoder fails this gate with the first differences and the counts
per line kind. Docs/formats.md ("Parity") documents the line kinds; each later format adds one.

    python Tests/parity.py          ROADIE_EXE overrides build/windows/Debug/roadie.exe; BL_GAME_DIR the install

Mutation checks (2026-11-04, both bite, both reverted):
  * Python texture.info reading width at 0x14 (and height at 0x18) instead of 0x10/0x14: all 10,656
    T lines differ from the C++ side, exit 1.
  * C++ Texture ReadInfo reading width at 0x14 instead of 0x10: the 1,186 T lines whose width differs
    from the height differ from the Python side, exit 1.
"""
import os
import subprocess
import sys
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "Blender", "BrutalLegend"))
from Brutal import texture
from Brutal.library import Library


def python_lines() -> list[bytes]:
    lib = Library()
    lines = []
    for bundle, e in lib.entries():
        lines.append(f"R\t{e.path}\t{e.compression}\t{e.header_size}\t{e.usize}")
        if e.type == "Texture" and not e.path.lower().startswith("lighting/textures/rsalights/"):
            data = bundle.read(e)
            i = texture.info(data)
            dds = texture.dds(data)
            lines.append(f"T\t{e.path}\t{i['format']}\t{i['width']}\t{i['height']}\t{i['mips']}"
                         f"\t{len(dds)}\t{zlib.crc32(dds):08x}")
    lib.close()
    return sorted(l.encode("utf-8") for l in lines)


def cpp_lines() -> list[bytes]:
    exe = os.environ.get("ROADIE_EXE") or os.path.join(ROOT, "build", "windows", "Debug", "roadie.exe")
    cmd = [exe, "digest"]
    if os.environ.get("BL_GAME_DIR"):
        cmd += ["--game", os.environ["BL_GAME_DIR"]]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        sys.exit(f"{' '.join(cmd)} exited {p.returncode}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return sorted(l.rstrip(b"\r") for l in p.stdout.split(b"\n") if l)


def main() -> int:
    cpp = cpp_lines()
    py = python_lines()
    kinds = {}
    for l in cpp:
        kinds[l[:1]] = kinds.get(l[:1], 0) + 1
    diffs = []
    for i in range(max(len(cpp), len(py))):
        a = cpp[i] if i < len(cpp) else None
        b = py[i] if i < len(py) else None
        if a != b:
            diffs.append((i, a, b))
    counts = "  ".join(f"{k.decode()} {n}" for k, n in sorted(kinds.items()))
    if diffs:
        print(f"PARITY FAIL: {len(diffs)} differing lines (C++ {len(cpp)}, Python {len(py)}; {counts})")
        for i, a, b in diffs[:5]:
            print(f"  line {i}\n    C++:    {a.decode('utf-8', 'replace') if a else None}"
                  f"\n    Python: {b.decode('utf-8', 'replace') if b else None}")
        return 1
    print(f"PARITY OK: {len(cpp)} lines identical  ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
