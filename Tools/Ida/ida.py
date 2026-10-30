"""Headless queries against the BrutalLegend.exe IDA 9.4 database (idalib).

    python Tools/Ida/ida.py strings REGEX            strings matching REGEX, with xref'ing functions
    python Tools/Ida/ida.py xrefs EA|NAME            code xrefs to an address
    python Tools/Ida/ida.py decomp EA|NAME [-d N]    Hex-Rays pseudocode of the function and its callees
                                                     down to depth N, written to .evidence/decomp/
    python Tools/Ida/ida.py imm TAG...               code using a 4-char tag (as stored, LE) or 0x constant
    python Tools/Ida/ida.py vtable CLASS             virtual methods of CLASS (from its RTTI vftable)
    python Tools/Ida/ida.py rename EA NAME           name a function and save the database

Build the database first with Tools/Ida/analyze.py.
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB = os.environ.get("BL_IDB", os.path.join(ROOT, ".evidence", "ida", "BrutalLegend.exe.i64"))
DECOMP_DIR = os.path.join(ROOT, ".evidence", "decomp")


def ea_of(s):
    import ida_name
    import idaapi
    try:
        return int(s, 16)
    except ValueError:
        ea = ida_name.get_name_ea(idaapi.BADADDR, s)
        if ea == idaapi.BADADDR:
            sys.exit(f"unknown name {s}")
        return ea


def func_name(ea):
    import ida_funcs
    import ida_name
    f = ida_funcs.get_func(ea)
    if not f:
        return f"{ea:#x}"
    return f"{ida_name.get_name(f.start_ea)}@{f.start_ea:#x}"


def cmd_strings(a):
    import idautils
    rx = re.compile(a.regex)
    for s in idautils.Strings():
        t = str(s)
        if rx.search(t):
            users = sorted({func_name(x.frm) for x in idautils.XrefsTo(s.ea)})
            print(f"{s.ea:#x} {t!r:60} {' '.join(users[:6])}")


def cmd_xrefs(a):
    import idautils
    for x in idautils.XrefsTo(ea_of(a.ea)):
        print(f"{x.frm:#x} {func_name(x.frm)}")


def cmd_decomp(a):
    import ida_funcs
    import ida_hexrays
    import idautils
    os.makedirs(DECOMP_DIR, exist_ok=True)
    root = ida_funcs.get_func(ea_of(a.ea))
    seen, frontier, out = set(), [(root.start_ea, 0)], []
    while frontier:
        ea, depth = frontier.pop(0)
        if ea in seen:
            continue
        seen.add(ea)
        try:
            text = str(ida_hexrays.decompile(ea))
        except Exception as ex:
            text = f"// decompile failed: {ex}"
        out.append(f"// ===== {func_name(ea)} (depth {depth})\n{text}\n")
        if depth < a.depth:
            f = ida_funcs.get_func(ea)
            for item in idautils.FuncItems(f.start_ea):
                for x in idautils.CodeRefsFrom(item, False):
                    g = ida_funcs.get_func(x)
                    if g and g.start_ea == x and not (g.flags & ida_funcs.FUNC_LIB):
                        frontier.append((x, depth + 1))
    path = os.path.join(DECOMP_DIR, f"{root.start_ea:08x}.c")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"{len(out)} functions -> {path}")
    if a.print:
        print("\n".join(out))


def cmd_imm(a):
    import ida_bytes
    import ida_segment
    seg = ida_segment.get_segm_by_name(".text")
    text = ida_bytes.get_bytes(seg.start_ea, seg.end_ea - seg.start_ea)
    for tag in a.values:
        v = int(tag, 16) if tag.startswith("0x") else int.from_bytes(tag.encode("latin-1"), "little")
        pat, i, n = v.to_bytes(4, "little"), 0, 0
        while n < 40 and (i := text.find(pat, i)) >= 0:
            ea = seg.start_ea + i
            head = ida_bytes.get_item_head(ea)
            if ida_bytes.is_code(ida_bytes.get_flags(head)):
                print(f"{tag!r} {v:#010x} {head:#x} {func_name(head)}")
                n += 1
            i += 1


def cmd_vtable(a):
    import ida_bytes
    import ida_name
    import idaapi
    import idautils
    ea = ida_name.get_name_ea(idaapi.BADADDR, f"??_7{a.cls}@@6B@")
    if ea == idaapi.BADADDR:
        hits = [n for _, n in idautils.Names() if a.cls in n and n.startswith("??_7")]
        sys.exit(f"no vftable for {a.cls}; candidates: {hits[:10]}")
    for i in range(a.count):
        tgt = ida_bytes.get_dword(ea + 4 * i)
        if not ida_bytes.is_code(ida_bytes.get_flags(tgt)):
            break
        print(f"+{4 * i:#04x} {func_name(tgt)}")


def cmd_rename(a):
    import ida_name
    ida_name.set_name(ea_of(a.ea), a.name, ida_name.SN_CHECK)
    print(f"{a.ea} -> {a.name}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("strings"); p.add_argument("regex"); p.set_defaults(fn=cmd_strings)
    p = sub.add_parser("xrefs"); p.add_argument("ea"); p.set_defaults(fn=cmd_xrefs)
    p = sub.add_parser("decomp"); p.add_argument("ea"); p.add_argument("-d", "--depth", type=int, default=0)
    p.add_argument("-p", "--print", action="store_true"); p.set_defaults(fn=cmd_decomp)
    p = sub.add_parser("imm"); p.add_argument("values", nargs="+"); p.set_defaults(fn=cmd_imm)
    p = sub.add_parser("vtable"); p.add_argument("cls"); p.add_argument("-n", "--count", type=int, default=40)
    p.set_defaults(fn=cmd_vtable)
    p = sub.add_parser("rename"); p.add_argument("ea"); p.add_argument("name"); p.set_defaults(fn=cmd_rename)
    a = ap.parse_args()

    import idapro
    if idapro.open_database(DB, run_auto_analysis=False):
        sys.exit(f"cannot open {DB}")
    try:
        a.fn(a)
    finally:
        idapro.close_database(save=a.cmd == "rename")


if __name__ == "__main__":
    main()
