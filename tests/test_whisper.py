from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from voice_translator import whisper


class WhisperCommandTests(unittest.TestCase):
    def test_build_command_requests_russian_translation(self) -> None:
        command = whisper.build_command(Path("recording.wav"))

        self.assertIn("--language", command)
        self.assertIn("ru", command)
        self.assertIn("--translate", command)
        self.assertIn("--no-timestamps", command)

    def test_frozen_resource_root_uses_app_contents_resources(self) -> None:
        with (
            patch.object(whisper.sys, "frozen", True, create=True),
            patch.object(
                whisper.sys,
                "executable",
                "/Applications/Dicta.app/Contents/MacOS/Dicta",
            ),
        ):
            root = whisper._resource_root()

        self.assertEqual(
            root,
            Path("/Applications/Dicta.app/Contents/Resources"),
        )

    def test_translate_audio_returns_clean_stdout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n  Hello world.  \n\n", stderr="diagnostics"
        )

        with (
            patch.object(whisper, "_require_file"),
            patch("voice_translator.whisper.subprocess.run", return_value=completed),
        ):
            result = whisper.translate_audio(Path("recording.wav"))

        self.assertEqual(result, "Hello world.")

    def test_translate_audio_summarizes_whisper_failure(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="setup details\nbackend error: allocation failed\nmore details",
        )

        with (
            patch.object(whisper, "_require_file"),
            patch("voice_translator.whisper.subprocess.run", return_value=completed),
        ):
            with self.assertRaisesRegex(whisper.WhisperError, "backend error"):
                whisper.translate_audio(Path("recording.wav"))


if __name__ == "__main__":
    unittest.main()
