import signal
import unittest
from unittest.mock import Mock, patch

from voice_translator.menu_bar import MenuBarController


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


if __name__ == "__main__":
    unittest.main()
