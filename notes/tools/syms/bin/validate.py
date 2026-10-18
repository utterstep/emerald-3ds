#!/usr/bin/env python3
"""Check jp_syms.tsv against the known Japanese points of the repository:
tools/locales/japanese-symbols.s.gz (graphics + Easy Chat lists), and
tools/locales/japanese.json.gz (text offsets by source position, graphics by path, Easy Chat lists,
the credits table, the Trainer Hill default challenge).
Text positions refer to the patched, unlocalised tree (agents/build/gen_tree)."""
import collections
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

S = common.S
WT = os.path.join(S, "wt_build")
TREE = os.path.join(S, "agents", "build", "gen_tree")
VANILLA = os.path.join(common.SYMS, "pokeemerald")


def load_tsv():
    rows = {}
    for line in open(os.path.join(common.SYMS, "jp_syms.tsv")):
        p = line.rstrip("\n").split("\t")
        if p[0] == "symbol":
            continue
        rows[p[0]] = p
    return rows


def known_points():
    """[(symbol, jp_addr, source)]"""
    pts = []
    for line in gzip.open(os.path.join(WT, "tools/locales/japanese-symbols.s.gz"), "rt"):
        m = re.match(r"\.equ (\S+), (\d+)", line)
        if m:
            pts.append((m.group(1), int(m.group(2)), "symbols.s"))
    man = json.load(gzip.open(os.path.join(WT, "tools/locales/japanese.json.gz")))
    for sym, off, size in man["easy_chat_id_lists"]:
        pts.append((sym, common.ROM + off, "json:easy_chat"))
    # graphics: path -> symbol through INCBIN in the vanilla sources
    incbin = collections.defaultdict(list)
    rx = re.compile(r"(\w+)\s*(?:\[[^\]]*\])+\s*=\s*INCBIN_\w+\(\s*\"([^\"]+)\"")
    for root, _, files in os.walk(os.path.join(VANILLA, "src")):
        for fn in files:
            if fn.endswith((".c", ".h")):
                txt = open(os.path.join(root, fn), encoding="latin-1").read()
                for m in rx.finditer(txt):
                    incbin[m.group(2)].append(m.group(1))
    for path, off, size in man["graphics"]:
        for sym in incbin.get(path, []):
            pts.append((sym, common.ROM + off, "json:graphics"))
    for g in [g for g in man["graphics_layout_differs"] if g.get("offset") is not None]:
        for sym in incbin.get(g["path"], []):
            pts.append((sym, common.ROM + g["offset"], "json:graphics_layout"))
    # texts: the label right before the first edit after it
    lab_c = re.compile(r"(\w+)\s*(?:\[[^\]]*\])+\s*=\s*$")
    for rel, f in man["files"].items():
        path = os.path.join(TREE, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        edits = sorted(f["edits"])
        last_label_pos = -1
        if rel.endswith((".s", ".inc")):
            labels = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^(\w+)::?", text)]
            li = 0
            used = set()
            for start, end, off, size, kind in edits:
                while li + 1 < len(labels) and labels[li + 1][0] < start:
                    li += 1
                if li < len(labels) and labels[li][0] < start and li not in used:
                    between = text[labels[li][0]:start]
                    # only the label's first text
                    if between.count(".string") <= 1 and between.count("\n") <= 3:
                        used.add(li)
                        pts.append((labels[li][1], common.ROM + off, "json:text"))
        else:
            for start, end, off, size, kind in edits:
                if kind not in ("c", "c_eos"):
                    continue
                before = text[max(0, start - 200):start]
                m = lab_c.search(before)
                if m:
                    pts.append((m.group(1), common.ROM + off, "json:text"))
    if man.get("credits"):
        pts.append(("sCreditsEntryPointerTable", common.ROM + man["credits"], "json:credits"))
    return pts


def main():
    rows = load_tsv()
    pts = known_points()
    res = collections.defaultdict(collections.Counter)
    bad = collections.defaultdict(list)
    seen = set()
    for sym, a, src in pts:
        if (sym, src) in seen:
            continue
        seen.add((sym, src))
        r = rows.get(sym)
        if r is None:
            res[src]["no-symbol"] += 1
            continue
        if not r[3]:
            res[src]["unmatched"] += 1
            continue
        ja = int(r[3], 16) & (~1 if r[1] == "func" else ~0)
        meth = r[8] or "?"
        cb = "conf>=%.1f" % (min(int(float(r[7]) * 10), 9) / 10)
        if ja == a:
            res[src]["ok"] += 1
            res["method:" + meth]["ok"] += 1
            res[cb]["ok"] += 1
        else:
            res[src]["WRONG"] += 1
            res["method:" + meth]["WRONG"] += 1
            res[cb]["WRONG"] += 1
            bad[src].append((sym, hex(a), r[3], meth, r[7]))
    for k in sorted(res):
        print("%-24s %s" % (k, dict(res[k])))
    for src, lst in bad.items():
        print("--", src, len(lst))
        for x in lst[:15]:
            print("   ", x)
    if "-v" in sys.argv:
        for src, lst in bad.items():
            for x in lst:
                print(src, *x)


if __name__ == "__main__":
    main()
