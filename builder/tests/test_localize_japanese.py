"""Japanese staging against tiny synthetic bytes, never ROM fixtures."""
import contextlib
import gzip
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import localize_japanese
from emerald3ds_builder.rom import Rom

BASE = 0x08000000
LZ, RAW, CREDITS, RECORDS, CREDIT_TEXT, MOVES = 64, 96, 128, 160, 200, 300


class JapaneseStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root / "tree"
        data = bytearray(512)
        data[8:11] = b"\x51\x52\xff"                    # a string
        data[16:22] = b"\x10\x18\x00\x00\x00\x00"       # a 6-byte category: no terminator
        data[24:33] = bytes([4, 6, 26, 13, 7, 9]) + b"\x01\x02\xff"   # braille, header included
        data[LZ:LZ + 13] = b"\x10\x08\x00\x00\x00" + bytes(range(1, 9))  # LZ77: 8 literal bytes
        data[RAW:RAW + 8] = bytes(range(0x20, 0x28))
        for page_entry in range(5):                     # one credits page: a title and 4 blanks
            struct.pack_into("<I", data, CREDITS + 4 * page_entry, BASE + RECORDS + (8 if page_entry else 0))
        data[RECORDS:RECORDS + 8] = bytes([7, 1, 0, 0]) + struct.pack("<I", BASE + CREDIT_TEXT)
        data[RECORDS + 8:RECORDS + 16] = bytes([0, 0, 0, 0]) + struct.pack("<I", BASE + CREDIT_TEXT + 2)
        data[CREDIT_TEXT:CREDIT_TEXT + 3] = b"\x01\xff\xff"
        struct.pack_into("<3H", data, MOVES, 3, 1, 2)   # the list in the ROM's (kana) order
        self.data = bytes(data)
        self.sha = hashlib.sha1(self.data).hexdigest()
        self.rom = Rom(self.data, self.sha, "SYNTHETIC", "BPEJ", self.root / "fixture")
        self.sources = {
            "src/names.c": 'const u8 sName[] = _("NAME");\nconst u8 sCategory[12] = _("SEED");\n',
            "data/text/braille.inc": 'Braille:\n\tbrailleformat 4, 6, 26, 13, 7, 9\n\t.braille "AB$"\n',
            "include/constants/global.h": "#define GAME_LANGUAGE (LANGUAGE_ENGLISH)\n",
            "src/contest_util.c": "#define CONTEST_TITLE_JAPANESE 1\n",
            "src/data/easy_chat/easy_chat_group_move_1.h":
                "const u16 gEasyChatGroup_Move1[] = {\n    MOVE_POUND,\n    MOVE_KARATE_CHOP,\n    MOVE_DOUBLE_SLAP,\n};\n",
            "include/constants/moves.h":
                "#define MOVE_POUND 1\n#define MOVE_KARATE_CHOP 2\n#define MOVE_DOUBLE_SLAP 3\n",
        }
        for name, text in self.sources.items():
            path = self.tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        names = self.sources["src/names.c"]
        braille = self.sources["data/text/braille.inc"]
        span = lambda text, needle: [text.index(needle), text.index(needle) + len(needle)]
        self.manifest = {
            "rom_sha1": self.sha, "credits": CREDITS, "credits_entries": 5, "floors": [],
            "graphics": [["graphics/a/tiles.4bpp.lz", LZ, 13], ["graphics/a/icon.4bpp", RAW, 8],
                         ["graphics/a/title.bin", RAW, 4]],
            "graphics_patches": {"0071-x": {"file": "src/contest_util.c", "marker": "CONTEST_TITLE_JAPANESE"}},
            "graphics_patch_of": {"graphics/a/title.bin": "0071-x"},
            "files": {
                "src/names.c": {"sha256": hashlib.sha256(names.encode()).hexdigest(), "edits": [
                    span(names, '_("NAME")') + [8, 3, "c"], span(names, '_("SEED")') + [16, 2, "c_eos"]]},
                "data/text/braille.inc": {"sha256": hashlib.sha256(braille.encode()).hexdigest(), "edits": [
                    [braille.index("brailleformat"), len(braille) - 1, 24, 9, "asm"]]}}}
        self.locales = self.root / "tools/locales"
        self.locales.mkdir(parents=True)
        self.symbols = (".syntax unified\n.equ gEasyChatGroup_Move1, %d\n.size gEasyChatGroup_Move1, 6\n"
                        % (BASE + MOVES)).encode()

    def stage(self):
        (self.locales / "japanese.json.gz").write_bytes(gzip.compress(json.dumps(self.manifest).encode()))
        (self.locales / "japanese-symbols.s.gz").write_bytes(gzip.compress(self.symbols))
        with patch.object(localize_japanese, "ROOT", self.root), \
                patch.object(localize_japanese, "JAPANESE_SHA1", self.sha), \
                patch.object(localize_japanese, "load_rom", return_value=self.rom), \
                contextlib.redirect_stdout(io.StringIO()):
            localize_japanese.stage(self.tree, self.rom.source)

    def assert_untouched(self):
        for name, text in self.sources.items():
            self.assertEqual((self.tree / name).read_bytes(), text.encode(), name)
        self.assertFalse((self.tree / ".emerald3ds-locale").exists())
        self.assertFalse((self.tree / "graphics").exists())
        self.assertFalse((self.tree / "src/data/credits.h").exists())

    def test_strings_categories_and_braille_are_staged(self):
        self.stage()
        self.assertEqual((self.tree / "src/names.c").read_text(),
                         "const u8 sName[] = {0x51,0x52,0xFF};\nconst u8 sCategory[12] = {0x10,0x18,0xFF};\n")
        self.assertEqual((self.tree / "data/text/braille.inc").read_text(),
                         "Braille:\n\t\n\t.byte 0x04,0x06,0x1A,0x0D,0x07,0x09,0x01,0x02,0xFF\n\n")
        self.assertEqual((self.tree / ".emerald3ds-locale").read_text(), "BPEJ experimental\n")

    def test_language_symbols_and_easy_chat_order_are_staged(self):
        self.stage()
        self.assertEqual((self.tree / "include/constants/global.h").read_text(),
                         "#define GAME_LANGUAGE (LANGUAGE_JAPANESE)\n")
        self.assertEqual((self.tree / "build/japanese-reference.s").read_bytes(), self.symbols)
        self.assertEqual((self.tree / "src/data/easy_chat/easy_chat_group_move_1.h").read_text(),
                         "const u16 gEasyChatGroup_Move1[] = {\n    MOVE_DOUBLE_SLAP,\n    MOVE_POUND,\n"
                         "    MOVE_KARATE_CHOP,\n};\n")

    def test_graphics_are_staged_and_decompressed(self):
        self.stage()
        self.assertEqual((self.tree / "graphics/a/tiles.4bpp.lz").read_bytes(), self.data[LZ:LZ + 13])
        self.assertEqual((self.tree / "graphics/a/tiles.4bpp").read_bytes(), bytes(range(1, 9)))
        self.assertEqual((self.tree / "graphics/a/icon.4bpp").read_bytes(), self.data[RAW:RAW + 8])
        self.assertEqual((self.tree / "graphics/a/title.bin").read_bytes(), self.data[RAW:RAW + 4])

    def test_credits_are_rebuilt_with_the_rom_page_count(self):
        self.stage()
        credits = (self.tree / "src/data/credits.h").read_text()
        self.assertIn("enum { PAGE_COUNT = 1 };", credits)
        self.assertIn("static const u8 sJapaneseCreditsText_%d[] = {0x01,0xFF};" % CREDIT_TEXT, credits)
        self.assertIn("= {7,1,sJapaneseCreditsText_%d};" % CREDIT_TEXT, credits)
        self.assertIn("{&sJapaneseCreditsEntry_%d,%s},\n};" % (RECORDS, ",".join(
            ["&sJapaneseCreditsEntry_%d" % (RECORDS + 8)] * 4)), credits)

    def test_a_graphic_that_needs_a_patch_is_refused_without_it(self):
        (self.tree / "src/contest_util.c").write_text("// another patch set\n")
        self.sources["src/contest_util.c"] = "// another patch set\n"
        with self.assertRaisesRegex(ValueError, "needs patch 0071-x"):
            self.stage()
        self.assert_untouched()

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

    def test_bad_data_leaves_all_sources_untouched(self):
        for key, value, error in (("graphics", [["graphics/a/x.4bpp", 508, 8]], "Graphic outside ROM"),
                                  ("credits_entries", 4, "Invalid credits table"),
                                  ("floors", [["sFloors_Normal", 0, 3808]], "no Trainer Hill floors")):
            with self.subTest(key=key):
                saved = self.manifest[key]
                self.manifest[key] = value
                with self.assertRaisesRegex(ValueError, error):
                    self.stage()
                self.assert_untouched()
                self.manifest[key] = saved
        (self.tree / "include/constants/global.h").write_text("#define GAME_LANGUAGE (LANGUAGE_FRENCH)\n")
        self.sources["include/constants/global.h"] = "#define GAME_LANGUAGE (LANGUAGE_FRENCH)\n"
        with self.assertRaisesRegex(ValueError, "GAME_LANGUAGE"):
            self.stage()
        self.assert_untouched()

    def test_bad_edits_leave_all_sources_untouched(self):
        edits = self.manifest["files"]["src/names.c"]["edits"]
        for edit, error in (([edits[0][0], edits[0][1], 511, 8, "c"], "out-of-range"),
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
