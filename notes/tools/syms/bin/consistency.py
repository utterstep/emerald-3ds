#!/usr/bin/env python3
"""Self-consistency of the map: in identical functions, every BL target and every pool pointer
to a symbol start must land on that symbol's mapped JP address."""
import collections, os, pickle, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, norm
from common import ROM, u32, bl_target
st = pickle.load(open(os.path.join(common.SYMS, "state.pkl"), "rb"))
en = common.load_en(); jp = common.load_jp(); enr = en["rom"]
F = en["funcs"]
for f in F:
    norm.normalise(f, en)
fj = {F[i].addr: st["jaddr"][i] for i in range(len(F))}
fstat = {F[i].addr: st["status"][i] for i in range(len(F))}
dj = {en["data"][k].addr: v[0] for k, v in st["dmap"].items()}
c = collections.Counter()
bad = collections.Counter()
for i, f in enumerate(F):
    if st["status"][i] != "identical":
        continue
    a = st["jaddr"][i]
    for off, kind, cls in f.checks:
        if kind == "BL":
            t, u = bl_target(enr, f.addr + off), bl_target(jp, a + off)
            if t in fj:
                if fj[t] is None:
                    c["bl->unmatched"] += 1
                elif fj[t] == u:
                    c["bl ok"] += 1
                else:
                    c["bl MISMATCH"] += 1
                    bad[("bl", F[i].name)] += 1
        elif kind == "W":
            v, w = u32(enr, f.addr - ROM + off), u32(jp, a - ROM + off)
            if cls == "F" and (v & ~1) in fj:
                x = fj[v & ~1]
                c["fptr ok" if x == (w & ~1) else "fptr->unmatched" if x is None else "fptr MISMATCH"] += 1
            elif v in dj:
                c["dptr ok" if dj[v] == w else "dptr MISMATCH"] += 1
                if dj[v] != w:
                    bad[("d", F[i].name)] += 1
            elif common.ptr_class(v) in ("E", "I", "R"):
                c["ptr not a mapped start"] += 1
print(dict(c))
print(bad.most_common(10))
