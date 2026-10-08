import signal
import unittest
from unittest.mock import Mock, patch

from voice_translator.menu_bar import (
    RECENT_TRANSLATION_LIMIT,
    TRANSLATION_PREVIEW_LENGTH,
    MenuBarController,
)
from voice_translator.service import ServiceState, VoiceTranslatorService
from voice_translator.text_insertion import TargetContext, TextInsertionError


class CapturedThread:
    instances = []

    def __init__(self, target, name):
        self.target = target
        self.name = name
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


class MenuBarShutdownTests(unittest.TestCase):
    def setUp(self) -> None:
        CapturedThread.instances.clear()
        self.service = Mock()
        self.hotkey = Mock()
        self.controller = MenuBarController.alloc().init()
        self.controller.configure(self.service, self.hotkey)

    def test_shutdown_request_is_non_blocking_and_idempotent(self) -> None:
        with patch("voice_translator.menu_bar.threading.Thread", CapturedThread):
            self.assertTrue(self.controller.request_shutdown())
            self.assertFalse(self.controller.request_shutdown())

        self.hotkey.stop.assert_called_once_with()
        self.service.shutdown.assert_not_called()
        self.assertEqual(len(CapturedThread.instances), 1)
        self.assertTrue(CapturedThread.instances[0].started)

    def test_sigint_uses_shared_shutdown_request(self) -> None:
        self.controller.request_shutdown = Mock()

        self.controller.handle_sigint(signal.SIGINT)

        self.controller.request_shutdown.assert_called_once_with()


class MenuBarHUDTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.hotkey = Mock()
        self.hud = Mock()
        self.controller = MenuBarController.alloc().init()
        self.controller.configure(self.service, self.hotkey, self.hud)

    def test_service_states_map_to_hud_messages(self) -> None:
        self.controller._apply_state(ServiceState.RECORDING)
        self.controller._apply_state(ServiceState.PROCESSING)
        self.controller._apply_state(ServiceState.DONE)
        self.controller._apply_state(ServiceState.READY)

        self.hud.show_recording.assert_called_once_with()
        self.hud.show_translating.assert_called_once_with()
        self.hud.show_done.assert_called_once_with()
        self.hud.hide.assert_not_called()

    def test_failure_requests_error_then_idle_preserves_transient(self) -> None:
        self.controller._apply_state(ServiceState.ERROR)
        self.controller._apply_state(ServiceState.READY)

        self.hud.show_error.assert_called_once_with()
        self.hud.hide.assert_not_called()

        self.controller._apply_state(ServiceState.STARTING)
        self.hud.hide.assert_called_once_with()

    def test_idle_without_completion_hides_hud(self) -> None:
        self.controller._apply_state(ServiceState.READY)

        self.hud.hide.assert_called_once_with()

    def test_hud_failure_does_not_escape_state_update(self) -> None:
        self.hud.show_recording.side_effect = RuntimeError("broken HUD")

        self.controller._apply_state(ServiceState.RECORDING)

        self.hud.show_recording.assert_called_once_with()


