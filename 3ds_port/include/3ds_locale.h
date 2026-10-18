#ifndef CTR_LOCALE_H
#define CTR_LOCALE_H

#include "constants/global.h"

/* Native UI literals are converted from UTF-8 into the game font encoding
 * (3ds_locale_text.h). The Japanese labels are kana, in the game's own
 * words where it has them (no kanji: the font has none); CtrLocale_ToGame
 * draws a label with kana in the Japanese glyphs, 8 pixels each, and one
 * without in the Latin glyphs, in any build. */
#if GAME_LANGUAGE == LANGUAGE_SPANISH
#define CTR_TEXT(english, spanish, french, italian, japanese) (spanish)
#elif GAME_LANGUAGE == LANGUAGE_FRENCH
#define CTR_TEXT(english, spanish, french, italian, japanese) (french)
#elif GAME_LANGUAGE == LANGUAGE_ITALIAN
#define CTR_TEXT(english, spanish, french, italian, japanese) (italian)
#elif GAME_LANGUAGE == LANGUAGE_JAPANESE
#define CTR_TEXT(english, spanish, french, italian, japanese) (japanese)
#else
#define CTR_TEXT(english, spanish, french, italian, japanese) (english)
#endif

/* The glyph set the game's strings start in: the Japanese one in a Japanese
 * build, the Latin one in any other (see 3ds_locale_text.h). */
#define CTR_LOCALE_JAPANESE_FIRST (GAME_LANGUAGE == LANGUAGE_JAPANESE)

#endif
