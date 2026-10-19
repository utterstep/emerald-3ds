#ifndef CTR_READING_H
#define CTR_READING_H

/*
 * The reading pane (3ds_reading.c, docs/FURIGANA.md): the message the top
 * screen prints, on the bottom screen in kanji with furigana, a page at a
 * time. Its data is the player's own (scripts/gen_furigana.py); without it
 * nothing is shown.
 *
 * SDK-free: the game's text code tells it what it prints, the bottom screen
 * (3ds_bottom_ui.c) asks it what to show.
 */
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
/* Draws its page into [x0, x1) x [y0, y1) of a bottom-screen canvas
 * (column-major RGB565, as 3ds_bottom_ui.c's), in the text colour and shadow
 * of the box the caller drew there. */
void CtrReading_Draw(uint16_t *canvas, int width, int height, int x0, int y0, int x1, int y1, uint16_t fg,
                     uint16_t shadow);

#endif
