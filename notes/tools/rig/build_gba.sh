#!/bin/sh
# build_gba.sh TREE OUT : scratch GBA build (mGBA checks only, never shipped) of a
# bootstrapped, staged tree. Copies TREE to OUT, sets the port-only units aside,
# restores the decomp's own audio and flash code, adds link stubs, runs make modern.
# Result: OUT/pokeemerald_modern.gba (+ .map/.elf). Log: OUT.log
# RIG_FILL=1 also builds in rig_fill.c (CB2_RigFillSave, the test-save filler).
# JOBS (default 2) is make's -j.
set -e
TREE=$1; OUT=$2; RIG=$(dirname "$(readlink -f "$0")")
rm -rf "$OUT" "$OUT.aside"; cp -a "$TREE" "$OUT"; mkdir -p "$OUT.aside"
cd "$OUT"
for f in src/platform src/stub.c src/music_player.c src/sound_mixer.c src/agb_flash_dummy.c; do
  [ -e "$f" ] && mv "$f" "$OUT.aside/"
done
git checkout HEAD -- asm/macros/m4a.inc asm/macros/music_voice.inc audio_rules.mk \
  constants/m4a_constants.inc sound/MPlayDef.s sound/music_player_table.inc sound/song_table.inc \
  src/m4a.c src/m4a_tables.c src/sound.c include/gba/m4a_internal.h \
  include/gba/flash_internal.h src/agb_flash.c src/agb_flash_1m.c src/agb_flash_le.c src/agb_flash_mx.c
cp "$RIG/gba_rig_stubs.c" src/
[ "${RIG_FILL:-0}" = 1 ] && cp "$RIG/rig_fill.c" src/
make modern -j"${JOBS:-2}" ASM_PSEUDO_OP_CONV=cat FIX_UNDERSCORE=true > "$OUT.log" 2>&1 || { tail -30 "$OUT.log"; exit 1; }
ls -la pokeemerald_modern.gba
