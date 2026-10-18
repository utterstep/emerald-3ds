# Idea: a kanji and furigana reading pane on the bottom screen

**Status: idea, for after the Japanese build works** (docs/JAPANESE.md). Nothing is implemented.

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

## Open questions

- How much kanji: the jōyō set for everything, or a lighter density for beginners.
- Word meanings on tap: which dictionary data, under which licence.
