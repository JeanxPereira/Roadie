"""Package the Blender extension: blender/brutal_legend + brutal/ vendored inside it.

    python tools/build_addon.py            -> dist/brutal_legend-<version>.zip
    python tools/build_addon.py --dev DIR  -> also copy the unpacked package into DIR
"""
import argparse
import os
import re
import shutil
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON = os.path.join(ROOT, "blender", "brutal_legend")
LIB = os.path.join(ROOT, "brutal")


def files():
    for base, prefix in ((ADDON, "brutal_legend"), (LIB, "brutal_legend/brutal")):
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fn:
                if f.endswith((".py", ".toml")):
                    src = os.path.join(dp, f)
                    yield src, prefix + "/" + os.path.relpath(src, base).replace(os.sep, "/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev")
    a = ap.parse_args()
    version = re.search(r'^version = "([^"]+)"', open(os.path.join(ADDON, "blender_manifest.toml")).read(), re.M)[1]
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"brutal_legend-{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in files():
            z.write(src, arc)
    print(out)
    if a.dev:
        dst = os.path.join(a.dev, "brutal_legend")
        shutil.rmtree(dst, ignore_errors=True)
        for src, arc in files():
            p = os.path.join(a.dev, *arc.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            shutil.copy2(src, p)
        print(dst)


if __name__ == "__main__":
    main()
