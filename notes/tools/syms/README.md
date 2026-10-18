# Japanese ROM symbol map (BPEJ <-> pokeemerald)

`jp_syms.tsv` maps every function and data symbol of the vanilla English build of the
pinned pokeemerald (76463dac, agbcc, `make`; `pokeemerald.gba: OK` against `rom.sha1`) to
its address in the Japanese cartridge `$S/rom/bpej.gba`. `DIFFERENCES.md` lists, per
source file, where the Japanese code differs. Scratch only: nothing here is in the
repository, and nothing here may be committed (it is derived from the ROM).

## Use

```
./jpaddr.sh CB2_InitTitleScreen          # row(s) of a symbol (re:REGEX for a pattern)
./jpaddr.sh 0x080aa100                   # which EN symbol's JP counterpart contains this JP address
./jpaddr.sh --en 0x080aa7a5              # EN address -> symbol and its JP address
./jpdis.sh  CB2_InitTitleScreen          # EN listing, then the JP one
./jpdis.sh  CB2_InitTitleScreen --side   # side by side, aligned (| differs, < EN only, > JP only)
./jpdis.sh  CB2_InitTitleScreen --diff   # unified diff, addresses and pool values normalised
./jpdis.sh  --jp-range 0x080e4110 0x080e414c   # any JP range (JP-only code from DIFFERENCES.md)
```

Listings name every address through the map: a name in a JP listing means "the JP
counterpart of this EN symbol"; `L+0x..` is a label inside the function; unmapped JP
addresses stay numeric. Literal pools and jump tables print as `.word`.

TSV columns: `symbol kind en_addr jp_addr en_size jp_size status confidence method source`

- `kind`: `func` (Thumb functions have bit 0 set in both addresses, as in the ELF),
  `data` (ROM), `ram` (EWRAM/IWRAM).
- `status`: `identical` (code or bytes equal once relocated addresses are masked),
  `changed` (counterpart found, body differs), `unmatched` (no counterpart found).
- `jp_size`: functions: EN size if identical, else the JP function's extent (code + pool).
  Data: EN size if identical, strings: JP length, else the span to the JP address of the
  next EN symbol (can include JP-only data placed after it; blank when unknown).
- `source`: the decomp file. Static names repeated in several files appear once per file.
- Regenerate: `python3 -I bin/match.py && python3 -I bin/validate.py && python3 -I bin/report.py`
  (about 40 s; `bin/consistency.py` re-checks the call graph).

## Coverage

| | identical | changed | unmatched | total |
|---|---|---|---|---|
| functions | 13,110 (82.7%) | 2,554 (16.1%) | 192 (1.2%) | 15,856 |
| ROM data symbols | 39,330 | 14,940 | 1,146 | 55,416 |
| RAM symbols | 1,027 | 29 | 6 | 1,062 |

JP code with no EN counterpart: 20,650 bytes in 132 functions (`DIFFERENCES.md`).
Unmatched data is mostly what Japanese stores differently: move and ability descriptions
(JP keeps them in fixed 2-D char arrays, no pointer table: `gMoveDescriptionPointers`
has no counterpart), the bard's sound tables (JP bard is other code), English-only
strings, the four Trainer Hill modes, unused RAM fillers. Strings that changed are
`changed` (other text, other length).

## Validation

Against the repository's known Japanese points (`bin/validate.py`):

- `tools/locales/japanese-symbols.s.gz`: 83 of 87 equal, 1 wrong
  (`gFontShortJapaneseGlyphs`: JP keeps its fonts elsewhere and the font code changed),
  3 unmatched (`gFontNormalJapaneseGlyphs`, `gPokenavConditionCancel_Gfx`,
  `gTitleScreenEmeraldVersionPal`).
- `tools/locales/japanese.json.gz`: texts 12,944 equal, 37 wrong (0.3%), 584 unmatched
  (355 move and 78 ability descriptions, see above); graphics 79+18 equal, 1 wrong,
  3 unmatched; the four Easy Chat lists and the credits table equal.
- Self-consistency: in the 13,110 identical functions, all 29,633 BL targets, 3,621
  function pointers and 27,642 data pointers land on the mapped JP address of their
  target (0 mismatches).

