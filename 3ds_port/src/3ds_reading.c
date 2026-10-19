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
 * the game's bytes for each message's template to its tokens and the
 * dictionary word of each of its kanji groups, and furigana/font.bin holds
 * its glyphs, M PLUS Rounded 1c rendered at the screen's own resolution with
 * 16 levels of ink: the text at 24 pixels with its readings at 12, and 18 and
 * 10 for a page too long for those. The text has the game's colours and
 * shadow. furigana/dict.bin has the words' readings and glosses (JMdict) and
 * their kanji's details (KANJIDIC2), furigana/english.bin each message's
 * English line. All are optional data: without the table CtrReading_Stamp is
 * always 0 and the bottom screen is as it was; without the dictionary a tapped
 * word shows its kanji and reading only.
 *
 * The game tells this file what it prints (text.c's AddTextPrinter) and what
 * it expanded into the buffers it prints from (StringExpandPlaceholders,
 * BattleStringExpandPlaceholders, DynamicPlaceholderTextUtil_ExpandPlaceholders).
 * A printed text that is a template of the table, or a buffer expanded from
 * one, is the message on show. The values of its placeholders - the player's
 * name, a Pokémon's - are read off the printed text by matching the template's
 * own bytes around them, and drawn as the game printed them.
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
 * A tap on a word in kanji opens a small box over the pane with its reading
 * and meaning, and a tap on the box goes through its kanji (readings, strokes,
 * school grade) and back; a tap elsewhere closes it. Each word opened is
 * written to the word log, sdmc:/3ds/emerald3ds/words.tsv, with the sentence
 * and its English line, for Anki. The last messages stay in a backlog: a pull
 * down on the pane, or from the top edge of the bottom screen in the field
 * and in a battle, shows them all, the newest last, to scroll through and tap
 * as the pane, in a box of its own colours with りれき under it; a pull back up
 * past the newest, the next message or another screen closes it.
 *
 * The pane goes as the text does on the top screen: when its
 * window is wiped once the message is printed or taken off the screen
 * (window.c, the message box closing among them), when another text replaces
 * it there, when the screen that printed it goes, and in the field when the
 * player can move again.
 */
#include <stdio.h>
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
#define TABLE_MAGIC 0x35544746  /* "FGT5" */
#define FONT_MAGIC 0x33464746   /* "FGF3" */
#define DICT_MAGIC 0x31444746   /* "FGD1" */
#define ENGLISH_MAGIC 0x31454746 /* "FGE1" */
#define TABLE_HEADER 16
#define GAME_MAP_SIZE (256 * 2)
#define FACE_HEADER 12
#define DICT_HEADER 16
#define NO_WORD 0xFFFF

#ifndef CTR_READING_LOG_PATH
#define CTR_READING_LOG_PATH CTR_DATA_DIR "words.tsv"
#endif

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

/* A kanji of dict.bin. */
typedef struct
{
    u16 code;
    u8 strokes, grade;
    u32 offset;
} Kanji;

static struct
{
    u8 *table, *font, *dict;
    u32 count, blobSize;
    const u16 *gameMap;
    const Entry *index;
    const u8 *blob;
    Face faces[FACE_COUNT];
    /* The game's down arrow and its dark one: three frames of 8x16, 4bpp. */
    u8 *arrows[2];
    /* The dictionary: each word's place in the strings, each kanji. */
    u32 wordCount, kanjiCount, stringsSize;
    const u32 *words;
    const Kanji *kanji;
    const u8 *strings;
} sData;

#define MAX_TEXT 1024
#define MAX_HOLES 16

typedef struct
{
    u16 start, length;
} Span;

/* A message as printed: its tokens and the word of each of its groups, the
 * text the game printed (its placeholders' values read off it) and its place
 * in the table, for its English line. */
typedef struct
{
    const u16 *tokens, *words;
    u16 count, wordCount, length;
    u32 entry;
    u8 holeCount;
    Span holes[MAX_HOLES];
    u8 text[MAX_TEXT];
} Message;

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
    /* What the printer reads; the message keeps a copy of it, as its buffer
     * may be written again while the pane still shows it. */
    const u8 *printed;
    u32 serial;
    Message m;
} sMsg;

/* The backlog: the last messages, the oldest at sLogNext once it is full. */
#define BACKLOG 32
static Message sLog[BACKLOG];
static int sLogCount, sLogNext;

/* What has the screen besides the page: the backlog, scrolled `scroll`
 * pixels back from its end, and the word box. `version` changes with either,
 * for the bottom screen to draw them. */
static struct
{
    bool8 backlog;
    int scroll, height;
    MainCallback callback2;
    u32 version;
} sView;

static struct
{
    bool8 on, top;
    u8 page, baseCount, readingCount;
    u16 word;
    const u16 *base, *reading;
    const Message *msg;
    /* Where it was drawn, for the taps on it. */
    int x0, y0, x1, y1;
} sPopup;

/* The latest expansions, newest last: a printed buffer is looked up here for
 * the template it came from. */
#define EXPANDED_KEEP 8
static struct
{
    const u8 *dest, *src;
} sExpanded[EXPANDED_KEEP];
static u8 sExpandedNext;

