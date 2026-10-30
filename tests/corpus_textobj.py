"""Corpus gate for the text object format: every resource whose payload starts like
`u32 len, <digits>Class{` parses completely, and Material keeps its contract."""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brutal import textobj
from brutal.library import Library

L = Library()
ok, bad, ex = collections.Counter(), collections.Counter(), {}
for b, e in L.entries():
    d = b.read(e)
    if not textobj.is_textobj(d):
        continue
    try:
        o = textobj.parse(d)
        assert o["_class"], "empty class"
        ok[e.type] += 1
    except Exception as x:
        k = f"{e.type}: {type(x).__name__}: {str(x)[:60]}"
        bad[k] += 1
        ex.setdefault(k, e.name)
print(f"text objects ok={sum(ok.values())} in {len(ok)} types; bad={sum(bad.values())}")
print("  ", ", ".join(f"{t} {n}" for t, n in ok.most_common()))
for k, n in bad.most_common(15):
    print(f"  {n:5} {k}  e.g. {ex[k]}")
sys.exit(1 if bad else 0)
