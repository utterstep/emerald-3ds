# The screen rig (scratch only)

Tools to SEE the same game screens in the user's Japanese cartridge
(`$S/rom/bpej.gba`) and in a scratch GBA build of our Japanese tree, and to
compile-check the 3DS port without devkitPro. Nothing here goes into the
repository: it holds ROM-derived screenshots and saves.

`S=/tmp/claude-0/-home-user-emerald-3ds/c4c4699c-d4de-55cd-b65c-d8ca8f277cfe/scratchpad`

| File | What |
|---|---|
| `mgbarig` / `mgbarig.c` | headless mGBA driver, commands on stdin (below) |
| `build_gba.sh TREE OUT` | scratch GBA build of a staged tree (`RIG_FILL=1` adds the save filler, `JOBS`, default 2) |
| `saves/*.sav`, `make_saves.py`, `rig_fill.c` | test saves for both ROMs, and how they are made |
| `screens/`, `screens.py` | an input script per screen, both ROMs, side-by-side montages in `shots/` |
| `ctr_compile_check.sh`, `ctr_compile_compare.py`, `ctr/` | 3DS compile check with Ubuntu's arm-none-eabi-gcc |
| `riglib.py`, `ov.py`, `where.py`, `montage.py` | helpers (symbols, montages, the player's position) |

## Screens: `screens.py`

```sh
python3 $S/gba/rig/screens.py                       # every screen, JP ROM and $S/gba/ja's build
python3 $S/gba/rig/screens.py --only party summary   # some
python3 $S/gba/rig/screens.py --build $S/gba/me/pokeemerald_modern.gba   # your build (.map/.elf beside it)
python3 $S/gba/rig/screens.py --list                # what each script shows
```

Output: `shots/<screen>.png`, every shot of the screen in order, JP ROM left, build
right; single shots in `shots/jp/<screen>/` and `shots/build/<screen>/` with the
resolved `script.txt` and mgbarig's `log.txt`. All 23 screens take ~1.5 min (2 jobs).

Screens (all work in both ROMs): `title` (copyright, intro, title), `continue` (main
menu with a save, as the build draws it: see below), `continue_fixed`, `new_game`
(Birch, gender, player naming screen and its keyboard pages), `nickname` (Name
Rater: nickname naming screen), `start_menu` (+ save prompt), `party`, `mail`,
`summary` (info, skills, battle moves, contest moves, move details),
`pokedex` (list, entry, area map, cry, size), `pokedex_search`, `bag` (every
pocket, item menu), `berry_tag`, `pokenav` (main menu, condition graph),
`pokenav_map`, `pokenav_matchcall` (Match Call list and a call, ribbons list and a
mon's ribbons), `pokeblock` (case, block menu, feeding with the condition graph),
`trainer_card` (front, back), `easy_chat` (Mauville's bard in the Pokémon Center:
song editor, word groups, words, alphabet mode), `slot_machine` (Game Corner),
`contest` (Lilycove Normal Cool: stage, move menu, results pages), `credits`
(gMain.callback2 poked to CB2_StartCreditsSequence, 30 shots 500 frames apart),
`options`.

Script syntax (`screens/NAME.txt` for both ROMs, or `NAME.jp.txt`/`NAME.build.txt`):
mgbarig commands plus `include FILE` (`screens/FILE.inc`: `boot_pc`, `boot_mauville`,
`boot_namerater`, `boot_contest`, `boot_save`, `start_menu`), `jp: CMD` / `build: CMD`
(one ROM only), `repeat N CMD`, `{sym}`, `{sym+0x10}`, `{sym|1}` (Thumb function
pointer), `{SAVES}`, `shot NAME`. Symbols: the build's from its `.map` plus the `.elf`'s
static ones; the JP ROM's from `$S/gba/syms/jp_syms.tsv` (jp_addr column; preliminary,
see its README), then `jp_fallback_syms.tsv` (name, address; none needed so far).
A script needing a missing symbol is skipped for that ROM and the montage says so.
To write a new one: copy a script, run `--only NAME`, look at `shots/NAME.png`;
`python3 where.py 'include boot_mauville; hold UP 20; run 120'` prints the player's
map position and facing in the build.

## mgbarig

`$S/gba/rig/mgbarig ROM < script`. Commands (hex numbers, decimal frame counts):
`run N`, `hold KEYS N`, `tap KEYS [N]` (2 frames, then N idle, default 20), `shot
F.png`, `savestate F`, `loadstate F`, `sav F` (battery save, before the first frame),
`savout F` (write the battery save now), `rtc SECONDS`, `w8/w16/w32 ADDR VAL`,
`r8/r16/r32 ADDR`, `dump ADDR LEN F`, `wfile ADDR F`, `until ADDR VAL MASK [N]`,
`untilnot ADDR VAL MASK [N]`, `tapuntil KEYS N ADDR VAL MASK [MAX]` (tap every N
frames until the condition), `regs` (r0-r15: where a hang loops), `echo TEXT`.
Keys: A B SELECT START RIGHT LEFT UP DOWN R L, joined with `+`.

Changed in this round: `sav` loads a copy into memory, so a test save never
changes (mGBA itself writes a save back by syncing its mapped file a few frames
after the game's last flash write; `savout` is how the rig gets it); the clock
is a fixed fake epoch (2026-01-01 12:00 UTC, running with the frames) so runs
repeat; `#include <mgba/flags.h>` first (struct mCore has fields under
USE_DEBUGGERS: without it `savedataClone` called the wrong slot); the parser
matches the command word (before, `savestate F` was read as `sav estate`).

## Test saves: `saves/`

| Save | Where |
|---|---|
| `pc.sav` | Mauville Pokémon Center 1F, facing the nurse (the bard is at (2,3)) |
| `mauville.sav` | Mauville City (8,14), facing the Game Corner's door |
| `namerater.sav` | Slateport, the Name Rater's house, facing him |
| `contest.sav` | Lilycove Contest Lobby, facing the contest receptionist |

Same game in all: player ユウキ (male, ID 51230: the old man is the bard), 52:34
played, ¥123456, 777 coins, 5 badges, text speed fast; party Swampert ラグ (Mystic
Water, 10 ribbons incl. Champion/Effort/contest ranks), Gardevoir サーナ, Altaria
チルル (Orange Mail with words), Pikachu (no nickname, Light Ball, 3/4 HP),
Zangoose ザンギ (poisoned), Milotic ミロ (sheen 255, ribbons); every mon its own
condition stats; Pokédex (national on): seen Hoenn 181 / national 203, caught
111 / 122; bag: 28 items incl. mail, 11 ball kinds, TMs, HM01-08, 30 berries, key
items incl. both bikes, Coin Case, Pokéblock Case, Wailmer Pail, Soot Sack;
10 Pokéblocks; PokéNav with Match Call (Mom, Birch, May, Steven, Norman, Mr. Stone,
3 gym leaders, 11 trainers), ribbons menu; trainer card back stats.

How they are made (`python3 make_saves.py [--built DIR]`, ~15 s): a copy of a built
scratch tree (default `$S/gba/ja`) gets `rig_fill.c` and relinks; at its title screen
gMain.callback2 is pointed at `CB2_RigFillSave` (NewGameInitData, then the game's own
CreateMon/GiveMonToPlayer/AddBagItem/AddPokeblock/GiveMailToMonByItemId/flags, then a
warp); the rig saves with START > SAVE (the decomp's flash code, as a player would)
and `savout` writes the file. Then each save is loaded in both ROMs:
`saves/proof.png` (Continue screen, field, party for each).

**Compatibility.** The Japanese and international Emerald saves have the same
layout: the JP ROM's save-section table (`sSaveSlotLayout`, at 0x085ACA08) is byte
for byte our build's (SaveBlock2 0xF2C, SaveBlock1 0x3D88 in 4 sectors,
PokemonStorage 0x83D0 in 9), same signature/checksum/footer; and the JP ROM reads
every part of these saves correctly: name, play time, badges, dex counts, party
(kana nicknames, OT, ID, held items, status, HP, met place), summary pages,
ribbons, conditions, bag, berries, Pokéblocks, mail words, Match Call, coins,
trainer card. Strings are the shared charset (kana 0x01-0xA0, digits and Latin as
in the international games); the mons are LANGUAGE_JAPANESE.
In-game saving in the scratch build works: the saves above were written by it, and
continuing one, stepping aside and saving again (the overwrite prompt) gives a save
the JP ROM continues at the new place (`saves/proof_resave.png`).

## 3DS compile check: `ctr_compile_check.sh WORKTREE STAGED_TREE [OUT]`

```sh
$S/gba/rig/ctr_compile_check.sh $S/wt_mine $S/gba/mine/tree           # ~1.5 min, -j2
$S/gba/rig/ctr_compile_check.sh $S/wt_mine $S/agents/build/gen_tree $S/gba/rig/ctr/out/en_mine
python3 $S/gba/rig/ctr_compile_compare.py --compare OUT_JA OUT_EN [--warnings]
```

OUT/tree = the staged tree's top level as symlinks + a copy of WORKTREE/3ds_port, so
the port's `../../include/...` and the game's compile from the root resolve as in a
bootstrapped tree; then `make -k --output-sync -j2` of every C object of the
Makefile's `OBJECTS` (the 37 native units incl. `ctr_voxel.c`, the bridge and voxel
units, every game unit through preproc), with the Makefile's own flags. It warns
when the staged tree's patch digest is not the worktree's. Out: `make.log`,
`errors.tsv` (unit, file:line, kind, message), `failed.txt`. `--compare` lists the
diagnostics only the first run has ("real") and those both have.

Toolchain differences and stubs (`ctr/`): `ctr/devkitpro/devkitARM/bin/arm-none-eabi-gcc`
runs Ubuntu's GCC 13.2 with `-mfpu=vfp` (devkitARM's GCC is configured with it;
`-mfloat-abi=hard` needs an FPU) and `-idirafter ctr/stub`; `libctru/include` is
libctru + citro3d + citro2d headers from `$S/ext` (no generated headers were needed).
The one stub: `ctr/stub/sys/iosupport.h` (devoptab_t, devoptab_list, STD_IN/OUT/ERR,
DIR_ITER as devkitARM's newlib declares them; 3ds_log.c uses it). Nothing is linked.
Limits: devkitARM ships a newer GCC (14/15): warnings it adds (and GCC 14's default
errors outside the Makefile's -Wno-error list, e.g. -Wreturn-mismatch) are not seen;
data (`.s`), the link, RomFS generation are not checked.

Result for ja/build (0003b98, $S/agents/build/e2e) and English (gen_tree, same
patches): all 368 objects compile in both, 0 errors; warnings: 2531 Japanese, all
also in English (English has one more, a trigraph in strings.c). `ctr/out/ja_build`,
`ctr/out/en_build`, `ctr/out/compare_ja_en.txt`.

## What the screens show about our build (for the gap agents)

- **Main menu with a save hangs** (`continue`): the staged `gText_ContinueMenuPlayer`/
  `Time`/`Pokedex` are the JP ROM's texts with `{STR_VAR_1..3}` (FD 02..04), but
  main_menu.c (MainMenu_FormatSavegame*) never fills gStringVar1-3, so
  StringExpandPlaceholders copies from the zeroed gStringVar1 into gStringVar4 forever
  (`regs`: PC in StringExpandPlaceholders, dest past 0x02E7xxxx). The boot includes
  poke 0xFF into gStringVar1-3 for the build so the other screens can get past it
  (`continue_fixed` shows what is drawn then: values misplaced, ":52:34", "ひ122").
- Naming screens open on the international keyboard (ABC/lower/others), not かな/カナ.
- Summary/party/bag/trainer card/ribbons: English section headers, numbers drawn with
  stray "5"s (e.g. ×52, 551/552, 5555), Pokédex HT/WT imperial, "POKéDEX" header and
  START menu, condition graph COOL/BEAUTY labels, berry tag flavours, Easy Chat (2 word
  columns, Latin alphabet mode, DEL. ALL/CANCEL/OK), slot machine SELECT/B labels,
  contest results title garbled, credits pages and pacing differ from the JP ROM
  (ours reaches THE END ~2000 frames earlier and has no copyright page).

## Known limits

- Frame-count timings; the contest waits on gMain.callback2 (CB2_ContestMain,
  CB2_ShowContestResults) since its RNG differs between the ROMs (opponents differ).
- The JP symbol table is preliminary; the scripts use only gMain,
  CB2_StartCreditsSequence, CB2_ContestMain, CB2_ShowContestResults (all checked by
  the screens working).
- The saves are a sketch of a story state (5 badges, Mauville after Wally); events
  elsewhere may trigger. NPCs walk: scripts avoid them, but a changed RNG can block one.
- `build_gba.sh` copies the whole tree (~250 MB); `make_saves.py` copies a built one.
