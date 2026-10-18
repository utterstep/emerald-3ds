#!/usr/bin/env python3
"""ctr_compile_compare.py: read ctr_compile_check.sh runs.

    --errors OUT          parse OUT/make.log into OUT/errors.tsv (unit, file:line, kind, message;
                          warnings too, kind "warning")
    --compare NEW BASE    errors of NEW (e.g. a staged Japanese tree) that BASE (the English
                          tree, the same worktree) does not have: a message counts as the
                          base's when the base has it as often in the same unit (line
                          numbers ignored, quoted names kept). Those are the real ones; the
                          rest come from the toolchain, the stubs or code both share.
"""
import argparse
import collections
import os
import re
import sys
from pathlib import Path

DIAG = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)? (?P<kind>error|fatal error|warning): (?P<msg>.*)$")
OBJ = re.compile(r"-o (?:\S*/3ds_port/)?(build/\S+\.o)\b")


def parse(out):
    out = Path(out)
    unit = None
    rows = []
    for line in open(out / "make.log", errors="replace"):
        line = line.rstrip("\n")
        if ("arm-none-eabi-gcc" in line or "arm-none-eabi-cpp" in line) and " -o " in line:
            m = OBJ.search(line)
            if m:
                unit = m.group(1)
            continue
        m = DIAG.match(line)
        if m:
            f = m.group("file")
            # Paths from the tree's root: absolute ones inside the scratch tree, the
            # game's (compiled from the root) and the port's (from 3ds_port/).
            if f.startswith("/"):
                f = re.sub(r"^.*?/tree/", "", f)
            elif not (unit or "").startswith("build/root"):
                f = os.path.normpath("3ds_port/" + f)
            rows.append((unit or "?", "%s:%s" % (f, m.group("line")), m.group("kind"), m.group("msg")))
        elif line.startswith("make: *** [") and "Error" in line:
            m = re.search(r"\[(?:\S*/)?(build/\S+\.o)\]", line)
            if m and not any(r[0] == m.group(1) for r in rows):
                rows.append((m.group(1), "-", "error", line))
    with open(out / "errors.tsv", "w") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    return rows


def load(out):
    p = Path(out) / "errors.tsv"
    if not p.exists():
        return parse(out)
    return [tuple(l.rstrip("\n").split("\t", 3)) for l in open(p) if l.strip()]


def norm(msg):
    return re.sub(r"\d+", "N", msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--errors", metavar="OUT")
    ap.add_argument("--compare", nargs=2, metavar=("NEW", "BASE"))
    ap.add_argument("--warnings", action="store_true", help="compare warnings too")
    a = ap.parse_args()
    if a.errors:
        rows = parse(a.errors)
        errs = [r for r in rows if r[2] != "warning"]
        units = collections.Counter(r[0] for r in errs)
        print("%d errors in %d units (%d warnings)" % (len(errs), len(units), len(rows) - len(errs)))
    if a.compare:
        new, base = load(a.compare[0]), load(a.compare[1])
        if not a.warnings:
            new = [r for r in new if r[2] != "warning"]
            base = [r for r in base if r[2] != "warning"]
        seen = collections.Counter((r[0], norm(r[3])) for r in base)
        only, shared = [], []
        for r in new:
            k = (r[0], norm(r[3]))
            if seen[k] > 0:
                seen[k] -= 1
                shared.append(r)
            else:
                only.append(r)
        print("# %d diagnostics only in %s (real), %d shared with %s (toolchain/stubs/common)" %
              (len(only), a.compare[0], len(shared), a.compare[1]))
        for r in only:
            print("NEW\t" + "\t".join(r))
        for r in shared:
            print("SHARED\t" + "\t".join(r))


if __name__ == "__main__":
    main()
