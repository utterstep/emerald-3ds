#!/usr/bin/env python3
"""A candidate for tools/locales/japanese-symbols.s.gz from jp_syms.tsv (addresses and sizes only,
the format of the Italian file: .global/.type/.equ/.size, unmapped symbols at 0). The 87 entries
of the current file win over the map. Not for committing as is: review first.

  symfile.py OUT.s [--min-conf 0.9]"""
import gzip
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import lookup  # noqa: E402


def main():
    out = sys.argv[1]
    min_conf = float(sys.argv[sys.argv.index("--min-conf") + 1]) if "--min-conf" in sys.argv else 0.9
    known = {}
    cur = os.path.join(common.S, "wt_build", "tools/locales/japanese-symbols.s.gz")
    name = None
    for line in gzip.open(cur, "rt"):
        m = re.match(r"\.equ (\S+), (\d+)", line)
        if m:
            known.setdefault(m.group(1), [int(m.group(2)), None])
        m = re.match(r"\.size (\S+), (\d+)", line)
        if m and m.group(1) in known:
            known[m.group(1)][1] = int(m.group(2))
    rows = lookup.load()
    count = {}
    for r in rows:
        count[r[0]] = count.get(r[0], 0) + 1
    lines = [".syntax unified"]
    stats = {"mapped": 0, "zero": 0, "dup-skipped": 0, "known": 0}
    for r in rows:
        sym, kind, ea, ja, es, js, st, cf = r[:8]
        if count[sym] > 1:
            stats["dup-skipped"] += 1  # static symbols with the same name in several files
            continue
        typ = "%function" if kind == "func" else "%object"
        if sym in known:
            addr, size = known[sym]
            size = size if size is not None else int(js or es)
            stats["known"] += 1
        elif ja and float(cf) >= min_conf and (st == "identical" or js):
            addr, size = int(ja, 16), int(js or es)
            stats["mapped"] += 1
        else:
            addr, size = 0, 0
            stats["zero"] += 1
        lines += [".global " + sym, ".type %s, %s" % (sym, typ), ".equ %s, %d" % (sym, addr),
                  ".size %s, %d" % (sym, size)]
    open(out, "w").write("\n".join(lines) + "\n")
    print(out, stats)


if __name__ == "__main__":
    main()
