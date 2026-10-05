"""Native macOS menu bar entry point for Dicta."""

import signal
import threading

from voice_translator.config import PRODUCT_NAME, PUSH_TO_TALK_LABEL
from voice_translator.hotkey import GlobalPushToTalkHotkey, HotkeyError
from voice_translator.permissions import PermissionSetupError, require_macos_permissions
from voice_translator.service import ServiceState, VoiceTranslatorService
from voice_translator.text_insertion import capture_target_application, insert_text


def main() -> int:
    """Run Dicta as a native macOS status item."""
    try:
        require_macos_permissions()
    except PermissionSetupError as error:
        print(f"Error: {error}")
        return 1

    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
        )
        from PyObjCTools import MachSignals
    except ImportError as error:
        print(f"Error: The PyObjC Cocoa package is not installed: {error}")
        return 1

    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    controller = MenuBarController.alloc().init()
    service = VoiceTranslatorService(
        text_inserter=controller.insert_text_on_main_thread,
        target_capturer=controller.capture_target_on_main_thread,
    )
    hotkey = GlobalPushToTalkHotkey(
        on_start=service.start_recording,
        on_stop=service.stop_recording,
    )
    controller.configure(service, hotkey)
    service.set_state_callback(controller.service_state_changed)
    MachSignals.signal(signal.SIGINT, controller.handle_sigint)

    try:
        controller.start()
        print(
            f"{PRODUCT_NAME} is running in the menu bar. "
            f"Hold {PUSH_TO_TALK_LABEL} to dictate.",
            flush=True,
        )
        application.run()
    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
        controller.request_shutdown()
        application.run()
    except HotkeyError as error:
        print(f"Error: {error}")
        return 1
    finally:
        controller.shutdown()

    print(f"{PRODUCT_NAME} stopped.")
    return 0


try:
    import objc
    from AppKit import (
        NSApplication,
        NSImage,
        NSMenu,
        NSMenuItem,
        NSStatusBar,
        NSVariableStatusItemLength,
    )
    from Foundation import NSObject, NSThread
except ImportError:
    # Importing this module remains harmless on non-macOS test systems. main()
    # still reports the missing Cocoa dependency if someone tries to run it.
    class _ObjCFallback:
        @staticmethod
        def python_method(method):
            return method

    objc = _ObjCFallback()
    NSObject = object


class MenuBarController(NSObject):
    """Own the status item and translate service state into menu updates."""

    @objc.python_method
    def configure(self, service, hotkey) -> None:
        self._service = service
        self._hotkey = hotkey
        self._status_item = None
        self._status_menu_item = None
        self._toggle_menu_item = None
        self._did_shutdown = False
        self._shutdown_thread = None

    def start(self) -> None:
        self._build_menu()
        self._hotkey.start()

    def _build_menu(self) -> None:
        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(
            NSVariableStatusItemLength
        )

        button = self._status_item.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "waveform", PRODUCT_NAME
        )
        if image is not None:
            image.setTemplate_(True)
            button.setImage_(image)
        else:
            button.setTitle_("VT")
        button.setToolTip_(PRODUCT_NAME)

        menu = NSMenu.alloc().init()
        self._status_menu_item = self._disabled_item("Status: Ready")
        menu.addItem_(self._status_menu_item)
        menu.addItem_(NSMenuItem.separatorItem())

        self._toggle_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Disable Dictation", "toggleDictation:", ""
        )
        self._toggle_menu_item.setTarget_(self)
        menu.addItem_(self._toggle_menu_item)

        menu.addItem_(self._disabled_item(f"Shortcut: {PUSH_TO_TALK_LABEL}"))
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Quit {PRODUCT_NAME}", "quitVoiceTranslator:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self._status_item.setMenu_(menu)

        self._apply_state(self._service.state)

    @staticmethod
    def _disabled_item(title):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, None, ""
        )
        item.setEnabled_(False)
        return item

    @objc.python_method
    def service_state_changed(self, state: ServiceState) -> None:
        """Schedule UI work on AppKit's main thread."""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyServiceState:", state.name, False
        )

    @objc.python_method
    def insert_text_on_main_thread(
        self, text: str, target
    ) -> None:
        """Run the existing AppKit-based insertion on AppKit's main thread."""
        self._run_on_main_thread(insert_text, text, target)

    @objc.python_method
    def capture_target_on_main_thread(self):
        """Capture the focused target without using AppKit off the main thread."""
        return self._run_on_main_thread(capture_target_application)

    @staticmethod
    @objc.python_method
    def _run_on_main_thread(action, *args):
        if NSThread.isMainThread():
            return action(*args)

        task = _MainThreadTask.alloc().init()
        task.configure(action, args)
        return task.run_on_main_thread()

    def applyServiceState_(self, state_name) -> None:
        self._apply_state(ServiceState[str(state_name)])

    def _apply_state(self, state: ServiceState) -> None:
        if self._status_menu_item is None:
            return

        labels = {
            ServiceState.DISABLED: "Disabled",
            ServiceState.READY: "Ready",
            ServiceState.STARTING: "Ready",
            ServiceState.RECORDING: "Recording",
            ServiceState.PROCESSING: "Translating",
            ServiceState.STOPPING: "Translating",
        }
        self._status_menu_item.setTitle_(f"Status: {labels[state]}")
        toggle_title = (
            "Disable Dictation"
            if self._service.is_enabled
            else "Enable Dictation"
        )
        self._toggle_menu_item.setTitle_(toggle_title)

    def toggleDictation_(self, sender) -> None:
        del sender
        self._service.set_enabled(not self._service.is_enabled)

    @objc.python_method
    def handle_sigint(self, signum) -> None:
        """Handle SIGINT delivered through PyObjC's Cocoa run-loop bridge."""
        if signum == signal.SIGINT:
            print("\nShutting down...", flush=True)
            self.request_shutdown()

    def quitVoiceTranslator_(self, sender) -> None:
        del sender
        self.request_shutdown()

    @objc.python_method
    def request_shutdown(self) -> bool:
        """Begin the shared, non-blocking shutdown path exactly once."""
        if self._did_shutdown:
            return False

        self._did_shutdown = True
        self._hotkey.stop()
        self._shutdown_thread = threading.Thread(
            target=self._shutdown_then_terminate,
            name="voice-translator-shutdown",
        )
        self._shutdown_thread.start()
        return True

    @objc.python_method
    def _shutdown_then_terminate(self) -> None:
        self._service.shutdown()
        self._hotkey.join(timeout=1.0)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "finishTermination:", None, False
        )

    def finishTermination_(self, sender) -> None:
        NSApplication.sharedApplication().terminate_(sender)

    def shutdown(self) -> None:
        if self._did_shutdown:
            return
        self._did_shutdown = True
        self._hotkey.stop()
        self._service.shutdown()
        self._hotkey.join(timeout=1.0)


class _MainThreadTask(NSObject):
    """Synchronously execute one callable on AppKit's main thread."""

    @objc.python_method
    def configure(self, action, arguments) -> None:
        self._action = action
        self._arguments = arguments
        self._result = None
        self._error = None

    @objc.python_method
    def run_on_main_thread(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "executeTask:", None, True
        )
        if self._error is not None:
            raise self._error
        return self._result

    def executeTask_(self, unused) -> None:
        del unused
        if not NSThread.isMainThread():
            self._error = RuntimeError(
                "The AppKit operation was not dispatched to the macOS main thread."
            )
            return

        try:
            self._result = self._action(*self._arguments)
        except Exception as error:
            self._error = error
