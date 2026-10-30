"""Run every gate. The verdict is the exit code.

    python check.py            corpus gates (needs the game; BL_GAME_DIR)
    python check.py --blender  also the Blender 5.2 smoke import (needs .evidence/blender or BL_BLENDER)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GATES = ["tests/corpus_dfpf.py", "tests/corpus_mesh.py", "tests/corpus_rig_tex.py",
         "tests/corpus_material.py", "tests/corpus_textobj.py", "tests/corpus_anim.py",
         "tests/corpus_shaders.py", "tests/corpus_gfx.py"]


def run(cmd):
    print(f"--> {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main():
    failed = [g for g in GATES if os.path.exists(os.path.join(ROOT, g)) and run([sys.executable, g])]
    if "--blender" in sys.argv:
        out = os.path.join(ROOT, ".evidence", "renders", "check.png")
        if run(["sh", "tools/blender.sh", "--python", "tests/blender/smoke.py", "--", out,
                "characters/bipeds/a01_avatar/rig/a01_avatar"]):
            failed.append("blender smoke")
    print("FAIL: " + ", ".join(failed) if failed else "ALL GATES PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
