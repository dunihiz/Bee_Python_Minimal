"""Regression for E21 dropping ordinary text in the On_EndEdit replacement.

Native evidence: UnityFramework method 8504, 0x6a5f0e0. The native path
clears the input then applies chat restriction/rate/filter rules, routes to
network/local output, closes the entry UI and updates its normal counters.
This fixture records that boundary; it is not an iPhone integration test.
"""
from pathlib import Path
import math
import os
import tempfile
import unittest

from ifix_format import parse_original
from HeroSkin_DumpRepack import decrypt
from chat_camera import (CAMERA_KEY, ESP_KEY, HUD_KEY, SKIN_KEY, SKIN_ARM_KEY,
                         build_chat_camera)


from chat_vm import ChatNative, execute_chat


class ChatPassthroughE22Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        output = Path(cls.temp.name) / 'HeroSkin_1.bytes'
        # Override to exercise an actual delivered package (e.g. E21) as well
        # as the new generator. Never assume build_update uses the generator.
        package = os.environ.get('CHAT_PASSTHROUGH_HERO1')
        if package:
            output = Path(package)
        else:
            build_chat_camera(output=output,
                              toggle_keys={'esp': ESP_KEY, 'hud': HUD_KEY},
                              skin_key=SKIN_KEY, skin_arm_key=SKIN_ARM_KEY)
            from chat_passthrough import update_confirmed_chat
            update_confirmed_chat(output)
        cls.patch = parse_original(decrypt(output, 'HeroSkin_1'))
        cls.chat_id = next(f['method_id'] for f in cls.patch['fixes']
                           if 'InBattleMsgInputView' in f['desc'] and 'On_EndEdit' in f['desc'])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self): self.native = ChatNative()

    def edit(self, text):
        self.native.input_text = text
        execute_chat(self.patch, self.chat_id, object(), text, self.native)

    def test_native_exception_restores_hook_and_next_command_works(self):
        adjacent=self.native.wrappers[self.native.slot+1]
        self.native.fail_native=True
        self.edit('hello')
        self.assertIs(self.native.wrappers[self.native.slot],self.native.wrapper)
        self.assertIs(self.native.wrappers[self.native.slot+1],adjacent)
        self.native.fail_native=False
        self.edit('/eskin 9')
        self.edit('ok')
        self.assertEqual(self.native.prefs[SKIN_KEY],9)
        self.assertEqual(self.native.sent,[('ok',1)])

    def test_native_delegation_never_recurses_or_leaves_slot_disabled(self):
        self.edit('hello')
        self.assertEqual(self.native.native_slot_states,[None])
        self.assertIs(self.native.wrappers[self.native.slot],self.native.wrapper)

    def test_ordinary_text_before_any_command_uses_native_chat(self):
        self.edit('tập trung đường giữa')
        self.assertEqual(self.native.sent, [('tập trung đường giữa', 1)])
        self.assertEqual(self.native.input_text, '')

    def test_ordinary_text_after_skin_command_is_sent_once(self):
        self.edit('/eskin 15')
        self.assertEqual(self.native.prefs[SKIN_KEY], 15)
        self.assertEqual(self.native.prefs[SKIN_ARM_KEY], 1)
        self.assertEqual(self.native.sent, [])
        self.edit('đợi mình chút')
        self.assertEqual(self.native.sent, [('đợi mình chút', 1)])
        self.assertEqual(self.native.normal_edits, ['đợi mình chút'])
        self.assertEqual(self.native.input_text, '')

    def test_repeated_commands_do_not_swallow_subsequent_normal_messages(self):
        for command in ('/eskin 9', '/eskin 15', '/hud off', '/esp on', '/ecam 2.1'):
            self.edit(command)
            self.edit('ok')
        self.assertEqual(self.native.sent, [('ok', 1)] * 5)
        self.assertEqual(self.native.refreshes, 1)

    def test_ordinary_chat_retains_native_block_rules(self):
        self.native.blocked = True
        self.edit('/eskin 15')
        self.edit('hello')
        self.assertEqual(self.native.normal_edits, ['hello'])
        self.assertEqual(self.native.sent, [])

    def test_unknown_slash_text_is_normal_chat(self):
        self.edit('/help')
        self.assertEqual(self.native.sent, [('/help', 1)])

    def test_commands_are_local_and_do_not_enter_native_chat(self):
        for command in ('/eskin 15', '/ecam 2.1', '/hud off', '/esp on'):
            self.edit(command)
        self.assertEqual(self.native.sent, [])
        self.assertEqual(self.native.normal_edits, [])
        self.assertAlmostEqual(self.native.prefs[CAMERA_KEY], 2.1, places=5)


if __name__ == '__main__': unittest.main(verbosity=2)
