#ifndef CTR_LOCALE_TEXT_H
#define CTR_LOCALE_TEXT_H
#include <stddef.h>
#include <stdint.h>
#include "3ds_locale.h"

/*
 * The bottom screen uses the cartridge font, which expects game character
 * codes rather than UTF-8. Codes follow pret/pokeemerald's
 * constants/characters.h and charmap.txt; no glyph pixels live here.
 *
 * The font has two glyph sets on the same codes: the Latin one (accented
 * letters at 0x01-0x9F) and the Japanese one (kana there, and punctuation of
 * its own: graphics/fonts/japanese_normal.png). A game string starts in its
 * build's set (CTR_LOCALE_JAPANESE_FIRST) and the control codes FC 15
 * (EXT_CTRL_CODE_JPN) and FC 16 (EXT_CTRL_CODE_ENG) switch it, as the
 * game's text printer does.
 */
#define CTR_LOCALE_CTRL 0xFC    /* EXT_CTRL_CODE_BEGIN */
#define CTR_LOCALE_JPN 0x15     /* EXT_CTRL_CODE_JPN: Japanese glyphs from here */
#define CTR_LOCALE_ENG 0x16     /* EXT_CTRL_CODE_ENG: Latin glyphs from here */
#define CTR_GLYPH_NONE 0xFFFF   /* the set has no such character */

/* Before a game string the port builds from Latin glyphs (arrows, "Lv"):
 * the switch to them, in a Japanese build. */
#if CTR_LOCALE_JAPANESE_FIRST
#define CTR_LOCALE_LATIN_START CTR_LOCALE_CTRL, CTR_LOCALE_ENG,
#else
#define CTR_LOCALE_LATIN_START
#endif

static inline uint16_t CtrLocale_LatinGlyph(uint32_t c)
{
    if (c >= 'A' && c <= 'Z') return 0xBB + c - 'A';
    if (c >= 'a' && c <= 'z') return 0xD5 + c - 'a';
    if (c >= '0' && c <= '9') return 0xA1 + c - '0';
    switch (c)
    {
    case ' ': return 0x00;
    case '/': return 0xBA;
    case '-': return 0xAE;
    case '.': return 0xAD;
    case ',': return 0xB8;
    case ':': return 0xF0;
    case '!': return 0xAB;
    case '?': return 0xAC;
    case '\'': case 0x2019: return 0xB4;
    case '*': return 0x1B; /* Original POK*MON labels. */
    case '%': return 0x5B;
    case '&': return 0x2D;
    case 0x2026: return 0xB0;
    case 0x2642: return 0xB5;
    case 0x2640: return 0xB6;
    case 0xd7: return 0xB9;
    case 0xc0: return 0x01;
    case 0xc1: return 0x02;
    case 0xc2: return 0x03;
    case 0xc7: return 0x04;
    case 0xc8: return 0x05;
    case 0xc9: return 0x06;
    case 0xca: return 0x07;
    case 0xcb: return 0x08;
    case 0xcc: return 0x09;
    case 0xcd: return 0x5A;
    case 0xce: return 0x0B;
    case 0xcf: return 0x0C;
    case 0xd3: return 0x0E;
    case 0xd4: return 0x0F;
    case 0xd9: return 0x11;
    case 0xda: return 0x12;
    case 0xdb: return 0x13;
    case 0xe0: return 0x16;
    case 0xe1: return 0x17;
    case 0xe2: return 0x68;
    case 0xe7: return 0x19;
    case 0xe8: return 0x1A;
    case 0xe9: return 0x1B;
    case 0xea: return 0x1C;
    case 0xeb: return 0x1D;
    case 0xec: return 0x1E;
    case 0xed: return 0x6F;
    case 0xee: return 0x20;
    case 0xef: return 0x21;
    case 0xf3: return 0x23;
    case 0xf4: return 0x24;
    case 0xf9: return 0x26;
    case 0xfa: return 0x27;
    case 0xfb: return 0x28;
    case 0xf1: return 0x29;
    case 0xf2: return 0x22;
    case 0xd1: return 0x14;
    case 0xd2: return 0x0D;
    case 0xfc: return 0xF6;
    case 0xdc: return 0xF3;
    case 0xa1: return 0x52;
    case 0xbf: return 0x51;
    default: return CTR_GLYPH_NONE;
    }
}

