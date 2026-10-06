"""Capture an application context and paste into its current cursor position."""

from dataclasses import dataclass
import os
import time

from voice_translator.config import PASTE_COMPLETION_DELAY_SECONDS, PRODUCT_NAME

# Hardware key codes from the macOS ANSI keyboard layout. CoreGraphics uses
# these physical positions without translating through the current input source.
MAC_KEY_CODE_V = 9
MAC_KEY_CODE_LEFT_COMMAND = 55


class TextInsertionError(RuntimeError):
    """Raised when a target cannot be captured or text cannot be inserted safely."""


class _TransientTargetCaptureError(TextInsertionError):
    """Raised when the frontmost application changes during capture."""


@dataclass(frozen=True)
class TargetContext:
    process_id: int
    name: str
    window_element: object | None = None


@dataclass(frozen=True)
class _ContextSnapshot:
    process_id: int
    window_element: object | None


@dataclass(frozen=True)
class PasteboardItemSnapshot:
    values: tuple[tuple[str, bytes], ...]


def capture_target_context() -> TargetContext:
    """Capture the frontmost application and an optional reliable AX window."""
    try:
        from AppKit import NSRunningApplication, NSWorkspace
        from CoreFoundation import CFEqual
        import ApplicationServices as accessibility
    except ImportError as error:
        raise TextInsertionError(
            "The PyObjC Cocoa package is not installed."
        ) from error

    return _capture_target_context(
        accessibility,
        NSRunningApplication,
        CFEqual,
        workspace=NSWorkspace.sharedWorkspace(),
        current_process_id=os.getpid(),
    )


def _capture_target_context(
    accessibility,
    running_application_class,
    elements_equal=lambda first, second: first == second,
    *,
    workspace,
    current_process_id: int | None = None,
    retry_delays: tuple[float, ...] = (0.0, 0.025, 0.050, 0.100, 0.175),
    sleeper=time.sleep,
) -> TargetContext:
    """Capture two coherent application/window snapshots with bounded retries."""
    last_error = None
    for attempt_number, delay in enumerate(retry_delays, start=1):
        if delay:
            sleeper(delay)
        try:
            first = _capture_context_snapshot(
                accessibility, workspace, current_process_id
            )
            second = _capture_context_snapshot(
                accessibility, workspace, current_process_id
            )
            if first.process_id != second.process_id:
                raise _TransientTargetCaptureError(
                    "The frontmost application changed while dictation was starting."
                )
            if (
                first.window_element is not None
                and second.window_element is not None
                and not elements_equal(first.window_element, second.window_element)
            ):
                raise _TransientTargetCaptureError(
                    "The active application window changed while dictation was starting."
                )

            window_element = None
            if (
                first.window_element is not None
                and second.window_element is not None
            ):
                window_element = first.window_element
            elif (
                first.window_element is not None
                or second.window_element is not None
            ):
                print(
                    "Target capture: AX window identity was inconsistent; "
                    "continuing with application-level verification.",
                    flush=True,
                )

            application = (
                running_application_class.runningApplicationWithProcessIdentifier_(
                    first.process_id
                )
            )
            if application is None:
                raise _TransientTargetCaptureError(
                    "The frontmost application is no longer running."
                )
            return TargetContext(
                process_id=first.process_id,
                name=str(application.localizedName() or "Unknown application"),
                window_element=window_element,
            )
        except _TransientTargetCaptureError as error:
            last_error = error
            print(
                f"Target capture attempt {attempt_number}/{len(retry_delays)} "
                f"failed (transient): {error}",
                flush=True,
            )

    elapsed_ms = int(sum(retry_delays) * 1000)
    raise TextInsertionError(
        "Could not capture a stable frontmost application "
        f"after {len(retry_delays)} attempts over {elapsed_ms} ms. "
        f"Last failure: {last_error}"
    )


def _capture_context_snapshot(
    accessibility, workspace, current_process_id
) -> _ContextSnapshot:
    workspace_application = workspace.frontmostApplication()
    if workspace_application is None:
        raise _TransientTargetCaptureError(
            "NSWorkspace returned no frontmost application."
        )
    process_id = int(workspace_application.processIdentifier())
    _reject_self_target(process_id, current_process_id)

    _verify_optional_systemwide_pid(accessibility, process_id)
    window_element = _optional_focused_window(accessibility, process_id)
    return _ContextSnapshot(process_id, window_element)


