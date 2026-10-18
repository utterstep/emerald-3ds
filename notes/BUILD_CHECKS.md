# Japanese Emerald 3DS: how the build branch was checked

Branch `feature/japanese-build` (built as `ja/build` in a cloud session, then pushed).
The checks below ran in that session, which had no devkitPro; `$S` is its scratchpad,
which is gone: the trees, logs and check scripts it names were not kept. The build and
install steps are in docs/JAPANESE.md on the build branch.

## What is in the build

```
0003b98 Add a tool that re-pins the locale manifests to a changed patched tree
e4f13f5 Japanese: the docs and the staging message follow the merged engine
800b274 Japanese: string_util.h includes the language constants (0058)
201b972 Merge ja/engine into ja/build
6472ffc Merge ja/data into ja/build
c217405 Merge ja/uitext into ja/build      (contains ja/portui)
de7d66e Merge ja/tooling into ja/build
```

- **ja/tooling**: `bootstrap.py --japanese-rom`, the builders, the web builder and
  `build_release.py --japanese-rom` accept the BPEJ dump; the Japanese ROM guard in
  `3ds_port/src/3ds_data.c`; `make pak` records the BPEJ fingerprint; follower texts in
  Japanese (`followers/text/ja.bin`, through a change to patch 0056).
- **ja/portui + ja/uitext**: the bottom screen and the HD battle boxes draw both glyph
  sets; every `CTR_TEXT` has a kana label.
- **ja/data**: `tools/localize_japanese.py` stages texts (19,167), 83 graphics, the
  credits (45 pages), the four Easy Chat lists, the reference symbols and
  `GAME_LANGUAGE`; patches 0070-0073 (credits timing, contest title layout, menu info
  icons, title version palette); `tools/locales/japanese-symbols.s.gz`.
- **ja/engine**: patches 0057-0061 (Japanese glyphs and font metrics, native names,
  5-character names, record mixing / Trainer Hill, text built in code).
- **Manifests**: `japanese.json.gz` is ja/data's, re-pinned through 0057-0061 with
  `$S/agents/engine/repin.py --old <0001-0056 + 0070-0073> --new <all patches>`: four files
  re-pinned (TrainerHill_Entrance/scripts.inc, 24 of 24 spans moved; battle_message.c,
  naming_screen.c, string_util.c), identical to ja/engine's re-pin of those files. repin.py
  leaves `unmapped_source_texts` positions alone, so `$S/agents/build/repin_unmapped.py`
  mapped the 15 that moved (3 in scripts.inc, 12 in naming_screen.c) the same way, each
  read back unchanged. `tools/repin_locales.py` on the build branch (0003b98) now does both. Spanish, French and Italian are ja/engine's re-pinned manifests.
