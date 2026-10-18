"""Normalised function bodies: stable byte segments plus relocation checks, and a heuristic
Thumb tokeniser used for fuzzy comparison (same rules on both ROMs)."""
from common import (ROM, R_ARM_ABS32, R_ARM_REL32, R_ARM_THM_CALL, R_ARM_PC24, R_ARM_CALL,
                    R_ARM_JUMP24, R_ARM_THM_JUMP11, R_ARM_THM_JUMP8, R_ARM_ABS8, R_ARM_ABS16,
                    ptr_class, u16, u32, is_bl)


def normalise(f, en):
    """Fill f.segs [(off, bytes)], f.checks [(off, kind, cls)], f.longest, f.key, f.relocs."""
    rom, relocs, fstarts = en["rom"], en["relocs"], en["func_starts"]
    base = f.addr - ROM
    body = bytearray(rom[base:base + f.size])
    mask = bytearray(f.size)
    checks = []
    frelocs = []
    for o in range(0, f.size):
        r = relocs.get(f.addr + o)
        if r is None:
            continue
        rtype, sym = r
        if rtype in (R_ARM_ABS32, R_ARM_REL32):
            if o + 4 > f.size:
                continue
            v = u32(rom, base + o)
            cls = ptr_class(v) if rtype == R_ARM_ABS32 else "P"
            if cls == "R" and (v & 1) and (v & ~1) in fstarts:
                cls = "F"
            if cls is None:
                continue  # an absolute constant symbol: compared exactly
            for k in range(4):
                mask[o + k] = 1
            checks.append((o, "W", cls))
            frelocs.append((o, "W", v))
        elif rtype == R_ARM_THM_CALL:
            for k in range(4):
                mask[o + k] = 1
            checks.append((o, "BL", None))
            frelocs.append((o, "BL", None))
        elif rtype in (R_ARM_PC24, R_ARM_CALL, R_ARM_JUMP24):
            for k in range(3):
                mask[o + k] = 1
            checks.append((o, "AB", rom[base + o + 3]))
            frelocs.append((o, "AB", None))
        elif rtype in (R_ARM_THM_JUMP11, R_ARM_THM_JUMP8):
            # branch out of the function (to another one): mask the offset
            h = u16(rom, base + o)
            mask[o] = 1
            if rtype == R_ARM_THM_JUMP11:
                mask[o + 1] = 1
                checks.append((o, "J11", None))
            else:
                checks.append((o, "J8", h >> 8))
        elif rtype in (R_ARM_ABS8, R_ARM_ABS16):
            pass
    segs = []
    o = 0
    while o < f.size:
        if mask[o]:
            o += 1
            continue
        s = o
        while o < f.size and not mask[o]:
            o += 1
        segs.append((s, bytes(body[s:o])))
    f.segs = segs
    f.checks = checks
    f.relocs = frelocs
    f.longest = max(segs, key=lambda t: len(t[1])) if segs else None
    for o in range(f.size):
        if mask[o]:
            body[o] = 0
    f.key = (bytes(body), tuple((c[0], c[1], c[2]) for c in checks))


def verify(f, jp, a):
    """Does EN function f match the JP ROM at address a exactly (up to relocations)?"""
    base = a - ROM
    if base < 0 or base + f.size > len(jp):
        return False
    for off, seg in f.segs:
        if jp[base + off:base + off + len(seg)] != seg:
            return False
    for off, kind, cls in f.checks:
        if kind == "W":
            v = u32(jp, base + off)
            c = ptr_class(v)
            if cls == "F":
                if c != "R" or not (v & 1):
                    return False
            elif cls == "P":
                pass
            elif c != cls:
                return False
        elif kind == "BL":
            if not is_bl(jp, a + off):
                return False
        elif kind == "AB":
            if jp[base + off + 3] != cls:
                return False
        elif kind == "J11":
            if (u16(jp, base + off) & 0xF800) != 0xE000:
                return False
        elif kind == "J8":
            if jp[base + off + 1] != cls:
                return False
    return True


# ---- heuristic tokeniser -------------------------------------------------------------------

T_BL = 1 << 20
T_W = 2 << 20      # + class code
T_CONST = 1 << 40  # + value
CLS_CODE = {"E": 1, "I": 2, "R": 3, "F": 4}