Precision per method on those points (the `confidence` column of data symbols is this
precision, times the vote share): `pool` 449/449, `pool-aligned` 574/594, `data-ptr`
5,276/5,287, `data-gap:both` 3,074/3,075, `data-gap:closed` 376/379, `data-gap:back`
3,348/3,352. Function confidences: identical 0.98-1.0; changed ones by call-graph
agreement and instruction similarity (below 0.7 = check by eye; the JP extent may be off,
or the function was rewritten).

## Method

1. **Build.** agbcc from `$S/ext/agbcc` (host gcc), installed into a clean clone of the
   pinned commit; `make tools`, `make -j2 compare`. `en.gba`, `en.elf`, `en.map` are its
   outputs; `en_relocs.elf` is the same link with `--emit-relocs` (byte-identical image),
   which gives every relocation (BL, literal-pool and table pointers) by final address.
2. **Normalised bodies.** Each EN function is its bytes with the relocated fields masked
   (BL pairs, pointer words); a JP address matches when the stable bytes are equal, the
   BL fields are BLs and each pointer word has the same class (EWRAM, IWRAM, ROM, function).
3. **Anchors** (`anchor`): functions whose normalised body occurs once in the JP code area
   (the longest stable run is searched, the whole body verified); anchors out of link
   order are dropped (longest increasing subsequence). 10,593 anchors.
4. **Link order** (`link-order`): neighbours of identical functions verified at the same
   relative offset (JP keeps the object order). **Call graph** (`callgraph`): BL targets
   and function-pointer words at the same position in identical functions name the callee's
   JP address; verified = identical, otherwise `changed` (voted). `anchor-order`: repeated
   bodies resolved by position.
5. **Gaps** (`gap-align`): EN functions still unmapped between two mapped ones are aligned
   (dynamic programming) with the JP code between them, cut into functions by an agbcc
   function-extent finder (last return no branch jumps past, plus its pool; exact on
   15,817 of 15,844 EN Thumb functions); score = token similarity (instructions with branch
   and pool offsets dropped, ldr tokens by loaded class), kept at >= 0.4.
6. **Data.** `pool`: literal-pool words of identical functions; `pool-aligned`: the ldr
   and BL tokens of changed functions paired through the instruction alignment.
   `data-ptr`: pointer words inside mapped tables, scripts and structs whose JP copy has the
   same layout, including arrays of structs whose JP element is shorter (stride and field
   offsets inferred, e.g. `gItems` 44 -> 40 bytes, `gTrainers` 40 -> 32). `data-gap`: runs
   of unmapped symbols between mapped ones walked forward and backward (identical bytes, or
   strings cut at the JP terminators); `both` = the walks agree, `closed` = the forward walk
   lands exactly on the next symbol, `back` = backward walk only (string counts checked),
   `span` = same JP and EN distance. `data-order`: neighbours of identical data.
   `content`: unique byte-for-byte copy.
7. **Report** (`bin/report.py`): per file the changed functions (sizes, similarity,
   inserted/deleted/replaced instructions, calls and data added/removed), EN-only functions,
   JP-only code (gaps between mapped JP functions, attributed to the file whose unmatched
   EN functions sit there) and changed or unmatched data.

## A fuller reference symbol file

`docs/JAPANESE.md` item 8 asks for a fuller `tools/locales/japanese-symbols.s.gz`. The
map can produce it: `python3 -I bin/symfile.py OUT.s` writes the Italian file's format
(`.global/.type/.equ/.size`, addresses and sizes only, unmapped at 0, the 87 current
entries kept) — `japanese-symbols.candidate.s` here: 68,939 mapped symbols (confidence
>= 0.9), 2,867 at 0, 697 duplicate static names left out. It assembles with
`arm-none-eabi-as`. Not committed: the recipe uses each size to find bytes in the ROM, so
the `changed` data spans (which can include JP-only data) should be reviewed first, or the
file limited to `identical` symbols.

## Files

`jp_syms.tsv`, `DIFFERENCES.md`, `jpaddr.sh`, `jpdis.sh`, `state.pkl` (the map for scripts),
`match.log`, `validate.log`, `bin/` (common.py loaders, norm.py normalisation/tokeniser/
extent, match.py, datamap.py, validate.py, consistency.py, report.py, dis.py, lookup.py,
symfile.py, elf32.py), `pokeemerald/` (the EN build tree), `agbcc_src/`.
