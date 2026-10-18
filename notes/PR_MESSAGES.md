# PR 1 — Localization: French and Italian braille texts keep their brailleformat header

**Base:** `integration` · **Commit:** `ef6fe02` (cherry-pick of the first commit of `feature/japanese-text-draft`)

## Problem

The French and Italian manifests map each braille text (`data/text/braille.inc`) to the ROM bytes
of the text alone, but the source span they replace also covers the `brailleformat` line. Staging
therefore drops the 6-byte header. `ScrCmd_braillemessage` always skips those 6 bytes
(`ptr + 6`), so in the French and Italian builds every braille message (Sealed Chamber, Desert
Ruins, Island Cave, Ancient Tomb, the underwater sign) loses its first characters, and the two
one-character panels read into the next string.

The Spanish manifest's ranges include the header, so the Spanish build is not affected. I found
this from the manifests' layout (the 6-byte gaps between consecutive braille ranges in the French
and Italian ROMs, none in the Spanish one) and the engine code; I have not seen it on hardware.

## Change

`tools/localize_french.py` and `tools/localize_italian.py` keep the source's `brailleformat` line
for a braille edit unless the ROM range already starts with those 6 bytes, so the change is safe
for either manifest convention.

## Testing

- New `builder/tests/test_localize_braille.py` (synthetic bytes, both locales): the header is kept
  when the range is the text alone and not doubled when the range holds it. Both tests fail without
  the fix.
- `python -m unittest discover -s builder/tests`: all pass. `python tools/release_audit.py --repo . --strict`: clean.

## Limitations

Not checked on a console: worth a look at a braille panel in a French or Italian build.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HWtry5KnJGgBuabFnyVuYm

---

# Other upstream issues found along the way (no PR yet)

- **Flaky test, voxel generators:** `builder/tests/test_web.py`
  `RunnerTests.test_inprocess_matches_subprocess` fails about one run in three to eight, on
  `integration` too. `voxel.run_generators` runs the generators in parallel, and
  `gen_intro_margins.py` sometimes starts before the generator that writes
  `3ds_port/romfs/voxel/regions.bin`, which it reads (FileNotFoundError). Likely fix: run the
  generators that read another one's output after it (a dependency order), or serially.

---

# PR 2 (draft) — Japanese: playing Emerald 3DS from the Japanese cartridge

**Base:** `integration` · **Branch:** `feature/japanese-text-draft` (and the build work that follows)

## Why

Japanese is the one Emerald cartridge the port cannot use. This PR adds it, from the player's own
clean dump (BPEJ, SHA-1 `d7cf8f156ba9c455d164e1ea780a6bf1945465c2`), with the same rule as the
other languages: the repository holds source positions and ROM offsets, never game content.

## What is in this PR so far

- `tools/locales/japanese.json.gz`: 19,167 of 19,403 source texts mapped to the Japanese ROM,
  including 55 vanilla texts that none of the existing locale manifests covers. The other 236 are
  listed with their reason (absent from the Japanese game, a layout that needs code, not mapped yet).
- `tools/localize_japanese.py`: stages that text (for inspection; not a playable build on its own).
- `docs/JAPANESE.md`: how the mapping was made and checked, what a Japanese build still needs, and
  what the mapping found in the existing locale manifests.

## How the mapping was made and checked

The Japanese ROM keeps the decomp's map table, script files and script commands, so the bytes
between two texts (script code) predict each Japanese text's position; every placement is tied to
identity evidence (per-map text counts, trainer IDs, C pointer tables, the Japanese script commands
that reference it), and every pair was read in both languages. Checks: source hashes, ROM ranges,
terminators, braille headers against the decomp's values, a staging dry run, and a host-compiler
build of the staged C files with no new errors. A held-out test (trainer-ID links hidden) placed 678
trainer texts, all correctly. `release_audit.py --strict` is clean, including its scan for runs of
Japanese ROM bytes.

## Proposed approach for the rest — feedback welcome before it lands

- **Compile-time, like the other languages:** `#if GAME_LANGUAGE == LANGUAGE_JAPANESE`, one more
  executable (`Emerald3DS-ja.3dsx`) and a `ja` payload; the English, Spanish, French and Italian
  builds do not change.
- **Japanese cartridge, Japanese behaviour:** where the Japanese game differs (5-character names,
  kana keyboards, no record-mixing refusal for Japanese partners, no Trainer Hill "closed" state,
  the bard singing per kana), the Japanese build follows it.
- **Phases:** (1) Japanese text everywhere: engine glyphs, the international "Japanese is foreign"
  handling inverted, the port's bottom screen and HD battle box; bootstrap and the ROM guard accept
  BPEJ. (2) Input and grammar: kana naming screen, Easy Chat and Union Room keyboards, text built in
  code. (3) Graphics, credits and Trainer Hill floors from the Japanese ROM; the bard. (4) Builder,
  web builder and release.
- The engine changes touch shared files (`text.c`, `pokemon.c` and others) behind
  `GAME_LANGUAGE`; I would like to know whether you prefer that split into several PRs.

## Findings about the existing locales (separate PRs)

- French and Italian braille headers: PR 1.
- 55 vanilla texts are in no locale manifest (braille alphabet panels, Union Room prompts, Mystery
  Gift texts and a few more), and 12 texts are mapped in some locale manifests only; details in
  `docs/JAPANESE.md`.

## Limitations

Draft: nothing here is playable yet, and nothing has run on a console or an emulator.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HWtry5KnJGgBuabFnyVuYm
