"""Data symbols (ROM data and RAM) of the EN build -> JP addresses.

Sources, strongest first:
  pool      literal-pool words of matched functions: at the same offset in identical functions,
            through the ldr instructions that load them in changed ones (aligned instructions)
  data-ptr  pointer words inside mapped tables, structs and scripts whose JP copy has the same
            layout (all pointer words of the same region class, or the prefix with equal bytes)
  data-gap  unmapped symbols between two mapped ones walked forward/backward: identical data
            (same bytes, pointers masked) or strings (cut at the JP terminators); confidence is
            high when the walk closes exactly on the next mapped symbol
  data-order neighbours of identical data at the same relative offset (edges of a run)
"""
import bisect
import collections
import difflib

import common
from common import ROM, ptr_class, u32
import norm


# precision per method on 13,000 validation points (bin/validate.py), rounded down
CALIBRATION = {
    "pool": 0.99, "pool-aligned": 0.96, "data-ptr": 0.99, "data-ptr-weak": 0.95,
    "data-gap:bo": 0.99, "data-gap:cl": 0.98, "data-gap:bw": 0.98, "data-gap:sp": 0.8,
    "data-order": 0.9, "ram-span": 0.8, "content": 0.97,
}


def map_data(en, jp, funcs, jaddr, status, jp_size, en_tokens, jp_tokens, log=print):
    enr = en["rom"]
    data = en["data"]
    fstart = en["func_starts"]
    n = len(funcs)
    secs = {s.name: (s.addr, s.addr + s.size) for s in en["rom_secs"]}
    EN_TEXT, EN_SCR, EN_LIB = secs[".text"], secs["script_data"], secs["lib_text"]
    mapped = [i for i in range(n) if jaddr[i] is not None]
    jp_text_end = max(jaddr[i] + jp_size(i) for i in mapped if funcs[i].addr < EN_TEXT[1] and status[i] == "identical")
    lib = [i for i in mapped if EN_LIB[0] <= funcs[i].addr < EN_LIB[1]]
    JP_LIB = (min(jaddr[i] for i in lib), max(jaddr[i] + jp_size(i) for i in lib))
    JP_TEXT_END = (jp_text_end + 3) & ~3
    log("JP regions: code < %#x, scripts < %#x, lib < %#x" % (JP_TEXT_END, JP_LIB[0], JP_LIB[1]))

    def cls_en(v):
        c = ptr_class(v)
        if c != "R":
            return c
        if v < EN_TEXT[1] or EN_LIB[0] <= v < EN_LIB[1]:
            return "C"
        if EN_SCR[0] <= v < EN_SCR[1]:
            return "S"
        return "D"

    def cls_jp(v):
        c = ptr_class(v)
        if c != "R":
            return c
        if v < JP_TEXT_END or JP_LIB[0] <= v < JP_LIB[1]:
            return "C"
        if JP_TEXT_END <= v < JP_LIB[0]:
            return "S"
        return "D"

    dstarts = [d.addr for d in data]
    dvotes = collections.defaultdict(collections.Counter)
    fvotes = collections.defaultdict(collections.Counter)

    def data_of(v):
        k = bisect.bisect_right(dstarts, v) - 1
        if k >= 0:
            d = data[k]
            if d.addr <= v < d.addr + max(d.size, 1) or (v == d.addr + d.size and d.size):
                return d
        return None

    def pair(v, w, weight):
        ce = cls_en(v)
        if ce is None or ce != cls_jp(w):
            return
        if ce == "C":
            g = fstart.get(v & ~1)
            if g is not None and (v & 1) == (w & 1):
                fvotes[g.idx][w & ~1] += weight
            return
        d = data_of(v)
        if d is None:
            return
        k = v - d.addr
        dvotes[d.idx][w - k] += weight if k == 0 else weight * 0.25

    # votes from code
    for i in mapped:
        f, a = funcs[i], jaddr[i]
        if status[i] == "identical":
            for off, kind, c in f.checks:
                if kind == "W":
                    pair(u32(enr, f.addr - ROM + off), u32(jp, a - ROM + off), 1.0)
        else:
            ta = en_tokens(i)
            tb = jp_tokens(a, a + jp_size(i), f.thumb)
            sm = difflib.SequenceMatcher(None, [t[0] for t in ta], [t[0] for t in tb], autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "replace":
                    continue
                # replaced stretches: pair loads and calls in order when both sides have as many
                la = [t for t in ta[i1:i2] if 0x4800 <= t[0] <= 0x4FFF and t[2] is not None and ptr_class(t[2])]
                lb = [t for t in tb[j1:j2] if 0x4800 <= t[0] <= 0x4FFF and t[2] is not None and ptr_class(t[2])]
                if la and len(la) == len(lb) and len(la) <= 8:
                    for x, y in zip(la, lb):
                        pair(x[2], y[2], 0.3)
                ba = [t for t in ta[i1:i2] if t[0] == norm.T_BL]
                bb = [t for t in tb[j1:j2] if t[0] == norm.T_BL]
                if ba and len(ba) == len(bb) and len(ba) <= 8:
                    for x, y in zip(ba, bb):
                        g = fstart.get(x[2])
                        if g is not None:
                            fvotes[g.idx][y[2]] += 0.3
            for blk in sm.get_matching_blocks():
                wt = 0.5 if blk.size >= 2 else 0.3
                for k in range(blk.size):
                    x, y = ta[blk.a + k], tb[blk.b + k]
                    if x[2] is None or y[2] is None:
                        continue
                    if x[0] == norm.T_BL:
                        g = fstart.get(x[2])
                        if g is not None:
                            fvotes[g.idx][y[2]] += wt
                    elif 0x4800 <= x[0] <= 0x4FFF:
                        pair(x[2], y[2], wt)

    dmap = {}
    jclaim = {}
    shares = {}

    def put(di, w, cf, meth):
        if di in dmap or w in jclaim:
            return False
        dmap[di] = (w, round(cf, 3), meth)
        jclaim[w] = di
        return True

    def resolve(meth):
        added = 0
        for di, c in dvotes.items():
            if di in dmap:
                continue
            (w, nv), tot = c.most_common(1)[0], sum(c.values())
            share = nv / tot
            if share < 0.5 or nv < 0.2:
                continue
            m = meth
            if meth == "pool" and nv < 1:
                m = "pool-aligned"  # only from aligned instructions of changed functions
            elif meth == "data-ptr" and nv < 0.3:
                m = "data-ptr-weak"
            if put(di, w, share * min(1.0, 0.55 + 0.45 * nv), m):
                shares[di] = share
                added += 1
        return added

    reloc_addrs = sorted(a for a, (t, s) in en["relocs"].items() if t == common.R_ARM_ABS32 and a >= ROM)

    def drelocs(d):
        k0 = bisect.bisect_left(reloc_addrs, d.addr)
        k1 = bisect.bisect_left(reloc_addrs, d.addr + d.size)
        return reloc_addrs[k0:k1]

    def same_data(d, w):
        if not d.size or d.kind != "data":
            return False
        a, b = d.addr - ROM, w - ROM
        if b < 0 or b + d.size > len(jp):
            return False
        prev = 0
        for ra in drelocs(d):
            o = ra - d.addr
            if o < prev:
                continue
            if enr[a + prev:a + o] != jp[b + prev:b + o]:
                return False
            if o + 4 <= d.size and cls_en(u32(enr, a + o)) != cls_jp(u32(jp, b + o)):
                return False
            prev = o + 4
        return enr[a + prev:a + d.size] == jp[b + prev:b + d.size]

    text_cache = {}

    def text_len(d):
        """EN string length (with its 0xFF) when d is one string followed only by padding."""
        if d.idx in text_cache:
            return text_cache[d.idx]
        r = None
        if d.kind == "data" and 1 <= d.size <= 4096 and d.section in (".rodata", "script_data"):
            b = enr[d.addr - ROM:d.addr - ROM + d.size]
            k = b.find(b"\xff")
            if k >= 0 and not b[k + 1:].strip(b"\0") and not drelocs(d):
                r = k + 1
        text_cache[d.idx] = r
        return r

    def en_len(d):
        return text_len(d) or d.size

    def jp_end(di):
        w = dmap[di][0]
        d = data[di]
        if text_len(d):
            k = jp.find(b"\xff", w - ROM, w - ROM + 4 * d.size + 1024)
            return k + 1 + ROM if k >= 0 else None
        if same_data(d, w):
            return w + d.size
        return None

    def align_like(x, en_addr, pad):
        if not pad:
            return x
        al = 4 if en_addr % 4 == 0 else 2 if en_addr % 2 == 0 else 1
        return (x + al - 1) & -al

    def gap_walks():
        added = 0
        order = sorted(di for di in dmap if data[di].kind == "data")
        for p, q in zip(order, order[1:]):
            if q == p + 1:
                continue
            dp, dq = data[p], data[q]
            if dp.section != dq.section or dp.obj != dq.obj and q - p > 64:
                continue
            hi = dmap[q][0]
            lo = jp_end(p)
            cf = min(dmap[p][1], dmap[q][1])
            run = list(range(p + 1, q))
            if any(data[e].kind != "data" or data[e].section != dp.section for e in run):
                continue
            fw = {}
            closed = False
            if lo is not None and lo <= hi:
                x, prev_end = lo, dp.addr + en_len(dp)
                for e in run:
                    de = data[e]
                    pad = de.addr - prev_end
                    if pad < 0:
                        break
                    x = align_like(x, de.addr, pad)
                    if x >= hi:
                        break
                    ln = text_len(de)
                    if ln:
                        k = jp.find(b"\xff", x - ROM, hi - ROM)
                        if k < 0:
                            break
                        fw[e] = x
                        x, prev_end = k + 1 + ROM, de.addr + ln
                    elif same_data(de, x):
                        fw[e] = x
                        x, prev_end = x + de.size, de.addr + de.size
                    else:
                        break
                if len(fw) == len(run):
                    closed = align_like(x, dq.addr, dq.addr - prev_end) == hi
            bw = {}
            y, next_start = hi, dq.addr
            for e in reversed(run):
                de = data[e]
                ln = text_len(de)
                pad = next_start - (de.addr + en_len(de))
                if pad < 0:
                    break
                if ln:
                    end = y
                    if pad:
                        z = 0
                        while z < 3 and jp[end - 1 - ROM] == 0:
                            end -= 1
                            z += 1
                    if jp[end - 1 - ROM] != 0xFF:
                        break
                    pe = data[e - 1] if e - 1 >= 0 else None
                    if pe is not None and text_len(pe) and pe.addr + text_len(pe) == de.addr:
                        floor = lo if lo is not None else end - 1 - 4 * de.size - 1024
                        k = jp.rfind(b"\xff", max(floor, ROM) - ROM, end - 1 - ROM)
                        if k < 0:
                            break
                        start = k + 1 + ROM
                    elif e == p + 1 and lo is not None:
                        start = align_like(lo, de.addr, de.addr - (dp.addr + en_len(dp)))
                    else:
                        break
                    if lo is not None and start < lo:
                        break
                    bw[e] = start
                    y, next_start = start, de.addr
                else:
                    start = y - pad - de.size
                    if not same_data(de, start):
                        break
                    bw[e] = start
                    y, next_start = start, de.addr
            # all strings and the JP range holds another number of them: one side has a string
            # the other lacks, so a one-directional walk would shift by one
            mismatch = False
            if lo is not None and all(text_len(data[e]) for e in run) and text_len(dp) is not None:
                mismatch = jp[lo - ROM:hi - ROM].count(b"\xff") != len(run)
            for k, e in enumerate(run):
                a, b = fw.get(e), bw.get(e)
                base = 0.5 + 0.5 * cf
                if mismatch and (a is None or b is None or a != b):
                    continue
                if a is not None and b is not None:
                    if a == b:
                        added += put(e, a, base * 0.97, "data-gap:both")
                elif a is not None:
                    if closed:
                        added += put(e, a, base * 0.95, "data-gap:closed")
                    # an open forward walk is unreliable (JP-only strings in between): not used
                elif b is not None:
                    pos = len(run) - 1 - k
                    added += put(e, b, base * max(0.4, 0.8 - 0.1 * pos), "data-gap:bw%d" % min(pos, 3))
        return added

    def span_fill():
        """A run of unmapped symbols between two mapped ones whose JP distance equals the EN one:
        same layout, each symbol at its EN offset (ROM data and RAM)."""
        added = 0
        order = sorted(dmap)
        for p, q in zip(order, order[1:]):
            if q == p + 1:
                continue
            dp, dq = data[p], data[q]
            if dp.kind != dq.kind or dp.section != dq.section:
                continue
            wp, wq = dmap[p][0], dmap[q][0]
            if wq - wp != dq.addr - dp.addr:
                continue
            run = range(p + 1, q)
            if any(data[e].kind != dp.kind or data[e].section != dp.section or text_len(data[e]) for e in run):
                continue
            cf = 0.5 + 0.5 * min(dmap[p][1], dmap[q][1])
            for e in run:
                added += put(e, wp + (data[e].addr - dp.addr), cf * 0.85,
                             "ram-span" if dp.kind == "ram" else "data-gap:span")
        return added

    def edge_order():
        added = 0
        for di, (w, cf, meth) in list(dmap.items()):
            d = data[di]
            if d.kind != "data" or not same_data(d, w):
                continue
            for dj in (di - 1, di + 1):
                if 0 <= dj < len(data) and dj not in dmap:
                    e = data[dj]
                    if e.kind != "data" or e.section != d.section or not e.size:
                        continue
                    x = w + (e.addr - d.addr)
                    if same_data(e, x):
                        added += put(dj, x, cf * (0.97 if e.size >= 8 else 0.85), "data-order")
        return added

    propagated = set()

    def propagate():
        for di, (w, cf, meth) in list(dmap.items()):
            if di in propagated or cf < 0.45:
                continue
            propagated.add(di)
            d = data[di]
            if d.kind != "data" or not d.size:
                continue
            rs = drelocs(d)
            if not rs:
                continue
            pairs, ok = [], 0
            for ra in rs:
                v = u32(enr, ra - ROM)
                jo = w + (ra - d.addr) - ROM
                if jo < 0 or jo + 4 > len(jp):
                    continue
                x = u32(jp, jo)
                good = cls_en(v) is not None and cls_en(v) == cls_jp(x)
                ok += good
                pairs.append((ra, v, x, good))
            if pairs and ok >= 0.9 * len(rs) and same_layout_ok(d, w, rs):
                for ra, v, x, good in pairs:
                    if good:
                        pair(v, x, 0.5 * cf)
            elif stride_pairs(di, d, w, cf, rs):
                pass
            else:
                prev = d.addr
                for ra, v, x, good in pairs:
                    if not good or enr[prev - ROM:ra - ROM] != jp[w + (prev - d.addr) - ROM:w + (ra - d.addr) - ROM]:
                        break
                    pair(v, x, 0.4 * cf)
                    prev = ra + 4

    def jp_span(di, w):
        """Distance from w to the JP start of the EN successor (minus the EN padding), if mapped."""
        nx = di + 1
        if nx < len(data) and nx in dmap and dmap[nx][0] > w:
            return dmap[nx][0] - w - (data[nx].addr - (data[di].addr + data[di].size))
        return None

    def stride_pairs(di, d, w, cf, rs):
        """An array of structs whose JP element is smaller or larger (e.g. a shorter name field):
        find the EN stride from the pointer positions, the JP one from the JP size, and the JP
        offset of each pointer field (fields keep their order)."""
        js = jp_span(di, w)
        if not js or js == d.size or len(rs) < 8:
            return False
        offs = [ra - d.addr for ra in rs]
        oset = set(offs)
        p = None
        for cand in range(8, min(d.size // 4, 1024) + 1, 2):
            if d.size % cand:
                continue
            ok = sum(1 for o in offs if o + cand in oset or o + cand >= d.size)
            if ok >= 0.75 * len(offs):
                p = cand
                break
        if p is None:
            return False
        nel = d.size // p
        if js % nel:
            return False
        q = js // nel
        if q < 4:
            return False
        fields = sorted({o % p for o in offs})
        prev_f = -1
        out = []
        for f in fields:
            ks = [o // p for o in offs if o % p == f]
            cands = [f - (p - q), f] + sorted(range(0, q - 3), key=lambda x: abs(x - (f - (p - q))))
            chosen = None
            for g in cands:
                if g <= prev_f or g < 0 or g > q - 4:
                    continue
                good = 0
                for k in ks:
                    v = u32(enr, d.addr - ROM + k * p + f)
                    x = u32(jp, w - ROM + k * q + g)
                    good += cls_en(v) is not None and cls_en(v) == cls_jp(x)
                if good >= 0.95 * len(ks):
                    chosen = g
                    break
            if chosen is None:
                continue
            prev_f = chosen
            for k in ks:
                out.append((u32(enr, d.addr - ROM + k * p + f), u32(jp, w - ROM + k * q + chosen)))
        if not out:
            return False
        for v, x in out:
            pair(v, x, 0.4 * cf)
        return True

    def same_layout_ok(d, w, rs):
        """Tables of pointers only, or structs whose non-pointer bytes mostly agree."""
        a, b = d.addr - ROM, w - ROM
        if len(rs) * 4 >= d.size * 0.9:
            return True
        same = tot = 0
        prev = 0
        for ra in rs:
            o = ra - d.addr
            if o > prev:
                x, y = enr[a + prev:a + o], jp[b + prev:b + o]
                tot += len(x)
                same += sum(1 for i in range(len(x)) if x[i] == y[i])
            prev = o + 4
        return tot == 0 or same >= 0.5 * tot

    resolve("pool")
    log("data from code pools: %d" % len(dmap))
    def content_search():
        """Unmapped data without pointers (graphics, tables) found byte for byte, once, in the JP ROM."""
        added = 0
        for di, d in enumerate(data):
            if di in dmap or d.kind != "data" or d.size < 32 or drelocs(d) or text_len(d):
                continue
            b = enr[d.addr - ROM:d.addr - ROM + d.size]
            if len(set(b)) < 4:
                continue  # runs of one value are everywhere
            k = jp.find(b)
            if k < 0 or jp.find(b, k + 1) >= 0:
                continue
            added += put(di, k + ROM, 1.0, "content")
        return added

    content_done = False
    for rnd in range(60):
        before = len(dmap)
        propagate()
        resolve("data-ptr")
        g = 0
        while True:
            g1 = gap_walks()
            g += g1
            if not g1:
                break
        o = edge_order()
        g += span_fill()
        log("data round %d: +%d (gap %d, order %d), total %d" % (rnd, len(dmap) - before, g, o, len(dmap)))
        if len(dmap) == before:
            if content_done:
                break
            content_done = True
            c = content_search()
            log("data by content: +%d" % c)
            if not c:
                break

    # Confidence = precision of the method on the validation points (texts, graphics, Easy Chat
    # lists of tools/locales: bin/validate.py), times the vote share for voted symbols.
    for di, (w, cf, meth) in list(dmap.items()):
        base = CALIBRATION.get(meth.split(":")[0] + (":" + meth.split(":")[1][:2] if ":" in meth else ""),
                               CALIBRATION.get(meth, 0.8))
        if meth.startswith("data-gap:bw"):
            meth = "data-gap:back"
        if meth in ("data-gap:span", "ram-span") and same_data(data[di], w):
            base = 0.97
        dmap[di] = (w, round(base * shares.get(di, 1.0), 3), meth)

    # JP sizes and status
    dsizes, dstatus = {}, {}
    order = sorted(dmap)
    for k, di in enumerate(order):
        d = data[di]
        w = dmap[di][0]
        nxt = order[k + 1] if k + 1 < len(order) else None
        span_en = span_jp = None
        if nxt == di + 1 and data[nxt].kind == d.kind and dmap[nxt][0] > w:
            span_en = data[nxt].addr - d.addr
            span_jp = dmap[nxt][0] - w
            if span_jp > 4 * span_en + 0x10000:
                span_jp = None
        ln = text_len(d)
        js = None
        if ln:
            e = jp_end(di)
            if e:
                js = e - w + (d.size - ln)
        elif span_jp is not None:
            js = span_jp - (span_en - d.size)
        if d.kind == "data":
            ident = same_data(d, w) and (span_jp is None or span_jp == span_en)
        else:
            ident = span_jp is not None and span_jp == span_en
        if ident:
            js = d.size
        dstatus[di] = "identical" if ident else "changed"
        if js is not None and js >= 0:
            dsizes[di] = js
    return dmap, dsizes, dstatus, fvotes