class RecentTranslationsTests(unittest.TestCase):
    def setUp(self) -> None:
        from AppKit import NSMenu

        self.controller = MenuBarController.alloc().init()
        self.controller.configure(Mock(), Mock())
        self.controller._history_menu = NSMenu.alloc().initWithTitle_(
            "Recent Translations"
        )
        self.controller._history_menu.setAutoenablesItems_(False)

    def remember(self, text):
        with patch("voice_translator.menu_bar.insert_text"):
            self.controller.insert_text_on_main_thread(text, None)

    def test_empty_history_and_clear_show_disabled_placeholder(self) -> None:
        self.controller._refresh_history_menu()
        menu = self.controller._history_menu
        self.assertEqual(menu.numberOfItems(), 1)
        self.assertEqual(menu.itemAtIndex_(0).title(), "No recent translations")
        self.assertFalse(menu.itemAtIndex_(0).isEnabled())

        self.remember("A translation")
        self.controller.clearRecentTranslations_(None)

        self.assertEqual(list(self.controller._recent_translations), [])
        self.assertEqual(menu.numberOfItems(), 1)
        self.assertFalse(menu.itemAtIndex_(0).isEnabled())

    def test_only_five_latest_results_are_kept_newest_first(self) -> None:
        for index in range(RECENT_TRANSLATION_LIMIT + 2):
            self.remember(f"Translation {index}")

        menu = self.controller._history_menu
        expected = [f"Translation {index}" for index in range(6, 1, -1)]
        self.assertEqual(list(self.controller._recent_translations), expected)
        self.assertEqual(
            [menu.itemAtIndex_(i).representedObject() for i in range(5)], expected
        )
        self.assertTrue(menu.itemAtIndex_(5).isSeparatorItem())
        clear_item = menu.itemAtIndex_(6)
        self.assertEqual(clear_item.title(), "Clear History")
        self.assertEqual(str(clear_item.action()), "clearRecentTranslations:")
        self.assertIs(clear_item.target(), self.controller)

    def test_preview_is_short_but_full_unicode_text_is_preserved(self) -> None:
        text = "Hello 🌍\n\n" + "word " * 30
        self.remember(text)
        item = self.controller._history_menu.itemAtIndex_(0)

        self.assertEqual(item.representedObject(), text)
        self.assertNotIn("\n", item.title())
        self.assertTrue(item.title().endswith("…"))
        self.assertEqual(len(item.title()), len("Copy: ") + TRANSLATION_PREVIEW_LENGTH)
        self.assertEqual(str(item.action()), "copyRecentTranslation:")

    def test_copy_uses_displayed_result_after_new_translation_arrives(self) -> None:
        text = "Original 🌍\n  indentation\nSecond paragraph."
        self.remember(text)
        displayed_item = self.controller._history_menu.itemAtIndex_(0)
        self.remember("Newer translation")

        with patch("voice_translator.menu_bar.NSPasteboard") as pasteboard_class:
            pasteboard = pasteboard_class.generalPasteboard.return_value
            self.controller.copyRecentTranslation_(displayed_item)

        from AppKit import NSPasteboardTypeString

        pasteboard.clearContents.assert_called_once_with()
        pasteboard.setString_forType_.assert_called_once_with(
            text, NSPasteboardTypeString
        )

    def test_copy_failure_beeps(self) -> None:
        self.remember("A translation")
        with (
            patch("voice_translator.menu_bar.NSPasteboard") as pasteboard_class,
            patch("voice_translator.menu_bar.NSBeep") as beep,
        ):
            pasteboard = pasteboard_class.generalPasteboard.return_value
            pasteboard.setString_forType_.return_value = False
            self.controller.copyRecentTranslation_(
                self.controller._history_menu.itemAtIndex_(0)
            )
        beep.assert_called_once_with()

    def test_refused_insertion_retains_completed_translation(self) -> None:
        target = TargetContext(123, "Example")
        states = []
        service = VoiceTranslatorService(
            text_inserter=self.controller.insert_text_on_main_thread,
            on_state_change=states.append,
        )
        with (
            patch(
                "voice_translator.service.translate_audio", return_value="Recover me"
            ),
            patch(
                "voice_translator.menu_bar.insert_text",
                side_effect=TextInsertionError("The target window changed"),
            ),
        ):
            service._translate_and_insert(None, target)

        self.assertEqual(list(self.controller._recent_translations), ["Recover me"])
        self.assertEqual(states, [ServiceState.ERROR, ServiceState.READY])

    def test_empty_translation_is_not_kept(self) -> None:
        self.remember(" \n ")
        self.assertEqual(list(self.controller._recent_translations), [])

    def test_history_is_not_shared_between_controllers(self) -> None:
        self.remember("Private translation")
        other = MenuBarController.alloc().init()
        other.configure(Mock(), Mock())
        self.assertEqual(list(other._recent_translations), [])


if __name__ == "__main__":
    unittest.main()
