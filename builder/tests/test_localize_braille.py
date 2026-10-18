"""Braille texts keep their brailleformat header, against tiny synthetic bytes."""
import contextlib
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import localize_french
import localize_italian
from emerald3ds_builder.rom import Rom

BRAILLE = ("Braille_GoUpHere:\n"
           "\tbrailleformat 4, 6, 26, 13, 7, 9\n"
           "\t.braille \"GO UP HERE.$\"\n"
           "\n"
           "Text_Sign:\n"
           "\t.string \"A sign.$\"\n")
HEADER = bytes([4, 6, 26, 13, 7, 9])
LOCALES = ((localize_french, "FRENCH_SHA1", "french", "BPEF"),
           (localize_italian, "ITALIAN_SHA1", "italian", "BPEI"))


class BrailleHeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root / "tree"
        data = bytearray(128)
        data[16:19] = b"\x10\x11\xff"             # a braille text without its header
        data[32:41] = HEADER + b"\x12\x13\xff"    # a braille text with its header
        data[48:50] = b"\x14\xff"                 # an ordinary script text
        self.data = bytes(data)
        self.sha = hashlib.sha1(self.data).hexdigest()
        self.sources = {
            "data/text/braille.inc": BRAILLE,
            "src/data/credits.h": "/* synthetic credits placeholder */\n",
            "src/data/battle_frontier/trainer_hill.h": "/* no floors */\n",
            "include/constants/global.h": "#define GAME_LANGUAGE (LANGUAGE_ENGLISH)\n",
        }
        self.braille_span = (BRAILLE.index("brailleformat"), BRAILLE.index("\n\nText_Sign"))
        self.sign_span = (BRAILLE.index(".string"), len(BRAILLE) - 1)

    def stage(self, module, sha_name, name, code, braille_offset, braille_size):
        for path, text in self.sources.items():
            target = self.tree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode())
        locales = self.root / "tools/locales"
        locales.mkdir(parents=True, exist_ok=True)
        (locales / (name + "-symbols.s.gz")).write_bytes(gzip.compress(b".syntax unified\n"))
        edits = [[*self.braille_span, braille_offset, braille_size, "asm"],
                 [*self.sign_span, 48, 2, "asm"]]
        manifest = {"rom_sha1": self.sha, "graphics": [], "credits": 0, "credits_entries": 0, "floors": [],
                    "files": {"data/text/braille.inc": {
                        "sha256": hashlib.sha256(BRAILLE.encode()).hexdigest(), "edits": edits}}}
        (locales / (name + ".json.gz")).write_bytes(gzip.compress(json.dumps(manifest).encode()))
        rom = Rom(self.data, self.sha, "SYNTHETIC", code, self.root / "fixture")
        with patch.object(module, "ROOT", self.root), patch.object(module, sha_name, self.sha), \
                patch.object(module, "load_rom", return_value=rom), contextlib.redirect_stdout(io.StringIO()):
            module.stage(self.tree, rom.source)
        return (self.tree / "data/text/braille.inc").read_text()

    def test_header_is_kept_when_the_rom_range_is_the_text_alone(self):
        for locale in LOCALES:
            with self.subTest(locale=locale[2]):
                text = self.stage(*locale, 16, 3)
                self.assertIn("\tbrailleformat 4, 6, 26, 13, 7, 9\n\t.byte 0x10,0x11,0xFF\n", text)
                self.assertIn("Text_Sign:\n\t\n\t.byte 0x14,0xFF\n", text)

    def test_header_is_not_doubled_when_the_rom_range_holds_it(self):
        for locale in LOCALES:
            with self.subTest(locale=locale[2]):
                text = self.stage(*locale, 32, 9)
                self.assertNotIn("brailleformat", text)
                self.assertIn("\t.byte 0x04,0x06,0x1A,0x0D,0x07,0x09,0x12,0x13,0xFF\n", text)


if __name__ == "__main__":
    unittest.main()