static void Changed(void)
{
    ++sView.version;
}

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
    free(sData.dict);
    free(sData.arrows[0]);
    free(sData.arrows[1]);
    memset(&sData, 0, sizeof(sData));
}

/* dict.bin, if the player's data has it: a tapped word's reading and meaning. */
static void LoadDictionary(void)
{
    u32 size = 0, magic, header[3];

    if (!CtrData_Exists("furigana/dict.bin") || !(sData.dict = CtrData_Load("furigana/dict.bin", &size)))
        return;
    memcpy(&magic, sData.dict, 4);
    if (size >= DICT_HEADER)
        memcpy(header, sData.dict + 4, sizeof(header));
    if (magic != DICT_MAGIC || size < DICT_HEADER
     || (u64)DICT_HEADER + (u64)header[0] * 4 + (u64)header[1] * sizeof(Kanji) + header[2] > size)
    {
        CtrLog_Write(CTR_LOG_ERROR, "reading pane: furigana/dict.bin is not a dictionary");
        free(sData.dict);
        sData.dict = NULL;
        return;
    }
    sData.wordCount = header[0];
    sData.kanjiCount = header[1];
    sData.stringsSize = header[2];
    sData.words = (const u32 *)(sData.dict + DICT_HEADER);
    sData.kanji = (const Kanji *)(sData.words + sData.wordCount);
    sData.strings = (const u8 *)(sData.kanji + sData.kanjiCount);
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
    LoadDictionary();
    CtrLog_Write(CTR_LOG_GAME, "reading pane: %lu messages, %u characters, %u for readings, %lu words",
                 (unsigned long)sData.count, sData.faces[FACE_TEXT].count, sData.faces[FACE_RUBY].count,
                 (unsigned long)sData.wordCount);
}

void CtrReading_Reset(void)
{
    sMsg.on = FALSE;
    sPopup.on = FALSE;
    sView.backlog = FALSE;
    sLogCount = sLogNext = 0;
    memset(sExpanded, 0, sizeof(sExpanded));
    Changed();
}

/* A word of dict.bin: its dictionary form and reading (UCS-2), its gloss. */
static bool8 DictWord(u16 id, const u16 **word, u8 *wordLength, const u16 **reading, u8 *readingLength,
                      const char **gloss, u8 *glossLength)
{
    const u8 *s;

    if (!sData.dict || id >= sData.wordCount || sData.words[id] + 4 > sData.stringsSize)
        return FALSE;
    s = sData.strings + sData.words[id];
    if (sData.words[id] + 4 + (s[0] + s[1]) * 2 + s[2] > sData.stringsSize)
        return FALSE;
    *wordLength = s[0];
    *readingLength = s[1];
    *glossLength = s[2];
    *word = (const u16 *)(s + 4);
    *reading = *word + s[0];
    *gloss = (const char *)(*reading + s[1]);
    return TRUE;
}

