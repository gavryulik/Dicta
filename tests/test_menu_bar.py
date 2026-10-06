import signal
import unittest
from unittest.mock import Mock, patch

from voice_translator.menu_bar import MenuBarController
from voice_translator.service import ServiceState


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


if __name__ == "__main__":
    unittest.main()
