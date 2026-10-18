#!/usr/bin/env python3
"""Map the vanilla English build's functions and data to the Japanese ROM (BPEJ).

Phases:
  1. anchors: every EN function whose normalised body (BL targets, literal-pool pointers
     masked, pointer classes checked) occurs exactly once in the JP code area;
     out-of-order anchors are dropped unless they form a run (a moved object).
  2. link order: the neighbours of an identical function are tried at the same relative
     offset in the JP ROM (fills duplicates and small functions).
  3. call graph: BL targets and function-pointer pool words at the same position in identical
     functions give the callee's JP address (identical if its body verifies, else changed).
  4. gaps: EN functions still unmapped between two mapped ones are aligned with the JP code in
     between (cut at JP call targets / function pointers) by instruction-level similarity.
  5. data: literal-pool words of matched functions (aligned instructions for changed ones) give
     EN symbol <-> JP address votes; mapped pointer tables/scripts propagate to their targets.
Outputs jp_syms.tsv and state.pkl (used by report.py, jpdis.sh, jpaddr.sh).
"""
import bisect
import collections
import difflib
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import ROM, ptr_class, u32, bl_target  # noqa: E402
import norm  # noqa: E402
import datamap  # noqa: E402

OUT = common.SYMS
T0 = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - T0), *a, flush=True)


class State:
    pass


def lis_indices(seq):
    """Indices of a longest strictly increasing subsequence of seq."""
    tails, tails_i, prev = [], [], [-1] * len(seq)
    for i, x in enumerate(seq):
        j = bisect.bisect_left(tails, x)
        if j == len(tails):
            tails.append(x)
            tails_i.append(i)
        else:
            tails[j] = x
            tails_i[j] = i
        prev[i] = tails_i[j - 1] if j else -1
    out = []
    k = tails_i[-1] if tails_i else -1
    while k >= 0:
        out.append(k)
        k = prev[k]
    return out[::-1]


