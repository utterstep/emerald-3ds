/*
 * The reading pane (docs/FURIGANA.md).
 *
 * Japanese Emerald is written in kana only. While a message is open, the
 * bottom screen shows the same message with kanji and their readings over
 * them, the whole page the top screen is on at once; the top keeps the game's
 * own text, so both are there side by side.
 *
 * The annotated text is the player's own, made from their ROM and kept out of
 * the repository (scripts/gen_furigana.py): furigana/table.bin maps a hash of
 * the game's bytes for each message's template to its tokens, and
 * furigana/font.bin holds its glyphs, M PLUS Rounded 1c rendered at the
 * screen's own resolution with 16 levels of ink: the text at 24 pixels with
 * its readings at 12, and 18 and 10 for a page too long for those. The text
 * has the game's colours and shadow. Both files are optional data: without
 * them CtrReading_Stamp is always 0 and the bottom screen is as it was.
 *
 * The game tells this file what it prints (text.c's AddTextPrinter) and what
 * it expanded into the buffers it prints from (StringExpandPlaceholders,
 * BattleStringExpandPlaceholders, DynamicPlaceholderTextUtil_ExpandPlaceholders).
 * A printed text that is a template of the table, or a buffer expanded from
 * one, is the message on show. The values of its placeholders - the player's
 * name, a Pokémon's - are read off the printed text by matching the template's
 * own bytes around them, and drawn as the game spells them.
 *
 * Only a message that types out is one: menus and labels print at once.
 *
 * The page is the text printer's: the page breaks it has gone past, less the
 * one it waits at. With KANJI TYPE-OUT (OPTIONS, on by default) the page also
 * types out as the top screen's does: every character of the annotation stands
 * for characters the game prints, so each appears when they do, a word in
 * kanji with the first kana of its reading. The page is laid out once; a
 * frame draws only what the printer added (CtrReading_Advance). While the
 * printer waits for a button, the game's down arrow bounces after the text,
 * twice its size as the box is, in step with the top screen's.
 *
 * The pane goes as the text does on the top screen: when its
 * window is wiped once the message is printed or taken off the screen
 * (window.c, the message box closing among them), when another text replaces
 * it there, when the screen that printed it goes, and in the field when the
 * player can move again.
 */
#include <stdlib.h>
#include <string.h>

#include "global.h"
#include "main.h"
#include "overworld.h"
#include "script.h"
#include "string_util.h"
#include "text.h"
#include "constants/characters.h"

#include "3ds_data.h"
#include "3ds_extras.h"
#include "3ds_log.h"
#include "3ds_reading.h"

/* text.c: where a window's printer is in its text, what it does and its down
 * arrow's step; FALSE once it is done. */
bool8 CtrText_Progress(u8 windowId, const u8 **currentChar, u8 *state, u8 *arrow);

/* scripts/gen_furigana.py's formats. */
#define TABLE_MAGIC 0x34544746  /* "FGT4" */
#define FONT_MAGIC 0x33464746   /* "FGF3" */
#define TABLE_HEADER 16
#define GAME_MAP_SIZE (256 * 2)
#define FACE_HEADER 12

enum
{
    TOK_RUBY = 0xE000,
    TOK_RUBY_TEXT,
    TOK_RUBY_END,
    TOK_NEWLINE,
    TOK_SCROLL,
    TOK_PAGE,
    TOK_HOLE = 0xE100,
    TOK_HOLE_END = 0xE200,
    /* + n: the n characters after it spell one button icon or symbol (two of
     * the printed text's bytes). */
    TOK_ICON = 0xE200,
    TOK_ICON_END = 0xE210,
};

typedef struct
{
    u32 lo, hi, offset;
} Entry;

/* A glyph: its ink (w x h, 4 bits a pixel, the left one high) at (x, y) from
 * the left of its advance and the top of the line. */
typedef struct
{
    u16 code;
    u8 advance, w, h;
    s8 x, y;
    u8 pad;
    u32 offset;
} Glyph;

/* One size of the font; inkTop and inkBottom are the rows the CJK glyphs'
 * ink spans, which lines are set by. */
typedef struct
{
    u8 size, ascent, inkTop, inkBottom;
    u16 count;
    const Glyph *glyphs;
    const u8 *data;
    u32 dataSize;
} Face;

/* font.bin's faces, in its order. */
enum { FACE_TEXT, FACE_RUBY, FACE_TEXT_SMALL, FACE_RUBY_SMALL, FACE_COUNT };

static struct
{
    u8 *table, *font;
    u32 count, blobSize;
    const u16 *gameMap;
    const Entry *index;
    const u8 *blob;
    Face faces[FACE_COUNT];
    /* The game's down arrow and its dark one: three frames of 8x16, 4bpp. */
    u8 *arrows[2];
} sData;

#define MAX_TEXT 1024
#define MAX_HOLES 16

typedef struct
{
    u16 start, length;
} Span;

