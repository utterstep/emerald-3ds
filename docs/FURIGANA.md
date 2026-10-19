# Idea: a kanji and furigana reading pane on the bottom screen

**Status: a first version is built, not yet tried on a console.** All 11,286 messages
that need it are converted (see *Full run*); *Building it* says how a build gets them.

## Why

Japanese Emerald is written in kana only: there are no kanji, so there is nothing to put furigana
on. For someone learning Japanese, a kanji version of the same text, with the reading over every
kanji, turns the game into reading practice.

## The idea

While a message is open, the bottom screen shows the same message in kanji with furigana, in a
larger and clearer font, as one complete page (not letter by letter). The top screen keeps the
game's own kana dialogue, untouched, so both versions are visible side by side.

- **Always on** in the Japanese build: no setting needed at first.
- **Later:** tapping a word on the bottom screen shows its meaning.

Why the bottom screen rather than the top-screen dialogue box: the port already draws game strings
on the bottom screen in its own code (3ds_port/src/3ds_bottom_ui.c), so the pane needs no
reimplementation of the game's text printer (printing speed, scrolling, prompts, colours, pauses)
and cannot break the game's text flow. Furigana in the top-screen box would need an HD dialogue box
that replaces that printer; it stays possible later.

## Content

- **What gets kanji:** everyday words in jōyō kanji (the ~2,100 taught in school), with furigana on
  every kanji. Katakana words, Pokémon, moves and names stay as the game writes them; no rare or
  ornate kanji. Dialogue and battle messages first; menus and names stay kana.
- **A built-in check:** the source is kana, so the furigana of each kanji are exactly the kana it
  replaces. Dropping the kanji and keeping the readings must give back the original text byte for
  byte, so the readings cannot drift from what the game says.
- **Making it:** agents convert the text (about 19,000 strings), checked mechanically as above;
  the choice between homophones and the kanji density need a native reader's spot checks. A pilot
  of a few hundred lines from varied places sets the style first.
- **Where it lives:** the kanji text is derived from the game's text, so it never goes into the
  repository. For a personal build it is generated from the player's own ROM into their data pack.
  Sharing it would need another format (for example kanji annotations keyed to text positions) and
  a closer look at what may be distributed.

## Engineering sketch

- **Data:** a table in the data pack from each message (by its address in the game data) to its
  annotated version, e.g. `[博士|はかせ]が [研究所|けんきゅうじょ]で まっている` as source markup,
  encoded with control codes for "kanji #n" and ruby start/end.
- **Hook:** when the game starts printing a message in the dialogue window (or the battle message
  box), the port looks it up and draws the annotated page on the bottom screen; placeholders
  (player name, STR_VAR) are expanded the same way the game expands them.
- **Font:** Nintendo's fonts cannot be used. Free bitmap fonts fit the style: Shinonome (public
  domain, 12-16 px) for the main text, misaki (8 px) or k8x12 for the furigana; shipped in the
  port's romfs.
- **Bottom screen:** the touch UI gives way to the reading pane while a message is open and
  comes back when it closes.

## Pilot

391 messages from varied places (towns, gym leaders, battle messages, Pokédex entries, item and
move descriptions) were converted by an agent with a style sheet and checked mechanically: all 391
give back the original kana. The result and the style sheet are kept outside the repository,
because both quote the game's text.

- **Density of the pilot:** about 6 kanji per message, 534 distinct kanji, about 17% of the
  characters (towns 6-8 per message, battle messages about 2, Pokédex entries about 15). Kanji for
  content words (nouns, verbs, adjectives); kana for grammar (particles, いる, ある, ～てみる, こと,
  もの) and for words that are customarily printed in kana.
- **Decided:** the density is right, and **the full run may use a bit more kanji**. Next step up,
  still how modern Japanese is printed: jōyō words the pilot kept in kana by custom, such as 誰,
  挨拶, 匂い, 多分, 色々, and ポケモン図鑑 for the Pokédex in dialogue. Grammar stays in kana; no
  non-jōyō kanji and no 事/物/居る/出来る for grammar words.