/* A kanji of dict.bin: its on and kun readings (、 between) and meaning. */
static const Kanji *DictKanji(u16 code, const u16 **on, u8 *onLength, const u16 **kun, u8 *kunLength,
                              const char **meaning, u8 *meaningLength)
{
    int lo = 0, hi = sData.dict ? (int)sData.kanjiCount : 0;
    const u8 *s;

    while (lo < hi)
    {
        int mid = (lo + hi) / 2;

        if (sData.kanji[mid].code < code)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (!sData.dict || lo >= (int)sData.kanjiCount || sData.kanji[lo].code != code
     || sData.kanji[lo].offset + 4 > sData.stringsSize)
        return NULL;
    s = sData.strings + sData.kanji[lo].offset;
    if (sData.kanji[lo].offset + 4 + (s[0] + s[1]) * 2 + s[2] > sData.stringsSize)
        return NULL;
    *onLength = s[0];
    *kunLength = s[1];
    *meaningLength = s[2];
    *on = (const u16 *)(s + 4);
    *kun = *on + s[0];
    *meaning = (const char *)(*kun + s[1]);
    return &sData.kanji[lo];
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

/* The table's message for a template: its tokens and words, and its place. */
static bool8 Find(u64 key, Message *m)
{
    u32 lo = 0, hi = sData.count, keyLo = (u32)key, keyHi = (u32)(key >> 32), offset;
    u16 n, words;

    while (lo < hi)
    {
        u32 mid = (lo + hi) / 2;
        const Entry *e = &sData.index[mid];

        if (e->hi < keyHi || (e->hi == keyHi && e->lo < keyLo))
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo >= sData.count || sData.index[lo].hi != keyHi || sData.index[lo].lo != keyLo)
        return FALSE;
    offset = sData.index[lo].offset;
    if (offset + 2 > sData.blobSize)
        return FALSE;
    memcpy(&n, sData.blob + offset, 2);
    if (offset + 4 + (u32)n * 2 > sData.blobSize)
        return FALSE;
    memcpy(&words, sData.blob + offset + 2 + (u32)n * 2, 2);
    if (offset + 4 + ((u32)n + words) * 2 > sData.blobSize)
        return FALSE;
    m->tokens = (const u16 *)(sData.blob + offset + 2);
    m->count = n;
    m->words = m->tokens + n + 1;
    m->wordCount = words;
    m->entry = lo;
    return TRUE;
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

/* The new message on show joins the backlog. */
static void Log(const Message *m)
{
    sLog[sLogNext] = *m;
    sLogNext = (sLogNext + 1) % BACKLOG;
    if (sLogCount < BACKLOG)
        ++sLogCount;
}

static bool8 Show(u8 windowId, const u8 *tmpl, const u8 *printed)
{
    static unsigned mismatches;
    static Message m;
    Span lits[MAX_HOLES + 1], found[MAX_HOLES];
    u32 tlen = Length(tmpl), elen;
    int holes;

    if (tlen >= MAX_TEXT || !Find(Hash(tmpl, tlen), &m))
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
    memcpy(m.text, printed, elen);
    m.text[elen] = EOS;
    memcpy(m.holes, found, sizeof(Span) * holes);
    m.holeCount = holes;
    m.length = elen;
    sMsg.m = m;
    Log(&m);
    sMsg.printed = printed;
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
    /* The next message closes the word box and the backlog: the pane has the
     * screen again. */
    sPopup.on = FALSE;
    sView.backlog = FALSE;
    Changed();
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

static void Hide(void)
{
    if (sMsg.on && sPopup.on && sPopup.msg == &sMsg.m)
        sPopup.on = FALSE;
    sMsg.on = FALSE;
    Changed();
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
            Hide();
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
        Hide();
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
    Hide();
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

    if (!CtrText_Progress(sMsg.window, &cur, &state, &arrow) || cur < sMsg.printed || cur > sMsg.printed + sMsg.m.length)
    {
        sMsg.printedTo = ~0u;
        sMsg.arrow = -1;
        return;
    }
    end = cur - sMsg.printed;
    for (u32 i = 0; i < end; i += Unit(sMsg.m.text + i))
    {
        if (sMsg.m.text[i] == CHAR_PROMPT_CLEAR)
        {
            ++clears;
            lastScrolls = scrolls;
            scrolls = 0;
        }
        else if (sMsg.m.text[i] == CHAR_PROMPT_SCROLL)
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
    if (sView.backlog && gMain.callback2 != sView.callback2)
    {
        sView.backlog = FALSE;
        sPopup.on = FALSE;
        Changed();
    }
    if (sMsg.on && (gMain.callback2 != sMsg.callback2 || gMain.inBattle != sMsg.inBattle
     || (gMain.callback2 == CB2_Overworld && !ArePlayerFieldControlsLocked() && !ScriptContext_IsEnabled())))
        Hide();
    if (sView.backlog)
        return 0x80000000u | (sMsg.on ? sMsg.serial : 0);
    if (!sMsg.on)
        return 0;
    UpdatePage();
    return (sMsg.serial << 12) | ((sMsg.page & 63) << 6) | sMsg.scrolls;
}

u32 CtrReading_View(void)
{
    return sView.version;
}

bool CtrReading_InBacklog(void)
{
    return sView.backlog;
}

bool CtrReading_OpenBacklog(void)
{
    if (!sData.table || sLogCount == 0)
        return FALSE;
    sView.backlog = TRUE;
    sView.scroll = 0;
    sView.callback2 = gMain.callback2;
    sPopup.on = FALSE;
    Changed();
    return TRUE;
}

/* ------------------------------------------------------------------------ */
/* Drawing                                                                  */
/* ------------------------------------------------------------------------ */

/* Between a word's readings and its kanji, under each line, and between two
 * words' readings side by side; between two messages of the backlog. */
#define RUBY_GAP 2
#define LINE_GAP 5
#define RUBY_SPACE 3
#define MESSAGE_GAP 12
/* The down arrow: twice the game's size, as the box's frame, a little after
 * the text. */
#define ARROW_SCALE 2
#define ARROW_GAP 3
/* The backlog's りれき, under its text: what tells it from the pane, with its
 * box's colours (3ds_bottom_ui.c). */
#define TITLE_H 16

/* The box the page is in (CtrReading_Draw), kept for the frames after; what
 * may be drawn on, [clip[0], clip[2]) x [clip[1], clip[3]). */
static struct
{
    u16 *canvas;
    int w, h, x0, y0, x1, y1;
    int clip[4];
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

static void Clip(int x0, int y0, int x1, int y1)
{
    sBox.clip[0] = max(x0, 0);
    sBox.clip[1] = max(y0, 0);
    sBox.clip[2] = min(x1, sBox.w);
    sBox.clip[3] = min(y1, sBox.h);
}

static void Put(int x, int y, u16 colour)
{
    if (x >= sBox.clip[0] && x < sBox.clip[2] && y >= sBox.clip[1] && y < sBox.clip[3])
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

        if (py < sBox.clip[1] || py >= sBox.clip[3])
            continue;
        for (int i = 0; i < g->w; ++i)
        {
            u32 a = i & 1 ? row[i >> 1] & 15 : row[i >> 1] >> 4;
            int px = x + g->x + i;

            if (a && px >= sBox.clip[0] && px < sBox.clip[2])
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

/* A run of characters (UCS-2), and where it ends. */
static int DrawRun(const Face *f, const u16 *s, int n, int x, int top)
{
    for (int i = 0; i < n; x += Advance(f, s[i]), ++i)
        DrawChar(f, s[i], x, top);
    return x;
}

static int RunWidth(const Face *f, const u16 *s, int n)
{
    int w = 0;

    for (int i = 0; i < n; ++i)
        w += Advance(f, s[i]);
    return w;
}

/* What a page is laid out in: characters, words in kanji with their
 * readings, line breaks; each with where in the printed text it appears. */
enum { PIECE_CHAR, PIECE_RUBY, PIECE_BREAK };

typedef struct
{
    u8 kind, baseCount, readingCount;
    u16 code, at, word;
    u16 readingAt;              /* PIECE_RUBY: its readings' places, in sReadingAt */
    const u16 *base, *reading;
} Piece;

#define MAX_PIECES 512
static Piece sPieces[MAX_PIECES];
static int sPieceCount;
static u16 sReadingAt[1024];
static int sReadingAtCount;
/* The message the pieces are of. */
static const Message *sPieceMsg;

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
static u32 NextShown(const Message *m, u32 e)
{
    while (e < m->length && m->text[e] == EXT_CTRL_CODE_BEGIN)
        e += Unit(m->text + e);
    return e;
}

/* A placeholder's value, as the game printed it. */
static void AddHole(const Message *m, int hole)
{
    u32 e = m->holes[hole].start, end = e + m->holes[hole].length;

    for (; e < end; e += Unit(m->text + e))
    {
        u8 c = m->text[e];

        if (c < CHAR_DYNAMIC && sData.gameMap[c])
            AddPiece(PIECE_CHAR, sData.gameMap[c], e);
    }
}

/* The page with something on it at or before the printer's: a message that
 * ends with a page break has an empty one after it. */
static u16 ChoosePage(const Message *m, u16 page)
{
    const u16 *t = m->tokens, *end = m->tokens + m->count;
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

#define ALL_PAGES 0xFFFF

/*
 * The pieces of page `page` of a message (ALL_PAGES: all of them, a page break
 * a line break), each with where in the printed text it appears. The tokens
 * and the printed text are walked together: a token's character stands for a
 * printed one, a word's reading for its kana, a run of placeholders for what
 * the game expanded it to, an icon for its two bytes, a break for the game's;
 * a colour or a pause has no token. A word is the k-th group's of the message.
 */
static void BuildPieces(const Message *m, u16 page)
{
    const u16 *t = m->tokens, *end = m->tokens + m->count;
    u32 e = 0;
    u16 p = 0, group = 0;

    sPieceMsg = m;
    sPieceCount = 0;
    sReadingAtCount = 0;
    while (t < end && (page == ALL_PAGES || p <= page))
    {
        u16 c = *t++;
        bool8 here = page == ALL_PAGES || p == page;

        if (c == TOK_PAGE || c == TOK_NEWLINE || c == TOK_SCROLL)
        {
            e = NextShown(m, e) + 1;
            if (c == TOK_PAGE)
                ++p;
            if (here && (c != TOK_PAGE || (page == ALL_PAGES && t < end)))
                AddPiece(PIECE_BREAK, 0, e);
        }
        else if (c >= TOK_HOLE && c < TOK_HOLE_END)
        {
            int hole = c - TOK_HOLE;

            if (hole < m->holeCount)
            {
                if (here)
                    AddHole(m, hole);
                e = m->holes[hole].start + m->holes[hole].length;
            }
        }
        else if (c >= TOK_ICON && c < TOK_ICON_END)
        {
            u32 at = NextShown(m, e);

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
                e = NextShown(m, e);
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
                u->word = group < m->wordCount ? m->words[group] : NO_WORD;
                /* The word in kanji with the first kana of its reading. */
                u->at = sReadingAt[first];
            }
            ++group;
            ++t;
        }
        else if (c < TOK_RUBY || c > 0xF8FF)
        {
            e = NextShown(m, e);
            if (here)
                AddPiece(PIECE_CHAR, c, e);
            ++e;
        }
    }
}

static int BaseWidth(const Piece *u)
{
    return RunWidth(sText, u->base, u->baseCount);
}

static int ReadingWidth(const Piece *u)
{
    return RunWidth(sRuby, u->reading, u->readingCount);
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

static int LinePitch(void)
{
    return LineInk() + LINE_GAP;
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

/* Each word in kanji on the screen, where a tap finds it. */
typedef struct
{
    s16 x0, y0, x1, y1;
    u16 at, word;
    u8 baseCount, readingCount;
    const u16 *base, *reading;
    const Message *msg;
} Target;

#define MAX_TARGETS 256
static Target sTargets[MAX_TARGETS];
static int sTargetCount;
/* The rows pieces are placed in: lines wholly outside are left out. */
static int sPlaceTop = -0x7FFF, sPlaceBottom = 0x7FFF;

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

    if (y + LineInk() <= sPlaceTop || y >= sPlaceBottom)
        return;
    if (u->kind == PIECE_CHAR)
        AddItem(u->at, u->code, x, textTop, FALSE);
    else if (u->kind == PIECE_RUBY)
    {
        int bx = x + padLeft, rx = bx + BaseWidth(u) / 2 - ReadingWidth(u) / 2;

        if (sTargetCount < MAX_TARGETS)
            sTargets[sTargetCount++] = (Target){bx - 2, y - 2, bx + BaseWidth(u) + 2, y + LineInk() + 3, u->at,
                                                u->word, u->baseCount, u->readingCount, u->base, u->reading,
                                                sPieceMsg};
        for (int i = 0; i < u->baseCount; bx += Advance(sText, u->base[i]), ++i)
            AddItem(u->at, u->base[i], bx, textTop, FALSE);
        for (int k = 0; k < u->readingCount; rx += Advance(sRuby, u->reading[k]), ++k)
            AddItem(sReadingAt[u->readingAt + k], u->reading[k], rx, y - sRuby->inkTop, TRUE);
    }
}

/*
 * Lays out the pieces from (x0, y0), `width` wide and at most `lines` lines,
 * and places their glyphs if `place`; the lines they take, or more than
 * `lines` if they do not fit. Lines wrap at the game's word gaps, as its own
 * lines break: a phrase that would run past the edge starts the next line,
 * unless it is longer than a line, and a wrapped line does not start with a
 * gap. Two words' readings side by side keep RUBY_SPACE between them.
 */
static int Layout(int x0, int y0, int width, int lines, bool8 place)
{
    int x = 0, line = 0, rubyEnd = -1, pitch = LinePitch();

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
    return height < LineInk() ? 0 : (height - LineInk()) / LinePitch() + 1;
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
static void DrawPrinted(u32 printedTo)
{
    for (int i = 0; i < sItemCount; ++i)
    {
        Item *it = &sItems[i];

        if (it->drawn || it->at >= printedTo)
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

/* The page on show, as far as the printer has printed it. */
static void DrawPage(int x0, int y0, int x1, int y1)
{
    int middle;

    BuildPieces(&sMsg.m, ChoosePage(&sMsg.m, sMsg.page));
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
    DrawPrinted(sMsg.printedTo);
    UpdateArrow();
}

/* The backlog's messages, the oldest first. */
static const Message *LogMessage(int i)
{
    return &sLog[(sLogNext + BACKLOG - sLogCount + i) % BACKLOG];
}

static const u16 sTitle[] = {0x308A, 0x308C, 0x304D};   /* りれき */

/*
 * The backlog: every message it keeps, whole and in the small faces, the
 * newest at the bottom of the box, scrolled sView.scroll pixels back; りれき
 * under them.
 */
static void DrawBacklog(int x0, int y0, int x1, int y1)
{
    int bottom = y1 - TITLE_H, height = 0, y;

    sText = &sData.faces[FACE_TEXT_SMALL];
    sRuby = &sData.faces[FACE_RUBY_SMALL];
    for (int i = 0; i < sLogCount; ++i)
    {
        BuildPieces(LogMessage(i), ALL_PAGES);
        height += Layout(x0, 0, x1 - x0, 0x7FFF, FALSE) * LinePitch() + (i ? MESSAGE_GAP : 0);
    }
    sView.height = height;
    sView.scroll = max(0, min(sView.scroll, height - (bottom - y0)));
    /* Short of a box, the backlog starts at its top. */
    y = height <= bottom - y0 ? y0 : bottom - height + sView.scroll;
    sItemCount = 0;
    sPlaceTop = y0;
    sPlaceBottom = bottom;
    Clip(x0 - 4, y0, x1 + 4, bottom);
    for (int i = 0; i < sLogCount; ++i)
    {
        int lines;

        BuildPieces(LogMessage(i), ALL_PAGES);
        lines = Layout(x0, y, x1 - x0, 0x7FFF, FALSE);
        if (y + lines * LinePitch() > y0 && y < bottom)
            Layout(x0, y, x1 - x0, 0x7FFF, TRUE);
        y += lines * LinePitch() + MESSAGE_GAP;
        /* A rule in the text's shadow between two messages. */
        if (i + 1 < sLogCount)
            for (int x = x0; x < x1; x += 2)
                Put(x, y - MESSAGE_GAP / 2 - 2, sBox.pal[3]);
    }
    sPlaceTop = -0x7FFF;
    sPlaceBottom = 0x7FFF;
    sItemsLeft = sItemCount;
    DrawPrinted(~0u);
    Clip(0, 0, sBox.w, sBox.h);
    DrawRun(&sData.faces[FACE_RUBY], sTitle, 3, x1 - RunWidth(&sData.faces[FACE_RUBY], sTitle, 3),
            y1 - TITLE_H + 2 - sData.faces[FACE_RUBY].inkTop);
}

void CtrReading_Draw(u16 *canvas, int width, int height, int x0, int y0, int x1, int y1, const u16 *pal)
{
    sBox.canvas = canvas;
    sBox.w = width;
    sBox.h = height;
    sBox.x0 = x0;
    sBox.y0 = y0;
    sBox.x1 = x1;
    sBox.y1 = y1;
    memcpy(sBox.pal, pal, sizeof(sBox.pal));
    Clip(0, 0, width, height);
    sBox.valid = FALSE;
    sTargetCount = 0;
    if (!sData.table)
        return;
    if (sView.backlog)
        DrawBacklog(x0, y0, x1, y1);
    else if (sMsg.on)
    {
        DrawPage(x0, y0, x1, y1);
        sBox.valid = TRUE;
    }
}

bool CtrReading_Advance(int rect[4])
{
    /* The word box and the backlog stay as they are drawn. */
    if (!sBox.valid || !sMsg.on || sView.backlog || sPopup.on)
        return FALSE;
    sDirty[0] = sDirty[1] = 0x7FFF;
    sDirty[2] = sDirty[3] = -0x7FFF;
    DrawPrinted(sMsg.printedTo);
    UpdateArrow();
    rect[0] = max(sDirty[0], 0);
    rect[1] = max(sDirty[1], 0);
    rect[2] = min(sDirty[2], sBox.w);
    rect[3] = min(sDirty[3], sBox.h);
    return rect[0] < rect[2] && rect[1] < rect[3];
}

/* ------------------------------------------------------------------------ */
/* The word box and the word log                                            */
/* ------------------------------------------------------------------------ */

bool CtrReading_Popup(bool *top)
{
    *top = sPopup.top;
    return sPopup.on;
}

/* The kanji of the tapped word's group, past its kana (its okurigana). */
static int KanjiOf(u16 *out, int max)
{
    int n = 0;

    for (int i = 0; i < sPopup.baseCount && n < max; ++i)
        if (sPopup.base[i] >= 0x3400)
            out[n++] = sPopup.base[i];
    return n;
}

/* ASCII as the font's characters, wrapped at spaces in `width`, `lines` at
 * most; where it ends. */
static int DrawAscii(const Face *f, const char *s, int n, int x0, int y, int width, int lines)
{
    u16 run[256];
    int count = 0, x = x0, line = 0, top = y - f->inkTop, pitch = f->inkBottom - f->inkTop + 3;

    for (int i = 0; i < n && i < 256; ++i)
        run[count++] = (u8)s[i];
    for (int i = 0; i < count && line < lines;)
    {
        int j = i, w = 0;

        while (j < count && run[j] != ' ')
            w += Advance(f, run[j++]);
        if (x > x0 && x + w > x0 + width)
        {
            x = x0;
            ++line;
            if (line >= lines)
                break;
        }
        x = DrawRun(f, run + i, j - i, x, top + line * pitch);
        if (j < count)
            x += Advance(f, ' ');
        i = j + 1;
    }
    return y + (line + 1) * pitch;
}

static void DrawLabelled(const Face *f, const u16 *label, int labelCount, const u16 *s, int n, int x, int y)
{
    x = DrawRun(f, label, labelCount, x, y - f->inkTop);
    DrawRun(f, s, n, x + f->size / 2, y - f->inkTop);
}

/* The number in the font's digits, from x; where it ends. */
static int DrawNumber(const Face *f, unsigned n, int x, int top)
{
    u16 digits[6];
    int count = 0;

    do
        digits[count++] = '0' + n % 10;
    while ((n /= 10) && count < 6);
    for (int i = count - 1; i >= 0; --i)
    {
        DrawChar(f, digits[i], x, top);
        x += Advance(f, digits[i]);
    }
    return x;
}

void CtrReading_DrawPopup(u16 *canvas, int width, int height, int x0, int y0, int x1, int y1, const u16 *pal)
{
    static const u16 sOn[] = {0x304A, 0x3093}, sKun[] = {0x304F, 0x3093}, sStrokes[] = {0x304B, 0x304F};
    static const u16 sKanjiNext[] = {0x304B, 0x3093, 0x3058, ' ', 0x25B6};   /* かんじ ▶ */
    const Face *text = &sData.faces[FACE_TEXT], *ruby = &sData.faces[FACE_RUBY];
    u16 kanji[8];
    int count;

    sBox.canvas = canvas;
    sBox.w = width;
    sBox.h = height;
    memcpy(sBox.pal, pal, sizeof(sBox.pal));
    Clip(x0 - 4, y0 - 2, x1 + 4, y1);
    sPopup.x0 = x0 - 20;
    sPopup.y0 = y0 - 18;
    sPopup.x1 = x1 + 20;
    sPopup.y1 = y1 + 10;
    if (!sPopup.on)
        return;
    count = KanjiOf(kanji, ARRAY_COUNT(kanji));
    if (sPopup.page == 0)
    {
        const u16 *word = sPopup.base, *reading = sPopup.reading;
        u8 wordLength = sPopup.baseCount, readingLength = sPopup.readingCount, glossLength = 0;
        const char *gloss = NULL;
        int wordW, rubyW, y;

        DictWord(sPopup.word, &word, &wordLength, &reading, &readingLength, &gloss, &glossLength);
        /* The word in the text's face, its reading over it as in the pane. */
        wordW = RunWidth(text, word, wordLength);
        rubyW = RunWidth(ruby, reading, readingLength);
        DrawRun(ruby, reading, readingLength, x0 + max(0, wordW - rubyW) / 2, y0 - ruby->inkTop);
        y = y0 + (ruby->inkBottom - ruby->inkTop) + RUBY_GAP;
        DrawRun(text, word, wordLength, x0 + max(0, rubyW - wordW) / 2, y - text->inkTop);
        y += text->inkBottom - text->inkTop + 6;
        if (gloss)
            DrawAscii(ruby, gloss, glossLength, x0, y, x1 - x0, 3);
        if (count)
            DrawRun(ruby, sKanjiNext, ARRAY_COUNT(sKanjiNext), x1 - RunWidth(ruby, sKanjiNext, ARRAY_COUNT(sKanjiNext)),
                    y1 - (ruby->inkBottom - ruby->inkTop) - 2 - ruby->inkTop);
    }
    else if (sPopup.page <= count)
    {
        u16 code = kanji[sPopup.page - 1];
        const u16 *on, *kun;
        const char *meaning;
        u8 onLength, kunLength, meaningLength;
        const Kanji *k = DictKanji(code, &on, &onLength, &kun, &kunLength, &meaning, &meaningLength);
        int x = x0 + text->size + 12, y = y0, pitch = ruby->inkBottom - ruby->inkTop + 5;

        /* The kanji large at the left, its details right of it. */
        DrawChar(text, code, x0, y0 + 4 - text->inkTop);
        if (k)
        {
            DrawLabelled(ruby, sOn, 2, on, onLength, x, y);
            DrawLabelled(ruby, sKun, 2, kun, kunLength, x, y + pitch);
            x = DrawNumber(ruby, k->strokes, x, y + 2 * pitch - ruby->inkTop);
            x = DrawRun(ruby, sStrokes, 2, x, y + 2 * pitch - ruby->inkTop);
            if (k->grade)
            {
                static const u16 sGrade[] = {0x3000, 0x5C0F};   /* 小 */
                static const u16 sSecondary[] = {0x3000, 0x4E2D};   /* 中 */

                if (k->grade <= 6)
                {
                    x = DrawRun(ruby, sGrade, 2, x, y + 2 * pitch - ruby->inkTop);
                    DrawNumber(ruby, k->grade, x, y + 2 * pitch - ruby->inkTop);
                }
                else if (k->grade == 8)
                    DrawRun(ruby, sSecondary, 2, x, y + 2 * pitch - ruby->inkTop);
            }
            DrawAscii(ruby, meaning, meaningLength, x0 + text->size + 12, y + 3 * pitch, x1 - x0 - text->size - 12, 1);
        }
        if (count)
            DrawRun(ruby, sKanjiNext + 4, 1, x1 - Advance(ruby, 0x25B6),
                    y1 - (ruby->inkBottom - ruby->inkTop) - 2 - ruby->inkTop);
    }
    Clip(0, 0, width, height);
}

/* UCS-2 as UTF-8, into out (n bytes at most); where it ends. */
static char *Utf8(char *out, char *end, u16 c)
{
    if (c < 0x80 && out + 1 < end)
        *out++ = c == '\t' || c == '\n' ? ' ' : (char)c;
    else if (c < 0x800 && out + 2 < end)
    {
        *out++ = 0xC0 | (c >> 6);
        *out++ = 0x80 | (c & 63);
    }
    else if (c >= 0x800 && out + 3 < end)
    {
        *out++ = 0xE0 | (c >> 12);
        *out++ = 0x80 | ((c >> 6) & 63);
        *out++ = 0x80 | (c & 63);
    }
    return out;
}

static char *Utf8Run(char *out, char *end, const u16 *s, int n)
{
    for (int i = 0; i < n; ++i)
        out = Utf8(out, end, s[i]);
    return out;
}

/* The message as Anki's furigana write it: 漢字[かんじ], a space before each
 * word in kanji, which Anki does not show; its placeholders as printed. */
static char *Sentence(char *out, char *end, const Message *m)
{
    BuildPieces(m, ALL_PAGES);
    for (int i = 0; i < sPieceCount; ++i)
    {
        const Piece *u = &sPieces[i];

        if (u->kind == PIECE_CHAR)
            out = Utf8(out, end, u->code);
        else if (u->kind == PIECE_RUBY)
        {
            if (i > 0)
                out = Utf8(out, end, ' ');
            out = Utf8Run(out, end, u->base, u->baseCount);
            out = Utf8(out, end, '[');
            out = Utf8Run(out, end, u->reading, u->readingCount);
            out = Utf8(out, end, ']');
        }
    }
    return out;
}

/* The message's English line, from furigana/english.bin. */
static char *English(char *out, char *end, const Message *m)
{
    FILE *f = CtrData_Open("furigana/english.bin");
    u32 head[2], at[2];

    if (!f)
        return out;
    if (fread(head, 4, 2, f) == 2 && head[0] == ENGLISH_MAGIC && m->entry < head[1]
     && fseek(f, 8 + m->entry * 4, SEEK_SET) == 0 && fread(at, 4, 2, f) == 2 && at[1] >= at[0]
     && fseek(f, 8 + (head[1] + 1) * 4 + at[0], SEEK_SET) == 0)
    {
        u32 n = min(at[1] - at[0], (u32)(end - out - 1));

        n = fread(out, 1, n, f);
        for (u32 i = 0; i < n; ++i)
            if (out[i] == '\t' || out[i] == '\n')
                out[i] = ' ';
        out += n;
    }
    fclose(f);
    return out;
}

/* The word opened, as a line of the word log: its dictionary form, reading,
 * gloss, the sentence with furigana and its English; not twice in a row. */
static void LogWord(void)
{
    static u32 last;
    char line[2048], *p = line, *end = line + sizeof(line) - 2;
    const u16 *word = sPopup.base, *reading = sPopup.reading;
    u8 wordLength = sPopup.baseCount, readingLength = sPopup.readingCount, glossLength = 0;
    const char *gloss = "";
    u32 key = sPopup.word != NO_WORD ? sPopup.word : 0x10000u | (sPopup.base[0] ^ (sPopup.reading[0] << 1));
    FILE *f;
    bool8 fresh;

    if (key == last)
        return;
    last = key;
    DictWord(sPopup.word, &word, &wordLength, &reading, &readingLength, &gloss, &glossLength);
    p = Utf8Run(p, end, word, wordLength);
    *p++ = '\t';
    p = Utf8Run(p, end, reading, readingLength);
    *p++ = '\t';
    for (int i = 0; i < glossLength && p < end; ++i)
        *p++ = gloss[i] == '\t' ? ' ' : gloss[i];
    *p++ = '\t';
    p = Sentence(p, end, sPopup.msg);
    *p++ = '\t';
    p = English(p, end, sPopup.msg);
    *p++ = '\n';
    f = fopen(CTR_READING_LOG_PATH, "r");
    fresh = f == NULL;
    if (f)
        fclose(f);
    if (!(f = fopen(CTR_READING_LOG_PATH, "a")))
    {
        CtrLog_Write(CTR_LOG_ERROR, "reading pane: no word log at %s", CTR_READING_LOG_PATH);
        return;
    }
    /* Anki's import reads its settings from the file's head. */
    if (fresh)
        fputs("#separator:tab\n#html:false\n#columns:Word\tReading\tMeaning\tSentence\tEnglish\n", f);
    fwrite(line, 1, p - line, f);
    fclose(f);
}

/* ------------------------------------------------------------------------ */
/* Touch                                                                    */
/* ------------------------------------------------------------------------ */

static struct
{
    bool8 down, dragged, pulled;
    int startX, startY, lastX, lastY, scroll;
} sTouch;

static const Target *TargetAt(int x, int y)
{
    for (int i = 0; i < sTargetCount; ++i)
    {
        const Target *t = &sTargets[i];

        /* On the page, only a word already printed. */
        if (x >= t->x0 && x < t->x1 && y >= t->y0 && y < t->y1
         && (sView.backlog || t->msg != &sMsg.m || t->at < sMsg.printedTo))
            return t;
    }
    return NULL;
}

static void Open(const Target *t)
{
    sPopup.on = TRUE;
    sPopup.page = 0;
    sPopup.word = t->word;
    sPopup.base = t->base;
    sPopup.baseCount = t->baseCount;
    sPopup.reading = t->reading;
    sPopup.readingCount = t->readingCount;
    sPopup.msg = t->msg;
    /* Over the half of the screen the word is not in. */
    sPopup.top = (t->y0 + t->y1) / 2 >= sBox.h / 2;
    Changed();
    LogWord();
}

int CtrReading_Touch(int phase, int x, int y)
{
    if (phase == CTR_READING_DOWN)
    {
        sTouch.down = TRUE;
        sTouch.dragged = sTouch.pulled = FALSE;
        sTouch.startX = sTouch.lastX = x;
        sTouch.startY = sTouch.lastY = y;
        sTouch.scroll = sView.scroll;
        return CTR_READING_TAKEN;
    }
    if (!sTouch.down)
        return CTR_READING_NONE;
    if (phase == CTR_READING_MOVE)
    {
        int dy = y - sTouch.startY, dx = x - sTouch.startX;

        sTouch.lastX = x;
        sTouch.lastY = y;
        if (dy > 8 || dy < -8 || dx > 8 || dx < -8)
            sTouch.dragged = TRUE;
        /* The backlog follows the finger, and a pull back up past its newest
         * message closes it, as a pull down on the page brings it. */
        if (sView.backlog && sTouch.dragged && !sPopup.on && sTouch.scroll + dy < -40)
        {
            sView.backlog = FALSE;
            sTouch.pulled = TRUE;
            Changed();
        }
        else if (sView.backlog && sTouch.dragged && !sPopup.on && sTouch.scroll + dy != sView.scroll)
        {
            sView.scroll = max(0, sTouch.scroll + dy);
            Changed();
        }
        else if (!sView.backlog && !sTouch.pulled && dy > 40 && CtrReading_OpenBacklog())
        {
            sTouch.pulled = TRUE;
            sTouch.scroll = 0;
            sTouch.startY = y;
        }
        return CTR_READING_TAKEN;
    }
    /* A tap, where it was let go. */
    sTouch.down = FALSE;
    x = sTouch.lastX;
    y = sTouch.lastY;
    if (sTouch.dragged)
        return CTR_READING_TAKEN;
    if (sPopup.on)
    {
        u16 kanji[8];

        /* On the box, its next page: its kanji, then the word again. */
        if (x >= sPopup.x0 && x < sPopup.x1 && y >= sPopup.y0 && y < sPopup.y1)
            sPopup.page = sPopup.page < KanjiOf(kanji, ARRAY_COUNT(kanji)) ? sPopup.page + 1 : 0;
        else
        {
            const Target *t = TargetAt(x, y);

            sPopup.on = FALSE;
            if (t)
                Open(t);
        }
        Changed();
        return CTR_READING_TAKEN;
    }
    {
        const Target *t = TargetAt(x, y);

        if (t)
        {
            Open(t);
            return CTR_READING_TAKEN;
        }
    }
    return sView.backlog ? CTR_READING_TAKEN : CTR_READING_MISSED;
}
