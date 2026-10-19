#!/usr/bin/env python3
"""gen_furigana.py --dir DIR --charmap CHARMAP --out OUTDIR: the reading pane's data.

The Japanese build's bottom screen can show the message the top screen is
printing in kanji with furigana (3ds_port/src/3ds_reading.c, docs/FURIGANA.md).
Its text is the player's own: DIR is the folder of the kanji conversion
(out/furigana.json, every message's kana as the game holds it and its
[漢字|よみ] markup) with fonts/ beside it, kept outside the repository because
it is derived from the game's text. This writes, into OUTDIR (the romfs):

  furigana/table.bin  every annotated message, keyed by a hash of the game's
                      bytes for its kana (the template the game prints from),
                      and the character each of the game's bytes stands for;
  furigana/font.bin   the glyphs those messages and the game's characters
                      need, rendered from M PLUS Rounded 1c (fonts/mplusround)
                      at the screen's own resolution, 16 levels of ink a pixel:
                      the text at 24 pixels and its readings at 12, and 18 and
                      10 for a page too long for those.

Without DIR there is nothing to write and the pane stays off. Both formats are
read by 3ds_reading.c; the numbers below are its.
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TABLE_MAGIC = b"FGT3"
FONT_MAGIC = b"FGF3"

# Tokens of an annotated message; anything else is a character (UCS-2).
TOK_RUBY = 0xE000      # base characters follow
TOK_RUBY_TEXT = 0xE001 # its reading follows
TOK_RUBY_END = 0xE002
TOK_NEWLINE = 0xE003   # \n
TOK_SCROLL = 0xE004    # \l: a new line, the box scrolls
TOK_PAGE = 0xE005      # \p: a new page
TOK_HOLE = 0xE100      # + n: the n-th run of placeholders, as the game expanded it

# The game's control bytes (charmap.txt).
CHAR_DYNAMIC = 0xF7
CHAR_KEYPAD_ICON = 0xF8
CHAR_EXTRA_SYMBOL = 0xF9
CHAR_PROMPT_SCROLL = 0xFA
CHAR_PROMPT_CLEAR = 0xFB
EXT_CTRL_CODE_BEGIN = 0xFC
PLACEHOLDER_BEGIN = 0xFD
CHAR_NEWLINE = 0xFE
EOS = 0xFF

# The faces, in the order 3ds_reading.c takes them: text and readings, then
# the same a size down.
FONT_FILE = Path("mplusround") / "MPLUSRounded1c-Medium.ttf"
FACES = [("text", 24), ("ruby", 12), ("text", 18), ("ruby", 10)]

# Where the charmap names a byte by the Latin character its international
# font has, what the Japanese font draws there (graphics/fonts/normal.hwjpnfont).
JAPANESE_GLYPH = {"“": "『", "”": "』", "‘": "「", "’": "」", "¥": "円", "·": "・", "⋯": "…"}

# What the pane writes for the game's button icons and extra symbols.
KEYPAD = ["Ａ", "Ｂ", "Ｌ", "Ｒ", "ＳＴＡＲＴ", "ＳＥＬＥＣＴ", "↑", "↓", "←", "→", "↑↓", "←→", "＋"]
EXTRA = {0x00: "↑", 0x01: "↓", 0x02: "←", 0x03: "→", 0x04: "＋", 0x05: "Lv", 0x06: "PP", 0x07: "ID",
         0x08: "No", 0x09: "＿", 0x13: "（", 0x14: "）", 0x15: "◎", 0x16: "△", 0x17: "×"}
for _i in range(9):
    EXTRA[0x0A + _i] = "①②③④⑤⑥⑦⑧⑨"[_i]


def shown(c: str) -> str:
    return JAPANESE_GLYPH.get(c, c)


# --- The game's characters ------------------------------------------------

def game_chars(charmap: Path) -> list:
    """The character each single byte stands for in a Japanese build.

    charmap.txt lists the Latin set first and the Japanese one after
    '@ Hiragana'; a Japanese build draws the latter where both have a byte.
    Where only the Latin set names one, the conversion's text spells it that
    way too (it was decoded with the same charmap).
    """
    latin = [""] * 256
    japanese = [""] * 256
    section = latin
    for line in charmap.read_text(encoding="utf-8").splitlines():
        if line.startswith("@ Hiragana"):
            section = japanese
        m = re.match(r"^'(.)'\s*=\s*([0-9A-Fa-f]{2})\s*(?:@.*)?$", line)
        if m:
            b = int(m.group(2), 16)
            if not section[b]:
                section[b] = m.group(1)
    chars = [japanese[b] or latin[b] for b in range(256)]
    chars[0x00] = "　"
    return chars


def game_codes(chars: list) -> dict:
    codes = {}
    for b, c in enumerate(chars):
        if c and c not in codes and b not in (CHAR_DYNAMIC, CHAR_KEYPAD_ICON, CHAR_EXTRA_SYMBOL):
            codes[c] = b
    return codes


# --- Messages ---------------------------------------------------------------

def parse_markup(text: str):
    """[漢字|よみ] markup into (kind, value) parts: char, ruby, newline, scroll,
    page, ctrl (a control's bytes) and hole (a placeholder's bytes)."""
    parts = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "[":
            j = text.index("]", i)
            base, reading = text[i + 1:j].split("|")
            parts.append(("ruby", (base, reading)))
            i = j + 1
        elif c == "\\":
            parts.append(({"n": "newline", "l": "scroll", "p": "page"}[text[i + 1]], None))
            i += 2
        elif c == "{":
            j = text.index("}", i)
            parts.append(control(text[i + 1:j]))
            i = j + 1
        else:
            parts.append(("char", c))
            i += 1
    return parts


def control(body: str):
    """{V1} is FD 01; {C08:0F} is FC 08 0F; {F7:00} is F7 00."""
    if body.startswith("V"):
        return ("hole", bytes([PLACEHOLDER_BEGIN, int(body[1:])]))
    head, *args = body.split(":")
    if head.startswith("C"):
        return ("ctrl", bytes([EXT_CTRL_CODE_BEGIN, int(head[1:], 16)] + [int(a, 16) for a in args]))
    first = int(head, 16)
    if first == CHAR_DYNAMIC:
        return ("hole", bytes([first] + [int(a, 16) for a in args]))
    return ("ctrl", bytes([first] + [int(a, 16) for a in args]))


def encode(parts, codes: dict) -> bytes:
    """The game's bytes for a message's kana (its readings in place of its
    kanji), as the game holds the template; None if a character is not the
    game's."""
    out = bytearray()
    for kind, value in parts:
        if kind == "char":
            if value not in codes:
                return None
            out.append(codes[value])
        elif kind == "ruby":
            for c in value[1]:
                if c not in codes:
                    return None
                out.append(codes[c])
        elif kind in ("newline", "scroll", "page"):
            out.append({"newline": CHAR_NEWLINE, "scroll": CHAR_PROMPT_SCROLL, "page": CHAR_PROMPT_CLEAR}[kind])
        else:
            out += value
    out.append(EOS)
    return bytes(out)


