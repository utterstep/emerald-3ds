"""Draft Japanese staging against tiny synthetic bytes, never ROM fixtures."""
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
import localize_japanese
from emerald3ds_builder.rom import Rom


class JapaneseStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root / "tree"
        data = bytearray(range(128))
        data[8:11] = b"\x51\x52\xff"                    # a string
        data[16:22] = b"\x10\x18\x00\x00\x00\x00"       # a 6-byte category: no terminator
        data[24:33] = bytes([4, 6, 26, 13, 7, 9]) + b"\x01\x02\xff"   # braille, header included
        self.data = bytes(data)
        self.sha = hashlib.sha1(self.data).hexdigest()
        self.rom = Rom(self.data, self.sha, "SYNTHETIC", "BPEJ", self.root / "fixture")
        self.sources = {
            "src/names.c": 'const u8 sName[] = _("NAME");\nconst u8 sCategory[12] = _("SEED");\n',
            "data/text/braille.inc": 'Braille:\n\tbrailleformat 4, 6, 26, 13, 7, 9\n\t.braille "AB$"\n',
            "include/constants/global.h": "#define GAME_LANGUAGE (LANGUAGE_ENGLISH)\n",
        }
        for name, text in self.sources.items():
            path = self.tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        names = self.sources["src/names.c"]
        braille = self.sources["data/text/braille.inc"]
        span = lambda text, needle: [text.index(needle), text.index(needle) + len(needle)]
        self.manifest = {"rom_sha1": self.sha, "graphics": [], "credits": None, "floors": [], "files": {
            "src/names.c": {"sha256": hashlib.sha256(names.encode()).hexdigest(), "edits": [
                span(names, '_("NAME")') + [8, 3, "c"], span(names, '_("SEED")') + [16, 2, "c_eos"]]},
            "data/text/braille.inc": {"sha256": hashlib.sha256(braille.encode()).hexdigest(), "edits": [
                [braille.index("brailleformat"), len(braille) - 1, 24, 9, "asm"]]}}}
        self.locales = self.root / "tools/locales"
        self.locales.mkdir(parents=True)

    def stage(self):
        (self.locales / "japanese.json.gz").write_bytes(gzip.compress(json.dumps(self.manifest).encode()))
        with patch.object(localize_japanese, "ROOT", self.root), \
                patch.object(localize_japanese, "JAPANESE_SHA1", self.sha), \
                patch.object(localize_japanese, "load_rom", return_value=self.rom), \
                contextlib.redirect_stdout(io.StringIO()):
            localize_japanese.stage(self.tree, self.rom.source)

    def assert_untouched(self):
        for name, text in self.sources.items():
            self.assertEqual((self.tree / name).read_bytes(), text.encode(), name)
        self.assertFalse((self.tree / ".emerald3ds-locale").exists())

    def test_strings_categories_and_braille_are_staged(self):
        self.stage()
        self.assertEqual((self.tree / "src/names.c").read_text(),
                         "const u8 sName[] = {0x51,0x52,0xFF};\nconst u8 sCategory[12] = {0x10,0x18,0xFF};\n")
        self.assertEqual((self.tree / "data/text/braille.inc").read_text(),
                         "Braille:\n\t\n\t.byte 0x04,0x06,0x1A,0x0D,0x07,0x09,0x01,0x02,0xFF\n\n")
        self.assertIn("LANGUAGE_ENGLISH", (self.tree / "include/constants/global.h").read_text())
        self.assertEqual((self.tree / ".emerald3ds-locale").read_text(), "BPEJ draft\n")

    def test_wrong_rom_hash_is_rejected_before_any_write(self):
        self.manifest["rom_sha1"] = "00" * 20
        with self.assertRaisesRegex(ValueError, "clean Japanese BPEJ"):
            self.stage()
        self.assert_untouched()

    def test_source_mismatch_is_rejected_before_any_write(self):
        self.manifest["files"]["data/text/braille.inc"]["sha256"] = "00" * 32
        with self.assertRaisesRegex(ValueError, "Source differs"):
            self.stage()
        self.assert_untouched()

    def test_bad_edits_leave_all_sources_untouched(self):
        edits = self.manifest["files"]["src/names.c"]["edits"]
        for edit, error in (([edits[0][0], edits[0][1], 127, 8, "c"], "out-of-range"),
                            ([edits[0][0], edits[0][1], 8, 3, "unknown"], "Unknown edit kind")):
            with self.subTest(edit=edit):
                self.manifest["files"]["src/names.c"]["edits"] = [edit, edits[1]]
                with self.assertRaisesRegex(ValueError, error):
                    self.stage()
                self.assert_untouched()
        self.manifest["files"]["src/names.c"]["edits"] = [edits[0], edits[0][:]]
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            self.stage()
        self.assert_untouched()


if __name__ == "__main__":
    unittest.main()
