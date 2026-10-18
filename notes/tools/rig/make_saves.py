#!/usr/bin/env python3
"""make_saves.py [--built DIR] : the rig's test saves, made by the game's own code.

Copies a built scratch tree (default $S/gba/ja, made by build_gba.sh) to
$S/gba/rig/fill_build, adds rig_fill.c (CB2_RigFillSave) and relinks. In that ROM,
at the title screen, gMain.callback2 is pointed at CB2_RigFillSave: it runs
NewGameInitData, fills the save blocks (rig_fill.c says with what) and warps into
the map. The rig then saves with the start menu (the decomp's flash code, as the
player would) and writes the battery save with mgbarig's savout:

  saves/pc.sav        Mauville City Pokemon Center 1F, facing the nurse
  saves/mauville.sav  Mauville City, in front of the Game Corner's door
  saves/namerater.sav Slateport, the Name Rater's house, facing him (nickname screen)
  saves/contest.sav   Lilycove's Contest Lobby, facing the contest receptionist

Then each save is loaded in the Japanese ROM and in the build: the Continue screen,
the field and the party are written to saves/proof/ and saves/proof.png.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import riglib  # noqa: E402

RIG = riglib.RIG
SAVES = RIG / "saves"
FILL = RIG / "fill_build"

VARIANTS = {"pc": (0, ""), "mauville": (1, "tap UP 20\n"), "namerater": (2, "tap UP 20\n"),
            "contest": (3, "tap UP 20\n")}

# Start menu: POKeDEX, POKeMON, BAG, POKeNAV, player, SAVE: five steps down.
SAVE_KEYS = """tap START 30
tap DOWN 10
tap DOWN 10
tap DOWN 10
tap DOWN 10
tap DOWN 10
tap A 60
tap A 240
tap A 60
"""

# From power-on to the field: START skips the intro and the title screen's phases
# and opens the main menu (where START does nothing), A picks CONTINUE.
CONTINUE_KEYS = "run 300\n" + "tap START 30\n" * 10
# The build's CONTINUE window expands {STR_VAR_1..3} (the Japanese ROM's texts)
# that its main_menu.c never fills: StringExpandPlaceholders runs away and the
# menu stays black. Empty strings there let it draw (README: known gaps).
BUILD_CONTINUE_FIX = "w8 {gStringVar1} ff\nw8 {gStringVar2} ff\nw8 {gStringVar3} ff\n"


def build_fill(built):
    # A copy with its timestamps: only rig_fill.c compiles, then the link.
    shutil.rmtree(FILL, ignore_errors=True)
    subprocess.run(["cp", "-a", str(built), str(FILL)], check=True)
    shutil.copy(RIG / "rig_fill.c", FILL / "src" / "rig_fill.c")
    log = RIG / "fill_build.log"
    with open(log, "w") as f:
        r = subprocess.run(["make", "modern", "-j2", "ASM_PSEUDO_OP_CONV=cat", "FIX_UNDERSCORE=true"],
                           cwd=FILL, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise SystemExit("fill build failed, see %s" % log)
    return FILL / "pokeemerald_modern.gba"


def make(rom, name):
    variant, extra = VARIANTS[name]
    syms = riglib.build_syms(rom)
    script = riglib.resolve(
        "run 900\n"
        "w32 {gRigFillVariant} %x\n"
        "w32 {gMain} 0\n"
        "w32 {gMain+4} {CB2_RigFillSave|1}\n"
        "run 300\n" % variant + extra + SAVE_KEYS +
        "shot %s/proof/%s_saved.png\n"
        "savout %s/%s.sav\n" % (SAVES, name, SAVES, name), syms)
    out, err = riglib.run_rig(rom, script)
    if err.strip():
        print(err, file=sys.stderr)
    print(out.strip())


def proof(rom, tag, name):
    shots = []
    script = "sav %s/%s.sav\nrun 1\n" % (SAVES, name)
    if tag == "build":
        script += riglib.resolve(BUILD_CONTINUE_FIX, riglib.build_syms(rom))
    script += CONTINUE_KEYS
    for i, (keys, shot) in enumerate([
            ("", "continue"), ("tap A 300\n", "field"),
            ("tap START 30\ntap DOWN 10\ntap A 120\n", "party")]):
        f = SAVES / "proof" / ("%s_%s_%s.png" % (name, tag, shot))
        script += keys + "shot %s\n" % f
        shots.append(f)
    out, err = riglib.run_rig(rom, script)
    if err.strip():
        print(err, file=sys.stderr)
    return shots


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--built", default=str(riglib.DEFAULT_BUILD.parent),
                    help="a scratch tree built by build_gba.sh (default %(default)s)")
    args = ap.parse_args()
    (SAVES / "proof").mkdir(parents=True, exist_ok=True)
    rom = build_fill(Path(args.built))
    for name in VARIANTS:
        make(rom, name)
    files, labels = [], []
    for name in VARIANTS:
        for tag, r in (("jp", riglib.JP_ROM), ("build", Path(args.built) / "pokeemerald_modern.gba")):
            for f in proof(r, tag, name):
                files.append(f)
                labels.append(f.name)
    riglib.montage(SAVES / "proof.png", files, 6, labels)
    print("saves:", ", ".join(str(SAVES / (n + ".sav")) for n in VARIANTS))
    print("proof:", SAVES / "proof.png")


if __name__ == "__main__":
    main()