def main():
    en = common.load_en()
    jp = common.load_jp()
    enr = en["rom"]
    funcs = en["funcs"]
    data = en["data"]
    fstart = en["func_starts"]
    for f in funcs:
        norm.normalise(f, en)
    n = len(funcs)
    log("EN functions", n, "data symbols", len(data))

    # JP code area: up to the end of the JP library code (found after the anchors).
    CODE_LO, CODE_HI = ROM, ROM + 0x300000
    region = jp[CODE_LO - ROM:CODE_HI - ROM]

    jaddr = [None] * n      # JP start
    status = [None] * n     # identical / changed
    method = [None] * n
    conf = [0.0] * n
    claimed = {}            # JP start -> EN idx

    def assign(i, a, st, meth, c):
        if jaddr[i] is not None or a in claimed:
            return False
        jaddr[i], status[i], method[i], conf[i] = a, st, meth, c
        claimed[a] = i
        return True

    # ---- 1. anchors ----
    cand = []
    multi = {}
    for f in funcs:
        L = f.longest
        if not L or len(L[1]) < 10:
            continue
        off, seg = L
        hits, p, k = [], region.find(seg), 0
        while p >= 0 and k < 64:
            a = CODE_LO + p - off
            if a % 2 == 0 and norm.verify(f, jp, a):
                hits.append(a)
            p = region.find(seg, p + 1)
            k += 1
        if len(hits) == 1:
            cand.append((f.idx, hits[0]))
        elif hits:
            multi[f.idx] = hits
    cand.sort()
    keep = set(lis_indices([a for _, a in cand]))
    # out-of-order anchors kept when they form a run of >= 3 EN neighbours with one delta
    rejected = [c for k, c in enumerate(cand) if k not in keep]
    moved = set()
    for k in range(len(rejected)):
        i, a = rejected[k]
        d = a - funcs[i].addr
        run = [k]
        for kk in (k - 1, k + 1, k - 2, k + 2):
            if 0 <= kk < len(rejected):
                i2, a2 = rejected[kk]
                if a2 - funcs[i2].addr == d and abs(i2 - i) <= 3:
                    run.append(kk)
        if len(run) >= 3:
            moved.add(k)
    for k, (i, a) in enumerate(cand):
        if k in keep:
            assign(i, a, "identical", "anchor", 1.0)
        elif k in moved:
            assign(i, a, "identical", "anchor-moved", 0.95)
    log("anchors", len(cand), "kept", len(keep), "moved", len(moved), "dropped",
        len(rejected) - len(moved), "ambiguous", len(multi))

    def jend(i):
        """JP end of a mapped identical function (start + EN size)."""
        return jaddr[i] + funcs[i].size

    # ---- 2+3: link-order extension and call graph, to a fixed point ----
    votes = collections.defaultdict(collections.Counter)  # EN idx -> JP addr votes
    voted_from = set()

    def extend():
        added = 0
        changed = True
        while changed:
            changed = False
            for i in range(n):
                if status[i] != "identical":
                    continue
                for j in (i - 1, i + 1):
                    if 0 <= j < n and jaddr[j] is None:
                        a = jaddr[i] + (funcs[j].addr - funcs[i].addr)
                        if norm.verify(funcs[j], jp, a) and assign(j, a, "identical", "link-order", 0.98):
                            added += 1
                            changed = True
        return added

    def callgraph():
        for i in range(n):
            if status[i] != "identical" or i in voted_from:
                continue
            voted_from.add(i)
            f, a = funcs[i], jaddr[i]
            for off, kind, cls in f.checks:
                if kind == "BL":
                    t = bl_target(enr, f.addr + off)
                    u = bl_target(jp, a + off)
                    g = fstart.get(t)
                    if g is not None and u is not None:
                        votes[g.idx][u] += 1
                elif kind == "W" and cls == "F":
                    v = u32(enr, f.addr - ROM + off)
                    w = u32(jp, a - ROM + off)
                    g = fstart.get(v & ~1)
                    if g is not None:
                        votes[g.idx][w & ~1] += 1
        added = 0
        for j, c in votes.items():
            if jaddr[j] is not None:
                continue
            u, nv = c.most_common(1)[0]
            if norm.verify(funcs[j], jp, u):
                if assign(j, u, "identical", "callgraph", min(1.0, 0.9 + 0.02 * nv)):
                    added += 1
        return added

    while True:
        a1 = extend()
        a2 = callgraph()
        log("link-order +%d, callgraph-exact +%d" % (a1, a2))
        if not a1 and not a2:
            break
    # ambiguous exact hits resolved by order: the hit between the mapped neighbours
    for i, hits in multi.items():
        if jaddr[i] is not None:
            continue
        lo = max([jaddr[k] for k in range(max(0, i - 8), i) if jaddr[k] is not None] or [0])
        hi = min([jaddr[k] for k in range(i + 1, min(n, i + 9)) if jaddr[k] is not None] or [1 << 32])
        hs = [h for h in hits if lo < h < hi and h not in claimed]
        if len(hs) == 1:
            assign(i, hs[0], "identical", "anchor-order", 0.95)
    while extend() or callgraph():
        pass
    nid = sum(1 for s in status if s == "identical")
    log("identical", nid)
    write_tsv(en, funcs, jaddr, status, method, conf, {}, {}, partial=True)
    write_state(en, jp, funcs, jaddr, status, method, conf, None, {}, {}, partial=True)

    # ---- JP code end ----
    hi_code = max(jaddr[i] + funcs[i].size for i in range(n) if jaddr[i] is not None)
    CODE_HI = (hi_code + 0x3FF) & ~0x3FF
    log("JP code end %#x" % CODE_HI)

    def ident_ranges():
        rs = sorted((jaddr[i], jaddr[i] + funcs[i].size) for i in range(n) if status[i] == "identical")
        return rs, [r[0] for r in rs]

    def inside_identical(u, rr):
        rs, st = rr
        k = bisect.bisect_right(st, u) - 1
        return k >= 0 and rs[k][0] < u < rs[k][1]

    # ---- 3b: call-graph votes for changed functions ----
    def cg_changed():
        added = 0
        rr = ident_ranges()
        for j, c in votes.items():
            if jaddr[j] is not None:
                continue
            u, nv = c.most_common(1)[0]
            tot = sum(c.values())
            if ROM <= u < CODE_HI and not inside_identical(u, rr):
                added += assign(j, u, "changed", "callgraph", round(0.6 + 0.4 * nv / tot, 3) if nv >= 2 else 0.6)
        return added

    log("callgraph changed +%d" % cg_changed())

    # ---- JP sizes: identical = EN size; changed = the agbcc function extent ----
    size_cache = {}

    def next_start(a):
        st = sorted_starts()
        k = bisect.bisect_right(st, a)
        return st[k] if k < len(st) else CODE_HI

    _ss = [None, -1]

    def sorted_starts():
        if _ss[1] != len(claimed):
            _ss[0] = sorted(claimed)
            _ss[1] = len(claimed)
        return _ss[0]

    def jp_size(i):
        if status[i] == "identical":
            return funcs[i].size
        a = jaddr[i]
        nxt = next_start(a)
        key = (i, a, nxt)
        if key not in size_cache:
            if not funcs[i].thumb:
                size_cache[key] = min(funcs[i].size, nxt - a)
            else:
                size_cache[key] = norm.func_extent(jp, a, min(nxt, a + 8 * funcs[i].size + 0x1000)) - a
        return size_cache[key]

    tok_cache = {}

    def en_tokens(i):
        key = ("en", i)
        if key not in tok_cache:
            f = funcs[i]
            tok_cache[key] = norm.tokenise(enr, f.addr, f.addr + f.size, f.thumb)
        return tok_cache[key]

    def jp_tokens(s, e, thumb=True):
        key = ("jp", s, e)
        if key not in tok_cache:
            tok_cache[key] = norm.tokenise(jp, s, e, thumb)
        return tok_cache[key]

    def similarity(i, s, e):
        a = [t[0] for t in en_tokens(i)]
        b = [t[0] for t in jp_tokens(s, e, funcs[i].thumb)]
        if not a or not b:
            return 0.0
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        return sm.ratio()

    def segment(lo, hi, cap=400):
        """JP code in [lo, hi) cut into agbcc functions."""
        segs, s = [], lo
        while s < hi and len(segs) < cap:
            if (s & 3) == 2 and jp[s - ROM:s - ROM + 2] == b"\0\0":
                s += 2
                continue
            e = norm.func_extent(jp, s, hi)
            if e <= s:
                break
            segs.append((s, e))
            s = e
        return segs

    # ---- 4. gaps between mapped functions (in EN order) ----
    def mapped_indices():
        return [i for i in range(n) if jaddr[i] is not None]

    def fill_gaps():
        added = 0
        mi = mapped_indices()
        for p, q in zip(mi, mi[1:]):
            if q == p + 1:
                continue
            lo = jaddr[p] + jp_size(p)
            hi = jaddr[q]
            U = list(range(p + 1, q))
            if hi <= lo or hi - lo > 0x20000:
                continue
            segs = segment(lo, hi)
            if not segs or len(segs) > 4 * len(U) + 40:
                continue
            nu, ns = len(U), len(segs)
            sim = {}
            for x in range(nu):
                fx = funcs[U[x]]
                for y in range(ns):
                    s, e = segs[y]
                    if abs(x * ns / max(nu, 1) - y) > 6 + ns * 0.3:
                        continue
                    ln = e - s
                    if ln > 4 * fx.size + 64 or fx.size > 4 * ln + 64:
                        continue
                    sim[x, y] = similarity(U[x], s, e)
            D = [[0.0] * (ns + 1) for _ in range(nu + 1)]
            B = [[None] * (ns + 1) for _ in range(nu + 1)]
            for x in range(nu + 1):
                for y in range(ns + 1):
                    if x == 0 and y == 0:
                        continue
                    best, bk = -1e9, None
                    if x and y and (x - 1, y - 1) in sim and sim[x - 1, y - 1] >= 0.3:
                        v = D[x - 1][y - 1] + sim[x - 1, y - 1]
                        if v > best:
                            best, bk = v, "m"
                    if x and D[x - 1][y] > best:
                        best, bk = D[x - 1][y], "u"
                    if y and D[x][y - 1] > best:
                        best, bk = D[x][y - 1], "s"
                    D[x][y], B[x][y] = best, bk
            x, y = nu, ns
            pairs = []
            while x or y:
                bk = B[x][y]
                if bk == "m":
                    pairs.append((x - 1, y - 1))
                    x, y = x - 1, y - 1
                elif bk == "u":
                    x -= 1
                else:
                    y -= 1
            for x, y in pairs:
                r = sim[x, y]
                if r >= 0.4:
                    s, e = segs[y]
                    i = U[x]
                    st = "identical" if norm.verify(funcs[i], jp, s) else "changed"
                    cf = 0.98 if st == "identical" else round(min(0.95, 0.3 + 0.7 * r), 3)
                    if assign(i, s, st, "gap-align", cf):
                        added += 1
        return added

    for rnd in range(4):
        g = fill_gaps()
        e2 = extend()
        c2 = callgraph()
        c3 = cg_changed()
        log("gap round %d: +%d aligned, +%d link-order, +%d callgraph, +%d callgraph-changed" % (rnd, g, e2, c2, c3))
        if not g and not e2 and not c2 and not c3:
            break

    # similarity / confidence of changed functions
    simv = {}

    def score_changed():
        for i in range(n):
            if status[i] == "changed":
                r = similarity(i, jaddr[i], jaddr[i] + jp_size(i))
                simv[i] = r
                if method[i] == "callgraph":
                    # the call graph is strong evidence; a low similarity means a rewrite
                    conf[i] = round(max(0.5, min(0.97, conf[i] * (0.6 + 0.4 * r))), 3)

    score_changed()
    log("functions: identical %d changed %d unmatched %d" % (
        sum(1 for s in status if s == "identical"), sum(1 for s in status if s == "changed"),
        sum(1 for s in status if s is None)))

    # ---- 5. data (and functions only reached through data pointers) ----
    for rnd in range(3):
        dmap, dsizes, dstatus, fvotes2 = datamap.map_data(en, jp, funcs, jaddr, status, jp_size,
                                                          en_tokens, jp_tokens, log=log)
        added = 0
        for j, c in fvotes2.items():
            if jaddr[j] is None:
                u, nv = c.most_common(1)[0]
                if norm.verify(funcs[j], jp, u):
                    added += assign(j, u, "identical", "funcptr", 0.95)
                elif nv >= 1 and ROM <= u < CODE_HI and nv >= 0.5 * sum(c.values()):
                    if funcs[j].thumb and not inside_identical(u, ident_ranges()):
                        e = norm.func_extent(jp, u, min(next_start(u), u + 8 * funcs[j].size + 0x1000))
                        r = similarity(j, u, e)
                        if r >= 0.5:
                            added += assign(j, u, "changed", "funcptr", round(0.3 + 0.6 * r, 3))
        log("functions from data pointers +%d" % added)
        if not added:
            break
        while extend() or callgraph():
            pass
        fill_gaps()
        score_changed()

    # secondary votes (from aligned changed code and data tables) confirm or weaken changed matches
    for i in range(n):
        if status[i] == "changed" and i in fvotes2:
            c = fvotes2[i]
            agree = c.get(jaddr[i], 0)
            tot = sum(c.values())
            if agree >= 0.5 * tot:
                conf[i] = round(min(0.99, conf[i] + 0.1), 3)
            elif tot >= 1:
                conf[i] = round(conf[i] * 0.7, 3)

    write_tsv(en, funcs, jaddr, status, method, conf, dmap, simv, jp_size=jp_size, partial=False,
              dsizes=dsizes, dstatus=dstatus)
    write_state(en, jp, funcs, jaddr, status, method, conf, jp_size, dmap, simv, partial=False,
                cstarts=sorted_starts(), code_hi=CODE_HI, dsizes=dsizes, dstatus=dstatus)
    log("done")


