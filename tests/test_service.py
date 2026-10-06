import unittest
import threading
from unittest.mock import Mock, patch

from voice_translator.service import ServiceState, VoiceTranslatorService
from voice_translator.text_insertion import TargetContext
from voice_translator.whisper import WhisperError


class ImmediateThread:
    def __init__(self, target, args, name):
        del name
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)

    def is_alive(self):
        return False

    def join(self):
        return None


class VoiceTranslatorServiceTests(unittest.TestCase):
    def test_successful_session_translates_inserts_and_becomes_ready(self) -> None:
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.capture_target_context",
                return_value=target,
            ),
            patch(
                "voice_translator.service.translate_audio",
                return_value="Translated text",
            ) as translate,
            patch("voice_translator.service.insert_text") as insert,
            patch("voice_translator.service.threading.Thread", ImmediateThread),
        ):
            service = VoiceTranslatorService()
            service.start_recording()
            service.stop_recording()

        recorder.start.assert_called_once_with()
        recorder.stop.assert_called_once()
        translate.assert_called_once()
        insert.assert_called_once_with("Translated text", target)
        self.assertIs(service._state, ServiceState.READY)

    def test_successful_session_reports_state_changes(self) -> None:
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")
        states = []

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.capture_target_context",
                return_value=target,
            ),
            patch(
                "voice_translator.service.translate_audio",
                return_value="Translated text",
            ),
            patch("voice_translator.service.insert_text"),
            patch("voice_translator.service.threading.Thread", ImmediateThread),
        ):
            service = VoiceTranslatorService(on_state_change=states.append)
            service.start_recording()
            service.stop_recording()

        self.assertEqual(
            states,
            [
                ServiceState.STARTING,
                ServiceState.RECORDING,
                ServiceState.PROCESSING,
                ServiceState.DONE,
                ServiceState.READY,
            ],
        )

    def test_failed_translation_reports_error_then_becomes_ready(self) -> None:
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")
        states = []

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.capture_target_context",
                return_value=target,
            ),
            patch(
                "voice_translator.service.translate_audio",
                side_effect=WhisperError("translation failed"),
            ),
            patch("voice_translator.service.threading.Thread", ImmediateThread),
        ):
            service = VoiceTranslatorService(on_state_change=states.append)
            service.start_recording()
            service.stop_recording()

        self.assertEqual(
            states,
            [
                ServiceState.STARTING,
                ServiceState.RECORDING,
                ServiceState.PROCESSING,
                ServiceState.ERROR,
                ServiceState.READY,
            ],
        )

    def test_disabled_service_ignores_start_and_can_be_enabled_again(self) -> None:
        states = []
        service = VoiceTranslatorService(on_state_change=states.append)

        with patch("voice_translator.service.MicrophoneRecorder") as recorder_class:
            service.set_enabled(False)
            service.start_recording()

            recorder_class.assert_not_called()
            self.assertFalse(service.is_enabled)
            self.assertIs(service.state, ServiceState.DISABLED)

            service.set_enabled(True)

        self.assertTrue(service.is_enabled)
        self.assertIs(service.state, ServiceState.READY)
        self.assertEqual(states, [ServiceState.DISABLED, ServiceState.READY])

    def test_setting_callback_immediately_reports_current_state(self) -> None:
        states = []
        service = VoiceTranslatorService()

        service.set_state_callback(states.append)

        self.assertEqual(states, [ServiceState.READY])

    def test_session_uses_injected_text_inserter(self) -> None:
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")
        text_inserter = Mock()

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.capture_target_context",
                return_value=target,
            ),
            patch(
                "voice_translator.service.translate_audio",
                return_value="Translated text",
            ),
            patch("voice_translator.service.threading.Thread", ImmediateThread),
        ):
            service = VoiceTranslatorService(text_inserter=text_inserter)
            service.start_recording()
            service.stop_recording()

        text_inserter.assert_called_once_with("Translated text", target)

    def test_session_uses_injected_target_capturer(self) -> None:
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")
        target_capturer = Mock(return_value=target)

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.capture_target_context"
            ) as default_capturer,
        ):
            service = VoiceTranslatorService(target_capturer=target_capturer)
            service.start_recording()
            service._start_worker.join(timeout=1.0)

        target_capturer.assert_called_once_with()
        default_capturer.assert_not_called()
        self.assertIs(service.state, ServiceState.RECORDING)
        service.shutdown()

    def test_shutdown_waits_for_stop_transition_before_cleanup(self) -> None:
        stop_entered = threading.Event()
        allow_stop_to_finish = threading.Event()
        shutdown_announced = threading.Event()
        recorder = Mock()
        recorder.is_recording = True
        temporary_directory = Mock()
        temporary_directory.name = "/tmp/voice-translator-test"
        target = TargetContext(process_id=123, name="Example")

        def blocking_stop(audio_path) -> None:
            del audio_path
            recorder.is_recording = False
            stop_entered.set()
            allow_stop_to_finish.wait()

        def state_changed(state) -> None:
            if state is ServiceState.STOPPING:
                shutdown_announced.set()

        recorder.stop.side_effect = blocking_stop

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.tempfile.TemporaryDirectory",
                return_value=temporary_directory,
            ),
            patch(
                "voice_translator.service.translate_audio",
                return_value="Translated text",
            ),
        ):
            service = VoiceTranslatorService(
                on_state_change=state_changed,
                text_inserter=Mock(),
                target_capturer=Mock(return_value=target),
            )
            service.start_recording()
            service._start_worker.join(timeout=1.0)

            stop_thread = threading.Thread(target=service.stop_recording)
            shutdown_thread = threading.Thread(target=service.shutdown)
            stop_thread.start()
            self.assertTrue(stop_entered.wait(timeout=1.0))
            shutdown_thread.start()

            try:
                self.assertTrue(shutdown_announced.wait(timeout=1.0))
                temporary_directory.cleanup.assert_not_called()
                recorder.cancel.assert_not_called()
            finally:
                allow_stop_to_finish.set()
                stop_thread.join(timeout=1.0)
                shutdown_thread.join(timeout=1.0)

        self.assertFalse(stop_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        recorder.stop.assert_called_once()
        recorder.cancel.assert_not_called()
        temporary_directory.cleanup.assert_called_once_with()

    def test_release_during_slow_target_capture_is_preserved(self) -> None:
        capture_started = threading.Event()
        allow_capture = threading.Event()
        session_finished = threading.Event()
        recorder = Mock()
        recorder.is_recording = False
        target = TargetContext(process_id=123, name="Example")

        def capture_target():
            capture_started.set()
            allow_capture.wait(timeout=1.0)
            return target

        def state_changed(state) -> None:
            if state is ServiceState.READY:
                session_finished.set()

        with (
            patch(
                "voice_translator.service.MicrophoneRecorder",
                return_value=recorder,
            ),
            patch(
                "voice_translator.service.translate_audio",
                return_value="Translated text",
            ),
        ):
            service = VoiceTranslatorService(
                on_state_change=state_changed,
                text_inserter=Mock(),
                target_capturer=capture_target,
            )
            service.start_recording()
            self.assertTrue(capture_started.wait(timeout=1.0))

            service.stop_recording()
            allow_capture.set()

            self.assertTrue(session_finished.wait(timeout=1.0))

        recorder.start.assert_called_once_with()
        recorder.stop.assert_called_once()
        self.assertIs(service.state, ServiceState.READY)

    def test_repeated_start_during_capture_does_not_duplicate_session(self):
        capture_started = threading.Event()
        allow_capture = threading.Event()
        target_capturer = Mock()
        target = TargetContext(process_id=123, name="Example")

        def capture_target():
            capture_started.set()
            allow_capture.wait(timeout=1.0)
            return target

        target_capturer.side_effect = capture_target
        recorder = Mock()
        recorder.is_recording = False

        with patch(
            "voice_translator.service.MicrophoneRecorder",
            return_value=recorder,
        ) as recorder_class:
            service = VoiceTranslatorService(target_capturer=target_capturer)
            service.start_recording()
            self.assertTrue(capture_started.wait(timeout=1.0))

            service.start_recording()
            allow_capture.set()
            service._start_worker.join(timeout=1.0)

        target_capturer.assert_called_once_with()
        recorder_class.assert_called_once_with()
        recorder.start.assert_called_once_with()
        self.assertIs(service.state, ServiceState.RECORDING)
        service.shutdown()


if __name__ == "__main__":
    unittest.main()
