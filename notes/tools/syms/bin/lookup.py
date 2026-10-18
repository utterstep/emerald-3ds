#!/usr/bin/env python3
"""Lookups in jp_syms.tsv.

  lookup.py SYMBOL...          rows of these symbols (exact name; 're:REGEX' for a pattern)
  lookup.py 0xADDR...          the JP symbol containing this JP address (and the EN one)
  lookup.py --en 0xADDR...     the EN symbol containing this EN address and its JP address
"""
import bisect
import os
import signal
import re
import sys

SYMS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSV = os.path.join(SYMS, "jp_syms.tsv")
COLS = ["symbol", "kind", "en_addr", "jp_addr", "en_size", "jp_size", "status", "confidence", "method", "source"]


def load():
    rows = []
    for line in open(TSV):
        p = line.rstrip("\n").split("\t")
        if p[0] == "symbol":
            continue
        rows.append(p)
    return rows


class Index:
    """Address -> row lookups for one side (col 2 = EN, col 3 = JP)."""

    def __init__(self, rows, col):
        ent = []
        for r in rows:
            if not r[col]:
                continue
            a = int(r[col], 16)
            if r[1] == "func":
                a &= ~1
            if col == 2:
                size = r[4]
            else:  # JP side: the JP size, the EN one when identical, else the start only
                size = r[5] or (r[4] if r[6] == "identical" else 1)
                if r[1] != "func" and r[5] and r[6] == "changed":
                    # a data span can run over JP-only data placed after the symbol
                    size = min(int(r[5]), max(2 * int(r[4]), int(r[4]) + 32))
            ent.append((a, int(size or 0), r))
        # functions first at equal addresses
        ent.sort(key=lambda t: (t[0], t[2][1] != "func", -t[1]))
        self.ent = ent
        self.starts = [t[0] for t in ent]

    def find(self, addr):
        """(row, offset) of the symbol containing addr, or (None, None)."""
        k = bisect.bisect_right(self.starts, addr) - 1
        best = None
        j = k
        while j >= 0 and j > k - 64:
            a, size, r = self.ent[j]
            if a <= addr < a + max(size, 1):
                if best is None or a > best[0] or (a == best[0] and r[1] == "func"):
                    best = (a, r)
                if a == addr:
                    break
            j -= 1
        if best is None:
            return None, None
        return best[1], addr - best[0]

    def name(self, addr):
        r, off = self.find(addr)
        if r is None:
            return None
        return r[0] + ("+%#x" % off if off else "")


def fmt(r):
    return "  ".join("%s=%s" % (c, v) for c, v in zip(COLS, r) if v != "")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    rows = load()
    side = "jp"
    if args[0] == "--en":
        side = "en"
        args = args[1:]
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    idx = None
    rc = 0
    for a in args:
        if re.fullmatch(r"(0x)?[0-9a-fA-F]{7,8}", a):
            if idx is None:
                idx = Index(rows, 3 if side == "jp" else 2)
            r, off = idx.find(int(a, 16))
            if r is None:
                print("%s: no mapped symbol contains this %s address" % (a, side.upper()))
                rc = 1
            else:
                print("%s = %s+%#x  (%s)" % (a, r[0], off, fmt(r)))
        elif a.startswith("re:"):
            rx = re.compile(a[3:])
            for r in rows:
                if rx.search(r[0]):
                    print(fmt(r))
        else:
            if a not in by:
                print("%s: not in the EN build's symbols" % a)
                rc = 1
            for r in by.get(a, []):
                print(fmt(r))
    return rc


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
