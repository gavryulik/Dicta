"""Microphone recording helpers."""

from pathlib import Path
import threading
import wave


SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2


class AudioRecordingError(RuntimeError):
    """Raised when microphone audio cannot be recorded."""


class MicrophoneRecorder:
    """Record 16-bit mono PCM audio from the default microphone."""

    def __init__(self) -> None:
        self._stream = None
        self._chunks: list[bytes] = []
        self._chunks_lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        """Start recording without blocking the calling thread."""
        if self.is_recording:
            raise AudioRecordingError("Recording is already active.")

        sd = _load_sounddevice()

        with self._chunks_lock:
            self._chunks = []

        def collect_audio(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            with self._chunks_lock:
                self._chunks.append(bytes(indata))

        stream = None
        try:
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=collect_audio,
            )
            stream.start()
            self._stream = stream
        except sd.PortAudioError as error:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise _microphone_error() from error

    def stop(self, output_path: Path) -> None:
        """Stop recording and save the captured audio as a PCM WAV file."""
        if not self.is_recording:
            raise AudioRecordingError("Recording is not active.")

        stream = self._stream
        self._stream = None

        try:
            stream.stop()
        except Exception as error:
            raise _microphone_error() from error
        finally:
            stream.close()

        with self._chunks_lock:
            chunks = list(self._chunks)
            self._chunks = []

        if not chunks:
            raise AudioRecordingError("No audio was captured.")

        _write_wav(output_path, chunks)

    def cancel(self) -> None:
        """Stop recording and discard any captured audio."""
        stream = self._stream
        self._stream = None

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            finally:
                stream.close()

        with self._chunks_lock:
            self._chunks = []


def record_until_enter(output_path: Path) -> None:
    """Record the default microphone until the user presses Enter."""
    recorder = MicrophoneRecorder()

    try:
        recorder.start()
        input()
        recorder.stop(output_path)
    except BaseException:
        if recorder.is_recording:
            recorder.cancel()
        raise


def _load_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as error:
        raise AudioRecordingError(
            "The sounddevice package is not installed. "
            "Activate the virtual environment and install requirements.txt."
        ) from error

    return sd


def _microphone_error() -> AudioRecordingError:
    return AudioRecordingError(
        "Could not record from the default microphone. Check the input device "
        "and enable Microphone access for Dicta "
        "in System Settings > Privacy & Security > Microphone."
    )


def _write_wav(output_path: Path, chunks: list[bytes]) -> None:
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(b"".join(chunks))
