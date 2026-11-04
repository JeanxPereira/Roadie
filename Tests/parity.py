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
from collections import Counter

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


# The measured install facts (globals.md, 2026-11-03): a side that produces fewer lines has lost records.
EXPECTED = {"R": 71095, "T": 10656}


def count_kinds(lines: list[bytes]) -> dict[str, int]:
    kinds = {k: 0 for k in EXPECTED}
    for l in lines:
        kinds[l[:1].decode("latin-1")] = kinds.get(l[:1].decode("latin-1"), 0) + 1
    return kinds


def main() -> int:
    sides = {"C++": cpp_lines(), "Python": python_lines()}
    problems = []
    for side, lines in sides.items():
        got = count_kinds(lines)
        for kind, want in EXPECTED.items():
            if got[kind] != want:
                problems.append(f"{side} has {got[kind]} {kind} lines, expected {want}")
        for kind in sorted(set(got) - set(EXPECTED)):
            problems.append(f"{side} has {got[kind]} lines of unknown kind {kind!r}")
    cpp, py = sides["C++"], sides["Python"]
    # Multiset difference, so one missing line does not shift every later position.
    only_cpp = sorted((Counter(cpp) - Counter(py)).elements())
    only_py = sorted((Counter(py) - Counter(cpp)).elements())
    counts = "  ".join(f"{k} {n}" for k, n in count_kinds(cpp).items())
    if problems or only_cpp or only_py:
        print(f"PARITY FAIL: C++ {len(cpp)} lines, Python {len(py)} lines; {len(only_cpp)} only in C++, {len(only_py)} only in Python")
        for p in problems:
            print(f"  count: {p}")
        for label, only in (("only in C++", only_cpp), ("only in Python", only_py)):
            for l in only[:5]:
                print(f"  {label}: {l.decode('utf-8', 'replace')}")
        return 1
    print(f"PARITY OK: {len(cpp)} lines identical  ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
