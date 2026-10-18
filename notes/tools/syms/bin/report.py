#!/usr/bin/env python3
"""DIFFERENCES.md from state.pkl: per source file, the functions that differ, the EN functions
with no JP counterpart, the JP code with no EN counterpart, and the data that differs."""
import bisect
import collections
import difflib
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import norm  # noqa: E402
from common import ROM  # noqa: E402

RELEVANT = {
    "naming_screen": ["src/naming_screen.c", "src/text_input_strings.c"],
    "union_room_chat": ["src/union_room_chat.c", "src/union_room_chat_display.c", "src/union_room_chat_objects.c"],
    "easy_chat": ["src/easy_chat.c"],
    "summary screen": ["src/pokemon_summary_screen.c"],
    "pokedex": ["src/pokedex.c", "src/pokedex_area_screen.c", "src/pokedex_area_region_map.c", "src/pokedex_cry_screen.c"],
    "pokenav condition / pokeblock feed": ["src/pokenav_conditions.c", "src/pokenav_conditions_gfx.c",
                                           "src/pokenav_conditions_search_results.c", "src/menu_specialized.c",
                                           "src/pokeblock_feed.c", "src/use_pokeblock.c", "src/pokeblock.c"],
    "berry tag": ["src/item_menu.c", "src/berry_tag_screen.c", "src/berry.c"],
    "slot machine": ["src/slot_machine.c"],
    "trainer hill": ["src/trainer_hill.c"],
    "bard": ["src/bard_music.c", "src/mauville_old_man.c"],
    "credits": ["src/credits.c"],
    "walda phrase": ["src/walda_phrase.c"],
    "title screen": ["src/title_screen.c"],
    "contest": ["src/contest.c", "src/contest_util.c", "src/contest_painting.c", "src/contest_ai.c",
                "src/contest_link.c", "src/contest_link_util.c", "src/contest_effect.c"],
    "frontier tourney": ["src/battle_dome.c"],
}
REL_OF = {f: k for k, fs in RELEVANT.items() for f in fs}


