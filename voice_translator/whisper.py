"""Integration with the local whisper.cpp command-line tool."""

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resource_root() -> Path:
    """Return source root or the frozen app's Contents/Resources directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[1] / "Resources"
    return PROJECT_ROOT


RESOURCE_ROOT = _resource_root()
WHISPER_BINARY = RESOURCE_ROOT / "vendor/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = RESOURCE_ROOT / "vendor/whisper.cpp/models/ggml-medium.bin"


class WhisperError(RuntimeError):
    """Raised when whisper.cpp cannot translate an audio file."""


def build_command(audio_path: Path) -> list[str]:
    """Build the whisper.cpp command for Russian-to-English translation."""
    return [
        str(WHISPER_BINARY),
        "--model",
        str(WHISPER_MODEL),
        "--file",
        str(audio_path),
        "--language",
        "ru",
        "--translate",
        "--no-timestamps",
    ]


def translate_audio(audio_path: Path) -> str:
    """Translate Russian speech in an audio file into English text."""
    _require_file(WHISPER_BINARY, "whisper.cpp binary")
    _require_file(WHISPER_MODEL, "Whisper model")
    _require_file(audio_path, "recorded audio")

    completed = subprocess.run(
        build_command(audio_path),
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        reason = _short_error(completed.stderr)
        raise WhisperError(f"whisper.cpp failed: {reason}")

    translation = _clean_output(completed.stdout)
    if not translation:
        raise WhisperError("whisper.cpp returned no translation.")

    return translation


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise WhisperError(f"The {description} was not found at: {path}")


def _clean_output(output: str) -> str:
    lines = (line.strip() for line in output.splitlines())
    return "\n".join(line for line in lines if line)


def _short_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]

    for line in lines:
        lowered = line.lower()
        if "error:" in lowered or "failed" in lowered:
            return line

    return lines[-1] if lines else "unknown error"
