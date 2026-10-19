#!/usr/bin/env python3
"""furigana_words.py --dir DIR: the words of the kanji conversion, for the reading pane's taps.

The reading pane (3ds_port/src/3ds_reading.c, docs/FURIGANA.md) shows a word's
reading and meaning when it is tapped. This finds, for every [漢字|よみ] group of
the conversion in DIR (out/furigana.json), the dictionary word it belongs to,
and writes DIR/dict/words.json for gen_furigana.py to pack: those words with a
short English gloss from JMdict, their kanji's readings, stroke counts and
school grades from KANJIDIC2, and for each message the word of each of its
groups in order. Both dictionaries are the EDRDG's (CC BY-SA 4.0), in
DIR/dict/src; nothing of them or of the game's text goes into the repository.

A group is often only a word's kanji, its okurigana outside it (お[待|ま]たせ).
The morphological analyser (SudachiPy, run once here, not in the build:
uv run --with sudachipy --with sudachidict_core) says which word of the
sentence the group is in. In order, the group is:
  - in a verb or an adjective, that word by its dictionary form (待たせ is
    待つ, 負けた is 負ける, not the noun 負け), a potential form by its verb
    (勝てる is 勝つ);
  - its kanji with the kana after them, as long as JMdict has the word
    written and read so ([長|なが]い is 長い);
  - else the analyser's word, by its dictionary form;
  - else its kanji alone as JMdict writes and reads them.
A group none of those find keeps its kanji's details only.
"""
import argparse
import collections
import gzip
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

GLOSS_LENGTH = 72


# A godan verb's potential form ends in the e row and る (勝てる): its verb ends
# in the u row (勝つ).
POTENTIAL = {"え": "う", "け": "く", "げ": "ぐ", "せ": "す", "て": "つ", "ね": "ぬ", "べ": "ぶ", "め": "む", "れ": "る"}


def hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def kana(c: str) -> bool:
    return "ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c == "ー"


