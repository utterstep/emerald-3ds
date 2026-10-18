#!/usr/bin/env python3
"""Disassemble a function of the EN build and its JP counterpart, with symbol names.

  dis.py SYMBOL [--en | --jp | --diff | --side] [--width N]
  dis.py --jp-range 0xSTART 0xEND      (any JP range, e.g. a gap of JP-only code)

Literal pools and jump tables print as .word (the code is re-assembled with .inst/.word so
objdump knows where data is). Addresses are replaced by names: EN ones by the EN symbols,
JP ones through jp_syms.tsv (an EN name means "the JP counterpart of"); unmapped JP addresses
stay numeric. --diff prints a unified diff of the two listings without addresses."""
import difflib
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import norm  # noqa: E402
import lookup  # noqa: E402

ROM = common.ROM


def listing(rom, start, end, thumb, namer):
    toks = norm.tokenise(rom, start, end, thumb)
    data_at = {}
    for tok, a, x in toks:
        if tok >= norm.T_W:
            data_at[a] = x if x is not None else common.u32(rom, a - ROM)
    lines = [".syntax unified", ".thumb" if thumb else ".arm", ".text"]
    a = start
    while a < end:
        if a in data_at and a + 4 <= end:
            lines.append(".word %#x" % common.u32(rom, a - ROM))
            a += 4
        elif thumb:
            if a + 2 > end:
                break
            lines.append(".inst.n %#x" % common.u16(rom, a - ROM))
            a += 2
        else:
            lines.append(".inst %#x" % common.u32(rom, a - ROM))
            a += 4
    with tempfile.TemporaryDirectory() as td:
        src, obj = os.path.join(td, "f.s"), os.path.join(td, "f.o")
        open(src, "w").write("\n".join(lines) + "\n")
        subprocess.run(["arm-none-eabi-as", "-mcpu=arm7tdmi", "-o", obj, src], check=True)
        out = subprocess.run(["arm-none-eabi-objdump", "-d", "--adjust-vma=%#x" % start, obj],
                             capture_output=True, text=True, check=True).stdout
    res = []
    rx = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{4,8} ?)+)\s+(.*)$")
    for l in out.splitlines():
        m = rx.match(l)
        if not m:
            continue
        addr = int(m.group(1), 16)
        ins = m.group(3).split("@")[0].rstrip()
        ins = re.sub(r"\s*<[^>]*>", "", ins)
        ins = ins.replace("\t", " ")
        if addr in data_at:
            v = common.u32(rom, addr - ROM)
            nm = namer(v & ~1 if (v & 1) and namer(v & ~1) else v)
            ins = ".word %#010x" % v + ("  ; %s" % nm if nm else "")
        else:
            mm = re.match(r"ldr\s+(r\d+), \[pc, #(\d+)\]", ins)
            if mm:
                t = ((addr + 4) & ~3) + int(mm.group(2))
                if start <= t + 4 <= end + 4 and t - ROM + 4 <= len(rom):
                    v = common.u32(rom, t - ROM)
                    nm = namer(v & ~1 if (v & 1) and namer(v & ~1) else v)
                    ins = "ldr %s, =%#x" % (mm.group(1), v) + ("  ; %s" % nm if nm else "")
            else:
                def rep(mo):
                    v = int(mo.group(0), 16)
                    if start <= v < end:
                        return "%s+%#x" % ("L", v - start)
                    nm = namer(v)
                    return nm or mo.group(0)
                ins = re.sub(r"0x8[0-9a-f]{6}\b", rep, ins)
                if re.match(r"(bl|b|b[a-z]{2})(\.[nw])?\s", ins):
                    ins = re.sub(r"(?<![#\w])8[0-9a-f]{6}\b", lambda mo: rep(re.match(r".*", "0x" + mo.group(0))), ins)
        res.append((addr, m.group(2).strip(), ins))
    return res


def key(ins, sym=None):
    """Comparison form of a listing line: a named value compares by its name only, and labels
    inside the function compare equal."""
    ins = re.sub(r"=0x[0-9a-f]+  ; (\S+)", r"=\1", ins)
    ins = re.sub(r"\bL\+0x[0-9a-f]+", "L", ins)
    if sym:
        ins = re.sub(re.escape(sym) + r"\+0x[0-9a-f]+", "L", ins)
    ins = re.sub(r"\.word 0x[0-9a-f]+  ; (\S+)", r".word \1", ins)
    return ins


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    rows = lookup.load()
    en_idx = lookup.Index(rows, 2)
    jp_idx = lookup.Index(rows, 3)
    enr = open(common.EN_ROM, "rb").read()
    jp = open(common.JP_ROM, "rb").read()
    width = 60
    if "--width" in args:
        k = args.index("--width")
        width = int(args[k + 1])
        del args[k:k + 2]
    if args[0] == "--jp-range":
        s, e = int(args[1], 16), int(args[2], 16)
        for a, b, ins in listing(jp, s, e, True, jp_idx.name):
            print("%08x  %-9s %s" % (a, b, ins))
        return 0
    sym = args[0]
    mode = args[1] if len(args) > 1 else "--both"
    r = [x for x in rows if x[0] == sym and x[1] == "func"]
    if not r:
        print("%s: not an EN function in jp_syms.tsv" % sym)
        return 1
    r = r[0]
    ea, es = int(r[2], 16), int(r[4])
    thumb = bool(ea & 1)
    ea &= ~1
    en_l = listing(enr, ea, ea + es, thumb, en_idx.name)
    jp_l = None
    hdr = "%s  [%s, %s]  EN %#x+%d" % (sym, r[6], r[10] if len(r) > 10 else r[9], ea, es)
    if r[3]:
        ja = int(r[3], 16) & ~1
        js = int(r[5] or r[4])
        jp_l = listing(jp, ja, ja + js, thumb, jp_idx.name)
        hdr += "  JP %#x+%d  conf %s (%s)" % (ja, js, r[7], r[8])
    print(hdr)
    if mode in ("--both", "--en"):
        print("---- EN")
        for a, b, ins in en_l:
            print("%08x  %-9s %s" % (a, b, ins))
    if jp_l is not None and mode in ("--both", "--jp"):
        print("---- JP")
        for a, b, ins in jp_l:
            print("%08x  %-9s %s" % (a, b, ins))
    if jp_l is not None and mode == "--diff":
        x = [key(i, sym) for _, _, i in en_l]
        y = [key(i, sym) for _, _, i in jp_l]
        for l in difflib.unified_diff(x, y, "EN " + sym, "JP " + sym, lineterm="", n=3):
            print(l)
    if jp_l is not None and mode == "--side":
        x = [key(i, sym) for _, _, i in en_l]
        y = [key(i, sym) for _, _, i in jp_l]
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            for k in range(max(i2 - i1, j2 - j1)):
                l = en_l[i1 + k] if i1 + k < i2 else None
                rr = jp_l[j1 + k] if j1 + k < j2 else None
                mark = " " if op == "equal" else "|" if (l and rr) else "<" if l else ">"
                ls = ("%08x %s" % (l[0], l[2]))[:width] if l else ""
                rs = ("%08x %s" % (rr[0], rr[2]))[:width] if rr else ""
                print("%-*s %s %s" % (width, ls, mark, rs))
    if jp_l is None:
        print("(no JP counterpart)")
    return 0


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
