"""Long-running record, translate, and insert workflow."""

from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path
import tempfile
import threading

from voice_translator.audio import AudioRecordingError, MicrophoneRecorder
from voice_translator.config import PUSH_TO_TALK_LABEL
from voice_translator.text_insertion import (
    TargetContext,
    TextInsertionError,
    capture_target_context,
    insert_text,
)
from voice_translator.whisper import WhisperError, translate_audio


class ServiceState(Enum):
    DISABLED = auto()
    READY = auto()
    STARTING = auto()
    RECORDING = auto()
    PROCESSING = auto()
    DONE = auto()
    ERROR = auto()
    STOPPING = auto()


class VoiceTranslatorService:
    """Coordinate repeated push-to-talk dictation sessions."""

    def __init__(
        self,
        on_state_change: Callable[[ServiceState], None] | None = None,
        text_inserter: Callable[[str, TargetContext], None] | None = None,
        target_capturer: Callable[[], TargetContext] | None = None,
    ) -> None:
        self._state = ServiceState.READY
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._enabled = True
        self._on_state_change = on_state_change
        self._text_inserter = text_inserter or insert_text
        self._target_capturer = target_capturer or capture_target_context
        self._recorder: MicrophoneRecorder | None = None
        self._temporary_directory: tempfile.TemporaryDirectory | None = None
        self._audio_path: Path | None = None
        self._target: TargetContext | None = None
        self._start_worker: threading.Thread | None = None
        self._stop_worker: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._stop_in_progress = False
        self._stop_requested_during_start = False
        self._shutting_down = False

    @property
    def state(self) -> ServiceState:
        with self._lock:
            return self._state

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_state_callback(
        self, callback: Callable[[ServiceState], None] | None
    ) -> None:
        """Set the optional UI-independent state listener."""
        with self._lock:
            self._on_state_change = callback
            state = self._state
        self._notify_state(state)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable starting new dictation sessions."""
        with self._lock:
            self._enabled = enabled
            if self._state in (ServiceState.READY, ServiceState.DISABLED):
                self._state = (
                    ServiceState.READY if enabled else ServiceState.DISABLED
                )
            state = self._state
        self._notify_state(state)

    def start_recording(self) -> None:
        """Queue one recording start without blocking the hotkey listener."""
        with self._lock:
            if (
                not self._enabled
                or self._state is not ServiceState.READY
                or self._shutting_down
            ):
                return
            self._state = ServiceState.STARTING
            self._stop_requested_during_start = False
            start_worker = threading.Thread(
                target=self._start_recording_workflow,
                args=(),
                name="voice-translator-start-worker",
            )
            self._start_worker = start_worker
        self._notify_state(ServiceState.STARTING)
        start_worker.start()

    def _start_recording_workflow(self) -> None:
        """Capture the target and open the microphone away from the event tap."""

        temporary_directory = None
        recorder = MicrophoneRecorder()

        try:
            target = self._target_capturer()
            temporary_directory = tempfile.TemporaryDirectory(
                prefix="voice-translator-"
            )
            audio_path = Path(temporary_directory.name) / "recording.wav"
            recorder.start()
        except (AudioRecordingError, TextInsertionError) as error:
            if temporary_directory is not None:
                temporary_directory.cleanup()
            self._report_error(error)
            self._set_ready()
            return

        with self._lock:
            if self._shutting_down or not self._enabled:
                recorder.cancel()
                temporary_directory.cleanup()
                self._state = (
                    ServiceState.STOPPING
                    if self._shutting_down
                    else ServiceState.DISABLED
                )
                state = self._state
                should_abort = True
            else:
                self._recorder = recorder
                self._temporary_directory = temporary_directory
                self._audio_path = audio_path
                self._target = target
                self._state = ServiceState.RECORDING
                state = self._state
                should_abort = False
                stop_was_requested = self._stop_requested_during_start

        self._notify_state(state)
        if should_abort:
            return

        window_status = (
            "available" if target.window_element is not None else "unavailable"
        )
        print(
            f"Target: {target.name} (PID {target.process_id}, "
            f"window verification={window_status})",
            flush=True,
        )
        print(
            f"Recording... release {PUSH_TO_TALK_LABEL} to stop.",
            flush=True,
        )

        if stop_was_requested:
            self.stop_recording()

    def stop_recording(self) -> None:
        """Queue recording stop, preserving release during target capture."""
        with self._lock:
            if self._state is ServiceState.STARTING:
                self._stop_requested_during_start = True
                return
            if self._state is not ServiceState.RECORDING:
                return

            self._state = ServiceState.PROCESSING
            recorder = self._recorder
            audio_path = self._audio_path
            target = self._target
            self._stop_in_progress = True
            stop_worker = threading.Thread(
                target=self._stop_recording_workflow,
                args=(recorder, audio_path, target),
                name="voice-translator-stop-worker",
            )
            self._stop_worker = stop_worker
        self._notify_state(ServiceState.PROCESSING)
        stop_worker.start()

    def _stop_recording_workflow(self, recorder, audio_path, target) -> None:
        """Finish audio and launch translation away from the event tap."""
        try:
            if recorder is None or audio_path is None or target is None:
                self._report_error(
                    RuntimeError("The recording session is incomplete.")
                )
                self._finish_session()
                return

            try:
                recorder.stop(audio_path)
            except AudioRecordingError as error:
                self._report_error(error)
                self._finish_session()
                return

            print("Recording stopped. Translating...", flush=True)

            worker = threading.Thread(
                target=self._translate_and_insert,
                args=(audio_path, target),
                name="voice-translator-worker",
            )
            with self._lock:
                self._worker = worker
            worker.start()
        finally:
            self._finish_stop_transition()

    def shutdown(self) -> None:
        """Stop recording or wait for active processing, then clean up."""
        with self._condition:
            self._shutting_down = True
            self._state = ServiceState.STOPPING
            start_worker = self._start_worker
        self._notify_state(ServiceState.STOPPING)

        if (
            start_worker is not None
            and start_worker is not threading.current_thread()
            and start_worker.is_alive()
        ):
            start_worker.join()

        with self._condition:
            while self._stop_in_progress:
                self._condition.wait()
            recorder = self._recorder
            worker = self._worker

        if recorder is not None and recorder.is_recording:
            recorder.cancel()

        if worker is not None and worker.is_alive():
            print("Waiting for the current translation to finish...", flush=True)
            worker.join()

        self._cleanup_temporary_directory()

    def _finish_stop_transition(self) -> None:
        """Allow shutdown to continue after stop has published its worker."""
        with self._condition:
            self._stop_in_progress = False
            self._stop_worker = None
            self._condition.notify_all()

    def _translate_and_insert(
        self, audio_path: Path, target: TargetContext
    ) -> None:
        try:
            translation = translate_audio(audio_path).strip()
            if not translation:
                raise WhisperError("whisper.cpp returned no translation.")

            print("\nEnglish translation:\n", flush=True)
            print(translation, flush=True)

            with self._lock:
                shutting_down = self._shutting_down

            if not shutting_down:
                self._text_inserter(translation, target)
                print(f"Paste command sent to {target.name}.", flush=True)
                self._set_outcome(ServiceState.DONE)
        except (WhisperError, TextInsertionError) as error:
            self._report_error(error)
        finally:
            self._finish_session()

    def _finish_session(self) -> None:
        self._cleanup_temporary_directory()

        with self._lock:
            self._recorder = None
            self._audio_path = None
            self._target = None
            self._stop_requested_during_start = False
            self._worker = None

            if not self._shutting_down:
                self._state = (
                    ServiceState.READY
                    if self._enabled
                    else ServiceState.DISABLED
                )
                state = self._state
                should_print_ready = True
            else:
                self._state = ServiceState.STOPPING
                state = self._state
                should_print_ready = False

        self._notify_state(state)
        if should_print_ready:
            if state is ServiceState.READY:
                print(f"Ready. Hold {PUSH_TO_TALK_LABEL} to dictate.", flush=True)
            else:
                print("Dictation disabled.", flush=True)

    def _cleanup_temporary_directory(self) -> None:
        with self._lock:
            temporary_directory = self._temporary_directory
            self._temporary_directory = None

        if temporary_directory is not None:
            temporary_directory.cleanup()

    def _set_ready(self) -> None:
        with self._lock:
            if not self._shutting_down:
                self._state = (
                    ServiceState.READY
                    if self._enabled
                    else ServiceState.DISABLED
                )
            state = self._state
        self._notify_state(state)

    def _notify_state(self, state: ServiceState) -> None:
        with self._lock:
            callback = self._on_state_change
        if callback is None:
            return
        try:
            callback(state)
        except Exception as error:
            print(f"Status callback error: {error}", flush=True)

    def _set_outcome(self, state: ServiceState) -> None:
        with self._lock:
            if self._shutting_down:
                return
            self._state = state
        self._notify_state(state)

    def _report_error(self, error: Exception) -> None:
        print(f"Error: {error}", flush=True)
        self._set_outcome(ServiceState.ERROR)
