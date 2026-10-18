"""Re-pinning locale manifests through a patch, on tiny synthetic trees."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import repin_locales

OLD = 'static const u8 sA[] = _("ONE");\nstatic const u8 sB[] = _("TWO");\n'
NEW = 'static const u8 sA[] = _("ONE");\n#if PORT\nint x;\n#endif\nstatic const u8 sB[] = _("TWO");\n'


class RepinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.old, self.new = root / "old", root / "new"
        for tree, text in ((self.old, OLD), (self.new, NEW)):
            (tree / "src").mkdir(parents=True)
            (tree / "src/a.c").write_text(text)
        span = lambda text, needle: [text.index(needle), text.index(needle) + len(needle)]
        self.manifest = {"files": {"src/a.c": {
            "sha256": hashlib.sha256(OLD.encode()).hexdigest(),
            "edits": [span(OLD, '_("ONE")') + [0, 4, "c"], span(OLD, '_("TWO")') + [8, 4, "c"]]}},
            "unmapped_source_texts": [{"file": "src/a.c", "start": OLD.index("sB"), "end": OLD.index("sB") + 2}]}

    def test_spans_follow_the_change_and_read_the_same(self):
        changed = repin_locales.repin(self.manifest, self.old, self.new)
        self.assertEqual(len(changed), 1)
        entry = self.manifest["files"]["src/a.c"]
        self.assertEqual(entry["sha256"], hashlib.sha256(NEW.encode()).hexdigest())
        self.assertEqual([NEW[s:e] for s, e, *_ in entry["edits"]], ['_("ONE")', '_("TWO")'])
        self.assertEqual([e[2:] for e in entry["edits"]], [[0, 4, "c"], [8, 4, "c"]])
        item = self.manifest["unmapped_source_texts"][0]
        self.assertEqual(NEW[item["start"]:item["end"]], "sB")

    def test_a_changed_span_is_refused(self):
        (self.new / "src/a.c").write_text(NEW.replace('_("TWO")', '_("TOO")'))
        with self.assertRaisesRegex(ValueError, "not inside unchanged lines"):
            repin_locales.repin(self.manifest, self.old, self.new)

    def test_the_old_tree_must_be_the_pinned_one(self):
        (self.old / "src/a.c").write_text(OLD + "\n")
        with self.assertRaisesRegex(ValueError, "not the pinned one"):
            repin_locales.repin(self.manifest, self.old, self.new)


if __name__ == "__main__":
    unittest.main()
