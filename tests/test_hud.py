import unittest
from unittest.mock import Mock, call, patch

import voice_translator.hud as hud_module
from voice_translator.hud import (
    HUD_VISIBLE_SECONDS,
    StatusHUD,
    _NonActivatingPanel,
)


class StatusHUDTests(unittest.TestCase):
    def test_public_states_use_expected_text_and_completion_delay(self) -> None:
        hud = Mock()

        StatusHUD.show_recording(hud)
        StatusHUD.show_translating(hud)
        StatusHUD.show_done(hud)
        StatusHUD.show_error(hud)

        self.assertEqual(
            hud._show.call_args_list,
            [
                call("Recording…"),
                call("Translating…"),
                call("Done", hide_after=HUD_VISIBLE_SECONDS),
                call("Error", hide_after=HUD_VISIBLE_SECONDS),
            ],
        )
        self.assertEqual(HUD_VISIBLE_SECONDS, 0.7)

    @unittest.skipIf(hud_module.objc is None, "PyObjC is unavailable")
    def test_panel_cannot_become_key_or_main(self) -> None:
        panel = _NonActivatingPanel.alloc()

        self.assertFalse(panel.canBecomeKeyWindow())
        self.assertFalse(panel.canBecomeMainWindow())

    @unittest.skipIf(hud_module.objc is None, "PyObjC is unavailable")
    def test_label_frame_is_centered_in_hud(self) -> None:
        from Foundation import NSMakeRect

        hud = StatusHUD.alloc().init()
        hud._panel = Mock()
        hud._effect_view = Mock()
        hud._label = Mock()
        hud._label.frame.return_value = NSMakeRect(0.0, 0.0, 80.0, 18.0)
        screen = Mock()
        screen.visibleFrame.return_value = NSMakeRect(0.0, 0.0, 1200.0, 800.0)

        with patch("voice_translator.hud.NSScreen") as screen_class:
            screen_class.mainScreen.return_value = screen
            hud._resize_and_position()

        label_frame = hud._label.setFrame_.call_args.args[0]
        panel_frame = hud._panel.setFrame_display_.call_args.args[0]
        self.assertEqual(label_frame.origin.x, 18.0)
        self.assertEqual(label_frame.origin.y, 12.0)
        self.assertEqual(label_frame.size.width, 80.0)
        self.assertEqual(label_frame.size.height, 18.0)
        self.assertEqual(panel_frame.size.height, 42.0)

    @unittest.skipIf(hud_module.objc is None, "PyObjC is unavailable")
    def test_completion_timer_hides_panel(self) -> None:
        from Foundation import NSObject

        hud = StatusHUD.alloc().init()
        timer = NSObject.alloc().init()
        panel = Mock()
        hud._hide_timer = timer
        hud._panel = panel

        hud.hideAfterDelay_(timer)

        self.assertIsNone(hud._hide_timer)
        panel.orderOut_.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
