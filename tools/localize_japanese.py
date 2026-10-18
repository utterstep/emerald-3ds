#!/usr/bin/env python3
"""Stage the BPEJ localization from a user's clean Japanese ROM.

Japanese counterpart of tools/localize_italian.py, with the same manifest layout
and validation rules: the checked-in manifest contains source positions, ROM
offsets, symbol names and sizes, never game text or graphics. Run after
bootstrap applies the pinned source patches.

It stages the texts, the graphics whose Japanese version has the English size and
layout (.lz streams are also decompressed to the plain file), the credits
(src/data/credits.h rebuilt from the ROM: 45 pages in Japanese), the Easy Chat
move and Pokemon id lists in the ROM's kana order, the reference symbols
(addresses only) and GAME_LANGUAGE = LANGUAGE_JAPANESE. A few graphics need a
code patch of this repository (the manifest's "graphics_patch_of"); they are
staged only into a tree that has it. Graphics with another size or layout
("graphics_layout_differs") and the Trainer Hill floors (the Japanese ROM has no
counterpart of the four modes) stay English. Patches 0057-0061, 0063, 0064, 0066,
0070-0076 and 0083 make a Japanese build behave like the Japanese game; what is still
open is listed
in docs/JAPANESE.md, and console play testing is pending.

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
sys.path.insert(0, str(ROOT / "tools"))
from emerald3ds_builder.rom import load_rom
from emerald3ds_builder.recipe import lz77_decompress
from locale_lists import stage_id_lists

JAPANESE_SHA1 = "d7cf8f156ba9c455d164e1ea780a6bf1945465c2"
ENGLISH_LANGUAGE = "#define GAME_LANGUAGE (LANGUAGE_ENGLISH)"
JAPANESE_LANGUAGE = "#define GAME_LANGUAGE (LANGUAGE_JAPANESE)"


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


def credits_header(source: bytes, table: int, count: int) -> bytes:
    """src/data/credits.h from the ROM's credits records (5 entries per page)."""
    if count <= 0 or count % 5 or not 0 <= table <= len(source) - 4 * count:
        raise ValueError("Invalid credits table")
    entries = []
    for index in range(count):
        record = struct.unpack_from("<I", source, table + index * 4)[0] - 0x08000000
        if not 0 <= record <= len(source) - 8:
            raise ValueError("Invalid credits record")
        raw = source[record:record + 8]
        offset = struct.unpack_from("<I", raw, 4)[0] - 0x08000000
        end = source.find(b"\xff", offset, offset + 200) if 0 <= offset < len(source) else -1
        if end < 0 or raw[0] > 40 or raw[1] not in (0, 1) or raw[2:4] != b"\0\0":
            raise ValueError("Invalid credits text")
        entries.append((record, offset, end + 1, raw[0], raw[1]))
    lines = ["enum { PAGE_COUNT = %d };" % (count // 5), "#define ENTRIES_PER_PAGE 5"]
    texts, records = {}, {}
    for record, offset, end, unknown, title in entries:
        if offset not in texts:
            texts[offset] = "sJapaneseCreditsText_" + str(offset)
            lines.append("static const u8 " + texts[offset] + "[] = {" + encoded(source[offset:end]) + "};")
        if record not in records:
            records[record] = "sJapaneseCreditsEntry_" + str(record)
            lines.append("static const struct CreditsEntry " + records[record] + " = {"
                         + str(unknown) + "," + str(title) + "," + texts[offset] + "};")
    lines.append("static const struct CreditsEntry *const sCreditsEntryPointerTable[PAGE_COUNT][ENTRIES_PER_PAGE] = {")
    for index in range(0, len(entries), 5):
        lines.append("{" + ",".join("&" + records[e[0]] for e in entries[index:index + 5]) + "},")
    lines.append("};")
    return ("\n".join(lines) + "\n").encode()


def collect(tree: Path, rom_path: Path) -> dict[Path, bytes]:
    """Validate every source and ROM reference and return {path: new bytes}; nothing is written."""
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

    # Graphics with the English size and layout. Some need this repository's code patch
    # for their Japanese layout: refuse them in a tree without it.
    patches = manifest.get("graphics_patches", {})
    for relative, offset, size in manifest["graphics"]:
        if not 0 <= offset < offset + size <= len(source):
            raise ValueError("Graphic outside ROM: " + relative)
        patch = manifest.get("graphics_patch_of", {}).get(relative)
        if patch is not None:
            need = patches[patch]
            code = tree / need["file"]
            if not code.is_file() or need["marker"] not in code.read_text(encoding="utf-8"):
                raise ValueError("%s needs patch %s (%s)" % (relative, patch, need["file"]))
        writes[tree / relative] = source[offset:offset + size]
        if relative.endswith(".lz"):
            writes[tree / relative[:-3]] = lz77_decompress(source, offset)
    # Graphics with another size or layout stay English ("graphics_layout_differs"), and so
    # do the Trainer Hill floors: the Japanese ROM has no counterpart of the four modes.
    if manifest["floors"]:
        raise ValueError("The Japanese manifest has no Trainer Hill floors to stage")

    if manifest["credits"] is not None:
        writes[tree / "src/data/credits.h"] = credits_header(source, manifest["credits"], manifest["credits_entries"])

    path = tree / "include/constants/global.h"
    text = path.read_text(encoding="utf-8")
    if text.count(ENGLISH_LANGUAGE) != 1:
        raise ValueError("include/constants/global.h does not define GAME_LANGUAGE as English")
    writes[path] = text.replace(ENGLISH_LANGUAGE, JAPANESE_LANGUAGE).encode()

    # Reference symbols (addresses only) and Easy Chat's move and Pokemon lists in the
    # ROM's kana order.
    symbols = ROOT / "tools/locales/japanese-symbols.s.gz"
    writes[tree / "build/japanese-reference.s"] = gzip.decompress(symbols.read_bytes())
    stage_id_lists(tree, source, symbols, writes)
    writes[tree / ".emerald3ds-locale"] = b"BPEJ experimental\n"
    return writes


def stage(tree: Path, rom_path: Path) -> None:
    writes = collect(tree, rom_path)
    # Everything was validated before the first write.
    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print("Japanese game data staged; console play testing is pending (docs/JAPANESE.md).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    args = parser.parse_args()
    stage(args.tree.resolve(), args.rom.resolve())


if __name__ == "__main__":
    main()