- **Fix found by the checks (800b274)**: 0058 put two inline functions that read
  `GAME_LANGUAGE`/`LANGUAGE_JAPANESE` into `include/string_util.h`. `src/mini_printf.c`
  includes that header without `global.h`, so the unit failed to compile in every
  language ("LANGUAGE_JAPANESE undeclared"). The 3DS build compiles that unit with the
  same includes (full.mk takes all of src/*.c), so the English build would have broken
  too. `string_util.h` now includes `constants/global.h`. Patch 0058 regenerated (header
  says why); the objects of every unit in English, Spanish, French and Italian are unchanged.
- **Docs**: `docs/JAPANESE.md` combines every branch: status, build steps, what each
  patch does (marked *done*) and what is still open. `docs/DEVELOPMENT.md` has
  tooling's "Other languages" and uitext's glyph test. README and RELEASING.md no
  longer call the build a draft or say the ja release variant waits for the symbol file.
  `localize_japanese.py` no longer says the engine changes are pending.

No regeneration was needed between the data and engine patches: 0070-0073 change
credits.c, contest_util.c, menu.c and title_screen.c, and 0057-0061 change none of those.

## Checks and results

| # | Check | Result |
|---|---|---|
| 1 | Merges in order tooling, uitext, data, engine (`--no-ff`) | done. JAPANESE.md conflicted in the data and engine merges; japanese.json.gz in the engine merge (resolved as above) |
| 2 | `tools/bootstrap.py --dir $S/agents/build/upstream` from ja/build (pinned 76463dac + 61 patches, `git apply`, no fuzz) | all 61 apply; re-run after the 0058 fix, all apply (bootstrap2.log) |
| 2b | The user's own path: `bootstrap.py --dir agents/build/e2e --japanese-rom rom/bpej.gba` (fetch, patch, make tools, make generated, staging) | rc 0; every file equals the staged copy in 3c (bootstrap_ja.log) |
| 3a | Pinned sha256 of every manifest file against the fresh tree (`check_pins.py`; the generated region_map_entries.h from a copy after `make generated`) | Spanish 449/449, French 454/454, Italian 449/449, Japanese 431/431 match |
| 3b | Spanish/French/Italian: edit *i* of each file reads in the fresh tree as edit *i* of the draft's manifest reads in a tree bootstrapped from feature/japanese-text-draft; ROM offset/size/kind and every other manifest key unchanged | es 19,348, fr 19,356, it 19,347 spans OK (40/41/40 moved, in 2 files) |
| 3b' | Japanese: every edit and unmapped span reads as ja/data's did in the draft tree | 19,402 spans OK |
| 3c | Staging `tools/localize_japanese.py --tree <copy of the fresh tree> --rom rom/bpej.gba` | rc 0 (localize.log) |
| 3c' | data agent's extended checker, copy `agents/build/checker/check_manifest.py --all-units` (only HERE/REPO/TREE changed; TREE = copy of the fresh tree after make tools, make generated and the 64 English graphics it compares sizes with) | 0 errors: sha256 431/431, completeness 19,402/19,402, terminators/c_eos/braille OK, dry run OK (19,167 edits parsed back, 83 graphics, 45 credits pages, 4 lists), 320 C + 2 asm units: 0 new errors, 0 new warnings (check_all.log) |
| 3c'' | Checker's dry-run output vs the real staging | 583 files, all identical |
| 3d | Syntax-only compile, every unit (`compile_cmp.py`: 320 game units with the draft/data pipeline, 52 port units with the portui flags) | English, fresh vs draft tree: 0 new errors. Japanese, staged tree vs English fresh tree: 0 new errors. Japanese engine only (forced global.h), fresh vs draft: 0 new errors. In both trees alike, 3 game units (battle_script_commands.c, save.c, tileset_anims.c: 64-bit host asserts/initializers) and 15 port units (need devkitPro's 3ds.h) fail |
| 3e | -O2 host objects (`obj_cmp.py`, agents/engine/obj.sh flags; es/fr/it through a global.h with that GAME_LANGUAGE): all 320 game units + data/event_scripts.s (TrainerHill scripts), draft vs fresh | en, es, fr, it each: 316 byte-identical; contest.c, secret_base.c, union_room.c same code, data, relocations and symbols except GCC's switch-table names (CSWTCH.956 vs .954); save.c and tileset_anims.c do not build on a 64-bit host in either tree. Control: the same comparison for Japanese differs in text.c, naming_screen.c, event_scripts.s, menu.c |
| 3f | `python -m unittest discover -s builder/tests` (on the build branch) | 111 tests OK, 4 skipped; test_inprocess_matches_subprocess passed first time |
| 3f' | Same suite inside a copy of the fresh tree (runs the 3 tests that need charmap.txt / battle_message.c) | those 3 pass; 2 others fail only because a tree has no licenses/ or patches/ (layout, not code) |
| 3f'' | CI host-tests job in a `git archive HEAD` copy (`mkdir -p 3ds_port/build`): pak, input, video decode, daynight/clock-store/encounters/night-lamps, voxel lighting/trees/ground mesh, voxel_night_test (gcc), bottom_map_test, glyph_sets_test | all PASS (hosttests*.log) |
| 3f''' | CI extras: compileall; synthetic web payload + `release_audit --zip ... --web-payload`; test_asset_table_compatibility; encounter_tables_test and berry_clock_test on the English tree and on the staged Japanese tree | all pass |
| 3g | `python tools/release_audit.py --repo . --strict --rom rom/bpej.gba` | clean (387 files, ROM scan) |

## Not verified here (no devkitPro in this container)

- devkitARM compile and link of the 3DSX, `make verify` (link audit), `make release pak`.
- The 15 port units that need devkitPro headers, among them tooling's `3ds_data.c` ROM
  guard (read by eye: its SHA-1 bytes are the ROM's d7cf8f15...45c2).
- Play on a console or emulator; the follower download; the release's Japanese
  variant and recipe.
- In every language, the port UI code changes on purpose (ja/portui's bug fix: a traded
  Japanese Pokémon's name is drawn in kana on the bottom screen and HD boxes, and the two
  Japanese half-width font sheets are preloaded with the Latin ones). So the port UI
  objects (3ds_bottom_ui.c, 3ds_battle_hud.c, 3ds_compat.c, 3ds_extras.c) are not
  identical to the draft's in English.
- Still open in the game (docs/JAPANESE.md): kana keyboards (naming screen, Union Room
  chat, Easy Chat), 19 screens whose Japanese graphics have another layout (summary,
  Pokédex, condition graph, slot machine...), the Pokédex page layout and metric units,
  the bard's song, the credits' scene pages, the two-floor Trainer Hill, two port texts
  (Exp. Share message, summary category label), a fuller symbol file for the ja release
  recipe.
- ja/uitext's commit 9ca7033 ends with "Co-Authored-By: Claude Fable 5.1"; it was merged
  as it is (history not rewritten).

## Building and installing the Japanese game (machine with devkitPro)

Requirements (docs/DEVELOPMENT.md): devkitPro with devkitARM, libctru, citro2d, citro3d
and 3dstools (`pacman -S --needed libctru citro2d citro3d 3dstools`), a host C/C++
compiler with libpng, Python 3.11+ with Pillow, git. On Windows use devkitPro's MSYS2
shell with MinGW64 on PATH. 

```sh
git checkout feature/japanese-build

# Reset build/upstream to the pinned decomp, apply the 61 patches, build the decomp
# tools and generated includes, stage the Japanese data from your cartridge dump
# (SHA-1 d7cf8f156ba9c455d164e1ea780a6bf1945465c2) and build the development 3DSX.
python3 tools/bootstrap.py --make -j8 --python python3 \
    --japanese-rom "/path/to/Pocket Monsters - Emerald (Japan).gba"

cd build/upstream/3ds_port

# Optional: follower Pokémon with their Japanese speech (downloads the sprites).
python3 ../builder/emerald3ds_builder/followers.py --out romfs --language ja

# The release executable and the data pack made from the Japanese ROM.
make release pak PYTHON=python3
```

Copy to the SD card, into `/3ds/emerald3ds/`:

- `build/upstream/3ds_port/dist/Emerald3DS.3dsx`
- `build/upstream/3ds_port/dist/Emerald3DS.smdh`
- `build/upstream/3ds_port/build/emerald3ds.pak`

Start "Emerald 3DS" from the Homebrew Launcher. The Japanese executable accepts only a
pack made from the Japanese ROM. Instead of the release files, the development build
`build/upstream/3ds_port/emerald3ds.3dsx` (data embedded) can be copied alone to
`/3ds/emerald3ds/`. For a log, create an empty `/3ds/emerald3ds/debug.txt`; the game then
writes `/3ds/emerald3ds/port.log`. Any later `bootstrap.py` run resets build/upstream;
running it without `--japanese-rom` goes back to English.