- **Defaults of the pilot, kept unless changed:** game terms as the game writes them (items, moves,
  abilities, Pokémon, types, trainer classes); generic parts of place and person names in kanji
  (地方, 森, 番道路, 博士), the proper-noun part as written; 私 for わたし/わたくし, 僕, 俺, 君,
  while katakana ボク/オレ/キミ stay; 分かる, 子供.
- **For the full run:** the converter gets the style sheet and a glossary of the game's terms, and
  every output goes through the check; failures are almost always a dropped full-width space or a
  reading that does not match the kana.

## Full run

Done in the cloud session by parallel agents with a shared style sheet and decision log,
then a consistency pass (318 messages aligned to one rule per word). Every message passes
the kana check. 5.4 kanji per message, 18.5% of printed characters, 1,357 distinct jōyō
kanji; 5,642 texts are kept as the game writes them (names, short labels) and 2,240 are
not text. The result (annotations, `furigana.json` keyed by ROM offset, review pages,
style sheet, decision log and the tools, which run with plain Python) is kept outside the
repository on the player's computer, because it is derived from the game's text.

Open style questions: place names in kana or kanji; stat names and map-name popups stay
kana for now.

## Building it

The code is in this repository; the text and the fonts are not.

- `3ds_port/scripts/gen_furigana.py` turns the conversion folder's `out/furigana.json`
  into `furigana/table.bin`, each message's tokens keyed by an FNV-1a hash of the game's
  bytes for its kana (the game prints from the same bytes, so no address map is needed),
  and `furigana/font.bin`, its glyphs: M PLUS Rounded 1c Medium (`fonts/mplusround/` in
  the same folder, SIL Open Font License) rendered with Pillow at the screen's own
  resolution, 16 levels of ink a pixel, at 24 pixels for the text and 12 for the
  readings, and 18 and 10 for a page too long for those. Both files are optional data
  (`tools/port_common/staging.py`): in a development build's RomFS, `make pak` and
  `make devdata`, never in a release.
- Set `FURIGANA_DIR` to that folder (in `3ds_port/local.mk` or the environment) and build
  as usual; without it nothing changes.
- `3ds_port/src/3ds_reading.c`: patch 0084 tells it what each text printer starts on and
  how fast (a message types out, a menu prints at once and is left alone), which template
  a printed buffer was expanded from (`StringExpandPlaceholders`,
  `BattleStringExpandPlaceholders`, `DynamicPlaceholderTextUtil_ExpandPlaceholders`) and
  when a window's text goes (`window.c`). A template of the table is the message on show;
  the values of its placeholders are read off the printed text around the template's own
  characters. The page is the text printer's, and the pane goes when the top screen's
  text does.
- The bottom screen (`3ds_bottom_ui.c`) gives way to the pane in the field, between the
  battle's menus and in the professor's welcome while a message is open: the game's
  dialogue frame at twice its size over the whole screen, and in it the page the top
  screen is on, in the box's text colour and shadow, the readings over the kanji, lines
  wrapped at the game's word gaps. 93% of pages fit at 24/12 pixels, nearly all the rest
  at 18/10; the few longer still (long scrolling passages) follow the top screen's
  scrolling. With KANJI TYPE-OUT (OPTIONS, ENHANCEMENTS, on by default) the page types
  out with the top screen's, every character when the game prints the one it stands for
  and a word in kanji with the first kana of its reading; while the game waits for a
  button, its red down arrow bounces after the text in step with the top screen's.
  Touches and the column's keys wait until it closes.

Not covered yet: texts the game builds in code (contest appeal lines, Easy Chat
speeches), texts the port adds, and descriptions shown on the game's own screens (Pokédex,
bag), which have the bottom screen to themselves.

## Next steps

1. Try it on the console: the font size, the colours, when the pane closes.
2. Before a build with the pane is shared: M PLUS Rounded 1c is under the SIL Open Font
   License, which belongs in NOTICE.md then. The table is never shared.
3. The player's builder: the conversion folder as an input of their data pack
   (`builder/emerald3ds_builder/build.py`, as the followers), and `verify` skipping
   `furigana/*` as it skips them.
4. Later: tap a word for its meaning (JMdict, CC BY-SA).

## Open questions

- Word meanings on tap: which dictionary data, under which licence.
