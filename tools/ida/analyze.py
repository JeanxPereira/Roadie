"""Build the IDA 9.4 database for BrutalLegend.exe headless (idalib).

Usage: python tools/ida/analyze.py [--exe PATH] [--out DIR]
The .i64 lands in the evidence dir, never in git.
"""
import argparse
import os
import shutil
import sys
import time

DEFAULT_EXE = r"D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend\BrutalLegend.exe"
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "..", ".evidence", "ida")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.environ.get("BL_EXE", DEFAULT_EXE))
    ap.add_argument("--out", default=os.environ.get("BL_IDA_DIR", DEFAULT_OUT))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, "BrutalLegend.exe")
    if not os.path.exists(work):
        shutil.copy2(args.exe, work)

    import idapro  # must be imported before any ida_* module
    t0 = time.time()
    if idapro.open_database(work, run_auto_analysis=True):
        sys.exit("open_database failed")
    import ida_auto, ida_funcs, idautils
    ida_auto.auto_wait()
    n = ida_funcs.get_func_qty()
    print(f"analysis done in {time.time() - t0:.0f}s, {n} functions")
    idapro.close_database(save=True)


if __name__ == "__main__":
    main()