static inline uint16_t CtrLocale_JapaneseGlyph(uint32_t c)
{
    /* charmap.txt's Hiragana, U+3041-U+3093 (0: none); its Katakana are
     * the same 0x50 on, U+30A1-U+30F3. */
    static const uint8_t kana[0x53] = {
        0x2F, 0x01, 0x30, 0x02, 0x31, 0x03, 0x32, 0x04, 0x33, 0x05, 0x06, 0x37,
        0x07, 0x38, 0x08, 0x39, 0x09, 0x3A, 0x0A, 0x3B, 0x0B, 0x3C, 0x0C, 0x3D,
        0x0D, 0x3E, 0x0E, 0x3F, 0x0F, 0x40, 0x10, 0x41, 0x11, 0x42, 0x50, 0x12,
        0x43, 0x13, 0x44, 0x14, 0x45, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x46,
        0x4B, 0x1B, 0x47, 0x4C, 0x1C, 0x48, 0x4D, 0x1D, 0x49, 0x4E, 0x1E, 0x4A,
        0x4F, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x34, 0x24, 0x35, 0x25, 0x36, 0x26,
        0x27, 0x28, 0x29, 0x2A, 0x2B, 0x00, 0x2C, 0x00, 0x00, 0x2D, 0x2E,
    };

    if (c >= 0x3041 && c <= 0x3093) return kana[c - 0x3041] ? kana[c - 0x3041] : CTR_GLYPH_NONE;
    if (c >= 0x30A1 && c <= 0x30F3) return kana[c - 0x30A1] ? kana[c - 0x30A1] + 0x50 : CTR_GLYPH_NONE;
    /* Letters and digits, ASCII or full width: the set's own A-Z, a-z, 0-9. */
    if (c >= 'A' && c <= 'Z') return 0xBB + c - 'A';
    if (c >= 'a' && c <= 'z') return 0xD5 + c - 'a';
    if (c >= '0' && c <= '9') return 0xA1 + c - '0';
    if (c >= 0xFF21 && c <= 0xFF3A) return 0xBB + c - 0xFF21;
    if (c >= 0xFF41 && c <= 0xFF5A) return 0xD5 + c - 0xFF41;
    if (c >= 0xFF10 && c <= 0xFF19) return 0xA1 + c - 0xFF10;
    switch (c)
    {
    case ' ': case 0x3000: return 0x00;
    case '!': case 0xFF01: return 0xAB;
    case '?': case 0xFF1F: return 0xAC;
    case 0x3002: return 0xAD;                       /* 。 */
    case '-': case 0x30FC: case 0xFF0D: return 0xAE; /* ー */
    case 0x30FB: return 0xAF;                       /* ・ */
    case 0x2025: case 0x2026: case 0x22EF: return 0xB0;
    case 0x300E: return 0xB1;                       /* 『 』 「 」 */
    case 0x300F: return 0xB2;
    case 0x300C: return 0xB3;
    case 0x300D: return 0xB4;
    case 0x2642: return 0xB5;
    case 0x2640: return 0xB6;
    case 0x5186: return 0xB7;                       /* 円 */
    case '.': case 0xFF0E: return 0xB8;             /* ． */
    case 0xd7: return 0xB9;                         /* × */
    case '/': case 0xFF0F: return 0xBA;
    case 0x25B6: return 0xEF;                       /* ▶ */
    case ':': case 0xFF1A: return 0xF0;
    default: return CTR_GLYPH_NONE;
    }
}

/* A character's code in the Latin or the Japanese glyph set, or
 * CTR_GLYPH_NONE when that set has none. */
static inline uint16_t CtrLocale_Glyph(uint32_t c, int japanese)
{
    return japanese ? CtrLocale_JapaneseGlyph(c) : CtrLocale_LatinGlyph(c);
}

/* The next code point of a UTF-8 string, U+FFFD for a malformed one. */
static inline uint32_t CtrLocale_NextCodePoint(const unsigned char **text)
{
    const unsigned char *p = *text;
    uint32_t c = *p++;
    unsigned extra = c >= 0xc2 && c <= 0xdf ? 1 : c >= 0xe0 && c <= 0xef ? 2 :
                     c >= 0xf0 && c <= 0xf4 ? 3 : 0;

    if (extra)
    {
        uint32_t value = c & ((1u << (6 - extra)) - 1);
        unsigned i;
        for (i = 0; i < extra && p[i] && (p[i] & 0xc0) == 0x80; ++i)
            value = (value << 6) | (p[i] & 0x3f);
        if (i == extra)
        {
            p += extra;
            c = value < (extra == 1 ? 0x80u : extra == 2 ? 0x800u : 0x10000u)
                || (value >= 0xd800 && value <= 0xdfff) || value > 0x10ffff ? 0xfffd : value;
        }
        else c = 0xfffd;
    }
    *text = p;
    return c;
}

/*
 * A label in game codes, one code a character. It is Japanese when it has a
 * character only the Japanese set has (kana, 。, full-width forms) and Latin
 * otherwise, so an English stand-in keeps the Latin glyphs in a Japanese
 * build; a character its set lacks takes the other's, and one neither has is
 * '?'. Where the set differs from the build's (CTR_LOCALE_JAPANESE_FIRST) the
 * label switches to it, and back before its end, so it can be joined to a
 * game string. Returns the codes written before the EOS (0xFF).
 */
static inline size_t CtrLocale_ToGame(uint8_t *out, size_t capacity, const char *text)
{
    const int first = CTR_LOCALE_JAPANESE_FIRST;
    const unsigned char *p = (const unsigned char *)text;
    int japanese = 0, set = first;
    size_t n = 0;

    if (!capacity) return 0;
    while (*p && !japanese)
    {
        uint32_t c = CtrLocale_NextCodePoint(&p);
        japanese = CtrLocale_LatinGlyph(c) == CTR_GLYPH_NONE && CtrLocale_JapaneseGlyph(c) != CTR_GLYPH_NONE;
    }
    p = (const unsigned char *)text;
    while (*p)
    {
        uint32_t c = CtrLocale_NextCodePoint(&p);
        int want = japanese;
        uint16_t code = CtrLocale_Glyph(c, want);
        size_t need;

        if (code == CTR_GLYPH_NONE)
        {
            want = !japanese;
            code = CtrLocale_Glyph(c, want);
        }
        if (code == CTR_GLYPH_NONE)
        {
            want = set;
            code = 0xAC; /* '?' in both sets */
        }
        /* The switch to its set, the code, the switch back and the EOS. */
        need = (want != set ? 2 : 0) + 1 + (want != first ? 2 : 0) + 1;
        if (n + need > capacity) break;
        if (want != set)
        {
            out[n++] = CTR_LOCALE_CTRL;
            out[n++] = want ? CTR_LOCALE_JPN : CTR_LOCALE_ENG;
            set = want;
        }
        out[n++] = (uint8_t)code;
    }
    if (set != first)
    {
        out[n++] = CTR_LOCALE_CTRL;
        out[n++] = first ? CTR_LOCALE_JPN : CTR_LOCALE_ENG;
    }
    out[n] = 0xff;
    return n;
}
#endif
