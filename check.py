"""Run every gate. The verdict is the exit code.

    python check.py            C++ build + unit tests, then the corpus gates and the C++/Python parity gate (needs the game; BL_GAME_DIR)
    python check.py --blender  also the Blender 5.2 smoke import (needs .evidence/blender or BL_BLENDER)
"""
import os
import shutil
import subprocess
import sys
import tempfile

DEFAULT_GAME_DIR = r"D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend"  # as Brutal/paths.py
ROOT = os.path.dirname(os.path.abspath(__file__))
GATES = ["Tests/corpus_mesh.py", "Tests/corpus_rig_tex.py",
         "Tests/corpus_material.py", "Tests/corpus_textobj.py", "Tests/corpus_anim.py",
         "Tests/corpus_shaders.py", "Tests/corpus_gfx.py", "Tests/corpus_ttf.py",
         "Tests/corpus_render.py"]


def run(cmd):
    print(f"--> {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def find_vcvars():
    """vcvars64.bat of the latest Visual Studio with the C++ tools, through vswhere."""
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(pf86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.exists(vswhere):
        raise RuntimeError(f"vswhere.exe not found at {vswhere}")
    out = subprocess.run([vswhere, "-latest", "-products", "*", "-requires",
                          "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                          "-property", "installationPath"], capture_output=True, text=True).stdout.strip()
    if not out:
        raise RuntimeError("no Visual Studio install with the C++ workload found")
    vcvars = os.path.join(out.splitlines()[0], "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not os.path.exists(vcvars):
        raise RuntimeError(f"{vcvars} not found")
    return vcvars


def run_in_vcvars(cmd):
    """Run one command inside the MSVC environment with clang-cl on PATH (BL_LLVM_DIR overrides the dir)."""
    llvm = os.environ.get("BL_LLVM_DIR", r"C:\Program Files\LLVM\bin")
    print(f"--> {' '.join(cmd)}", flush=True)
    tmp = tempfile.mkdtemp()
    try:
        bat = os.path.join(tmp, "run.bat")
        with open(bat, "w") as f:
            f.write("@echo off\r\n"
                    f'call "{find_vcvars()}" >nul\r\n'
                    "if errorlevel 1 exit /b 1\r\n"
                    "set VSLANG=1033\r\n"
                    f'set "PATH={llvm};%PATH%"\r\n'
                    + subprocess.list2cmdline(cmd) + "\r\n"
                    "exit /b %errorlevel%\r\n")
        return subprocess.call(["cmd", "/c", bat], cwd=ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


CPP_STEPS = [("cmake configure", ["cmake", "--preset", "windows"]),
             ("cmake build", ["cmake", "--build", "--preset", "windows-debug"]),
             ("ctest", ["ctest", "--preset", "windows-debug", "-LE", "corpus", "--no-tests=error"])]


def main():
    failed = []
    for name, cmd in CPP_STEPS:
        if run_in_vcvars(cmd):
            failed.append(name)
            break
    if not failed and os.path.isdir(os.path.join(os.environ.get("BL_GAME_DIR", DEFAULT_GAME_DIR), "Win", "Packs")):
        if run_in_vcvars(["ctest", "--preset", "windows-debug", "-L", "corpus", "--no-tests=error", "-V"]):
            failed.append("corpus (C++)")
    parity = os.path.join(ROOT, "Tests", "parity.py")
    if not failed and os.path.exists(parity) and os.path.isdir(os.path.join(os.environ.get("BL_GAME_DIR", DEFAULT_GAME_DIR), "Win", "Packs")):
        if run([sys.executable, "Tests/parity.py"]):  # after the C++ build: it runs build/windows/Debug/roadie.exe
            failed.append("parity")
    failed += [g for g in GATES if os.path.exists(os.path.join(ROOT, g)) and run([sys.executable, g])]
    if "--blender" in sys.argv:
        out = os.path.join(ROOT, ".evidence", "renders", "check.png")
        if run(["sh", "Tools/blender.sh", "--python", "Tests/Blender/smoke.py", "--", out,
                "characters/bipeds/a01_avatar/rig/a01_avatar"]):
            failed.append("blender smoke")
    print("FAIL: " + ", ".join(failed) if failed else "ALL GATES PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
