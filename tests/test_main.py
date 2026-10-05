import sys
import unittest
from unittest.mock import patch

from voice_translator.__main__ import main


class MainEntryPointTests(unittest.TestCase):
    def test_global_mode_is_no_longer_accepted(self) -> None:
        with patch.object(sys, "argv", ["voice_translator", "--global"]):
            with self.assertRaises(SystemExit) as raised:
                main()

        self.assertEqual(raised.exception.code, 2)

    def test_terminal_mode_remains_available(self) -> None:
        with (
            patch.object(sys, "argv", ["voice_translator", "--terminal"]),
            patch("voice_translator.app.main", return_value=17) as terminal_main,
        ):
            result = main()

        self.assertEqual(result, 17)
        terminal_main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
