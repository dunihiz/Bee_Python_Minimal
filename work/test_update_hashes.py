"""Kiểm thử `update_hashes` mà không đụng vào file thật của project."""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

import update_hashes

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

PAYLOADS = {
    "official-1": b"engine-hero-1-v2",
    "official-2": b"engine-hero-2-v2",
    "prematch": b"engine-prematch-v2",
    "donor": b"engine-donor-v2",
    "minimap": b"engine-minimap-v2",
}


class PinRegexTests(unittest.TestCase):
    """Regex phải khớp đúng một lần trên source hiện tại."""

    def test_builder_pins_match_exactly_once(self):
        for pin in update_hashes.PINS:
            text = (ROOT / pin.module_rel).read_text(encoding="utf-8")
            matches = list(re.finditer(pin.regex, text))
            self.assertEqual(len(matches), 1, pin.name)

    def test_readme_pins_match_exactly_once(self):
        for pin in update_hashes.README_PINS:
            text = (ROOT / pin.module_rel).read_text(encoding="utf-8")
            matches = list(re.finditer(pin.regex, text))
            self.assertEqual(len(matches), 1, pin.name)


class ApplyRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "work").mkdir()
        for name in ("build_m5.py", "auto_spells.py", "build_auto.py"):
            shutil.copyfile(WORK / name, self.root / "work" / name)
        self.inputs: dict[str, Path] = {}
        for name, data in PAYLOADS.items():
            pin = next(row for row in update_hashes.PINS if row.name == name)
            path = self.root / pin.input_rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.inputs[name] = path

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_updates_every_pin_and_is_idempotent(self):
        report = update_hashes.collect(self.root, inputs=self.inputs)
        self.assertFalse(report.errors)
        self.assertEqual(len(report.drift), len(update_hashes.PINS))

        touched = update_hashes.apply_changes(report, backup=True)
        self.assertEqual(sorted(touched),
                         ["work/auto_spells.py", "work/build_auto.py",
                          "work/build_m5.py"])

        builder = (self.root / "work/build_m5.py").read_text(encoding="utf-8")
        donor = (self.root / "work/auto_spells.py").read_text(encoding="utf-8")
        minimap = (self.root / "work/build_auto.py").read_text(encoding="utf-8")
        for name, text in (("official-1", builder), ("official-2", builder),
                           ("prematch", builder)):
            self.assertIn(update_hashes.sha256_file(self.inputs[name]), text)
        self.assertIn(update_hashes.sha256_file(self.inputs["donor"]), donor)
        self.assertIn(update_hashes.sha256_file(self.inputs["minimap"]), minimap)

        # Chạy lại: không còn drift, không ghi thêm.
        again = update_hashes.collect(self.root, inputs=self.inputs)
        self.assertEqual(again.drift, [])
        self.assertEqual(update_hashes.apply_changes(again), [])

    def test_missing_input_is_reported_not_written(self):
        self.inputs.pop("donor")
        (self.root / "inputs/donor/HeroSkin_2.bytes").unlink()
        report = update_hashes.collect(self.root, inputs=self.inputs)
        self.assertEqual([change.pin.name for change in report.missing], ["donor"])

    def test_refresh_sums_updates_only_touched_modules(self):
        sums = self.root / "SHA256SUMS.txt"
        sums.write_text(
            "0" * 64 + "  work/build_m5.py\n"
            + "1" * 64 + "  work/other.py\n", encoding="utf-8")
        (self.root / "work/other.py").write_text("x", encoding="utf-8")
        changed = update_hashes.refresh_sums(self.root, ["work/build_m5.py"])
        self.assertEqual(changed, ["work/build_m5.py"])
        lines = sums.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[0].startswith(
            update_hashes.sha256_file(self.root / "work/build_m5.py")))
        self.assertTrue(lines[1].startswith("1" * 64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