def tokens(parts) -> list:
    """The pane's tokens for a message. Placeholders next to each other are one
    hole: the game's expansion of them is read off the printed text as one."""
    out = []
    holes = 0
    last_hole = False
    for kind, value in parts:
        if kind == "hole":
            if not last_hole:
                out.append(TOK_HOLE + holes)
                holes += 1
            last_hole = True
            continue
        last_hole = False
        if kind == "char":
            out.append(ord(shown(value)))
        elif kind == "ruby":
            out.append(TOK_RUBY)
            out += [ord(shown(c)) for c in value[0]]
            out.append(TOK_RUBY_TEXT)
            out += [ord(shown(c)) for c in value[1]]
            out.append(TOK_RUBY_END)
        elif kind == "newline":
            out.append(TOK_NEWLINE)
        elif kind == "scroll":
            out.append(TOK_SCROLL)
        elif kind == "page":
            out.append(TOK_PAGE)
        elif kind == "ctrl":
            if value[0] == CHAR_KEYPAD_ICON and value[1] < len(KEYPAD):
                out += [ord(c) for c in KEYPAD[value[1]]]
            elif value[0] == CHAR_EXTRA_SYMBOL and value[1] in EXTRA:
                out += [ord(c) for c in EXTRA[value[1]]]
            # Colours, pauses, sounds: nothing to read.
    return out


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


# --- Fonts ------------------------------------------------------------------

