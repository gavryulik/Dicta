import unittest
from types import SimpleNamespace
from unittest.mock import patch

from voice_translator.config import (
    PUSH_TO_TALK_LABEL,
    PUSH_TO_TALK_MODIFIERS,
    PUSH_TO_TALK_VIRTUAL_KEY_CODE,
)
from voice_translator.hotkey import GlobalPushToTalkHotkey, ShortcutState


class FakeEvent:
    def __init__(self, key_code, flags):
        self.key_code = key_code
        self.flags = flags


class ShortcutStateTests(unittest.TestCase):
    def test_default_shortcut_is_option_space(self) -> None:
        self.assertEqual(PUSH_TO_TALK_MODIFIERS, frozenset({"alt"}))
        self.assertEqual(PUSH_TO_TALK_LABEL, "Option+Space")

    def test_full_chord_starts_once_despite_repeated_key_down(self) -> None:
        state = ShortcutState()

        self.assertFalse(state.press("alt"))
        self.assertTrue(state.press("space"))
        self.assertFalse(state.press("space"))

    def test_control_space_does_not_start_recording(self) -> None:
        state = ShortcutState()

        self.assertFalse(state.press("ctrl"))
        self.assertFalse(state.press("space"))

    def test_releasing_trigger_stops_once(self) -> None:
        state = ShortcutState()
        state.press("alt")
        state.press("space")

        self.assertTrue(state.release("space"))
        self.assertFalse(state.release("space"))

    def test_releasing_modifier_also_stops_recording(self) -> None:
        state = ShortcutState()
        state.press("alt")
        state.press("space")

        self.assertTrue(state.release("alt"))
        self.assertFalse(state.release("space"))


class ShortcutInterceptionTests(unittest.TestCase):
    def test_suppresses_only_space_with_option(self) -> None:
        option_mask = 1 << 19
        quartz = SimpleNamespace(
            kCGKeyboardEventKeycode=9,
            kCGEventFlagMaskAlternate=option_mask,
            CGEventGetIntegerValueField=lambda event, unused: event.key_code,
            CGEventGetFlags=lambda event: event.flags,
        )
        option_space = FakeEvent(PUSH_TO_TALK_VIRTUAL_KEY_CODE, option_mask)
        plain_space = FakeEvent(PUSH_TO_TALK_VIRTUAL_KEY_CODE, 0)
        option_v = FakeEvent(9, option_mask)

        with patch.dict("sys.modules", {"Quartz": quartz}):
            self.assertIsNone(
                GlobalPushToTalkHotkey._intercept_macos_event(
                    None, option_space
                )
            )
            self.assertIs(
                GlobalPushToTalkHotkey._intercept_macos_event(None, plain_space),
                plain_space,
            )
            self.assertIs(
                GlobalPushToTalkHotkey._intercept_macos_event(None, option_v),
                option_v,
            )


if __name__ == "__main__":
    unittest.main()