def ascii_text(text: str) -> str:
    """The gloss in the font's ASCII: accents dropped, the rest replaced."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return "".join(c if " " <= c <= "~" else "?" for c in text)


# --- JMdict -----------------------------------------------------------------

def load_jmdict(path: Path):
    """{kanji writing: [(entry number, [readings], glosses, common)]}."""
    by_kanji = collections.defaultdict(list)
    with gzip.open(path) as f:
        for _, entry in ET.iterparse(f):
            if entry.tag != "entry":
                continue
            kebs = [k.findtext("keb") for k in entry.findall("k_ele")]
            common = any(e.find("ke_pri") is not None for e in entry.findall("k_ele")) \
                or any(e.find("re_pri") is not None for e in entry.findall("r_ele"))
            rebs = [r.findtext("reb") for r in entry.findall("r_ele")]
            senses = []
            for sense in entry.findall("sense"):
                glosses = [g.text for g in sense.findall("gloss") if g.text]
                if glosses:
                    senses.append(glosses)
            seq = int(entry.findtext("ent_seq"))
            for keb in kebs:
                by_kanji[keb].append((seq, rebs, senses, common))
            entry.clear()
    return by_kanji


def gloss_of(senses) -> str:
    """The first sense's first glosses, and the second sense's first if there is room."""
    text = "; ".join(senses[0][:3])
    if len(senses) > 1 and len(text) < GLOSS_LENGTH - 12:
        text += "; " + senses[1][0]
    text = ascii_text(text)
    return text if len(text) <= GLOSS_LENGTH else text[:GLOSS_LENGTH - 3].rstrip() + "..."


def lookup(jmdict, writing: str, reading: str = None, starts: str = None):
    """The JMdict word written `writing` and read `reading` (or with a reading
    that starts with `starts`), common words first; None if there is none."""
    best = None
    for seq, rebs, senses, common in jmdict.get(writing, ()):
        for reb in rebs:
            if (reading is not None and reb == reading) or (starts is not None and reb.startswith(starts)):
                if senses and (best is None or (common and not best[3])):
                    best = (writing, reb, senses, common)
                break
    return best


# --- KANJIDIC2 --------------------------------------------------------------

def load_kanjidic(path: Path, wanted: set) -> dict:
    out = {}
    with gzip.open(path) as f:
        for _, ch in ET.iterparse(f):
            if ch.tag != "character":
                continue
            literal = ch.findtext("literal")
            if literal in wanted:
                misc = ch.find("misc")
                readings = ch.findall("reading_meaning/rmgroup/reading")
                meanings = [m.text for m in ch.findall("reading_meaning/rmgroup/meaning") if not m.get("m_lang")]
                out[literal] = {
                    "on": [r.text for r in readings if r.get("r_type") == "ja_on"][:4],
                    "kun": [r.text for r in readings if r.get("r_type") == "ja_kun"][:4],
                    "strokes": int(misc.findtext("stroke_count") or 0),
                    "grade": int(misc.findtext("grade") or 0),
                    "meaning": ascii_text(", ".join(meanings[:3]))[:40],
                }
            ch.clear()
    return out


# --- The conversion's groups ------------------------------------------------

def groups(annotated: str):
    """The message as plain text for the analyser, and each group's base,
    reading and span in it."""
    text = annotated.replace("{V1}", "ユウキ")
    text = re.sub(r"\{V\d+\}", "ナマエ", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = text.replace("\\n", "").replace("\\l", "").replace("\\p", "　")
    plain, found = [], []
    i = 0
    for m in re.finditer(r"\[([^|\]]+)\|([^\]]+)\]", text):
        plain.append(text[i:m.start()])
        start = sum(len(p) for p in plain)
        plain.append(m.group(1))
        found.append((m.group(1), m.group(2), start, start + len(m.group(1))))
        i = m.end()
    plain.append(text[i:])
    return "".join(plain), found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True, help="the kanji conversion's folder")
    args = ap.parse_args()
    from sudachipy import dictionary, tokenizer

    analyser = dictionary.Dictionary(dict="core").create()
    mode = tokenizer.Tokenizer.SplitMode.C
    src = args.dir / "dict" / "src"
    print("reading JMdict...", file=sys.stderr)
    jmdict = load_jmdict(src / "JMdict_e.gz")
    messages = json.loads((args.dir / "out" / "furigana.json").read_text(encoding="utf-8"))

    words, index = [], {}
    by_message = {}
    how = collections.Counter()
    lemma_reading = {}

    def word_id(found):
        writing, reading, senses, _ = found
        key = (writing, reading)
        if key not in index:
            index[key] = len(words)
            words.append({"word": writing, "reading": reading, "gloss": gloss_of(senses)})
        return index[key]

    kanji_seen = set()
    for m in messages:
        plain, found = groups(m["annotated"])
        if not found:
            continue
        tokens = []
        pos = 0
        for t in analyser.tokenize(plain, mode):
            tokens.append((pos, pos + len(t.surface()), t))
            pos += len(t.surface())
        ids = []
        for base, reading, start, end in found:
            kanji_seen.update(c for c in base if not kana(c))
            hit = None
            token = next((t for s0, e0, t in tokens if s0 <= start < e0), None)
            lemma = token.dictionary_form() if token is not None and base in token.dictionary_form() else None
            conjugates = token is not None and token.part_of_speech()[0] in ("動詞", "形容詞")

            def by_lemma():
                if lemma is None:
                    return None
                if lemma not in lemma_reading:
                    lemma_reading[lemma] = hiragana("".join(t.reading_form() for t in analyser.tokenize(lemma, mode)))
                found = lookup(jmdict, lemma, lemma_reading[lemma]) or lookup(jmdict, lemma, starts=reading)
                if not found and len(lemma) > 2 and lemma.endswith("る") and lemma[-2] in POTENTIAL:
                    verb = lemma[:-2] + POTENTIAL[lemma[-2]]
                    found = lookup(jmdict, verb, starts=reading)
                return found

            if conjugates:
                hit = by_lemma()
                if hit:
                    how["analyser"] += 1
            # Its kanji and the kana after them, as JMdict writes the word.
            if not hit:
                after = ""
                for c in plain[end:end + 5]:
                    if not kana(c):
                        break
                    after += c
                for n in range(len(after), -1, -1):
                    hit = lookup(jmdict, base + after[:n], reading + hiragana(after[:n]))
                    if hit:
                        how["okurigana" if n else "kanji"] += 1
                        break
            # The analyser's word, by its dictionary form.
            if not hit and not conjugates:
                hit = by_lemma()
                if hit:
                    how["analyser"] += 1
            ids.append(word_id(hit) if hit else -1)
            if not hit:
                how["none"] += 1
        by_message[m["key"]] = ids

    print("reading KANJIDIC2...", file=sys.stderr)
    kanji = load_kanjidic(src / "kanjidic2.xml.gz", kanji_seen)
    out = {
        "source": "JMdict and KANJIDIC2, EDRDG, CC BY-SA 4.0 (dict/src/LICENSE.txt)",
        "words": words,
        "kanji": kanji,
        "messages": by_message,
    }
    path = args.dir / "dict" / "words.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    total = sum(how.values())
    print("words: %d groups, %d words, %d kanji; found by okurigana %d, kanji %d, analyser %d, none %d "
          "(%.1f%% with a word)" % (total, len(words), len(kanji), how["okurigana"], how["kanji"], how["analyser"],
                                    how["none"], 100 * (total - how["none"]) / max(total, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