def _verify_optional_systemwide_pid(accessibility, expected_process_id):
    """Use system-wide AX focus only as a consistency signal when available."""
    system_wide = accessibility.AXUIElementCreateSystemWide()
    error_code, application_element = accessibility.AXUIElementCopyAttributeValue(
        system_wide, accessibility.kAXFocusedApplicationAttribute, None
    )
    if error_code == accessibility.kAXErrorAPIDisabled:
        raise TextInsertionError(
            f"Accessibility permission is disabled for {PRODUCT_NAME}."
        )
    if error_code != accessibility.kAXErrorSuccess or application_element is None:
        return

    pid_error, ax_process_id = accessibility.AXUIElementGetPid(
        application_element, None
    )
    if pid_error != accessibility.kAXErrorSuccess or ax_process_id is None:
        return
    if int(ax_process_id) != expected_process_id:
        raise _TransientTargetCaptureError(
            "NSWorkspace and Accessibility disagree about the frontmost application "
            f"(PIDs {expected_process_id} and {int(ax_process_id)})."
        )


def _optional_focused_window(accessibility, process_id):
    """Return a verified focused AX window, or None when no reliable one exists."""
    try:
        application_element = accessibility.AXUIElementCreateApplication(process_id)
    except Exception:
        return None
    if application_element is None:
        return None

    pid_error, application_process_id = accessibility.AXUIElementGetPid(
        application_element, None
    )
    if (
        pid_error == accessibility.kAXErrorSuccess
        and application_process_id is not None
        and int(application_process_id) != process_id
    ):
        raise _TransientTargetCaptureError(
            "The AX application PID does not match the frontmost application."
        )

    focused_window_attribute = getattr(
        accessibility, "kAXFocusedWindowAttribute", "AXFocusedWindow"
    )
    error_code, window_element = accessibility.AXUIElementCopyAttributeValue(
        application_element, focused_window_attribute, None
    )
    if error_code == accessibility.kAXErrorAPIDisabled:
        raise TextInsertionError(
            f"Accessibility permission is disabled for {PRODUCT_NAME}."
        )
    if error_code != accessibility.kAXErrorSuccess or window_element is None:
        return None

    pid_error, window_process_id = accessibility.AXUIElementGetPid(
        window_element, None
    )
    if (
        pid_error != accessibility.kAXErrorSuccess
        or window_process_id is None
        or int(window_process_id) != process_id
    ):
        return None
    return window_element


def _reject_self_target(process_id, current_process_id):
    if current_process_id is not None and process_id == current_process_id:
        raise TextInsertionError(
            f"{PRODUCT_NAME} cannot use itself as the dictation target."
        )


def insert_text(text: str, target: TargetContext) -> None:
    """Paste into the current cursor after verifying application/window context."""
    if not text.strip():
        return

    try:
        from AppKit import (
            NSPasteboard,
            NSPasteboardItem,
            NSPasteboardTypeString,
            NSWorkspace,
        )
        from Foundation import NSData
        from CoreFoundation import CFEqual
        import ApplicationServices as accessibility
        import Quartz
    except ImportError as error:
        raise TextInsertionError(
            "The macOS text-insertion dependencies are not installed."
        ) from error

    pasteboard = NSPasteboard.generalPasteboard()
    snapshot = _snapshot_pasteboard(pasteboard)
    owned_change_count = None

    try:
        pasteboard.clearContents()
        owned_change_count = pasteboard.changeCount()
        if not pasteboard.setString_forType_(text, NSPasteboardTypeString):
            raise TextInsertionError("Could not place translated text on the clipboard.")
        owned_change_count = pasteboard.changeCount()

        _verify_target_context(
            accessibility,
            CFEqual,
            target,
            workspace=NSWorkspace.sharedWorkspace(),
        )
        _post_paste_shortcut(Quartz)
        time.sleep(PASTE_COMPLETION_DELAY_SECONDS)
    except TextInsertionError:
        raise
    except Exception as error:
        raise TextInsertionError(
            f"Could not paste the translation. Enable Accessibility for {PRODUCT_NAME}."
        ) from error
    finally:
        if owned_change_count is not None:
            _restore_pasteboard_if_owned(
                pasteboard,
                owned_change_count,
                snapshot,
                NSPasteboardItem,
                NSData,
            )