static struct
{
    bool8 on;
    u8 window, inBattle;
    /* The printer's page, and the lines it has scrolled on it (\l). */
    u16 page;
    u8 scrolls;
    /* How much of the text it has printed (all of it: ~0), and the row of the
     * down arrow's picture it shows the arrow from (-1: none). */
    u32 printedTo;
    s8 arrow;
    MainCallback callback2;
    const u16 *tokens;
    u16 count;
    /* What the printer reads, and a copy of it: its buffer may be written
     * again while the pane still shows the message. */
    const u8 *printed;
    u16 length;
    u8 text[MAX_TEXT];
    Span holes[MAX_HOLES];
    u8 holeCount;
    u32 serial;
} sMsg;

/* The latest expansions, newest last: a printed buffer is looked up here for
 * the template it came from. */
#define EXPANDED_KEEP 8
static struct
{
    const u8 *dest, *src;
} sExpanded[EXPANDED_KEEP];
static u8 sExpandedNext;

/* ------------------------------------------------------------------------ */
/* The data                                                                 */
/* ------------------------------------------------------------------------ */

static bool8 ParseFace(Face *f, const u8 **p, const u8 *end)
{
    size_t size;

    if (end - *p < FACE_HEADER)
        return FALSE;
    f->size = (*p)[0];
    f->ascent = (*p)[1];
    f->inkTop = (*p)[2];
    f->inkBottom = (*p)[3];
    memcpy(&f->count, *p + 4, 2);
    memcpy(&f->dataSize, *p + 8, 4);
    size = FACE_HEADER + (size_t)f->count * sizeof(Glyph) + f->dataSize;
    if ((size_t)(end - *p) < size || f->inkBottom <= f->inkTop)
        return FALSE;
    f->glyphs = (const Glyph *)(*p + FACE_HEADER);
    f->data = *p + FACE_HEADER + (size_t)f->count * sizeof(Glyph);
    *p += size;
    return TRUE;
}

static void Unload(void)
{
    free(sData.table);
    free(sData.font);
    free(sData.arrows[0]);
    free(sData.arrows[1]);
    memset(&sData, 0, sizeof(sData));
}

void CtrReading_Init(void)
{
    u32 tableSize = 0, fontSize = 0, magic, header[3];
    const u8 *p;

    Unload();
    if (!CtrData_Exists("furigana/table.bin"))
        return;
    sData.table = CtrData_Load("furigana/table.bin", &tableSize);
    sData.font = CtrData_Load("furigana/font.bin", &fontSize);
    if (!sData.table || !sData.font || tableSize < TABLE_HEADER + GAME_MAP_SIZE || fontSize < 8)
    {
        CtrLog_Write(CTR_LOG_ERROR, "reading pane: furigana data incomplete");
        Unload();
        return;
    }
    memcpy(&magic, sData.table, 4);
    memcpy(header, sData.table + 4, sizeof(header));
    sData.count = header[0];
    sData.blobSize = header[1];
    if (magic != TABLE_MAGIC
     || (u64)TABLE_HEADER + GAME_MAP_SIZE + (u64)sData.count * sizeof(Entry) + sData.blobSize > tableSize)
    {
        CtrLog_Write(CTR_LOG_ERROR, "reading pane: furigana/table.bin is not a table");
        Unload();
        return;
    }
    sData.gameMap = (const u16 *)(sData.table + TABLE_HEADER);
    sData.index = (const Entry *)(sData.table + TABLE_HEADER + GAME_MAP_SIZE);
    sData.blob = (const u8 *)(sData.index + sData.count);

    memcpy(&magic, sData.font, 4);
    p = sData.font + 8;
    if (magic != FONT_MAGIC || sData.font[4] < FACE_COUNT)
        p = NULL;
    for (int i = 0; p && i < FACE_COUNT; ++i)
        if (!ParseFace(&sData.faces[i], &p, sData.font + fontSize))
            p = NULL;
    if (!p)
    {
        CtrLog_Write(CTR_LOG_ERROR, "reading pane: furigana/font.bin is not a font");
        Unload();
        return;
    }
    for (int i = 0; i < 2; ++i)
    {
        u32 size = 0;

        sData.arrows[i] = CtrData_Load(i ? "graphics/fonts/down_arrow_alt.4bpp" : "graphics/fonts/down_arrow.4bpp", &size);
        if (sData.arrows[i] && size < 3 * 64)
        {
            free(sData.arrows[i]);
            sData.arrows[i] = NULL;
        }
    }
    CtrLog_Write(CTR_LOG_GAME, "reading pane: %lu messages, %u characters, %u for readings", (unsigned long)sData.count,
                 sData.faces[FACE_TEXT].count, sData.faces[FACE_RUBY].count);
}

void CtrReading_Reset(void)
{
    sMsg.on = FALSE;
    memset(sExpanded, 0, sizeof(sExpanded));
}

/* ------------------------------------------------------------------------ */
/* Finding the message                                                      */
/* ------------------------------------------------------------------------ */

