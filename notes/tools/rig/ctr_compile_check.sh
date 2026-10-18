#!/bin/bash
# ctr_compile_check.sh WORKTREE STAGED_TREE [OUT] : compile (no link) every C unit of
# the 3DS build the way 3ds_port/Makefile and full.mk compile them, without devkitPro.
#
#   WORKTREE     a checkout of the repository: its 3ds_port/ is the one compiled
#   STAGED_TREE  a bootstrapped tree (tools/bootstrap.py, staged or English): the game
#   OUT          scratch output (default $RIG/ctr/out/<name of STAGED_TREE>)
#
# OUT/tree is STAGED_TREE's top level as symlinks plus a copy of WORKTREE/3ds_port, so
# the port's "../../include/..." and the game's compile from the tree's root resolve as
# in a bootstrapped tree. make runs there with -k -j2 and DEVKITPRO pointing at
# $RIG/ctr/devkitpro: Ubuntu's arm-none-eabi-gcc 13 behind a wrapper (adds -mfpu=vfp,
# which devkitARM's GCC is configured with; -mfloat-abi=hard needs it), the libctru,
# citro3d and citro2d headers from $S/ext, and the stubs of $RIG/ctr/stub for headers
# only devkitARM's newlib has (README lists them). Every target is an object file:
# native units (src/*.c, src/voxel/ctr_voxel.c), the bridge and voxel game units and
# every game unit (src/**/*.c through preproc), with the Makefile's own flags.
#
# Results: OUT/make.log (all output), OUT/errors.tsv (unit, file:line, message),
# OUT/failed.txt (objects not built). ctr_compile_compare.py compares two runs.
# ONLY=REGEX limits the objects (e.g. ONLY='build/[^r]' for the port's own units).
set -u
RIG=$(dirname "$(readlink -f "$0")")
WT=$(readlink -f "$1"); STAGED=$(readlink -f "$2")
OUT=${3:-$RIG/ctr/out/$(basename "$STAGED")}
FAKE=$RIG/ctr/devkitpro
[ -d "$WT/3ds_port" ] || { echo "no $WT/3ds_port"; exit 2; }
[ -d "$STAGED/src" ] || { echo "no $STAGED/src"; exit 2; }

# The staged tree must come from the worktree's patches.
want=$(python3 - "$WT" <<'EOF'
import hashlib, sys
from pathlib import Path
d = hashlib.sha256()
for p in sorted((Path(sys.argv[1]) / "patches" / "pokeemerald").glob("*.patch")):
    d.update(p.name.encode()); d.update(p.read_bytes())
print(d.hexdigest())
EOF
)
have=$(cat "$STAGED/.emerald3ds-patches" 2>/dev/null)
[ "$want" = "$have" ] || echo "WARNING: $STAGED was bootstrapped from other patches than $WT/patches ($have vs $want)"
echo "language: $(grep -o 'define GAME_LANGUAGE.*' "$STAGED/include/constants/global.h")"

rm -rf "$OUT"; mkdir -p "$OUT/tree"
for e in "$STAGED"/* "$STAGED"/.[!.]*; do
  [ -e "$e" ] || continue
  n=$(basename "$e")
  [ "$n" = 3ds_port ] || [ "$n" = .git ] && continue
  ln -s "$e" "$OUT/tree/$n"
done
mkdir -p "$OUT/tree/3ds_port"
(cd "$WT/3ds_port" && tar cf - --exclude=./build --exclude=./dist . ) | (cd "$OUT/tree/3ds_port" && tar xf -)

cd "$OUT/tree/3ds_port"
MK=(make -k DEVKITPRO="$FAKE" DEVKITARM="$FAKE/devkitARM" PYTHON=python3)
# The objects of C units, from the Makefile's own list.
"${MK[@]}" -s --eval='rig-print-objects: ; @echo $(OBJECTS)' rig-print-objects 2>/dev/null | tr ' ' '\n' \
  | grep '\.o$' | while read -r o; do
    case "$o" in
      build/root/src/*) echo "$o" ;;
      build/root/*|build/buildinfo.o|build/linkid.o) ;;
      build/bridge/*|build/voxel/*|build/ctr_voxel.o) echo "$o" ;;
      build/*) f="src/${o#build/}"; [ -f "${f%.o}.c" ] && echo "$o" ;;
    esac
  done | grep -E "${ONLY:-.}" > "$OUT/targets.txt"
echo "$(wc -l < "$OUT/targets.txt") objects"
"${MK[@]}" -j"${JOBS:-2}" --output-sync=target $(cat "$OUT/targets.txt") > "$OUT/make.log" 2>&1
for o in $(cat "$OUT/targets.txt"); do [ -f "$o" ] || echo "$o"; done > "$OUT/failed.txt"
python3 "$RIG/ctr_compile_compare.py" --errors "$OUT"
echo "$(wc -l < "$OUT/failed.txt") of $(wc -l < "$OUT/targets.txt") objects failed; $OUT/errors.tsv"
echo "compare with another run (e.g. the English tree): python3 $RIG/ctr_compile_compare.py --compare $OUT OTHER_OUT [--warnings]"
