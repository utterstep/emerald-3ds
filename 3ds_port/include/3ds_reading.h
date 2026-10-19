#ifndef CTR_READING_H
#define CTR_READING_H

/*
 * The reading pane (3ds_reading.c, docs/FURIGANA.md): the message the top
 * screen prints, on the bottom screen in kanji with furigana, a page at a
 * time; a tapped word's reading and meaning, the word log, the backlog of the
 * last messages. Its data is the player's own (scripts/gen_furigana.py);
 * without it nothing is shown.
 *
 * SDK-free: the game's text code tells it what it prints, the bottom screen
 * (3ds_bottom_ui.c) asks it what to show.
 */
#include <stdbool.h>
#include <stdint.h>

/* Loads furigana/table.bin and furigana/font.bin if the data has them. */
void CtrReading_Init(void);
/* Forgets the message on show (a soft reset). */
void CtrReading_Reset(void);

/* string_util.c, battle_message.c, dynamic_placeholder_text_util.c: src was
 * expanded into dest. */
void CtrReading_Expanded(const uint8_t *dest, const uint8_t *src);
/* text.c: a text printer started on a window with str, at `speed` (0 or
 * TEXT_SKIP_DRAW: all at once, as menus are). */
void CtrReading_Printing(uint8_t windowId, const uint8_t *str, uint8_t speed);
/* window.c: a window was wiped, or taken off the screen (hidden). */
void CtrReading_WindowCleared(uint8_t windowId, uint8_t hidden);

/* What the pane shows now, as a number that changes with it (the message, its
 * page and how far the page has scrolled); 0 when there is nothing to show. */
uint32_t CtrReading_Stamp(void);
/* Draws its page, as far as the top screen has printed it, into [x0, x1) x
 * [y0, y1) of a bottom-screen canvas (column-major RGB565, as
 * 3ds_bottom_ui.c's), in the colours of the box the caller drew there: `pal`
 * is the game's message box palette (1 its fill, 2 and 3 the text and its
 * shadow, 4 the down arrow's red). */
void CtrReading_Draw(uint16_t *canvas, int width, int height, int x0, int y0, int x1, int y1, const uint16_t *pal);
/* A later frame of the same page: draws onto that canvas what the top screen
 * has printed since, and the down arrow; TRUE with the rectangle it changed,
 * [rect[0], rect[2]) x [rect[1], rect[3]). */
bool CtrReading_Advance(int rect[4]);

/* A number that changes when the word box or the backlog does: the bottom
 * screen draws the pane again. */
uint32_t CtrReading_View(void);
/* The backlog, from the field or a battle (a pull from the screen's top
 * edge); FALSE if there is nothing in it. While it is open CtrReading_Stamp
 * is not 0, and the caller draws its box in the backlog's colours. */
bool CtrReading_OpenBacklog(void);
bool CtrReading_InBacklog(void);
/* Whether the word box is open, and over the top of the screen or its bottom;
 * the caller draws the box there and its words with CtrReading_DrawPopup,
 * into the box's room as for CtrReading_Draw. */
bool CtrReading_Popup(bool *top);
void CtrReading_DrawPopup(uint16_t *canvas, int width, int height, int x0, int y0, int x1, int y1,
                          const uint16_t *pal);

/* The bottom screen's touches while the pane or the backlog has the screen. */
enum { CTR_READING_DOWN, CTR_READING_MOVE, CTR_READING_UP };
/* What a touch did: nothing, something (redrawn by CtrReading_View), or a
 * tap on no word (the caller may take it as it would). */
enum { CTR_READING_NONE, CTR_READING_TAKEN, CTR_READING_MISSED };
int CtrReading_Touch(int phase, int x, int y);

#endif