/* The bytes of the character or control code at s, as the printer reads it. */
static u32 Unit(const u8 *s)
{
    switch (*s)
    {
    case EXT_CTRL_CODE_BEGIN:
        return 1 + (GetExtCtrlCodeLength(s[1]) ? GetExtCtrlCodeLength(s[1]) : 1);
    case PLACEHOLDER_BEGIN:
    case CHAR_DYNAMIC:
    case CHAR_KEYPAD_ICON:
    case CHAR_EXTRA_SYMBOL:
        return 2;
    default:
        return 1;
    }
}

/* The bytes before EOS, or MAX_TEXT if there is none soon. */
static u32 Length(const u8 *s)
{
    u32 n = 0;

    while (n < MAX_TEXT && s[n] != EOS)
        n += Unit(s + n);
    return n < MAX_TEXT ? n : MAX_TEXT;
}

/* FNV-1a, over the bytes gen_furigana.py hashed. */
static u64 Hash(const u8 *s, u32 length)
{
    u64 h = 0xCBF29CE484222325ull;

    for (u32 i = 0; i < length; ++i)
    {
        h ^= s[i];
        h *= 0x100000001B3ull;
    }
    return h;
}

static const u16 *Find(u64 key, u16 *count)
{
    u32 lo = 0, hi = sData.count, keyLo = (u32)key, keyHi = (u32)(key >> 32);

    while (lo < hi)
    {
        u32 mid = (lo + hi) / 2;
        const Entry *e = &sData.index[mid];

        if (e->hi < keyHi || (e->hi == keyHi && e->lo < keyLo))
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo < sData.count && sData.index[lo].hi == keyHi && sData.index[lo].lo == keyLo)
    {
        u32 offset = sData.index[lo].offset;
        u16 n;

        if (offset + 2 > sData.blobSize)
            return NULL;
        memcpy(&n, sData.blob + offset, 2);
        if (offset + 2 + (u32)n * 2 > sData.blobSize)
            return NULL;
        *count = n;
        return (const u16 *)(sData.blob + offset + 2);
    }
    return NULL;
}

/*
 * The template's literal runs around its placeholders: lits[0], a run of
 * placeholders, lits[1], ... lits[holes]. Placeholders next to each other are
 * one run (gen_furigana.py's holes), so the runs between them are not empty.
 */
static int Split(const u8 *t, u32 length, Span *lits)
{
    int holes = 0;
    bool8 inHole = FALSE;
    u32 i;

    lits[0].start = 0;
    for (i = 0; i < length; i += Unit(t + i))
    {
        bool8 hole = t[i] == PLACEHOLDER_BEGIN || t[i] == CHAR_DYNAMIC;

        if (hole && !inHole)
        {
            lits[holes].length = i - lits[holes].start;
            if (++holes >= MAX_HOLES)
                return -1;
        }
        else if (!hole && inHole)
            lits[holes].start = i;
        inHole = hole;
    }
    if (inHole)
        lits[holes].start = length;
    lits[holes].length = length - lits[holes].start;
    return holes;
}

/* The printed text from pos on as hole k, lits[k + 1], hole k + 1, ...: each
 * hole the shortest that lets the rest match. */
static bool8 Match(const u8 *t, const Span *lits, int k, int holes, const u8 *e, u32 pos, u32 elen, Span *found)
{
    const Span *next = &lits[k + 1];

    if (k == holes)
        return pos == elen;
    if (k + 1 == holes)
    {
        u32 at;

        if (elen < pos + next->length)
            return FALSE;
        at = elen - next->length;
        if (memcmp(e + at, t + next->start, next->length) != 0)
            return FALSE;
        found[k].start = pos;
        found[k].length = at - pos;
        return TRUE;
    }
    for (u32 at = pos; at + next->length <= elen; ++at)
    {
        if (memcmp(e + at, t + next->start, next->length) != 0)
            continue;
        found[k].start = pos;
        found[k].length = at - pos;
        if (Match(t, lits, k + 1, holes, e, at + next->length, elen, found))
            return TRUE;
    }
    return FALSE;
}

static bool8 Show(u8 windowId, const u8 *tmpl, const u8 *printed)
{
    static unsigned mismatches;
    Span lits[MAX_HOLES + 1], found[MAX_HOLES];
    u32 tlen = Length(tmpl), elen;
    const u16 *tokens;
    u16 count;
    int holes;

    if (tlen >= MAX_TEXT || !(tokens = Find(Hash(tmpl, tlen), &count)))
        return FALSE;
    elen = Length(printed);
    holes = Split(tmpl, tlen, lits);
    if (elen >= MAX_TEXT || holes < 0)
        return FALSE;
    if (holes == 0 ? elen != tlen || memcmp(printed, tmpl, tlen) != 0
                   : elen < lits[0].length || memcmp(printed, tmpl, lits[0].length) != 0
                     || !Match(tmpl, lits, 0, holes, printed, lits[0].length, elen, found))
    {
        if (mismatches++ < 8)
            CtrLog_Write(CTR_LOG_GAME, "reading pane: a printed text does not match its template");
        return FALSE;
    }
    memcpy(sMsg.text, printed, elen);
    sMsg.text[elen] = EOS;
    memcpy(sMsg.holes, found, sizeof(Span) * holes);
    sMsg.holeCount = holes;
    sMsg.printed = printed;
    sMsg.length = elen;
    sMsg.tokens = tokens;
    sMsg.count = count;
    sMsg.window = windowId;
    sMsg.page = 0;
    sMsg.scrolls = 0;
    sMsg.printedTo = 0;
    sMsg.arrow = -1;
    sMsg.callback2 = gMain.callback2;
    sMsg.inBattle = gMain.inBattle;
    if (++sMsg.serial >= 1u << 20)
        sMsg.serial = 1;
    sMsg.on = TRUE;
    return TRUE;
}

