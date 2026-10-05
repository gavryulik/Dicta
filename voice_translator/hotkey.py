"""System-wide push-to-talk keyboard shortcut."""

from collections.abc import Callable
import threading

from voice_translator.config import (
    PRODUCT_NAME,
    PUSH_TO_TALK_MODIFIERS,
    PUSH_TO_TALK_TRIGGER,
    PUSH_TO_TALK_VIRTUAL_KEY_CODE,
)


class HotkeyError(RuntimeError):
    """Raised when the global keyboard listener cannot be started."""


class ShortcutState:
    """Track a push-to-talk chord while ignoring repeated key-down events."""

    def __init__(self) -> None:
        self._pressed: set[str] = set()
        self._active = False

    def press(self, key_name: str | None) -> bool:
        """Return True exactly once when the full shortcut becomes pressed."""
        if key_name is None:
            return False

        self._pressed.add(key_name)
        shortcut = set(PUSH_TO_TALK_MODIFIERS) | {PUSH_TO_TALK_TRIGGER}

        if not self._active and shortcut.issubset(self._pressed):
            self._active = True
            return True

        return False

    def release(self, key_name: str | None) -> bool:
        """Return True exactly once when an active shortcut is released."""
        if key_name is None:
            return False

        was_active = self._active
        if key_name in PUSH_TO_TALK_MODIFIERS or key_name == PUSH_TO_TALK_TRIGGER:
            self._active = False

        self._pressed.discard(key_name)
        return was_active and not self._active


class GlobalPushToTalkHotkey:
    """Listen for the configured shortcut across all macOS applications."""

    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None]):
        self._on_start = on_start
        self._on_stop = on_stop
        self._state = ShortcutState()
        self._state_lock = threading.Lock()
        self._listener = None
        self._keyboard = None

    def start(self) -> None:
        try:
            from pynput import keyboard
        except ImportError as error:
            raise HotkeyError(
                "The pynput package is not installed. Activate the virtual "
                "environment and install requirements.txt."
            ) from error

        self._keyboard = keyboard
        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            darwin_intercept=self._intercept_macos_event,
        )

        try:
            self._listener.start()
            self._listener.wait()
        except Exception as error:
            raise HotkeyError(
                "Could not start the global shortcut listener. Enable Input "
                f"Monitoring for {PRODUCT_NAME}."
            ) from error

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def join(self, timeout: float | None = None) -> None:
        if self._listener is not None:
            self._listener.join(timeout)

    @property
    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def _on_key_press(self, key, injected=False) -> None:
        if injected:
            return

        key_name = self._key_name(key)
        with self._state_lock:
            should_start = self._state.press(key_name)

        if should_start:
            self._on_start()

    def _on_key_release(self, key, injected=False) -> None:
        if injected:
            return

        key_name = self._key_name(key)
        with self._state_lock:
            should_stop = self._state.release(key_name)

        if should_stop:
            self._on_stop()

    def _key_name(self, key) -> str | None:
        keyboard = self._keyboard
        if keyboard is None:
            return None

        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return "ctrl"
        if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
            return "alt"
        if key == keyboard.Key.space:
            return "space"
        return None

    @staticmethod
    def _intercept_macos_event(event_type, event):
        """Suppress only the shortcut's Space event, not normal typing."""
        del event_type

        import Quartz

        key_code = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )
        flags = Quartz.CGEventGetFlags(event)
        has_option = bool(flags & Quartz.kCGEventFlagMaskAlternate)

        if (
            key_code == PUSH_TO_TALK_VIRTUAL_KEY_CODE
            and has_option
        ):
            return None

        return event
