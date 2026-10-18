#!/usr/bin/env python3
"""screens.py [--only NAME...] [--build ROM.gba] : the same screens of the Japanese ROM
and of a build, side by side.

Each screen is an mgbarig script in screens/: NAME.txt for both ROMs, or NAME.jp.txt
and NAME.build.txt when they differ. The scripts are mgbarig's commands (mgbarig.c)
plus, resolved here:

  include FILE        the lines of screens/FILE.inc (boot sequences: boot_pc, ...)
  jp: CMD / build: CMD   a line for one ROM only
  repeat N CMD        CMD N times
  {sym} {sym+0x10} {sym|1}   an address: from the build's .map (next to its .gba), for
                      the Japanese ROM from $S/gba/syms/jp_syms.tsv or the hand-found
                      jp_fallback_syms.tsv ({sym|1}: a Thumb function pointer)
  {SAVES}             the test saves' directory
  shot NAME           shots/<rom>/<screen>/NAME.png

A screen whose script needs a symbol the ROM's table lacks is skipped for that ROM
(the montage says so). Output: shots/<screen>.png, every shot of the screen in
order, the Japanese ROM on the left and the build on the right.

  --build ROM   another build (default $S/gba/ja/pokeemerald_modern.gba; its .map must
                be beside it)
  --list        the screens and what each shows
"""
import argparse
import concurrent.futures
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import riglib  # noqa: E402

RIG = riglib.RIG
SCREENS = RIG / "screens"
SHOTS = RIG / "shots"


def screen_names():
    names = set()
    for p in SCREENS.glob("*.txt"):
        names.add(p.name.split(".")[0])
    return sorted(names)


def describe(name):
    for suffix in (".txt", ".jp.txt", ".build.txt"):
        p = SCREENS / (name + suffix)
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("#"):
                    return line.lstrip("# ")
    return ""


def expand(lines, tag, depth=0):
    out = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^(jp|build):\s*(.*)$", s)
        if m:
            if m.group(1) != tag:
                continue
            s = m.group(2)
        m = re.match(r"^include\s+(\S+)$", s)
        if m:
            if depth > 8:
                raise SystemExit("include loop at %s" % s)
            inc = SCREENS / (m.group(1) + ".inc")
            out += expand(inc.read_text().splitlines(), tag, depth + 1)
            continue
        m = re.match(r"^repeat\s+(\d+)\s+(.*)$", s)
        if m:
            out += [m.group(2)] * int(m.group(1))
            continue
        out.append(s)
    return out


def script_for(name, tag, syms, outdir):
    for suffix in (".%s.txt" % tag, ".txt"):
        p = SCREENS / (name + suffix)
        if p.exists():
            break
    else:
        return None, "no script"
    lines = expand(p.read_text().splitlines(), tag)
    shots = []
    res = []
    for s in lines:
        m = re.match(r"^shot\s+(\S+?)(?:\.png)?$", s)
        if m:
            f = outdir / (m.group(1) + ".png")
            shots.append(m.group(1))
            s = "shot %s" % f
        s = s.replace("{SAVES}", str(RIG / "saves"))
        try:
            s = riglib.resolve(s, syms)
        except KeyError as e:
            return None, "no symbol %s" % e
        res.append(s)
    return "\n".join(res) + "\n", shots


def run_one(name, tag, rom, syms):
    outdir = SHOTS / tag / name
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)
    script, shots = script_for(name, tag, syms, outdir)
    if script is None:
        return name, tag, [], shots
    (outdir / "script.txt").write_text(script)
    out, err = riglib.run_rig(rom, script)
    (outdir / "log.txt").write_text(out + err)
    return name, tag, shots, err.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="NAME")
    ap.add_argument("--build", default=str(riglib.DEFAULT_BUILD))
    ap.add_argument("--jp", default=str(riglib.JP_ROM))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    a = ap.parse_args()
    names = screen_names()
    if a.list:
        for n in names:
            print("%-22s %s" % (n, describe(n)))
        return
    if a.only:
        bad = [n for n in a.only if n not in names]
        if bad:
            raise SystemExit("unknown screen(s): %s (see --list)" % " ".join(bad))
        names = a.only
    roms = {"jp": (Path(a.jp), riglib.jp_syms()), "build": (Path(a.build), riglib.build_syms(a.build))}
    results = {}
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(run_one, n, t, roms[t][0], roms[t][1]) for n in names for t in roms]
        for f in futs:
            n, t, shots, note = f.result()
            results[(n, t)] = (shots, note)
    SHOTS.mkdir(exist_ok=True)
    for n in names:
        js, jn = results[(n, "jp")]
        bs, bn = results[(n, "build")]
        order = list(dict.fromkeys(js + bs))
        files, labels = [], []
        for s in order:
            for t, shots, note in (("jp", js, jn), ("build", bs, bn)):
                f = SHOTS / t / n / (s + ".png")
                files.append(f if s in shots else None)
                lab = "%s: %s" % ("JP ROM" if t == "jp" else "build", s)
                if s not in shots and isinstance(note, str) and note:
                    lab += " (%s)" % note
                labels.append(lab)
        if not order:
            files, labels = [None, None], ["JP ROM: %s" % jn, "build: %s" % bn]
        riglib.montage(SHOTS / (n + ".png"), files, 2, labels)
        notes = "; ".join("%s: %s" % (t, x) for t, x in (("jp", jn), ("build", bn)) if isinstance(x, str) and x)
        print("%-22s %s%s" % (n, SHOTS / (n + ".png"), ("  [" + notes[:200] + "]") if notes else ""))


if __name__ == "__main__":
    main()