def tokenise(rom, start, end, thumb=True):
    """[(token, addr, extra)] of ROM range [start, end): BL pairs (extra = target), literal pool
    words (extra = value), other halfwords with branch/literal offsets dropped."""
    out = []
    if not thumb:
        for a in range(start, end - 3, 4):
            w = u32(rom, a - ROM)
            if (w & 0x0E000000) == 0x0A000000:  # ARM B/BL
                out.append(((w >> 24) | 0x100000000, a, None))
            elif ptr_class(w):
                out.append((T_W + CLS_CODE[ptr_class(w)], a, w))
            else:
                out.append((w | T_CONST, a, None))
        return out
    pool = set()
    tables = set()
    a = start
    while a + 2 <= end:
        if a in pool:
            v = u32(rom, a - ROM)
            if start <= v < end and not (v & 1) and a + 4 <= end:
                # pointer into the function: a jump table
                t = v
                while t + 4 <= end and t not in pool:
                    w = u32(rom, t - ROM)
                    if not (start <= w < end):
                        break
                    tables.add(t)
                    t += 4
            c = ptr_class(v)
            tok = T_W + CLS_CODE[c] if c else (v | T_CONST)
            if c == "R" and (v & 1):
                tok = T_W + CLS_CODE["F"]
            out.append((tok, a, v))
            a += 4
            continue
        if a in tables:
            out.append((T_W + 5, a, u32(rom, a - ROM)))
            a += 4
            continue
        h = u16(rom, a - ROM)
        if (h & 0xF800) == 0xF000 and a + 4 <= end:
            h2 = u16(rom, a - ROM + 2)
            if (h2 & 0xF800) == 0xF800:
                off = ((h & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
                if off & 0x400000:
                    off -= 0x800000
                out.append((T_BL, a, a + 4 + off))
                a += 4
                continue
        if (h & 0xF800) == 0x4800:  # ldr rX, [pc, #imm]: extra = the loaded word
            t = ((a + 4) & ~3) + (h & 0xFF) * 4
            if a < t and t + 4 <= end:
                pool.add(t)
                v = u32(rom, t - ROM)
                c = ptr_class(v)
                # the token keeps what is loaded (pointer class or constant), not the register
                out.append((0x4800 + (CLS_CODE[c] if c else 0) * 0x100 + (0 if c else 0x80), a, v))
            else:
                out.append((h & 0xFF00, a, None))
        elif (h & 0xF000) == 0xD000 and (h & 0x0F00) < 0x0E00:  # b<cond>
            out.append((h & 0xFF00, a, None))
        elif (h & 0xF800) == 0xE000:  # b
            out.append((0xE000, a, None))
        elif (h & 0xF800) == 0xA000:  # adr
            out.append((h & 0xFF00, a, None))
        else:
            out.append((h, a, None))
        a += 2
    return out


def func_extent(rom, start, limit):
    """End of the Thumb function at start (agbcc code): the first terminal instruction that no
    earlier branch jumps past, plus the literal pool and jump tables after it. limit bounds it."""
    pool = set()
    maxref = start
    pool_end = start
    a = start
    while a + 2 <= limit:
        if a in pool:
            a += 4
            continue
        h = u16(rom, a - ROM)
        size = 2
        term = False
        if (h & 0xF800) == 0xF000 and a + 4 <= limit and (u16(rom, a - ROM + 2) & 0xF800) == 0xF800:
            size = 4
        elif (h & 0xF800) == 0x4800:
            t = ((a + 4) & ~3) + (h & 0xFF) * 4
            if t + 4 <= limit:
                pool.add(t)
                pool_end = max(pool_end, t + 4)
                v = u32(rom, t - ROM)
                if start <= v < limit and not (v & 1):  # jump table address
                    tt = v
                    while tt + 4 <= limit:
                        w = u32(rom, tt - ROM)
                        if not (start <= w < limit) or (w & 1):
                            break
                        pool.add(tt)
                        maxref = max(maxref, w + 2)
                        tt += 4
                    pool_end = max(pool_end, tt)
        elif (h & 0xF000) == 0xD000 and (h & 0x0F00) < 0x0E00:
            off = h & 0xFF
            if off & 0x80:
                off -= 0x100
            maxref = max(maxref, a + 4 + off * 2 + 2)
        elif (h & 0xF800) == 0xE000:
            off = h & 0x7FF
            if off & 0x400:
                off -= 0x800
            maxref = max(maxref, a + 4 + off * 2 + 2)
            term = True
        elif (h & 0xFF00) == 0xBD00:      # pop {..., pc}
            term = True
        elif (h & 0xFF87) == 0x4700:      # bx rX
            term = True
        elif (h & 0xFF87) == 0x4687:      # mov pc, rX
            term = True
        a += size
        if term and a >= maxref:
            end = max(a, pool_end)
            # pool words placed after this point (referenced later) are already in pool_end;
            # skip one alignment halfword before a pool
            if end == a and (a & 3) == 2 and a + 2 <= limit and u16(rom, a - ROM) == 0 and (a + 2) in pool:
                end = a + 2
            # a pool directly following the code
            while end + 4 <= limit and end in pool:
                end += 4
            if end >= maxref:
                return end
    return limit
