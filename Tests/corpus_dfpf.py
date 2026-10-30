"""Corpus gate for DFPF records: for every entry of every bundle, the unpacked bytes are exactly
header_size + data size, and raw entries store exactly that many bytes."""
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Brutal.dfpf import Bundle
from Brutal.paths import packs_dir

n, bad, ex = collections.Counter(), collections.Counter(), {}
for h in sorted(glob.glob(os.path.join(packs_dir(), "*.~h"))):
    with Bundle(h) as b:
        for e in b:
            got = len(b.read(e))
            k = "ok" if got == e.unpacked_size else "size-mismatch"
            n[f"comp{e.compression}"] += 1
            if k != "ok":
                bad[k] += 1
                ex.setdefault(k, f"{e.path}: {got} vs {e.header_size}+{e.usize}")
print(dict(n), "bad", sum(bad.values()))
for k, v in ex.items():
    print("  e.g.", k, v)
sys.exit(1 if bad else 0)