def data_jp_sizes(en, dmap):
    """JP size of each mapped data symbol: up to the JP address of its EN successor when that one
    is mapped and still follows it."""
    data = en["data"]
    out = {}
    order = sorted(dmap)
    for k, di in enumerate(order):
        w = dmap[di][0]
        nxt = order[k + 1] if k + 1 < len(order) else None
        d = data[di]
        if nxt == di + 1 and data[nxt].kind == d.kind:
            wn = dmap[nxt][0]
            if wn > w and (wn - w) < 4 * d.size + 0x10000:
                out[di] = wn - w
    return out


def write_tsv(en, funcs, jaddr, status, method, conf, dmap, simv, jp_size=None, partial=False,
              dsizes=None, dstatus=None):
    path = os.path.join(OUT, "jp_syms.tsv")
    tmp = path + ".tmp"
    with open(tmp, "w") as fo:
        fo.write("symbol\tkind\ten_addr\tjp_addr\ten_size\tjp_size\tstatus\tconfidence\tmethod\tsource\n")
        for i, f in enumerate(funcs):
            st = status[i] or "unmatched"
            if partial:
                st = "partial:" + st
            js = (jp_size(i) if jp_size else f.size) if jaddr[i] is not None else ""
            if partial and jaddr[i] is not None and st != "identical":
                js = ""
            meth = method[i] or ""
            for name in [f.name] + f.aliases:
                fo.write("%s\tfunc\t%#010x\t%s\t%d\t%s\t%s\t%s\t%s\t%s\n" % (
                    name, f.addr | (1 if f.thumb else 0),
                    ("%#010x" % (jaddr[i] | (1 if f.thumb else 0))) if jaddr[i] is not None else "",
                    f.size, js, st, ("%.3f" % conf[i]) if jaddr[i] is not None else "0", meth,
                    common.source_of(f.obj)))
        if dmap:
            data = en["data"]
            for di, d in enumerate(data):
                if di in dmap:
                    w, cf, meth = dmap[di]
                    js, st, ja = dsizes.get(di, ""), dstatus[di], "%#010x" % w
                else:
                    ja, js, st, cf, meth = "", "", "unmatched", 0, ""
                for name in [d.name] + d.aliases:
                    fo.write("%s\t%s\t%#010x\t%s\t%d\t%s\t%s\t%s\t%s\t%s\n" % (
                        name, d.kind, d.addr, ja, d.size, js, st, ("%.3f" % cf) if ja else "0", meth,
                        common.source_of(d.obj)))
    os.replace(tmp, path)


def write_state(en, jp, funcs, jaddr, status, method, conf, jp_size, dmap, simv, partial,
                cstarts=None, code_hi=None, dsizes=None, dstatus=None):
    st = {
        "partial": partial,
        "funcs": [(f.name, f.aliases, f.addr, f.size, f.thumb, common.source_of(f.obj)) for f in funcs],
        "jaddr": jaddr, "status": status, "method": method, "conf": conf,
        "jp_size": [jp_size(i) if (jp_size and jaddr[i] is not None) else None for i in range(len(funcs))],
        "sim": simv,
        "data": [(d.name, d.aliases, d.addr, d.size, d.kind, common.source_of(d.obj)) for d in en["data"]],
        "dmap": dmap, "dsizes": dsizes or {}, "dstatus": dstatus or {},
        "cstarts": cstarts, "code_hi": code_hi,
    }
    with open(os.path.join(OUT, "state.pkl.tmp"), "wb") as fo:
        pickle.dump(st, fo)
    os.replace(os.path.join(OUT, "state.pkl.tmp"), os.path.join(OUT, "state.pkl"))


if __name__ == "__main__":
    main()