void CtrReading_Expanded(const u8 *dest, const u8 *src)
{
    if (!sData.table)
        return;
    sExpanded[sExpandedNext].dest = dest;
    sExpanded[sExpandedNext].src = src;
    sExpandedNext = (sExpandedNext + 1) % EXPANDED_KEEP;
}

void CtrReading_Printing(u8 windowId, const u8 *str, u8 speed)
{
    const u8 *tmpl = NULL;

    if (!sData.table || !str)
        return;
    /* A menu's or a label's text, all at once: on the message's window, it
     * replaces the message. */
    if (speed == 0 || speed == TEXT_SKIP_DRAW)
    {
        if (sMsg.on && windowId == sMsg.window)
            sMsg.on = FALSE;
        return;
    }
    for (int i = 1; i <= EXPANDED_KEEP; ++i)
    {
        int slot = (sExpandedNext + EXPANDED_KEEP - i) % EXPANDED_KEEP;

        if (sExpanded[slot].dest == str)
        {
            tmpl = sExpanded[slot].src;
            break;
        }
    }
    /* A buffer may also hold a template copied as it is. */
    if ((tmpl && Show(windowId, tmpl, str)) || Show(windowId, str, str))
        return;
    if (sMsg.on && windowId == sMsg.window)
        sMsg.on = FALSE;
}

void CtrReading_WindowCleared(u8 windowId, u8 hidden)
{
    const u8 *cur;
    u8 state, arrow;

    if (!sMsg.on || windowId != sMsg.window)
        return;
    /* A printer wipes its own window at a page break: the message goes on. */
    if (!hidden && CtrText_Progress(windowId, &cur, &state, &arrow))
        return;
    sMsg.on = FALSE;
}

/*
 * The page the printer is on, the page breaks behind it less the one it waits
 * at, and the lines it has scrolled on that page, the same way; how much it
 * has printed, and the row its down arrow is shown from (sDownArrowYCoords, a
 * step behind its index, which moves on as it draws) while it waits for a
 * button with one. Once it is done, all of it where it ended.
 */
static void UpdatePage(void)
{
    static const s8 sArrowRows[] = {0, 1, 2, 1};
    const u8 *cur;
    u8 state, arrow;
    u32 end, clears = 0, scrolls = 0, lastScrolls = 0;

    if (!CtrText_Progress(sMsg.window, &cur, &state, &arrow) || cur < sMsg.printed || cur > sMsg.printed + sMsg.length)
    {
        sMsg.printedTo = ~0u;
        sMsg.arrow = -1;
        return;
    }
    end = cur - sMsg.printed;
    for (u32 i = 0; i < end; i += Unit(sMsg.text + i))
    {
        if (sMsg.text[i] == CHAR_PROMPT_CLEAR)
        {
            ++clears;
            lastScrolls = scrolls;
            scrolls = 0;
        }
        else if (sMsg.text[i] == CHAR_PROMPT_SCROLL)
            ++scrolls;
    }
    if (state == RENDER_STATE_CLEAR && clears)
    {
        --clears;
        scrolls = lastScrolls;
    }
    else if (state == RENDER_STATE_SCROLL_START && scrolls)
        --scrolls;
    sMsg.page = clears;
    sMsg.scrolls = min(scrolls, 63);
    sMsg.printedTo = CtrExtras_Get("reading_typeout") ? end : ~0u;
    sMsg.arrow = (state == RENDER_STATE_CLEAR || state == RENDER_STATE_SCROLL_START) && !gTextFlags.autoScroll
               ? sArrowRows[(arrow + 3) & 3] : -1;
}

u32 CtrReading_Stamp(void)
{
    if (!sMsg.on)
        return 0;
    if (gMain.callback2 != sMsg.callback2 || gMain.inBattle != sMsg.inBattle
     || (gMain.callback2 == CB2_Overworld && !ArePlayerFieldControlsLocked() && !ScriptContext_IsEnabled()))
    {
        sMsg.on = FALSE;
        return 0;
    }
    UpdatePage();
    return (sMsg.serial << 12) | ((sMsg.page & 63) << 6) | sMsg.scrolls;
}

/* ------------------------------------------------------------------------ */
/* Drawing                                                                  */
/* ------------------------------------------------------------------------ */

/* Between a word's readings and its kanji, under each line, and between two
 * words' readings side by side. */
#define RUBY_GAP 2
#define LINE_GAP 5
#define RUBY_SPACE 3
/* The down arrow: twice the game's size, as the box's frame, a little after
 * the text. */
