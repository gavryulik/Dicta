"""Terminal entry point for Dicta."""

from pathlib import Path
import sys
import tempfile

from voice_translator.audio import AudioRecordingError, record_until_enter
from voice_translator.whisper import WhisperError, translate_audio


def main() -> int:
    """Run one record-and-translate session."""
    try:
        input("Press Enter to start recording...")

        with tempfile.TemporaryDirectory(prefix="voice-translator-") as temp_dir:
            audio_path = Path(temp_dir) / "recording.wav"

            print("Recording... Press Enter to stop.")
            record_until_enter(audio_path)

            print("Translating...")
            translation = translate_audio(audio_path)

        print("\nEnglish translation:\n")
        print(translation)
        return 0
    except (AudioRecordingError, WhisperError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 130
