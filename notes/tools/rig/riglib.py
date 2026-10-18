"""Shared helpers of the screen rig: symbols, mgbarig runs, montages.

Scratch only (never shipped). Used by make_saves.py and screens.py.
"""
import os
import re
import subprocess
from pathlib import Path

RIG = Path(__file__).resolve().parent
S = RIG.parent.parent
MGBARIG = RIG / "mgbarig"
JP_ROM = S / "rom" / "bpej.gba"
DEFAULT_BUILD = S / "gba" / "ja" / "pokeemerald_modern.gba"
JP_SYMS = S / "gba" / "syms" / "jp_syms.tsv"
# Addresses in the Japanese ROM found by hand, used until (and where) jp_syms.tsv
# has no entry: name -> address (functions with the Thumb bit).
JP_FALLBACK = RIG / "jp_fallback_syms.tsv"


def read_map(map_path):
    """Global symbols of a GNU ld map file: name -> address."""
    syms = {}
    pat = re.compile(r"^\s+0x([0-9a-f]{8,16})\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
    with open(map_path, errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if m:
                syms.setdefault(m.group(2), int(m.group(1), 16))
    return syms


def read_tsv(path):
    """A symbol table: name<TAB>address lines (hex), or $S/gba/syms/jp_syms.tsv's
    columns (symbol kind en_addr jp_addr ... status ...: the jp_addr column, rows
    whose status is unmatched left out)."""
    syms = {}
    if not Path(path).exists():
        return syms
    col, status_col = 1, None
    with open(path, errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if line.startswith("#") or not line.strip():
                continue
            if parts[0] == "symbol" and "jp_addr" in parts:
                col = parts.index("jp_addr")
                status_col = parts.index("status") if "status" in parts else None
                continue
            if len(parts) <= col:
                continue
            if status_col is not None and len(parts) > status_col and parts[status_col] == "unmatched":
                continue
            try:
                syms.setdefault(parts[0], int(parts[col], 16))
            except ValueError:
                continue
    return syms


def build_syms(gba_path):
    """The build's symbols, from the .map next to the .gba. Its C functions are
    Thumb code: poke them as {name|1}."""
    m = Path(gba_path).with_suffix(".map")
    if not m.exists():
        raise SystemExit("no map file %s" % m)
    syms = read_map(m)
    # Static functions and data are in the ELF's symbol table only.
    elf = Path(gba_path).with_suffix(".elf")
    if elf.exists():
        out = subprocess.run(["arm-none-eabi-nm", str(elf)], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in "tTdDbBrR" and not parts[2].startswith("$"):
                syms.setdefault(parts[2], int(parts[0], 16))
    return syms


def jp_syms():
    syms = read_tsv(JP_FALLBACK)
    syms.update(read_tsv(JP_SYMS))
    return syms


SYM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:([+-])(0x[0-9a-fA-F]+|\d+))?(\|1)?\}")


def resolve(text, syms):
    """Replace {name}, {name+off} and {name|1} (a function pointer with the Thumb
    bit) with hex addresses. Raises KeyError naming a missing symbol."""
    def sub(m):
        name, sign, off, tbit = m.groups()
        if name not in syms:
            raise KeyError(name)
        v = syms[name]
        if off:
            o = int(off, 0)
            v = v + o if sign == "+" else v - o
        if tbit:
            v |= 1
        return "%x" % v
    return SYM_RE.sub(sub, text)


def run_rig(rom, script, cwd=None, timeout=600):
    p = subprocess.run([str(MGBARIG), str(rom)], input=script, capture_output=True, text=True,
                       cwd=cwd, timeout=timeout)
    return p.stdout, p.stderr


def montage(out, files, cols, labels=None, scale=2):
    from PIL import Image, ImageDraw
    ims = []
    for f in files:
        if f and Path(f).exists():
            ims.append(Image.open(f).convert("RGB"))
        else:
            ims.append(None)
    w, h = 240 * scale, 160 * scale
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 4), rows * (h + 18)), "white")
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * (w + 4), (i // cols) * (h + 18)
        if im is not None:
            sheet.paste(im.resize((w, h), Image.NEAREST), (x, y + 16))
        else:
            d.rectangle([x, y + 16, x + w - 1, y + 16 + h - 1], fill="#ccc")
            d.text((x + 8, y + 24), "missing", fill="black")
        label = labels[i] if labels else (Path(files[i]).name if files[i] else "")
        d.text((x + 2, y + 2), label, fill="black")
    sheet.save(out)
