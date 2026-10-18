#!/usr/bin/env python3
"""Re-pin the locale manifests (tools/locales/*.json.gz) to a changed patched tree.

    python tools/repin_locales.py --repo . --old OLD_TREE --new NEW_TREE [--check]

Run it after a patch changes a file the manifests pin. OLD_TREE is the patched tree
the manifests pin (every pinned file must hash to its pin there); NEW_TREE is the
same tree with the new patches applied. For every pinned file whose text changed,
each edit's [start, end) character span is mapped through a line diff of the two
texts: the span must lie inside one run of unchanged lines, and the mapped span of
the new text must read exactly as the old one. The positions of the manifest's
unmapped source texts are mapped the same way, and the file's sha256 is replaced.
Any span that cannot be mapped is an error and nothing is written. With --check
nothing is written either; the report says what would change.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import sys
from pathlib import Path

MANIFESTS = ("spanish", "french", "italian", "japanese")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def equal_blocks(old: str, new: str):
    a = old.splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    aoff, boff = [0], [0]
    for line in a:
        aoff.append(aoff[-1] + len(line))
    for line in b:
        boff.append(boff[-1] + len(line))
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [(aoff[i1], aoff[i2], boff[j1]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag == "equal"]


def map_span(rel: str, start: int, end: int, old: str, new: str, blocks) -> tuple[int, int]:
    for a0, a1, b0 in blocks:
        if a0 <= start and end <= a1:
            nstart, nend = start - a0 + b0, end - a0 + b0
            if new[nstart:nend] != old[start:end]:
                raise ValueError("%s: span %d-%d reads differently after the change" % (rel, start, end))
            return nstart, nend
    raise ValueError("%s: span %d-%d is not inside unchanged lines" % (rel, start, end))


def repin(manifest: dict, old_tree: Path, new_tree: Path) -> list[str]:
    """Update manifest in place; return a line per changed file."""
    changed, texts = [], {}
    for rel, entry in manifest["files"].items():
        if not (old_tree / rel).exists() and not (new_tree / rel).exists():
            continue  # generated at build time (src/data/region_map/region_map_entries.h)
        old = (old_tree / rel).read_text(encoding="utf-8")
        new = (new_tree / rel).read_text(encoding="utf-8")
        if sha(new) == entry["sha256"] or old == new:
            continue  # already pinned to the new tree, or unchanged
        if sha(old) != entry["sha256"]:
            raise ValueError("%s: the old tree is not the pinned one" % rel)
        blocks = equal_blocks(old, new)
        texts[rel] = (old, new, blocks)
        edits = [list(map_span(rel, e[0], e[1], old, new, blocks)) + list(e[2:]) for e in entry["edits"]]
        # The localizers require sorted, non-overlapping, in-range spans.
        previous = 0
        for start, end, *_ in sorted(edits):
            if not previous <= start < end <= len(new):
                raise ValueError("%s: overlapping or out-of-range span after mapping" % rel)
            previous = end
        moved = sum(1 for a, b in zip(entry["edits"], edits) if a[:2] != b[:2])
        entry["sha256"], entry["edits"] = sha(new), edits
        changed.append("%s (%d of %d spans moved)" % (rel, moved, len(edits)))
    unmapped = manifest.get("unmapped_source_texts")  # a count in some manifests
    for item in unmapped if isinstance(unmapped, list) else []:
        if isinstance(item, dict) and item.get("file") in texts and "start" in item:
            old, new, blocks = texts[item["file"]]
            start, end = map_span(item["file"], item["start"], item.get("end", item["start"]), old, new, blocks)
            item["start"] = start
            if "end" in item:
                item["end"] = end
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {}
    for name in MANIFESTS:
        path = args.repo / "tools/locales" / (name + ".json.gz")
        manifest = json.loads(gzip.decompress(path.read_bytes()))
        changed = repin(manifest, args.old, args.new)
        print("%s: %s" % (name, "; ".join(changed) if changed else "unchanged"))
        if changed:
            outputs[path] = gzip.compress(json.dumps(manifest, separators=(",", ":")).encode(), compresslevel=9, mtime=0)
    if not args.check:
        for path, data in outputs.items():
            path.write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