def _verify_target_context(
    accessibility, elements_equal, target: TargetContext, *, workspace
) -> None:
    """Require the captured application and optional window to remain current."""
    current_application = workspace.frontmostApplication()
    if current_application is None:
        raise TextInsertionError("Could not verify the frontmost application.")
    current_process_id = int(current_application.processIdentifier())
    if current_process_id != target.process_id:
        raise TextInsertionError(
            f"The frontmost application is no longer {target.name}; paste was cancelled."
        )

    _verify_optional_systemwide_pid(accessibility, target.process_id)
    if target.window_element is None:
        return

    current_window = _optional_focused_window(accessibility, target.process_id)
    if current_window is None:
        raise TextInsertionError(
            f"Could not verify the captured window in {target.name}; paste was cancelled."
        )
    if not elements_equal(current_window, target.window_element):
        raise TextInsertionError(
            f"A different window is active in {target.name}; paste was cancelled."
        )


def _post_paste_shortcut(quartz) -> None:
    """Post physical Command+V events without consulting the input layout."""
    source = quartz.CGEventSourceCreate(
        quartz.kCGEventSourceStateHIDSystemState
    )
    if source is None:
        raise TextInsertionError("Could not create a keyboard event source.")

    event_specs = (
        (MAC_KEY_CODE_LEFT_COMMAND, True, quartz.kCGEventFlagMaskCommand),
        (MAC_KEY_CODE_V, True, quartz.kCGEventFlagMaskCommand),
        (MAC_KEY_CODE_V, False, quartz.kCGEventFlagMaskCommand),
        (MAC_KEY_CODE_LEFT_COMMAND, False, 0),
    )
    events = []
    for key_code, is_key_down, flags in event_specs:
        event = quartz.CGEventCreateKeyboardEvent(
            source, key_code, is_key_down
        )
        if event is None:
            raise TextInsertionError("Could not create the paste keyboard events.")
        quartz.CGEventSetFlags(event, flags)
        events.append(event)

    command_down, v_down, v_up, command_up = events
    command_is_down = False
    try:
        quartz.CGEventPost(quartz.kCGHIDEventTap, command_down)
        command_is_down = True
        quartz.CGEventPost(quartz.kCGHIDEventTap, v_down)
        quartz.CGEventPost(quartz.kCGHIDEventTap, v_up)
    finally:
        if command_is_down:
            quartz.CGEventPost(quartz.kCGHIDEventTap, command_up)


def _snapshot_pasteboard(pasteboard) -> tuple[PasteboardItemSnapshot, ...]:
    snapshots: list[PasteboardItemSnapshot] = []
    for item in pasteboard.pasteboardItems() or []:
        values: list[tuple[str, bytes]] = []
        for type_name in item.types() or []:
            data = item.dataForType_(type_name)
            if data is not None:
                values.append((str(type_name), bytes(data)))
        snapshots.append(PasteboardItemSnapshot(tuple(values)))
    return tuple(snapshots)


def _restore_pasteboard(
    pasteboard,
    snapshot: tuple[PasteboardItemSnapshot, ...],
    pasteboard_item_class,
    data_class,
) -> None:
    pasteboard.clearContents()
    restored_items = []
    for saved_item in snapshot:
        item = pasteboard_item_class.alloc().init()
        for type_name, raw_data in saved_item.values:
            data = data_class.dataWithBytes_length_(raw_data, len(raw_data))
            item.setData_forType_(data, type_name)
        restored_items.append(item)
    if restored_items:
        pasteboard.writeObjects_(restored_items)


def _restore_pasteboard_if_owned(
    pasteboard,
    owned_change_count: int,
    snapshot: tuple[PasteboardItemSnapshot, ...],
    pasteboard_item_class,
    data_class,
) -> bool:
    """Restore a snapshot only while Dicta's pasteboard contents are current."""
    if pasteboard.changeCount() != owned_change_count:
        return False
    _restore_pasteboard(
        pasteboard, snapshot, pasteboard_item_class, data_class
    )
    return True
