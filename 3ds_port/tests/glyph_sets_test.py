"""The bottom screen's and the HD battle box's text in both glyph sets.

Compiles the production NextGlyph/GlyphWidth/GlyphTiles/StrWidth/GlyphInk
(3ds_bottom_ui.c) and NextGlyph/TextWidth/DrawGlyph (3ds_battle_hud.c) on the
host, for a Latin and a Japanese build, against synthetic glyph sheets (no
font pixels): EXT_CTRL_CODE_JPN/ENG switch the set, a Japanese glyph is 8
pixels wide, and its tiles are where src/text.c's DecompressGlyph_Normal and
_Small read them (0x100 halfwords a row of 16 glyphs, the bottom tiles 0x80
on; a Latin glyph 0x20 halfwords, its bottom tiles 0x10 on).
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path
from voxel_runtime_test import function, ROOT

COMMON = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef bool bool8;
#define TRUE true
#define FALSE false
#define EOS 0xFF
#define CHAR_NEWLINE 0xFE
#define CHAR_PROMPT_SCROLL 0xFA
#define CHAR_PROMPT_CLEAR 0xFB
#define EXT_CTRL_CODE_BEGIN 0xFC
#define PLACEHOLDER_BEGIN 0xFD
#define CHAR_DYNAMIC 0xF7
#define CHAR_KEYPAD_ICON 0xF8
#define CHAR_EXTRA_SYMBOL 0xF9
#define EXT_CTRL_CODE_COLOR 0x01
#define EXT_CTRL_CODE_JPN 0x15
#define EXT_CTRL_CODE_ENG 0x16
#define CHAR_H 0xC2
#define CHAR_MALE 0xB5
#define CTR_LOCALE_JAPANESE_FIRST JAPANESE_FIRST
static u8 GetExtCtrlCodeLength(u8 code) { return code == EXT_CTRL_CODE_COLOR ? 2 : 1; }
/* Sheets that name their glyphs: a Latin glyph's halfwords are its id, a
 * Japanese tile row's are 0x8000 | its id << 4 | (row & 7) | 8 for a bottom
 * tile. */
static u16 sLatin[0x200 * 0x20], sJapanese[0x2000];
static u8 sWidths[0x200];
static void MakeSheets(void)
{
    for (int id = 0; id < 0x200; ++id)
    {
        for (int i = 0; i < 0x20; ++i)
            sLatin[id * 0x20 + i] = (u16)id;
        sWidths[id] = (u8)(3 + id % 7);
        for (int row = 0; row < 16; ++row)
            sJapanese[0x100 * (id >> 4) + 8 * (id & 0xF) + (row >= 8 ? 0x80 : 0) + (row & 7)]
                = (u16)(0x8000 | id << 4 | (row & 7) | (row >= 8 ? 8 : 0));
    }
}
'''

BOTTOM = r'''
int main(void)
{
    static const u8 jpnName[] = {0xFC, 0x15, 0x51, 0x52, 0xFC, 0x16, 0xBB, 0xFE, 0xF9, 0x05, 0xFC, 0x01, 0x03, 0x01, 0xFF};
    static const u8 engName[] = {0x51, 0xFC, 0x16, 0xBB, 0xFC, 0x15, 0x52, 0xFF};
    Font font = {sLatin, sWidths, sJapanese, 13, 13};
    const u8 *s;
    bool8 japanese = JAPANESE_FIRST;
    int bottom;
    u16 g;

    MakeSheets();
    /* Another language's game: a Japanese name between JPN and ENG. */
    s = jpnName;
    assert(NextGlyph(&s, &japanese) == (GLYPH_JAPANESE | 0x51) && japanese);
    assert(NextGlyph(&s, &japanese) == (GLYPH_JAPANESE | 0x52));
    assert(NextGlyph(&s, &japanese) == 0xBB && !japanese);
    assert(NextGlyph(&s, &japanese) == 0xFFFE);
    assert(NextGlyph(&s, &japanese) == 0x105);
    assert(NextGlyph(&s, &japanese) == 0x01 && !japanese);
    assert(NextGlyph(&s, &japanese) == 0xFFFF && NextGlyph(&s, &japanese) == 0xFFFF);
    assert(StrWidth(&font, jpnName) == 8 + 8 + sWidths[0xBB]);
    /* The string's start is the build's set. */
    japanese = JAPANESE_FIRST;
    s = engName;
    g = NextGlyph(&s, &japanese);
    assert(g == (JAPANESE_FIRST ? (GLYPH_JAPANESE | 0x51) : 0x51));
    assert(NextGlyph(&s, &japanese) == 0xBB);
    assert(NextGlyph(&s, &japanese) == (GLYPH_JAPANESE | 0x52));
    assert(StrWidth(&font, engName) == (JAPANESE_FIRST ? 8 : sWidths[0x51]) + sWidths[0xBB] + 8);
    /* Tiles where DecompressGlyph_* reads them. */
    assert(GlyphTiles(&font, 0x1A3, &bottom) == sLatin + 0x1A3 * 0x20 && bottom == 0x10);
    assert(GlyphTiles(&font, GLYPH_JAPANESE | 0x1A3, &bottom) == sJapanese + 0x100 * 0x1A + 8 * 3 && bottom == 0x80);
    assert(GlyphWidth(&font, GLYPH_JAPANESE | 0xC2) == 8 && GlyphWidth(&font, 0xC2) == sWidths[0xC2]);
    /* Rows 0-7 from the top tile, 8-15 from the bottom one: pixel 0 is the
     * high byte's top bits, 2 (shadow) in this sheet's 0x8... rows. */
    for (int row = 0; row < 16; ++row)
        assert(GlyphInk(&font, GLYPH_JAPANESE | 0x51, 0, row));
    font.japanese = NULL;
    assert(!GlyphInk(&font, GLYPH_JAPANESE | 0x51, 0, 0) && StrWidth(&font, jpnName) == 16 + sWidths[0xBB]);
    puts(JAPANESE_FIRST ? "PASS bottom glyph sets (Japanese build)" : "PASS bottom glyph sets (Latin build)");
    return 0;
}
'''

HUD_GLOBALS = r'''
#define CTR_HUD_W 64
#define CTR_HUD_H 16
static int sRowTop = 0, sRowBottom = CTR_HUD_H;
#define gFontNormalLatinGlyphWidths sWidths
'''

HUD = r'''
int main(void)
{
    static const u8 name[] = {0xFC, 0x15, 0x51, 0x52, 0xFC, 0x16, 0xBB, 0xFF};
    static uint32_t pic[CTR_HUD_W * CTR_HUD_H];
    Glyphs glyphs = {sLatin, sJapanese};
    const u8 *s = name;
    bool japanese = JAPANESE_FIRST;

    MakeSheets();
    assert(NextGlyph(&s, &japanese) == (GLYPH_JAPANESE | 0x51));
    assert(NextGlyph(&s, &japanese) == (GLYPH_JAPANESE | 0x52));
    assert(NextGlyph(&s, &japanese) == 0xBB && NextGlyph(&s, &japanese) == -1);
    assert(TextWidth(name) == 16 + sWidths[0xBB]);
    /* A Japanese glyph: its 8 columns, every row, from its own tiles (the
     * sheet's rows are 0x8xxx: pixel 0 is 2, the shadow). */
    assert(DrawGlyph(pic, &glyphs, GLYPH_JAPANESE | 0x51, 4, 0, 1, 2) == 8);
    for (int row = 0; row < 16; ++row)
        assert(pic[row * CTR_HUD_W + 4] == 2 && pic[row * CTR_HUD_W + 3] == 0);
    glyphs.japanese = NULL;
    assert(DrawGlyph(pic, &glyphs, GLYPH_JAPANESE | 0x52, 20, 0, 1, 2) == 8 && pic[20] == 0);
    puts(JAPANESE_FIRST ? "PASS HD box glyph sets (Japanese build)" : "PASS HD box glyph sets (Latin build)");
    return 0;
}
'''


def defines(source, names):
    return ''.join(re.search(r'^#define %s .*\n' % name, source, re.M).group(0) for name in names)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cc', default='gcc')
    args = parser.parse_args()
    bottom = (ROOT / 'src/3ds_bottom_ui.c').read_text(encoding='utf-8')
    hud = (ROOT / 'src/3ds_battle_hud.c').read_text(encoding='utf-8')
    font = re.search(r'typedef struct\n\{\n    const u16 \*glyphs;.*?\} Font;\n', bottom, re.S).group(0)
    glyphs = re.search(r'typedef struct\n\{\n    const u16 \*latin, \*japanese;\n\} Glyphs;\n', hud).group(0)
    programs = {
        'bottom': COMMON + font + defines(bottom, ('GLYPH_JAPANESE', 'JAPANESE_GLYPH_WIDTH'))
        + ''.join(function(bottom, name) for name in (
            'static u16 NextGlyph(', 'static int GlyphWidth(', 'static const u16 *GlyphTiles(',
            'static int StrWidth(', 'static bool8 GlyphInk(')) + BOTTOM,
        'hud': COMMON + HUD_GLOBALS + glyphs + defines(hud, ('GLYPH_JAPANESE', 'JAPANESE_GLYPH_WIDTH'))
        + ''.join(function(hud, name) for name in (
            'static int GlyphWidth(', 'static int NextGlyph(', 'static int TextWidth(',
            'static int DrawGlyph(')) + HUD,
    }
    with tempfile.TemporaryDirectory(prefix='glyph-sets-') as tmp:
        for name, source in programs.items():
            for japanese in (0, 1):
                path = Path(tmp) / ('%s.c' % name)
                exe = Path(tmp) / ('%s%d.exe' % (name, japanese))
                path.write_text(source, encoding='utf-8')
                subprocess.run([args.cc, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                                '-DJAPANESE_FIRST=%d' % japanese, str(path), '-o', str(exe)], check=True)
                subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
