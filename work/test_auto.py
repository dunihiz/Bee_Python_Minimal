"""Regression tests for R8's presentation-free auto-spell hook."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from auto_spells import AUTO_BP_KEY, AUTO_SMITE_KEY
from build_auto import (
    BASE, FORBIDDEN_AUTO_CALLS, _real_instructions, build,
)
from chat_camera import ESP_KEY
from ifix_patch import Patch
from chat_vm import ChatNative, execute_chat


class AutoSpellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.output = root / "output"
        cls.archive = root / "bundle.zip"
        cls.manifest = build(cls.output, cls.archive)
        cls.hero1 = Patch(cls.output / "Thanos/HeroSkin_1.bytes", "HeroSkin_1").parsed
        cls.hero2 = Patch(cls.output / "Thanos/HeroSkin_2.bytes", "HeroSkin_2")
        with zipfile.ZipFile(BASE) as base:
            cls.base2_path = root / "r6-HeroSkin_2.bytes"
            cls.base2_path.write_bytes(base.read("Thanos/HeroSkin_2.bytes"))
            cls.base2 = Patch(cls.base2_path, "HeroSkin_2")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def frame_fix(parsed):
        return next(row for row in parsed["fixes"] if "get_frameSynchr" in row["desc"])

    def auto_method(self):
        fix = next(row for row in self.hero2.parsed["fixes"]
                   if "CPlayerLocationStat" in row["desc"])
        return self.hero2.parsed["methods"][fix["method_id"]]

    def test_minimap_is_byte_identical_to_r6(self):
        before = self.frame_fix(self.base2.parsed)
        after = self.frame_fix(self.hero2.parsed)
        self.assertEqual(
            self.base2.methods[before["method_id"]],
            self.hero2.methods[after["method_id"]],
        )

    def test_auto_method_has_no_ui_hud_or_esp_calls(self):
        method = self.auto_method()
        instructions = list(_real_instructions(method))
        names = {
            self.hero2.parsed["extern_methods"][row["operand"] & 65535]["method_name"]
            for row in instructions if row["op"] == "CallExtern"
        }
        self.assertFalse(names & FORBIDDEN_AUTO_CALLS)
        strings = {
            self.hero2.parsed["intern_strings"][row["operand"]]["value"]
            for row in instructions if row["op"] == "Ldstr"
        }
        self.assertFalse(any("ESP" in value or "HiddenHeroLines" in value
                             for value in strings))
        internal = {row["operand"] & 65535 for row in instructions
                    if row["op"] in {"Call", "Callvirt"}}
        # Relocated helper ids are offset by the ten R6 methods. The clean
        # method may call only its guard and distance helper.
        self.assertFalse(internal & {14, 15, 24, 25, 27})

    def test_request_use_skill_remains_for_both_auto_paths(self):
        method = self.auto_method()
        instructions = list(_real_instructions(method))
        names = [
            self.hero2.parsed["extern_methods"][row["operand"] & 65535]["method_name"]
            for row in instructions if row["op"] == "CallExtern"
        ]
        self.assertEqual(names.count("RequestUseSkill"), 2)

    def test_commands_and_normal_chat_work(self):
        chat_id = next(
            row["method_id"] for row in self.hero1["fixes"]
            if "InBattleMsgInputView" in row["desc"] and "On_EndEdit" in row["desc"]
        )
        native = ChatNative()
        for command, key in (("/trungtri on", AUTO_SMITE_KEY),
                             ("/bocpha on", AUTO_BP_KEY)):
            execute_chat(self.hero1, chat_id, object(), command, native)
            self.assertEqual(native.prefs[key], 1)
        execute_chat(self.hero1, chat_id, object(), "/esp on", native)
        self.assertEqual(native.prefs[ESP_KEY], 1)
        execute_chat(self.hero1, chat_id, object(), "chat thuong", native)
        self.assertEqual(native.sent, [("chat thuong", 1)])

    def test_package_has_only_hero1_and_hero2(self):
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(
                sorted(name for name in bundle.namelist() if name.endswith(".bytes")),
                ["Thanos/HeroSkin_1.bytes", "Thanos/HeroSkin_2.bytes"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
