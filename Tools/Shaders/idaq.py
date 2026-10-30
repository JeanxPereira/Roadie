"""Shader/material-specific IDA queries (idalib, read-only; one process at a time).

    python Tools/Shaders/idaq.py immfuncs 0xd8 0xe8 ...   functions whose instructions use ALL
                                                          these immediates as operands
    python Tools/Shaders/idaq.py decomp EA [EA ...]       Hex-Rays text of each function to
                                                          .evidence/decomp/<ea>.c (no callees)
    python Tools/Shaders/idaq.py xrefs EA [EA ...]        all xrefs (code and data) to each EA
    python Tools/Shaders/idaq.py disasm EA N              N instructions from EA
    python Tools/Shaders/idaq.py rename EA NAME [EA NAME ...]   name functions, save the database
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB = os.environ.get("BL_IDB", os.path.join(ROOT, ".evidence", "ida", "BrutalLegend.exe.i64"))
OUT = os.path.join(ROOT, ".evidence", "decomp")


def fname(ea):
    import ida_funcs
    import ida_name
    f = ida_funcs.get_func(ea)
    return f"{ida_name.get_name(f.start_ea)}@{f.start_ea:#x}" if f else f"{ea:#x}"


def immfuncs(vals):
    import ida_funcs
    import ida_ua
    import idautils
    want = set(vals)
    for fea in idautils.Functions():
        f = ida_funcs.get_func(fea)
        seen = set()
        for ea in idautils.FuncItems(f.start_ea):
            insn = ida_ua.insn_t()
            if not ida_ua.decode_insn(insn, ea):
                continue
            for op in insn.ops:
                if op.type == ida_ua.o_void:
                    break
                if op.type == ida_ua.o_imm:
                    seen.add(op.value & 0xFFFFFFFF)
                elif op.type in (ida_ua.o_displ, ida_ua.o_mem):
                    seen.add(op.addr & 0xFFFFFFFF)
        if want <= seen:
            print(fname(fea))


def decomp(eas):
    import ida_funcs
    import ida_hexrays
    os.makedirs(OUT, exist_ok=True)
    for ea in eas:
        f = ida_funcs.get_func(ea)
        if f is None:  # not yet a function in the database: define it (not saved)
            ida_funcs.add_func(ea)
            f = ida_funcs.get_func(ea)
        if f is None:
            print(f"{ea:#x}: not a function")
            continue
        try:
            text = str(ida_hexrays.decompile(f.start_ea))
        except Exception as ex:
            text = f"// decompile failed: {ex}"
        path = os.path.join(OUT, f"{f.start_ea:08x}.c")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"// ===== {fname(f.start_ea)}\n{text}\n")
        print(path)


def xrefs(eas):
    import idautils
    for ea in eas:
        for x in idautils.XrefsTo(ea):
            print(f"{ea:#x} <- {x.frm:#x} {fname(x.frm)}")


def disasm(ea, n):
    import idc
    for _ in range(n):
        print(f"{ea:#x} {idc.generate_disasm_line(ea, 0)}")
        ea = idc.next_head(ea)


def rename(pairs):
    import ida_name
    for ea, name in pairs:
        print(ea, name, ida_name.set_name(int(ea, 16), name, ida_name.SN_FORCE))


def main(argv):
    import idapro
    cmd, args = argv[0], argv[1:]
    if idapro.open_database(DB, run_auto_analysis=False):
        sys.exit(f"cannot open {DB}")
    try:
        if cmd == "immfuncs":
            immfuncs([int(v, 0) for v in args])
        elif cmd == "decomp":
            decomp([int(v, 16) for v in args])
        elif cmd == "xrefs":
            xrefs([int(v, 16) for v in args])
        elif cmd == "disasm":
            disasm(int(args[0], 16), int(args[1]))
        elif cmd == "rename":
            rename(list(zip(args[::2], args[1::2])))
        else:
            sys.exit(__doc__)
    finally:
        idapro.close_database(save=cmd == "rename")


if __name__ == "__main__":
    main(sys.argv[1:])
