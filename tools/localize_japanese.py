#!/usr/bin/env python3
"""Stage the draft BPEJ text localization from a user's clean Japanese ROM.

Draft counterpart of tools/localize_italian.py, with the same manifest layout
and validation rules: the checked-in manifest contains source positions, ROM
offsets and sizes, never game text or graphics. It stages text only. Graphics,
credits, Trainer Hill floors, the Easy Chat ID lists and GAME_LANGUAGE are not
mapped for Japanese yet and stay English, and the engine does not handle a
Japanese game yet, so the staged tree is for inspection, not for play
(docs/JAPANESE.md).

Differences from the Italian manifest: braille ranges include the 6-byte
brailleformat header, and kind "c_eos" is a Japanese string stored without its
terminator (the Pokedex categories), which the decomp's array needs appended.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))
from emerald3ds_builder.rom import load_rom

JAPANESE_SHA1 = "d7cf8f156ba9c455d164e1ea780a6bf1945465c2"


def encoded(data: bytes) -> str:
    return ",".join("0x%02X" % byte for byte in data)


def replacement(kind: str, data: bytes) -> str:
    size = len(data)
    if kind in ("c", "u8array"):
        return "{" + encoded(data) + "}"
    if kind == "c_eos":
        return "{" + encoded(data + b"\xff") + "}"
    if kind == "asm":
        return "\n\t.byte " + encoded(data) + "\n"
    if kind == "u32":
        return str(struct.unpack("<I", data)[0])
    if kind == "u16s":
        return ",".join("0x%04X" % n for n in struct.unpack("<6H", data))
    if kind == "u16array":
        return ",".join("0x%04X" % n for n in struct.unpack("<%dH" % (size // 2), data))
    if kind == "u16rows10":
        if size % 20:
            raise ValueError("Invalid mail word table dimensions")
        rows = [",".join("0x%04X" % n for n in struct.unpack_from("<10H", data, i))
                for i in range(0, size, 20)]
        return "{" + ",".join("{" + row + "}" for row in rows) + "}"
    raise ValueError("Unknown edit kind: " + kind)


def stage(tree: Path, rom_path: Path) -> None:
    manifest = json.loads(gzip.decompress((ROOT / "tools/locales/japanese.json.gz").read_bytes()))
    rom = load_rom(rom_path, supported=(JAPANESE_SHA1,))
    if rom.sha1 != manifest["rom_sha1"] or rom.sha1 != JAPANESE_SHA1:
        raise ValueError("This localization requires the clean Japanese BPEJ ROM")
    source = rom.data
    writes: dict[Path, bytes] = {}
    for relative, file in manifest["files"].items():
        path = tree / relative
        text = path.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != file["sha256"]:
            raise ValueError("Source differs from the pinned patched tree: " + relative)
        previous_end = 0
        for start, end, offset, size, kind in sorted(file["edits"]):
            if not previous_end <= start < end <= len(text) or not 0 <= offset < offset + size <= len(source):
                raise ValueError("Overlapping or out-of-range edit: " + relative)
            previous_end = end
        for start, end, offset, size, kind in sorted(file["edits"], reverse=True):
            text = text[:start] + replacement(kind, source[offset:offset + size]) + text[end:]
        writes[path] = text.encode()
    # Validate all source and ROM references before modifying the staged tree.
    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (tree / ".emerald3ds-locale").write_text("BPEJ draft\n")
    print("Japanese draft text staged: graphics, credits and floors are still English, "
          "and GAME_LANGUAGE is unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    args = parser.parse_args()
    stage(args.tree.resolve(), args.rom.resolve())


if __name__ == "__main__":
    main()
