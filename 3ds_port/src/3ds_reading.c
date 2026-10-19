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
 * one it waits at. The pane goes as the text does on the top screen: when its
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
#include "3ds_log.h"
#include "3ds_reading.h"

/* text.c: where a window's printer is in its text and what it does; FALSE
 * once it is done. */
bool8 CtrText_Progress(u8 windowId, const u8 **currentChar, u8 *state);

/* scripts/gen_furigana.py's formats. */
#define TABLE_MAGIC 0x33544746  /* "FGT3" */
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
    u8 state;

    if (!sMsg.on || windowId != sMsg.window)
        return;
    /* A printer wipes its own window at a page break: the message goes on. */
    if (!hidden && CtrText_Progress(windowId, &cur, &state))
        return;
    sMsg.on = FALSE;
}

/* The page the printer is on, the page breaks behind it less the one it waits
 * at, and the lines it has scrolled on that page, the same way. Once it is
 * done, where it ended. */
static void UpdatePage(void)
{
    const u8 *cur;
    u8 state;
    u32 end, clears = 0, scrolls = 0, lastScrolls = 0;

    if (!CtrText_Progress(sMsg.window, &cur, &state) || cur < sMsg.printed || cur > sMsg.printed + sMsg.length)
        return;
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

static u16 *sCanvas;
static int sW, sH;
static u16 sFg, sShadow;
/* The faces a page is set in. */
static const Face *sText, *sRuby;

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

        if (py < 0 || py >= sH)
            continue;
        for (int i = 0; i < g->w; ++i)
        {
            u32 a = i & 1 ? row[i >> 1] & 15 : row[i >> 1] >> 4;
            int px = x + g->x + i;

            if (a && px >= 0 && px < sW)
            {
                u16 *d = &sCanvas[px * sH + (sH - 1 - py)];

                *d = a == 15 ? colour : Blend(*d, colour, a);
            }
        }
    }
}

/* A character in the box's text colour, over its shadow a pixel right and
 * down, as the game's text has it. */
static void DrawChar(const Face *f, u16 code, int x, int top)
{
    DrawGlyph(f, code, x + 1, top + 1, sShadow);
    DrawGlyph(f, code, x, top, sFg);
}

/* What a page is laid out in: characters, words in kanji with their
 * readings, line breaks. */
enum { PIECE_CHAR, PIECE_RUBY, PIECE_BREAK };

typedef struct
{
    u8 kind, baseCount, readingCount;
    u16 code;
    const u16 *base, *reading;
} Piece;

#define MAX_PIECES 512
static Piece sPieces[MAX_PIECES];
static int sPieceCount;

static void AddPiece(u8 kind, u16 code)
{
    if (sPieceCount < MAX_PIECES)
    {
        sPieces[sPieceCount].kind = kind;
        sPieces[sPieceCount].code = code;
        ++sPieceCount;
    }
}

/* A placeholder's value, as the game printed it. */
static void AddHole(int hole)
{
    const u8 *s, *end;

    if (hole >= sMsg.holeCount)
        return;
    s = sMsg.text + sMsg.holes[hole].start;
    end = s + sMsg.holes[hole].length;
    for (; s < end; s += Unit(s))
    {
        if (*s < CHAR_DYNAMIC && sData.gameMap[*s])
            AddPiece(PIECE_CHAR, sData.gameMap[*s]);
    }
}

static void BuildPieces(const u16 *t, u16 count)
{
    const u16 *end = t + count;

    sPieceCount = 0;
    while (t < end)
    {
        u16 c = *t++;

        if (c == TOK_NEWLINE || c == TOK_SCROLL)
            AddPiece(PIECE_BREAK, 0);
        else if (c >= TOK_HOLE && c < TOK_HOLE_END)
            AddHole(c - TOK_HOLE);
        else if (c == TOK_RUBY && sPieceCount < MAX_PIECES)
        {
            Piece *u = &sPieces[sPieceCount];
            const u16 *base = t;

            while (t < end && *t != TOK_RUBY_TEXT)
                ++t;
            u->base = base;
            u->baseCount = t - base;
            u->reading = ++t;
            while (t < end && *t != TOK_RUBY_END)
                ++t;
            u->readingCount = t - u->reading;
            u->kind = PIECE_RUBY;
            ++sPieceCount;
            ++t;
        }
        else if (c < TOK_RUBY || c > 0xF8FF)
            AddPiece(PIECE_CHAR, c);
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

static void DrawPiece(const Piece *u, int x, int y, int padLeft)
{
    int textTop = y + (sRuby->inkBottom - sRuby->inkTop) + RUBY_GAP - sText->inkTop;

    if (u->kind == PIECE_CHAR)
        DrawChar(sText, u->code, x, textTop);
    else if (u->kind == PIECE_RUBY)
    {
        int bx = x + padLeft, rx = bx + BaseWidth(u) / 2 - ReadingWidth(u) / 2;

        for (int i = 0; i < u->baseCount; bx += Advance(sText, u->base[i]), ++i)
            DrawChar(sText, u->base[i], bx, textTop);
        for (int k = 0; k < u->readingCount; rx += Advance(sRuby, u->reading[k]), ++k)
            DrawChar(sRuby, u->reading[k], rx, y - sRuby->inkTop);
    }
}

/*
 * Lays out the page from (x0, y0), `width` wide and at most `lines` lines,
 * and draws it if `draw`; the lines it takes, or more than `lines` if it does
 * not fit. Lines wrap at the game's word gaps, as its own lines break: a
 * phrase that would run past the edge starts the next line, unless it is
 * longer than a line, and a wrapped line does not start with a gap. Two
 * words' readings side by side keep RUBY_SPACE between them.
 */
static int Layout(int x0, int y0, int width, int lines, bool8 draw)
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
        if (draw && line < lines)
            DrawPiece(&sPieces[i], x0 + x, y0 + line * pitch, padL);
        x += w;
    }
    return line + 1;
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

/* The lines a height holds in the faces the page is set in. */
static int LinesIn(int height)
{
    return height < LineInk() ? 0 : (height - LineInk()) / (LineInk() + LINE_GAP) + 1;
}

/* The tokens of page `page`, the last one with something on it if there are
 * fewer. */
static const u16 *PageTokens(u16 page, u16 *count)
{
    const u16 *start = sMsg.tokens, *end = sMsg.tokens + sMsg.count, *t;
    const u16 *chosen = start, *chosenEnd = end;
    u16 n = 0;

    for (t = start; t <= end; ++t)
    {
        if (t == end || *t == TOK_PAGE)
        {
            if (t > start)
            {
                if (n <= page)
                {
                    chosen = start;
                    chosenEnd = t;
                }
                ++n;
            }
            start = t + 1;
        }
    }
    *count = chosenEnd - chosen;
    return chosen;
}

void CtrReading_Draw(u16 *canvas, int width, int height, int x0, int y0, int x1, int y1, u16 fg, u16 shadow)
{
    u16 count;
    const u16 *t;

    sCanvas = canvas;
    sW = width;
    sH = height;
    sFg = fg;
    sShadow = shadow;
    if (!sMsg.on || !sData.table)
        return;
    t = PageTokens(sMsg.page, &count);
    BuildPieces(t, count);
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
    Layout(x0, y0, x1 - x0, LinesIn(y1 - y0), TRUE);
}
