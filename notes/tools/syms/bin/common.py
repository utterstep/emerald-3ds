"""Shared loading code for the EN<->JP symbol matcher.

EN side: the vanilla agbcc build of the pinned pokeemerald (en.gba), its ELF relinked with
--emit-relocs (en_relocs.elf, identical layout) and its .map.
JP side: the Japanese cartridge dump (no symbols).
"""
import bisect
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = os.path.dirname(HERE)
S = os.path.dirname(os.path.dirname(SYMS))
sys.path.insert(0, HERE)
import elf32  # noqa: E402

EN_ROM = os.path.join(SYMS, "en.gba")
EN_ELF = os.path.join(SYMS, "en_relocs.elf")
EN_MAP = os.path.join(SYMS, "en.map")
JP_ROM = os.path.join(S, "rom", "bpej.gba")
ROM = 0x08000000

R_ARM_ABS32, R_ARM_REL32, R_ARM_THM_CALL, R_ARM_PC24, R_ARM_CALL, R_ARM_JUMP24 = 2, 3, 10, 1, 28, 29
R_ARM_V4BX, R_ARM_THM_JUMP11, R_ARM_THM_JUMP8, R_ARM_ABS8, R_ARM_ABS16 = 40, 102, 103, 8, 5

CODE_SECTIONS = (".text", "lib_text")


def ptr_class(v):
    """Coarse class of a 32-bit word: E (EWRAM), I (IWRAM), R (ROM), or None (a constant)."""
    if 0x02000000 <= v < 0x02040000:
        return "E"
    if 0x03000000 <= v < 0x03008000:
        return "I"
    if 0x08000000 <= v < 0x0A000000:
        return "R"
    return None


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def u32(b, o):
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)


def bl_target(b, addr):
    """Target of the Thumb BL pair at ROM address addr in image b, or None."""
    o = addr - ROM
    h1, h2 = u16(b, o), u16(b, o + 2)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    off = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if off & 0x400000:
        off -= 0x800000
    return addr + 4 + off


def is_bl(b, addr):
    o = addr - ROM
    return (u16(b, o) & 0xF800) == 0xF000 and (u16(b, o + 2) & 0xF800) == 0xF800


def arm_b_target(b, addr):
    o = addr - ROM
    w = u32(b, o)
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    return addr + 8 + off * 4


class Func:
    __slots__ = ("name", "aliases", "addr", "size", "thumb", "obj", "section", "idx",
                 "segs", "checks", "longest", "key", "relocs")


class Data:
    __slots__ = ("name", "aliases", "addr", "size", "kind", "obj", "section", "idx", "sized")


