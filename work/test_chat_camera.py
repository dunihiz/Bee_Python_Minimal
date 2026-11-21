import tempfile
import unittest
from pathlib import Path

from ifix_format import parse_original
from HeroSkin_DumpRepack import decrypt
from ifix_verify import verify_patch

from chat_camera import (
    CAMERA_KEY,
    ESP_KEY,
    HUD_KEY,
    MAX_ZOOM,
    MIN_ZOOM,
    build_chat_camera,
    parse_ecam,
    parse_feature_toggle,
)


BASE = (Path(__file__).resolve().parent.parent / 'inputs/legacy-camera-fixture/HeroSkin_1.bytes')


class CommandTests(unittest.TestCase):
    def test_accepts_decimal_camera_command(self):
        self.assertEqual(parse_ecam('/ecam 2.1'), 2.1)
        self.assertEqual(parse_ecam('/ecam 1.75'), 1.75)

    def test_rejects_unrelated_or_invalid_text(self):
        for value in ('hello', '/ecam', '/ecam abc', '/ecam 2.1 extra',
                      '/ecam 1e2', '/ecam nan', ''):
            with self.subTest(value=value):
                self.assertIsNone(parse_ecam(value))

    def test_clamps_camera_range(self):
        self.assertEqual(parse_ecam('/ecam 0.2'), MIN_ZOOM)
        self.assertEqual(parse_ecam('/ecam 9'), MAX_ZOOM)

    def test_accepts_exact_esp_and_hud_toggle_commands(self):
        self.assertEqual(parse_feature_toggle('/esp on'), (ESP_KEY, 1))
        self.assertEqual(parse_feature_toggle('/esp off'), (ESP_KEY, 0))
        self.assertEqual(parse_feature_toggle('/hud on'), (HUD_KEY, 1))
        self.assertEqual(parse_feature_toggle('/hud off'), (HUD_KEY, 0))
        for value in ('/esp', '/esp ON', '/hud off now', 'hud on', ''):
            with self.subTest(value=value):
                self.assertIsNone(parse_feature_toggle(value))


class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'HeroSkin_1.bytes'
        build_chat_camera(BASE, cls.output)
        cls.patch = parse_original(decrypt(cls.output, 'HeroSkin_1'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_only_camera_and_chat_hooks_are_active(self):
        descriptions = [fix['desc'] for fix in self.patch['fixes']]
        self.assertEqual(len(descriptions), 2)
        self.assertTrue(any('CameraSystem' in desc and 'GetZoomRate' in desc
                            for desc in descriptions))
        self.assertTrue(any('InBattleMsgInputView' in desc and 'On_EndEdit' in desc
                            for desc in descriptions))
        self.assertFalse(any(word in desc for desc in descriptions
                             for word in ('Skin', 'ActorServerDataProvider', 'frameSynchr')))

    def test_camera_reads_persisted_command_value(self):
        camera_id = next(fix['method_id'] for fix in self.patch['fixes']
                         if 'GetZoomRate' in fix['desc'])
        method = self.patch['methods'][camera_id]
        calls = [self.patch['extern_methods'][i['operand'] & 0xffff]['method_name']
                 for i in method['instructions'] if i['op'] == 'CallExtern']
        strings = [self.patch['intern_strings'][i['operand']]['value']
                   for i in method['instructions'] if i['op'] == 'Ldstr']
        self.assertIn('GetFloat', calls)
        self.assertIn('Clamp', calls)
        self.assertIn(CAMERA_KEY, strings)

    def test_chat_hook_parses_and_persists_zoom(self):
        chat_id = next(fix['method_id'] for fix in self.patch['fixes']
                       if 'On_EndEdit' in fix['desc'])
        method = self.patch['methods'][chat_id]
        calls = [self.patch['extern_methods'][i['operand'] & 0xffff]['method_name']
                 for i in method['instructions'] if i['op'] == 'CallExtern']
        strings = [self.patch['intern_strings'][i['operand']]['value']
                   for i in method['instructions'] if i['op'] == 'Ldstr']
        self.assertIn('StartsWith', calls)
        self.assertIn('Substring', calls)
        self.assertIn('TryParse', calls)
        self.assertIn('SetFloat', calls)
        self.assertIn('get_InvariantCulture', calls)
        self.assertIn('IsNaN', calls)
        self.assertIn('IsInfinity', calls)
        self.assertIn('OnCameraHeightChanged', calls)
        self.assertIn('/ecam ', strings)
        self.assertIn(CAMERA_KEY, strings)

    def test_patch_has_no_touch_or_skin_dependencies(self):
        joined_types = '\n'.join(self.patch['extern_types'])
        active = {fix['method_id'] for fix in self.patch['fixes']}
        active_externs = {
            instruction['operand'] & 0xffff
            for method_id in active
            for instruction in self.patch['methods'][method_id]['instructions']
            if instruction['op'] == 'CallExtern'
        }
        active_descriptions = '\n'.join(
            self.patch['extern_methods'][index]['desc'] for index in active_externs
        )
        self.assertNotIn('UnityEngine.Touch', joined_types)
        self.assertNotIn('GetTouch', active_descriptions)
        self.assertNotIn('GetActorSkinID', active_descriptions)

    def test_all_active_bytecode_has_valid_stack_and_branches(self):
        active = {fix['method_id'] for fix in self.patch['fixes']}
        external_ids = {
            instruction['operand'] & 0xffff
            for method_id in active
            for instruction in self.patch['methods'][method_id]['instructions']
            if instruction['op'] == 'CallExtern'
        }
        arities = {
            index: (0 if self.patch['extern_methods'][index]['method_name']
                    in {'SetFloat', 'OnCameraHeightChanged'} else 1)
            for index in external_ids
        }
        report = verify_patch(self.patch, extern_returns=arities)
        self.assertEqual({method['method_id'] for method in report['methods']}, active)


if __name__ == '__main__':
    unittest.main()