def main():
    st = pickle.load(open(os.path.join(common.SYMS, "state.pkl"), "rb"))
    en = common.load_en()
    enr = en["rom"]
    jp = common.load_jp()
    F = st["funcs"]
    n = len(F)
    jaddr, status, jsz, sim = st["jaddr"], st["status"], st["jp_size"], st["sim"]
    D = st["data"]
    dmap, dsizes, dstatus = st["dmap"], st["dsizes"], st["dstatus"]

    # name lookups
    en_func = {F[i][2]: F[i][0] for i in range(n)}
    jp_func = {jaddr[i]: F[i][0] for i in range(n) if jaddr[i] is not None}
    en_d = sorted((d[2], d[3], d[0]) for d in D)
    en_ds = [x[0] for x in en_d]
    def jp_dsize(k):
        en_sz, js = D[k][3], dsizes.get(k)
        if dstatus.get(k) == "identical":
            return en_sz
        if js is None:
            return 1
        return min(js, max(2 * en_sz, en_sz + 32))  # a span can include JP-only data
    jp_d = sorted((dmap[k][0], jp_dsize(k), D[k][0]) for k in dmap)
    jp_ds = [x[0] for x in jp_d]

    def dname(tab, starts, v):
        k = bisect.bisect_right(starts, v) - 1
        if k >= 0 and tab[k][0] <= v < tab[k][0] + max(tab[k][1], 1):
            return tab[k][2]
        return None

    def en_name(v):
        if v & 1 and (v & ~1) in en_func:
            return en_func[v & ~1]
        return dname(en_d, en_ds, v)

    def jp_name(v):
        if v & 1 and (v & ~1) in jp_func:
            return jp_func[v & ~1]
        return dname(jp_d, jp_ds, v)

    def refs(rom, start, end, thumb, side):
        toks = norm.tokenise(rom, start, end, thumb)
        calls, datas = collections.Counter(), collections.Counter()
        for tok, a, x in toks:
            if x is None:
                continue
            if tok == norm.T_BL:
                nm = (en_func if side == "en" else jp_func).get(x)
                calls[nm or "%s:%#x" % (side.upper(), x)] += 1
            elif 0x4800 <= tok <= 0x4FFF and common.ptr_class(x):
                nm = en_name(x) if side == "en" else jp_name(x)
                if nm is None:
                    if (side == "en" and start <= x < end) or (side == "jp" and start <= x < end):
                        continue
                    nm = "%s:%#x" % (side.upper(), x)
                datas[nm] += 1
        return toks, calls, datas

    files = collections.defaultdict(lambda: {"changed": [], "enonly": [], "jponly": [], "ident": 0,
                                             "dchanged": [], "dunmatched": [], "dident": 0})
    for i in range(n):
        name, aliases, addr, size, thumb, src = F[i]
        fe = files[src]
        if status[i] == "identical":
            fe["ident"] += 1
        elif status[i] == "changed":
            ja, js = jaddr[i], jsz[i]
            ta, ce, de = refs(enr, addr, addr + size, thumb, "en")
            tb, cj, dj = refs(jp, ja, ja + js, thumb, "jp")
            sm = difflib.SequenceMatcher(None, [t[0] for t in ta], [t[0] for t in tb], autojunk=False)
            ins = dele = rep = 0
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "insert":
                    ins += j2 - j1
                elif op == "delete":
                    dele += i2 - i1
                elif op == "replace":
                    rep += max(i2 - i1, j2 - j1)
            fe["changed"].append(dict(name=name, en=addr, ja=ja, size=size, js=js, sim=sim.get(i, 0),
                                      ins=ins, dele=dele, rep=rep, conf=st["conf"][i], meth=st["method"][i],
                                      calls_add=sorted(set(cj) - set(ce)), calls_del=sorted(set(ce) - set(cj)),
                                      data_add=sorted(set(dj) - set(de)), data_del=sorted(set(de) - set(dj))))
        else:
            fe["enonly"].append(dict(name=name, en=addr, size=size))

    # JP-only code: gaps between mapped functions inside the JP code regions
    secs = {s.name: (s.addr, s.addr + s.size) for s in en["rom_secs"]}
    rng = sorted((jaddr[i], jaddr[i] + jsz[i], i) for i in range(n) if jaddr[i] is not None)
    text_fns = [r for r in rng if F[r[2]][2] < secs[".text"][1]]
    lib_fns = [r for r in rng if secs["lib_text"][0] <= F[r[2]][2] < secs["lib_text"][1]]
    regions = [(ROM, max(r[1] for r in text_fns)), (min(r[0] for r in lib_fns), max(r[1] for r in lib_fns))]
    jponly_total = 0
    for lo, hi in regions:
        inr = [r for r in rng if lo <= r[0] < hi]
        for (a, b, i), (c, d, j) in zip(inr, inr[1:]):
            if c <= b:
                continue
            g = jp[b - ROM:c - ROM]
            if not g.strip(b"\0"):
                continue
            s = b
            while s < c and jp[s - ROM:s - ROM + 2] == b"\0\0":
                s += 2
            segs = []
            while s < c and len(segs) < 50:
                e = norm.func_extent(jp, s, c)
                if e <= s:
                    break
                segs.append((s, e))
                s = e
                while s < c and jp[s - ROM:s - ROM + 2] == b"\0\0":
                    s += 2
            src_i, src_j = F[i][5], F[j][5]
            # the EN functions without a counterpart between the two neighbours own this code
            between_en = collections.Counter(F[k][5] for k in range(i + 1, j) if status[k] is None) if i < j else None
            owner = between_en.most_common(1)[0][0] if between_en else src_i
            for s, e in segs:
                toks, cj, dj = refs(jp, s, e, True, "jp")
                jponly_total += e - s
                ent = dict(start=s, end=e, after=F[i][0], before=F[j][0], calls=sorted(cj), data=sorted(dj),
                           between=None if src_i == src_j else (src_i, src_j))
                files[owner]["jponly"].append(ent)

    # data
    for k, d in enumerate(D):
        name, aliases, addr, size, kind, src = d
        fe = files[src]
        if k in dmap:
            if dstatus.get(k) == "identical":
                fe["dident"] += 1
            else:
                fe["dchanged"].append((name, kind, addr, size, dmap[k][0], dsizes.get(k), is_text(enr, kind, addr, size)))
        else:
            fe["dunmatched"].append((name, kind, addr, size, is_text(enr, kind, addr, size)))

    out = []
    w = out.append
    nf_i = sum(1 for s in status if s == "identical")
    nf_c = sum(1 for s in status if s == "changed")
    nf_u = sum(1 for s in status if s is None)
    w("# Japanese ROM (BPEJ) vs the English build: differences by source file\n")
    w("Generated by `bin/report.py` from `jp_syms.tsv` (see README.md for the method). "
      "Sizes in bytes; *sim* is the instruction-token similarity of a changed function "
      "(1.0 = same instructions, other constants/offsets); *instr* counts tokens "
      "(≈ instructions) +inserted/-deleted/~replaced in JP. Call and data lists name the EN "
      "symbol whose JP counterpart is referenced; `JP:0x…` is a JP address no EN symbol maps to "
      "(JP-only code or data), `EN:0x…` an unnamed EN object (a function-local static). JP-only code is "
      "JP code between two mapped functions that no EN function matches, cut into functions; it "
      "is listed under the file of the EN function before it. ★ marks the files of the open "
      "Japanese gaps.\n")
    w("Totals: %d EN functions: %d identical, %d changed, %d with no JP counterpart; "
      "%d bytes of JP-only code.\n" % (n, nf_i, nf_c, nf_u, jponly_total))
    w("Data sizes read EN size→JP span (up to the JP address of the next mapped symbol, so a span "
      "can include JP-only data after it; `?` when the next symbol is unmapped).\n")
    w("Inspect any entry with `./jpdis.sh NAME --side` (or `--jp-range START END` for JP-only code).\n")

    def row(src):
        fe = files[src]
        jpo = sum(x["end"] - x["start"] for x in fe["jponly"])
        dch = sum(1 for x in fe["dchanged"] if not x[6])
        dun = sum(1 for x in fe["dunmatched"] if not x[4])
        return "| %s%s | %d | %d | %d | %s | %d | %d |" % (
            src, " ★" if src in REL_OF else "", fe["ident"], len(fe["changed"]), len(fe["enonly"]),
            "%d B (%d)" % (jpo, len(fe["jponly"])) if fe["jponly"] else "", dch, dun)

    head = ("| file | identical | changed | EN only | JP-only code | data changed* | data unmatched* |\n"
            "|---|---|---|---|---|---|---|")
    hl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highlights.md")
    if os.path.exists(hl):
        w("\n" + open(hl).read().rstrip())
    w("\n## Files of the open Japanese gaps\n")
    w("*Data columns leave out strings (text symbols are listed per file below).*\n")
    w(head)
    for k, fs in RELEVANT.items():
        for f in fs:
            if f in files:
                w(row(f).replace("| " + f, "| %s: %s" % (k, f), 1))
    w("\n## All files with code differences\n")
    w(head)
    keyf = lambda s: -(len(files[s]["changed"]) + len(files[s]["enonly"]) * 2 + len(files[s]["jponly"]) * 2)
    diff_files = [s for s in files if files[s]["changed"] or files[s]["enonly"] or files[s]["jponly"]]
    for s in sorted(diff_files, key=lambda s: (keyf(s), s)):
        w(row(s))

    w("\n## Details\n")
    order = [f for fs in RELEVANT.values() for f in fs if f in files] + \
        sorted(s for s in diff_files if s not in REL_OF)
    seen = set()
    for src in order:
        if src in seen:
            continue
        seen.add(src)
        fe = files[src]
        if not (fe["changed"] or fe["enonly"] or fe["jponly"] or fe["dchanged"] or fe["dunmatched"]):
            continue
        w("\n### %s%s\n" % (src, " ★ (%s)" % REL_OF[src] if src in REL_OF else ""))
        w("%d identical, %d changed, %d EN-only functions; %d JP-only code blocks.\n" % (
            fe["ident"], len(fe["changed"]), len(fe["enonly"]), len(fe["jponly"])))
        if fe["changed"]:
            w("Changed functions:\n")
            for c in sorted(fe["changed"], key=lambda c: c["en"]):
                bits = []
                if c["calls_add"]:
                    bits.append("calls +" + ", +".join(c["calls_add"][:6]) + (" …" if len(c["calls_add"]) > 6 else ""))
                if c["calls_del"]:
                    bits.append("calls -" + ", -".join(c["calls_del"][:6]) + (" …" if len(c["calls_del"]) > 6 else ""))
                if c["data_add"]:
                    bits.append("data +" + ", +".join(c["data_add"][:6]) + (" …" if len(c["data_add"]) > 6 else ""))
                if c["data_del"]:
                    bits.append("data -" + ", -".join(c["data_del"][:6]) + (" …" if len(c["data_del"]) > 6 else ""))
                low = " (low confidence %.2f, %s)" % (c["conf"], c["meth"]) if c["conf"] < 0.7 else ""
                if not (c["ins"] or c["dele"] or c["rep"]):
                    low += " (same instructions: constants/offsets differ)"
                w("- `%s` %d → %d, sim %.2f, instr +%d/-%d/~%d, JP %#x%s%s" % (
                    c["name"], c["size"], c["js"], c["sim"], c["ins"], c["dele"], c["rep"], c["ja"], low,
                    ("; " + "; ".join(bits)) if bits else ""))
        if fe["enonly"]:
            w("\nEN functions with no JP counterpart:\n")
            w(", ".join("`%s` (%d)" % (x["name"], x["size"]) for x in fe["enonly"]))
        if fe["jponly"]:
            w("\nJP-only code:\n")
            for x in fe["jponly"]:
                pos = "after `%s`" % x["after"]
                if x["between"]:
                    pos += " (before `%s`, %s)" % (x["before"], x["between"][1])
                bits = []
                if x["calls"]:
                    bits.append("calls " + ", ".join(x["calls"][:8]) + (" …" if len(x["calls"]) > 8 else ""))
                if x["data"]:
                    bits.append("data " + ", ".join(x["data"][:8]) + (" …" if len(x["data"]) > 8 else ""))
                w("- %#x–%#x (%d B) %s%s" % (x["start"], x["end"], x["end"] - x["start"], pos,
                                             ("; " + "; ".join(bits)) if bits else ""))
        nt_ch = [x for x in fe["dchanged"] if not x[6]]
        t_ch = [x for x in fe["dchanged"] if x[6]]
        nt_un = [x for x in fe["dunmatched"] if not x[4]]
        t_un = [x for x in fe["dunmatched"] if x[4]]
        if nt_ch or nt_un or t_ch or t_un:
            w("\nData: %d identical, %d changed (%d strings), %d unmatched (%d strings).\n" % (
                fe["dident"], len(fe["dchanged"]), len(t_ch), len(fe["dunmatched"]), len(t_un)))
            if nt_ch:
                w("Changed (non-string): " + ", ".join(
                    "`%s` %d→%s" % (x[0], x[3], x[5] if x[5] is not None else "?") for x in nt_ch[:25])
                  + (" …" if len(nt_ch) > 25 else ""))
            if nt_un:
                w("\nUnmatched (non-string): " + ", ".join("`%s` (%d)" % (x[0], x[3]) for x in nt_un[:25])
                  + (" …" if len(nt_un) > 25 else ""))
    open(os.path.join(common.SYMS, "DIFFERENCES.md"), "w").write("\n".join(out) + "\n")
    print("functions", nf_i, nf_c, nf_u, "jp-only bytes", jponly_total)


def is_text(enr, kind, addr, size):
    if kind != "data" or not (1 <= size <= 4096):
        return False
    b = enr[addr - ROM:addr - ROM + size]
    k = b.find(b"\xff")
    return k >= 0 and not b[k + 1:].strip(b"\0")


if __name__ == "__main__":
    main()