def parse_map(path):
    """[(section, start, size, object)] for every input section with a nonzero size."""
    out = []
    lines = open(path, encoding="latin-1").read().split("\n")
    try:
        i0 = next(i for i, l in enumerate(lines) if l.startswith("Linker script and memory map"))
    except StopIteration:
        i0 = 0
    rx = re.compile(r"^ (\S+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$")
    rx2 = re.compile(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$")
    pending = None
    for l in lines[i0:]:
        m = rx.match(l)
        if m:
            sec, a, sz, obj = m.group(1), int(m.group(2), 16), int(m.group(3), 16), m.group(4).strip()
            pending = None
        else:
            if pending:
                m2 = rx2.match(l)
                pending_sec = pending
                pending = None
                if m2:
                    sec, a, sz, obj = pending_sec, int(m2.group(1), 16), int(m2.group(2), 16), m2.group(3).strip()
                else:
                    continue
            else:
                if re.match(r"^ (\.\S+|\S+_data|\S+_text|COMMON)$", l):
                    pending = l.strip()
                continue
        if sz and a and sec != "*fill*":
            out.append((sec, a, sz, obj))
    out.sort(key=lambda t: t[1])
    return out


class ObjIndex:
    """Address -> (section, object) lookups from the map."""

    def __init__(self, ranges):
        self.ranges = [r for r in ranges if r[0] != "*fill*"]
        self.starts = [r[1] for r in self.ranges]

    def find(self, addr):
        i = bisect.bisect_right(self.starts, addr) - 1
        if i >= 0:
            sec, a, sz, obj = self.ranges[i]
            if a <= addr < a + sz:
                return sec, obj
        return None, None


def source_of(obj):
    """'src/foo.o' -> 'src/foo.c' (or .s); library members unchanged."""
    if obj is None:
        return "?"
    o = obj
    if "(" in o:  # libgcc.a(_udivsi3.o)
        return os.path.basename(o)
    o = re.sub(r"^.*?build/emerald/", "", o)
    base = o[:-2] if o.endswith(".o") else o
    for ext in (".c", ".s"):
        if os.path.exists(os.path.join(SYMS, "pokeemerald", base + ext)):
            return base + ext
    return o


def load_en():
    """Functions, data symbols, relocations and the object index of the EN build."""
    e = elf32.Elf(EN_ELF)
    rom = open(EN_ROM, "rb").read()
    oi = ObjIndex(parse_map(EN_MAP))
    sec_by_name = {s.name: s for s in e.sections}
    rom_secs = [s for s in e.sections if s.addr >= ROM and s.size and s.type == 1]
    ram_secs = [s for s in e.sections if s.addr < ROM and s.addr and s.size]

    # Relocations keyed by final address (ROM sections only).
    relocs = {}
    for target, off, rtype, sym in e.relocations():
        if target.startswith(".debug") or rtype == R_ARM_V4BX:
            continue
        relocs[off] = (rtype, sym)

    # Mapping symbols ($t/$a/$d) in ROM.
    mapsyms = sorted((s.value, s.name[:2]) for s in e.symbols
                     if s.name[:2] in ("$t", "$a", "$d") and s.value >= ROM)

    # Functions.
    byaddr = {}
    for s in e.symbols:
        if s.type == elf32.STT_FUNC and s.value >= ROM:
            a = s.value & ~1
            byaddr.setdefault(a, []).append(s)
    funcs = []
    for a in sorted(byaddr):
        ss = sorted(byaddr[a], key=lambda s: (s.bind != 1, -s.size, s.name))
        f = Func()
        f.name = ss[0].name
        f.aliases = [x.name for x in ss[1:] if x.name != ss[0].name]
        f.addr = a
        f.size = max(x.size for x in ss)
        f.thumb = bool(ss[0].value & 1)
        f.section, f.obj = oi.find(a)
        funcs.append(f)
    # Sizes of 0 or overlapping: up to the next function.
    for i, f in enumerate(funcs):
        nxt = funcs[i + 1].addr if i + 1 < len(funcs) else None
        if f.size == 0 and nxt:
            f.size = nxt - f.addr
        if nxt and f.addr + f.size > nxt:
            f.size = nxt - f.addr
        f.idx = i
    func_starts = {f.addr: f for f in funcs}

    # Data symbols (ROM data and RAM), excluding code labels inside functions.
    fstarts = [f.addr for f in funcs]

    def in_func(a):
        i = bisect.bisect_right(fstarts, a) - 1
        return i >= 0 and funcs[i].addr <= a < funcs[i].addr + funcs[i].size

    dby = {}
    for s in e.symbols:
        if s.type not in (elf32.STT_OBJECT, elf32.STT_NOTYPE) or not s.name or s.name[0] in "$.":
            continue
        if s.shndx == 0 or s.shndx >= 0xff00:
            continue
        sec = e.sections[s.shndx]
        if not (sec.addr and sec.size) or sec.name.startswith(".debug"):
            continue
        v = s.value
        if v >= ROM and in_func(v):
            continue
        dby.setdefault(v, []).append(s)
    data = []
    for a in sorted(dby):
        ss = sorted(dby[a], key=lambda s: (s.type != elf32.STT_OBJECT, s.bind != 1, -s.size, s.name))
        d = Data()
        d.name = ss[0].name
        d.aliases = sorted({x.name for x in ss[1:]} - {d.name})
        d.addr = a
        d.size = max(x.size for x in ss)
        d.sized = d.size > 0
        d.kind = "ram" if a < ROM else "data"
        d.section, d.obj = oi.find(a)
        if d.section is None:
            d.section = e.sections[ss[0].shndx].name
        data.append(d)
    # Unsized symbols run to the next symbol or the end of their input section.
    allstarts = sorted(set([d.addr for d in data] + fstarts))
    for i, d in enumerate(data):
        if not d.size:
            j = bisect.bisect_right(allstarts, d.addr)
            nxt = allstarts[j] if j < len(allstarts) else d.addr + 4
            # bound by the object's section
            idx = bisect.bisect_right(oi.starts, d.addr) - 1
            if idx >= 0:
                sec, sa, ssz, obj = oi.ranges[idx]
                if sa <= d.addr < sa + ssz:
                    nxt = min(nxt, sa + ssz)
            d.size = max(nxt - d.addr, 0)
        d.idx = i
    return dict(elf=e, rom=rom, oi=oi, relocs=relocs, mapsyms=mapsyms, funcs=funcs,
                func_starts=func_starts, data=data, rom_secs=rom_secs, ram_secs=ram_secs)


def load_jp():
    return open(JP_ROM, "rb").read()