def face_block(font_path: Path, size: int, chars) -> tuple:
    """One size of the font: each character cropped to its ink, 4 bits a pixel
    (two a byte, the left one high), placed by its offset from the left of its
    advance and the top of the line (the font's ascent above the baseline).
    The header carries the rows the CJK glyphs' ink spans, which the pane lines
    up on."""
    font = ImageFont.truetype(str(font_path), size)
    ascent, descent = font.getmetrics()
    # A character the font lacks is drawn as its missing-glyph box.
    notdef = font.getmask("\uFFFE")
    notdef = (notdef.size, bytes(notdef))

    def drawn(c):
        mask = font.getmask(c)
        return mask.getbbox() is not None and (mask.size, bytes(mask)) != notdef

    have = sorted(c for c in chars if c in " 　" or (ord(c) < 0x10000 and drawn(c)))
    missing = sorted(set(chars) - set(have))
    entries = bytearray()
    data = bytearray()
    for c in have:
        x0, y0, x1, y1 = font.getbbox(c)
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        if c in " 　":
            w = h = x0 = y0 = 0
        image = Image.new("L", (max(w, 1), max(h, 1)), 0)
        if w and h:
            ImageDraw.Draw(image).text((-x0, -y0), c, font=font, fill=255)
        offset = len(data)
        for y in range(h):
            row = [(image.getpixel((x, y)) * 15 + 127) // 255 for x in range(w)] + [0]
            data += bytes((row[x] << 4) | row[x + 1] for x in range(0, w, 2))
        entries += struct.pack("<HBBBbbBI", ord(c), round(font.getlength(c)), w, h, x0, y0, 0, offset)
    ink = [font.getbbox(c) for c in "漢字験あア"]
    ink_top, ink_bottom = min(b[1] for b in ink), max(b[3] for b in ink)
    while len(data) % 4:
        data.append(0)
    header = struct.pack("<BBBBHHI", size, ascent, ink_top, ink_bottom, len(have), 0, len(data))
    return header + entries + data, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True, help="the kanji conversion's folder")
    ap.add_argument("--charmap", type=Path, required=True, help="the tree's charmap.txt")
    ap.add_argument("--out", type=Path, required=True, help="the romfs")
    args = ap.parse_args()

    chars = game_chars(args.charmap)
    codes = game_codes(chars)
    game_map = [ord(shown(c)) if c and b < CHAR_DYNAMIC else 0 for b, c in enumerate(chars)]

    messages = json.loads((args.dir / "out" / "furigana.json").read_text(encoding="utf-8"))
    entries = {}
    unencodable = clashes = 0
    text_chars, reading_chars = set(), set()
    for m in messages:
        parts = parse_markup(m["annotated"])
        template = encode(parts, codes)
        if template is None or template != encode(parse_markup(m["original"]), codes):
            unencodable += 1
            continue
        toks = tokens(parts)
        key = fnv1a64(template[:-1])
        if key in entries and entries[key] != toks:
            clashes += 1
            continue
        entries[key] = toks
        in_ruby = False
        for t in toks:
            if t == TOK_RUBY_TEXT:
                in_ruby = True
            elif t == TOK_RUBY_END:
                in_ruby = False
            elif t < 0xE000 or t > 0xF8FF:
                (reading_chars if in_ruby else text_chars).add(chr(t))
    # The game's own characters reach the pane through the placeholders.
    text_chars.update(chr(u) for u in game_map if u)

    blob = bytearray()
    index = []
    for key in sorted(entries):
        index.append(struct.pack("<QI", key, len(blob)))
        toks = entries[key]
        blob += struct.pack("<H", len(toks)) + b"".join(struct.pack("<H", t) for t in toks)
    table = (TABLE_MAGIC + struct.pack("<III", len(index), len(blob), 0)
             + b"".join(struct.pack("<H", u) for u in game_map) + b"".join(index) + blob)

    font_path = args.dir / "fonts" / FONT_FILE
    font = bytearray(FONT_MAGIC + struct.pack("<BBBB", len(FACES), 0, 0, 0))
    missing = set()
    for kind, size in FACES:
        block, lost = face_block(font_path, size, text_chars if kind == "text" else reading_chars)
        font += block
        missing.update(lost)

    out = args.out / "furigana"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("table.bin", table), ("font.bin", bytes(font))):
        path = out / name
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    print("furigana: %d messages, %d text characters, %d reading characters, font %d KiB; %d not the game's "
          "text, %d hash clashes, missing glyphs: %s" % (len(entries), len(text_chars), len(reading_chars),
                                                         len(font) // 1024, unencodable, clashes,
                                                         "".join(sorted(missing)) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