#define ARROW_SCALE 2
#define ARROW_GAP 3

/* The box the page is in (CtrReading_Draw), kept for the frames after. */
static struct
{
    u16 *canvas;
    int w, h, x0, y0, x1, y1;
    u16 pal[16];
    bool8 valid;
} sBox;
/* The faces the page is set in. */
static const Face *sText, *sRuby;
/* What a frame changed: [0, 2) x [1, 3). */
static int sDirty[4];

static void Dirty(int x0, int y0, int x1, int y1)
{
    sDirty[0] = min(sDirty[0], x0);
    sDirty[1] = min(sDirty[1], y0);
    sDirty[2] = max(sDirty[2], x1);
    sDirty[3] = max(sDirty[3], y1);
}

static void Put(int x, int y, u16 colour)
{
    if (x >= 0 && x < sBox.w && y >= 0 && y < sBox.h)
        sBox.canvas[x * sBox.h + (sBox.h - 1 - y)] = colour;
}

static const Glyph *FindGlyph(const Face *f, u16 code)
{
    int lo = 0, hi = f->count;

    while (lo < hi)
    {
        int mid = (lo + hi) / 2;

        if (f->glyphs[mid].code < code)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < f->count && f->glyphs[lo].code == code ? &f->glyphs[lo] : NULL;
}

static int Advance(const Face *f, u16 code)
{
    const Glyph *g;

    /* The game's word gap, the full-width space, at half its width. */
    if (code == 0x3000)
        return f->size / 2;
    g = FindGlyph(f, code);
    return g ? g->advance : f->size;
}

/* `a` sixteenths of `src` over `dst`, in RGB565. */
static u16 Blend(u16 dst, u16 src, u32 a)
{
    u32 r = ((dst >> 11) * (15 - a) + (src >> 11) * a + 7) / 15;
    u32 g = (((dst >> 5) & 63) * (15 - a) + ((src >> 5) & 63) * a + 7) / 15;
    u32 b = ((dst & 31) * (15 - a) + (src & 31) * a + 7) / 15;

    return (u16)((r << 11) | (g << 5) | b);
}

static void DrawGlyph(const Face *f, u16 code, int x, int top, u16 colour)
{
    const Glyph *g = FindGlyph(f, code);
    const u8 *row;
    int rowBytes;

    if (!g || !g->w || !g->h)
        return;
    rowBytes = (g->w + 1) / 2;
    if (g->offset + (u32)g->h * rowBytes > f->dataSize)
        return;
    row = f->data + g->offset;
    for (int y = 0; y < g->h; ++y, row += rowBytes)
    {
        int py = top + g->y + y;

        if (py < 0 || py >= sBox.h)
            continue;
        for (int i = 0; i < g->w; ++i)
        {
            u32 a = i & 1 ? row[i >> 1] & 15 : row[i >> 1] >> 4;
            int px = x + g->x + i;

            if (a && px >= 0 && px < sBox.w)
            {
                u16 *d = &sBox.canvas[px * sBox.h + (sBox.h - 1 - py)];

                *d = a == 15 ? colour : Blend(*d, colour, a);
            }
        }
    }
    Dirty(x + g->x, top + g->y, x + g->x + g->w, top + g->y + g->h);
}

/* A character in the box's text colour, over its shadow a pixel right and
 * down, as the game's text has it. */
static void DrawChar(const Face *f, u16 code, int x, int top)
{
    DrawGlyph(f, code, x + 1, top + 1, sBox.pal[3]);
    DrawGlyph(f, code, x, top, sBox.pal[2]);
}

/* What a page is laid out in: characters, words in kanji with their
 * readings, line breaks; each with where in the printed text it appears. */
enum { PIECE_CHAR, PIECE_RUBY, PIECE_BREAK };

typedef struct
{
    u8 kind, baseCount, readingCount;
    u16 code, at;
    u16 readingAt;              /* PIECE_RUBY: its readings' places, in sReadingAt */
    const u16 *base, *reading;
} Piece;

#define MAX_PIECES 512
static Piece sPieces[MAX_PIECES];
static int sPieceCount;
static u16 sReadingAt[1024];
static int sReadingAtCount;

static void AddPiece(u8 kind, u16 code, u32 at)
{
    if (sPieceCount < MAX_PIECES)
    {
        sPieces[sPieceCount].kind = kind;
        sPieces[sPieceCount].code = code;
        sPieces[sPieceCount].at = at;
        ++sPieceCount;
    }
}

/* From e, past what prints nothing (a colour, a pause), to the printed text's
 * next character. */
static u32 NextShown(u32 e)
{
    while (e < sMsg.length && sMsg.text[e] == EXT_CTRL_CODE_BEGIN)
        e += Unit(sMsg.text + e);
    return e;
}

/* A placeholder's value, as the game printed it. */
static void AddHole(int hole)
{
    u32 e = sMsg.holes[hole].start, end = e + sMsg.holes[hole].length;

    for (; e < end; e += Unit(sMsg.text + e))
    {
        u8 c = sMsg.text[e];

        if (c < CHAR_DYNAMIC && sData.gameMap[c])
            AddPiece(PIECE_CHAR, sData.gameMap[c], e);
    }
}

/* The page with something on it at or before the printer's: a message that
 * ends with a page break has an empty one after it. */
static u16 ChoosePage(u16 page)
{
    const u16 *t = sMsg.tokens, *end = sMsg.tokens + sMsg.count;
    u16 p = 0, chosen = 0;
    bool8 filled = FALSE;

    for (; t <= end && p <= page; ++t)
    {
        if (t == end || *t == TOK_PAGE)
        {
            if (filled)
                chosen = p;
            ++p;
            filled = FALSE;
        }
        else
            filled = TRUE;
    }
    return chosen;
}

/*
 * The pieces of page `page`, each with where in the printed text it appears.
 * The tokens and the printed text are walked together: a token's character
 * stands for a printed one, a word's reading for its kana, a run of
 * placeholders for what the game expanded it to, an icon for its two bytes,
 * a break for the game's; a colour or a pause has no token.
 */
static void BuildPieces(u16 page)
{
    const u16 *t = sMsg.tokens, *end = sMsg.tokens + sMsg.count;
    u32 e = 0;
    u16 p = 0;

    sPieceCount = 0;
    sReadingAtCount = 0;
    while (t < end && p <= page)
    {
        u16 c = *t++;
        bool8 here = p == page;

        if (c == TOK_PAGE || c == TOK_NEWLINE || c == TOK_SCROLL)
        {
            e = NextShown(e) + 1;
            if (c == TOK_PAGE)
                ++p;
            else if (here)
                AddPiece(PIECE_BREAK, 0, e);
        }
        else if (c >= TOK_HOLE && c < TOK_HOLE_END)
        {
            int hole = c - TOK_HOLE;

            if (hole < sMsg.holeCount)
            {
                if (here)
                    AddHole(hole);
                e = sMsg.holes[hole].start + sMsg.holes[hole].length;
            }
        }
        else if (c >= TOK_ICON && c < TOK_ICON_END)
        {
            u32 at = NextShown(e);

            for (int n = c - TOK_ICON; n > 0 && t < end; --n, ++t)
                if (here)
                    AddPiece(PIECE_CHAR, *t, at);
            e = at + 2;
        }
        else if (c == TOK_RUBY)
        {
            const u16 *base = t, *reading;
            int first = sReadingAtCount;

            while (t < end && *t != TOK_RUBY_TEXT)
                ++t;
            reading = ++t;
            for (; t < end && *t != TOK_RUBY_END; ++t)
            {
                e = NextShown(e);
                if (here && sReadingAtCount < (int)ARRAY_COUNT(sReadingAt))
                    sReadingAt[sReadingAtCount++] = e;
                ++e;
            }
            if (here && sPieceCount < MAX_PIECES && t > reading && sReadingAtCount - first == t - reading)
            {
                Piece *u = &sPieces[sPieceCount++];

                u->kind = PIECE_RUBY;
                u->base = base;
                u->baseCount = reading - 1 - base;
                u->reading = reading;
                u->readingCount = t - reading;
                u->readingAt = first;
                /* The word in kanji with the first kana of its reading. */
                u->at = sReadingAt[first];
            }
            ++t;
        }
        else if (c < TOK_RUBY || c > 0xF8FF)
        {
            e = NextShown(e);
            if (here)
                AddPiece(PIECE_CHAR, c, e);
            ++e;
        }
    }
}

static int BaseWidth(const Piece *u)
{
    int w = 0;

    for (int i = 0; i < u->baseCount; ++i)
        w += Advance(sText, u->base[i]);
    return w;
}

static int ReadingWidth(const Piece *u)
{
    int w = 0;

    for (int i = 0; i < u->readingCount; ++i)
        w += Advance(sRuby, u->reading[i]);
    return w;
}

/* The game's word gap: a full-width space. */
static bool8 IsSpace(int i)
{
    return sPieces[i].kind == PIECE_CHAR && sPieces[i].code == 0x3000;
}

/* The width piece i takes, and how far into it its kanji start. A reading
 * wider than its kanji reaches over the kana beside them, up to half a
 * reading's character either side; the rest is room around the kanji. */
static int PieceWidth(int i, bool8 lineStart, int *padLeft)
{
    const Piece *u = &sPieces[i];
    int reach = sRuby->size / 2, baseW, over, left, right, padL, padR;

    *padLeft = 0;
    if (u->kind == PIECE_CHAR)
        return Advance(sText, u->code);
    if (u->kind == PIECE_BREAK)
        return 0;
    baseW = BaseWidth(u);
    over = ReadingWidth(u) - baseW;
    left = over > 0 ? over / 2 : 0;
    right = over > 0 ? over - left : 0;
    padL = left - (!lineStart && i > 0 && sPieces[i - 1].kind == PIECE_CHAR ? min(left, reach) : 0);
    padR = right - (i + 1 < sPieceCount && sPieces[i + 1].kind == PIECE_CHAR ? min(right, reach) : 0);
    *padLeft = padL;
    return padL + baseW + padR;
}

/* The width of the phrase from piece i to the next word gap or line break. */
static int PhraseWidth(int i, bool8 lineStart)
{
    int w = 0, pad;

    for (int k = i; k < sPieceCount && sPieces[k].kind != PIECE_BREAK && !IsSpace(k); ++k)
        w += PieceWidth(k, lineStart && k == i, &pad);
    return w;
}

/* A line's ink: its readings, the gap, its text. */
static int LineInk(void)
{
    return (sRuby->inkBottom - sRuby->inkTop) + RUBY_GAP + (sText->inkBottom - sText->inkTop);
}

/* Each glyph of the page where it goes, with where in the printed text it
 * appears, and whether it is on the screen yet. */
typedef struct
{
    u16 at, code;
    s16 x, top;
    u8 ruby, drawn;
} Item;

#define MAX_ITEMS 1024
static Item sItems[MAX_ITEMS];
static int sItemCount, sItemsLeft;
/* Where the text ends, after its last character: the down arrow's place. */
static int sEndX, sEndY;

static void AddItem(u16 at, u16 code, int x, int top, bool8 ruby)
{
    if (sItemCount < MAX_ITEMS)
    {
        sItems[sItemCount] = (Item){at, code, x, top, ruby, FALSE};
        ++sItemCount;
    }
}

static void PlacePiece(const Piece *u, int x, int y, int padLeft)
{
    int textTop = y + (sRuby->inkBottom - sRuby->inkTop) + RUBY_GAP - sText->inkTop;

    if (u->kind == PIECE_CHAR)
        AddItem(u->at, u->code, x, textTop, FALSE);
    else if (u->kind == PIECE_RUBY)
    {
        int bx = x + padLeft, rx = bx + BaseWidth(u) / 2 - ReadingWidth(u) / 2;

        for (int i = 0; i < u->baseCount; bx += Advance(sText, u->base[i]), ++i)
            AddItem(u->at, u->base[i], bx, textTop, FALSE);
        for (int k = 0; k < u->readingCount; rx += Advance(sRuby, u->reading[k]), ++k)
            AddItem(sReadingAt[u->readingAt + k], u->reading[k], rx, y - sRuby->inkTop, TRUE);
    }
}

/*
 * Lays out the page from (x0, y0), `width` wide and at most `lines` lines,
 * and places its glyphs if `place`; the lines it takes, or more than `lines`
 * if it does not fit. Lines wrap at the game's word gaps, as its own lines
 * break: a phrase that would run past the edge starts the next line, unless
 * it is longer than a line, and a wrapped line does not start with a gap. Two
 * words' readings side by side keep RUBY_SPACE between them.
 */
static int Layout(int x0, int y0, int width, int lines, bool8 place)
{
    int x = 0, line = 0, rubyEnd = -1, pitch = LineInk() + LINE_GAP;

    for (int i = 0; i < sPieceCount; ++i)
    {
        int w, padL;

        if (sPieces[i].kind == PIECE_BREAK)
        {
            x = 0;
            ++line;
            continue;
        }
        if (x > 0 && IsSpace(i - 1) && !IsSpace(i) && x + PhraseWidth(i, FALSE) > width
         && PhraseWidth(i, TRUE) <= width)
        {
            x = 0;
            ++line;
        }
        if (x == 0 && i > 0 && IsSpace(i) && sPieces[i - 1].kind != PIECE_BREAK)
            continue;
        w = PieceWidth(i, x == 0, &padL);
        if (x + w > width && x > 0)
        {
            x = 0;
            ++line;
            w = PieceWidth(i, TRUE, &padL);
        }
        if (x == 0)
            rubyEnd = -1;
        if (sPieces[i].kind == PIECE_RUBY)
        {
            const Piece *u = &sPieces[i];
            int rx = x + padL + BaseWidth(u) / 2 - ReadingWidth(u) / 2;

            if (rubyEnd >= 0 && rx < rubyEnd + RUBY_SPACE && i > 0 && sPieces[i - 1].kind == PIECE_RUBY)
            {
                x += rubyEnd + RUBY_SPACE - rx;
                rx = rubyEnd + RUBY_SPACE;
            }
            rubyEnd = rx + ReadingWidth(u);
        }
        if (place && line < lines)
        {
            PlacePiece(&sPieces[i], x0 + x, y0 + line * pitch, padL);
            sEndX = x0 + x + w;
            sEndY = y0 + line * pitch;
        }
        x += w;
    }
    return line + 1;
}

/* The lines a height holds in the faces the page is set in. */
static int LinesIn(int height)
{
    return height < LineInk() ? 0 : (height - LineInk()) / (LineInk() + LINE_GAP) + 1;
}

/* The page without its first line. */
static void DropLine(void)
{
    int i = 0;

    while (i < sPieceCount && sPieces[i].kind != PIECE_BREAK)
        ++i;
    if (i < sPieceCount)
        ++i;
    memmove(sPieces, sPieces + i, (sPieceCount - i) * sizeof(Piece));
    sPieceCount -= i;
}

/* Draws the glyphs the printer has printed that are not on the screen yet. */
static void DrawPrinted(void)
{
    for (int i = 0; i < sItemCount; ++i)
    {
        Item *it = &sItems[i];

        if (it->drawn || it->at >= sMsg.printedTo)
            continue;
        DrawChar(it->ruby ? sRuby : sText, it->code, it->x, it->top);
        it->drawn = TRUE;
        --sItemsLeft;
    }
}

/* The down arrow's place, after the text with its middle on the text's (its
 * ink is rows 5-12 of its 16), and the row it is shown from on the screen
 * (-1: none). */
static int sArrowX, sArrowY;
static s8 sArrowShown;

/* As text.c's TextPrinterDrawDownArrow: the picture's rows from `from` on, 16
 * of them, so the arrow bounces up as `from` grows. */
static void DrawArrow(s8 from)
{
    const u8 *tiles = sData.arrows[gTextFlags.useAlternateDownArrow ? 1 : 0];
    int w = 8 * ARROW_SCALE, h = 16 * ARROW_SCALE;

    if (sArrowShown >= 0)
    {
        for (int x = sArrowX; x < sArrowX + w; ++x)
            for (int y = sArrowY; y < sArrowY + h; ++y)
                Put(x, y, sBox.pal[1]);
        Dirty(sArrowX, sArrowY, sArrowX + w, sArrowY + h);
    }
    sArrowShown = from;
    if (from < 0 || !tiles)
        return;
    for (int r = 0; r < 16; ++r)
    {
        int row = from + r;

        for (int c = 0; c < 8; ++c)
        {
            u8 b = tiles[(row / 8) * 32 + (row & 7) * 4 + c / 2], v = c & 1 ? b >> 4 : b & 15;

            for (int k = 0; v && k < ARROW_SCALE * ARROW_SCALE; ++k)
                Put(sArrowX + c * ARROW_SCALE + k % ARROW_SCALE, sArrowY + r * ARROW_SCALE + k / ARROW_SCALE,
                    sBox.pal[v]);
        }
    }
    Dirty(sArrowX, sArrowY, sArrowX + w, sArrowY + h);
}

/* The arrow the printer shows, once the page is out. */
static void UpdateArrow(void)
{
    s8 from = sItemsLeft > 0 ? -1 : sMsg.arrow;

    if (from != sArrowShown)
        DrawArrow(from);
}

void CtrReading_Draw(u16 *canvas, int width, int height, int x0, int y0, int x1, int y1, const u16 *pal)
{
    int middle;

    sBox.canvas = canvas;
    sBox.w = width;
    sBox.h = height;
    sBox.x0 = x0;
    sBox.y0 = y0;
    sBox.x1 = x1;
    sBox.y1 = y1;
    memcpy(sBox.pal, pal, sizeof(sBox.pal));
    sBox.valid = FALSE;
    if (!sMsg.on || !sData.table)
        return;
    BuildPieces(ChoosePage(sMsg.page));
    /* The large faces if the page fits in them, else the small ones. */
    sText = &sData.faces[FACE_TEXT];
    sRuby = &sData.faces[FACE_RUBY];
    if (Layout(x0, y0, x1 - x0, 0x7FFF, FALSE) > LinesIn(y1 - y0))
    {
        sText = &sData.faces[FACE_TEXT_SMALL];
        sRuby = &sData.faces[FACE_RUBY_SMALL];
    }
    /* A page longer than the box even so (a long scrolling one): from the
     * line the top screen has scrolled to, as far back as there is room. */
    for (int skip = 0; skip < sMsg.scrolls && Layout(x0, y0, x1 - x0, 0x7FFF, FALSE) > LinesIn(y1 - y0); ++skip)
        DropLine();
    sItemCount = 0;
    sEndX = x0;
    sEndY = y0;
    Layout(x0, y0, x1 - x0, LinesIn(y1 - y0), TRUE);
    sItemsLeft = sItemCount;
    middle = sEndY + (sRuby->inkBottom - sRuby->inkTop) + RUBY_GAP + (sText->inkBottom - sText->inkTop) / 2;
    sArrowX = min(sEndX + ARROW_GAP, x1 + 4 - 8 * ARROW_SCALE);
    sArrowY = middle - 9 * ARROW_SCALE;
    sArrowShown = -1;
    sBox.valid = TRUE;
    DrawPrinted();
    UpdateArrow();
}

bool CtrReading_Advance(int rect[4])
{
    if (!sBox.valid || !sMsg.on)
        return FALSE;
    sDirty[0] = sDirty[1] = 0x7FFF;
    sDirty[2] = sDirty[3] = -0x7FFF;
    DrawPrinted();
    UpdateArrow();
    rect[0] = max(sDirty[0], 0);
    rect[1] = max(sDirty[1], 0);
    rect[2] = min(sDirty[2], sBox.w);
    rect[3] = min(sDirty[3], sBox.h);
    return rect[0] < rect[2] && rect[1] < rect[3];
}
