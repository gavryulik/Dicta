from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave

from voice_translator.audio import (
    AudioRecordingError,
    CHANNELS,
    MicrophoneRecorder,
    SAMPLE_RATE,
    SAMPLE_WIDTH_BYTES,
    _write_wav,
)


class WavWritingTests(unittest.TestCase):
    def test_write_wav_uses_whisper_compatible_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "recording.wav"
            _write_wav(output_path, [b"\x00\x00" * 160])

            with wave.open(str(output_path), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), SAMPLE_RATE)
                self.assertEqual(wav_file.getnchannels(), CHANNELS)
                self.assertEqual(wav_file.getsampwidth(), SAMPLE_WIDTH_BYTES)
                self.assertEqual(wav_file.getnframes(), 160)


class MicrophoneRecorderStartTests(unittest.TestCase):
    def test_closes_constructed_stream_when_start_fails(self) -> None:
        class FakePortAudioError(Exception):
            pass

        stream = Mock()
        stream.start.side_effect = FakePortAudioError("start failed")
        sounddevice = SimpleNamespace(
            PortAudioError=FakePortAudioError,
            RawInputStream=Mock(return_value=stream),
        )

        with patch(
            "voice_translator.audio._load_sounddevice",
            return_value=sounddevice,
        ):
            recorder = MicrophoneRecorder()
            with self.assertRaises(AudioRecordingError):
                recorder.start()

        stream.close.assert_called_once_with()
        self.assertFalse(recorder.is_recording)

    def test_successful_start_keeps_stream_until_cancel(self) -> None:
        class FakePortAudioError(Exception):
            pass

        stream = Mock()
        sounddevice = SimpleNamespace(
            PortAudioError=FakePortAudioError,
            RawInputStream=Mock(return_value=stream),
        )

        with patch(
            "voice_translator.audio._load_sounddevice",
            return_value=sounddevice,
        ):
            recorder = MicrophoneRecorder()
            recorder.start()

        stream.start.assert_called_once_with()
        stream.close.assert_not_called()
        self.assertTrue(recorder.is_recording)

        recorder.cancel()

        stream.stop.assert_called_once_with()
        stream.close.assert_called_once_with()
        self.assertFalse(recorder.is_recording)


if __name__ == "__main__":
    unittest.main()
