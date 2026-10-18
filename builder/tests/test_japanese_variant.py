"""The Japanese (BPEJ) variant end to end on synthetic data: the ROM check,
bootstrap's --japanese-rom, the pack's fingerprint and follower texts, the
release's payload/ja/ and the web manifest. No ROM and no game data."""

import argparse
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "builder"))
sys.path.insert(0, str(ROOT / "tools"))
from emerald3ds_builder import followers, pak, recipe as rcp, rom as romlib  # noqa: E402
from emerald3ds_builder.build import Payload, build_pack  # noqa: E402
from emerald3ds_builder.errors import BuilderError  # noqa: E402
from emerald3ds_builder.web import supported_sha1s  # noqa: E402

JAPANESE_SHA1 = "d7cf8f156ba9c455d164e1ea780a6bf1945465c2"


def load_tool(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up
    with patch.dict(os.environ):  # bootstrap.py sets devkitPro's variables
        spec.loader.exec_module(module)
    return module


def japanese_rom(payload: bytes = b"TEST") -> tuple[bytes, str]:
    data = bytearray(b"\xff" * romlib.ROM_SIZE)
    data[0xA0:0xB0] = b"POKEMON EMERBPEJ"
    data[0x200:0x200 + len(payload)] = payload
    return bytes(data), hashlib.sha1(data).hexdigest()


class JapaneseRomTests(unittest.TestCase):
    def test_the_no_intro_dump_is_a_profile(self):
        self.assertEqual(romlib.JAPANESE_SHA1, JAPANESE_SHA1)
        self.assertEqual(romlib.ROM_PROFILES["BPEJ"], JAPANESE_SHA1)
        self.assertEqual(romlib.KNOWN_CODES["BPEJ"], "Pocket Monsters Emerald (Japan)")

    def test_clean_dump_is_recognised_trimmed_or_not(self):
        data, sha = japanese_rom()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(romlib.ROM_PROFILES, {"BPEJ": sha}):
            for name, content in (("full.gba", data), ("trimmed.gba", data[:0x210])):
                path = Path(tmp) / name
                path.write_bytes(content)
                rom = romlib.load_rom(path)
                self.assertEqual((rom.code, rom.sha1), ("BPEJ", sha))
                # what tools/localize_japanese.py asks for
                self.assertEqual(romlib.load_rom(path, supported=(sha,)).code, "BPEJ")

    def test_modified_dump_is_refused_with_the_clean_hash(self):
        data, _ = japanese_rom()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hack.gba"
            path.write_bytes(data)
            with self.assertRaises(BuilderError) as ctx:
                romlib.load_rom(path)
            self.assertEqual(ctx.exception.code, "rom_modified")
            self.assertIn(JAPANESE_SHA1, str(ctx.exception))
            # a build limited to the English ROM names the Japanese one as another game
            with self.assertRaises(BuilderError) as ctx:
                romlib.load_rom(path, supported=(romlib.SUPPORTED_SHA1,))
            self.assertEqual(ctx.exception.code, "rom_wrong_game")
            self.assertIn("Pocket Monsters Emerald (Japan)", ctx.exception.message)


class JapanesePackTests(unittest.TestCase):
    def test_pack_from_the_japanese_payload_carries_japanese_follower_texts(self):
        data, sha = japanese_rom()
        crc = zlib.crc32(b"TEST") & 0xFFFFFFFF
        corpus = ("Text File : 258\n~~~~\n" + "\n".join(["ポケモン"] * followers.TEXT_COUNT) + "\n~~~~\n")
        corpus = corpus.encode("utf-8")
        sources = {"sources": {"corpus": {"repo": "owner/repo", "commit": "c" * 40}}, "files": [
            {"source": "corpus", "path": "tp_param.csv", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            {"source": "corpus", "path": "ja.txt", "size": len(corpus), "sha256": hashlib.sha256(corpus).hexdigest(),
             "language": "ja", "bank": 258},
            {"source": "corpus", "path": "en.txt", "size": 1, "sha256": "0" * 64, "language": "en"}]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(romlib.ROM_PROFILES, {"BPEJ": sha}):
            root = Path(tmp)
            (root / "local" / "corpus").mkdir(parents=True)
            (root / "local" / "corpus" / "ja.txt").write_bytes(corpus)
            (root / "local" / "corpus" / "tp_param.csv").write_bytes(b"")
            (root / "payload" / "ja").mkdir(parents=True)
            english = rcp.Recipe(engine_abi=1, rom_sha1=romlib.SUPPORTED_SHA1, release="test")
            english.save(root / "payload" / "emerald3ds.recipe")
            rcp.Recipe(engine_abi=pak.engine_abi([("game/test.bin", 4, crc)]), rom_sha1=sha, release="test",
                       entries=[{"path": "game/test.bin", "size": 4, "crc": crc, "ops": [["C", 0x200, 4]]}]
                       ).save(root / "payload" / "ja" / "emerald3ds.recipe")
            (root / "rom.gba").write_bytes(data)
            fetcher = followers.Fetcher(sources, [root / "local"], network=False, workers=1)
            info = build_pack(root / "rom.gba", Payload(root / "payload"), root / "out.pak",
                              follower_fetcher=fetcher)
            self.assertEqual(info["payload"].root.name, "ja")
            self.assertEqual((info["rom"], info["followers"]["texts"]), ("BPEJ", 1))
            with pak.PakReader(root / "out.pak") as reader:
                self.assertEqual(reader.rom_sha1.hex(), sha)
                self.assertEqual(reader.read("game/test.bin"), b"TEST")
                text = reader.read("followers/text/ja.bin")
                self.assertEqual(text[8 + 4 * followers.TEXT_COUNT:][:5], b"\x9F\x59\x73\x7E\xFF")
                with self.assertRaises(KeyError):  # only the ROM's own language is fetched
                    reader.read("followers/text/en.bin")

    def test_the_game_accepts_only_its_own_language_pack(self):
        """3ds_port/src/3ds_data.c: each GAME_LANGUAGE's fingerprint is that
        language's ROM, English the fallback."""
        source = (ROOT / "3ds_port/src/3ds_data.c").read_text(encoding="utf-8")
        branches = re.findall(r"#(?:el)?if GAME_LANGUAGE == LANGUAGE_(\w+)\nstatic const uint8_t "
                              r"sSupportedRomSha1\[20\] = \{([^}]*)\}", source)
        fallback = re.search(r"#else\nstatic const uint8_t sSupportedRomSha1\[20\] = \{([^}]*)\}", source)
        codes = {"SPANISH": "BPES", "FRENCH": "BPEF", "ITALIAN": "BPEI", "JAPANESE": "BPEJ"}

        def sha(body):
            return bytes(int(b, 16) for b in re.findall(r"0x([0-9a-f]{2})", body)).hex()
        self.assertEqual(sorted(language for language, _ in branches), sorted(codes))
        for language, body in branches:
            self.assertEqual(sha(body), romlib.ROM_PROFILES[codes[language]], language)
        self.assertEqual(sha(fallback.group(1)), romlib.SUPPORTED_SHA1)

    def test_release_audit_knows_the_dump(self):
        audit = load_tool("release_audit_ja", "tools/release_audit.py")
        self.assertLessEqual(set(romlib.ROM_PROFILES.values()), audit.KNOWN_ROM_SHA1)


class BootstrapTests(unittest.TestCase):
    COMMIT = "a" * 40

    def setUp(self):
        self.bootstrap = load_tool("bootstrap_ja", "tools/bootstrap.py")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        (self.root / "patches" / "pokeemerald").mkdir(parents=True)
        (self.root / "tools" / "locales").mkdir(parents=True)
        (self.root / "upstream.lock").write_text(
            '[pokeemerald]\nrepository = "https://example.invalid/pokeemerald"\ncommit = "%s"\n' % self.COMMIT)
        manifest = {"graphics": [["graphics/title.4bpp.lz", 0, 4]], "files": {}}
        (self.root / "tools" / "locales" / "japanese.json.gz").write_bytes(
            gzip.compress(json.dumps(manifest).encode()))
        self.tree = Path(temp.name) / "tree"
        (self.tree / ".git").mkdir(parents=True)
        (self.tree / ".emerald3ds-patches").write_text(self.bootstrap.patch_digest([]) + "\n")
        self.rom = Path(temp.name) / "emerald-jp.gba"
        self.rom.write_bytes(b"synthetic")

    def main(self, *argv):
        commands = []

        def git(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return types.SimpleNamespace(stdout=self.COMMIT + "\n", returncode=0)
            return types.SimpleNamespace(stdout="", returncode=1)  # ls-files: nothing tracked
        with patch.object(self.bootstrap, "ROOT", self.root), \
                patch.object(self.bootstrap, "run", lambda cmd, cwd=None: commands.append([str(c) for c in cmd])), \
                patch.object(self.bootstrap.subprocess, "run", git), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.bootstrap.main(["--dir", str(self.tree)] + list(argv)), 0)
        return commands

    def test_japanese_rom_resets_and_stages_like_the_other_languages(self):
        (self.tree / "3ds_port" / "build").mkdir(parents=True)
        commands = self.main("--japanese-rom", str(self.rom), "--python", "py")
        self.assertIn(["git", "reset", "-q", "--hard", self.COMMIT], commands)
        self.assertFalse((self.tree / "3ds_port" / "build").exists())  # the other language's objects
        self.assertEqual(commands[-3:], [
            ["make", "tools", "-j4"], ["make", "generated", "-j4"],
            ["py", str(self.root / "tools" / "localize_japanese.py"), "--tree", str(self.tree.resolve()),
             "--rom", str(self.rom.resolve())]])
        self.assertTrue((ROOT / "tools" / "localize_japanese.py").is_file())

    def test_leaving_japanese_resets_the_tree_and_its_art(self):
        (self.tree / ".emerald3ds-locale").write_text("BPEJ draft\n")
        for name in ("3ds_port/romfs/a.bin", "graphics/title.4bpp", "graphics/title.4bpp.lz"):
            (self.tree / name).parent.mkdir(parents=True, exist_ok=True)
            (self.tree / name).write_bytes(b"x")
        commands = self.main()
        self.assertIn(["git", "reset", "-q", "--hard", self.COMMIT], commands)
        self.assertFalse((self.tree / ".emerald3ds-locale").exists())
        self.assertFalse((self.tree / "3ds_port/romfs").exists())
        self.assertFalse((self.tree / "graphics/title.4bpp").exists())
        self.assertFalse((self.tree / "graphics/title.4bpp.lz").exists())
        self.assertFalse(any("localize" in " ".join(c) for c in commands))

    def test_one_language_at_a_time(self):
        self.assertEqual(self.bootstrap.previous_manifest("BPEJ draft"), "japanese.json.gz")
        self.assertEqual(self.bootstrap.previous_manifest("BPEI experimental"), "italian.json.gz")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.bootstrap.main(["--japanese-rom", "a.gba", "--italian-rom", "b.gba"])


class ReleaseTests(unittest.TestCase):
    def test_japanese_rom_adds_payload_ja(self):
        release = load_tool("build_release_ja", "tools/build_release.py")
        args = argparse.Namespace(spanish_rom=None, french_rom=Path("f.gba"), italian_rom=None,
                                  japanese_rom=Path("j.gba"))
        self.assertEqual(release.chosen_locales(args), [
            {"code": "fr", "stem": "french", "rom": Path("f.gba"), "script": "localize_french.py"},
            {"code": "ja", "stem": "japanese", "rom": Path("j.gba"), "script": "localize_japanese.py"}])
        for locale in release.chosen_locales(args):
            self.assertTrue((ROOT / "tools" / locale["script"]).is_file())

    def test_a_variant_without_reference_symbols_stops_before_its_recipe(self):
        release = load_tool("build_release_ja2", "tools/build_release.py")
        locale = {"code": "ja", "stem": "japanese", "rom": Path("j.gba"), "script": "localize_japanese.py"}
        args = argparse.Namespace(make=None, skip_make=True, skip_recipe=False, nm="arm-none-eabi-nm")
        with tempfile.TemporaryDirectory() as tmp, patch.object(release, "ROOT", Path(tmp)), \
                patch.object(release, "run") as run:
            with self.assertRaises(SystemExit) as ctx:
                release.build_localized_variant(args, "v0", Path(tmp) / "payload" / "ja", locale)
            self.assertIn("japanese-reference.s", str(ctx.exception))
            run.assert_not_called()

    def test_web_manifest_describes_the_japanese_variant(self):
        import build_web_payload
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "payload"
            for sub, sha in (("", romlib.SUPPORTED_SHA1), ("ja", JAPANESE_SHA1)):
                folder = payload / sub
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "Emerald3DS.3dsx").write_bytes(b"3DSX" + sub.encode())
                (folder / "Emerald3DS.smdh").write_bytes(b"SMDH")
                rcp.Recipe(engine_abi=0x1234 + len(sub), rom_sha1=sha, release="v1.0.0").save(
                    folder / "emerald3ds.recipe")
            files = build_web_payload.collect(payload, licenses_root=Path(tmp))
            self.assertIn("payload/ja/Emerald3DS.3dsx", files)
            manifest = build_web_payload.make_manifest(files, "1.0.0", "v1.0.0")
            variant, = manifest["variants"]
            self.assertEqual(variant["rom"], {"sha1": JAPANESE_SHA1, "name": "Pocket Monsters Emerald (Japan)",
                                              "code": "BPEJ", "region": "Japan", "language": "ja"})
            self.assertEqual(variant["assets"]["threeDsx"]["releaseAsset"], "Emerald3DS-ja.3dsx")
            self.assertEqual(variant["dataAbi"], "%08x" % (0x1234 + 2))
            self.assertIn(JAPANESE_SHA1, supported_sha1s(manifest))
            self.assertEqual(Payload(payload).for_rom(JAPANESE_SHA1).root.name, "ja")


if __name__ == "__main__":
    unittest.main()
