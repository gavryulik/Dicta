"""Text insertion into the macOS field focused when dictation started."""

from dataclasses import dataclass
import time

from voice_translator.config import (
    APP_ACTIVATION_DELAY_SECONDS,
    PASTE_COMPLETION_DELAY_SECONDS,
    PRODUCT_NAME,
)

# Hardware key codes from the macOS ANSI keyboard layout. CoreGraphics uses
# these physical positions without translating the character through the
# currently selected input source.
MAC_KEY_CODE_V = 9
MAC_KEY_CODE_LEFT_COMMAND = 55


class TextInsertionError(RuntimeError):
    """Raised when translated text cannot be inserted."""


@dataclass(frozen=True)
class TargetApplication:
    process_id: int
    name: str
    focused_element: object
    element_description: str = "Unknown Accessibility element"


@dataclass(frozen=True)
class PasteboardItemSnapshot:
    values: tuple[tuple[str, bytes], ...]


def capture_target_application() -> TargetApplication:
    """Capture the system-wide app and element with keyboard focus."""
    try:
        from AppKit import NSRunningApplication
        from CoreFoundation import CFEqual
        import ApplicationServices as accessibility
    except ImportError as error:
        raise TextInsertionError(
            "The PyObjC Cocoa package is not installed."
        ) from error

    return _capture_accessibility_target(
        accessibility, NSRunningApplication, CFEqual
    )


def _capture_accessibility_target(
    accessibility, running_application_class, elements_equal=lambda a, b: a == b
) -> TargetApplication:
    """Capture one consistent snapshot from the system Accessibility tree."""
    system_wide = accessibility.AXUIElementCreateSystemWide()
    application_element = _required_ax_attribute(
        accessibility,
        system_wide,
        accessibility.kAXFocusedApplicationAttribute,
        "the focused application",
    )
    focused_element = _required_ax_attribute(
        accessibility,
        application_element,
        accessibility.kAXFocusedUIElementAttribute,
        "the focused editable element",
    )

    # Accessibility calls are separate operations. Confirm that neither focus
    # value changed between them rather than saving a mixed app/field pair.
    confirmed_application = _required_ax_attribute(
        accessibility,
        system_wide,
        accessibility.kAXFocusedApplicationAttribute,
        "the focused application",
    )
    confirmed_element = _required_ax_attribute(
        accessibility,
        confirmed_application,
        accessibility.kAXFocusedUIElementAttribute,
        "the focused editable element",
    )
    if not elements_equal(application_element, confirmed_application) or not elements_equal(
        focused_element, confirmed_element
    ):
        raise TextInsertionError(
            "Keyboard focus changed while dictation was starting. Please try again."
        )

    error_code, process_id = accessibility.AXUIElementGetPid(
        application_element, None
    )
    if error_code != accessibility.kAXErrorSuccess:
        raise TextInsertionError(
            "Could not determine the focused application's process ID."
        )

    application = running_application_class.runningApplicationWithProcessIdentifier_(
        process_id
    )
    if application is None:
        raise TextInsertionError("The focused application is no longer running.")

    return TargetApplication(
        process_id=int(process_id),
        name=str(application.localizedName() or "Unknown application"),
        focused_element=focused_element,
        element_description=_describe_ax_element(accessibility, focused_element),
    )


def _required_ax_attribute(accessibility, element, attribute, description):
    error_code, value = accessibility.AXUIElementCopyAttributeValue(
        element, attribute, None
    )
    if error_code != accessibility.kAXErrorSuccess or value is None:
        raise TextInsertionError(f"Could not capture {description}.")
    return value


def _describe_ax_element(accessibility, element) -> str:
    details = []
    attributes = (
        ("role", "kAXRoleAttribute"),
        ("subrole", "kAXSubroleAttribute"),
        ("title", "kAXTitleAttribute"),
        ("description", "kAXDescriptionAttribute"),
    )
    for label, constant_name in attributes:
        attribute = getattr(accessibility, constant_name, None)
        if attribute is None:
            continue
        error_code, value = accessibility.AXUIElementCopyAttributeValue(
            element, attribute, None
        )
        if error_code == accessibility.kAXErrorSuccess and value:
            details.append(f"{label}={value!s}")

    return ", ".join(details) or repr(element)


def insert_text(text: str, target: TargetApplication) -> None:
    """Paste Unicode text into the focused field of the captured application."""
    if not text.strip():
        return

    try:
        from AppKit import (
            NSApplicationActivateIgnoringOtherApps,
            NSPasteboard,
            NSPasteboardItem,
            NSPasteboardTypeString,
            NSRunningApplication,
        )
        from Foundation import NSData
        from CoreFoundation import CFEqual
        import ApplicationServices as accessibility
        import Quartz
    except ImportError as error:
        raise TextInsertionError(
            "The macOS text-insertion dependencies are not installed."
        ) from error

    application = NSRunningApplication.runningApplicationWithProcessIdentifier_(
        target.process_id
    )
    if application is None:
        raise TextInsertionError(f"{target.name} is no longer running.")

    pasteboard = NSPasteboard.generalPasteboard()
    snapshot = _snapshot_pasteboard(pasteboard)
    owned_change_count = None

    try:
        pasteboard.clearContents()
        owned_change_count = pasteboard.changeCount()
        if not pasteboard.setString_forType_(text, NSPasteboardTypeString):
            raise TextInsertionError("Could not place translated text on the clipboard.")
        owned_change_count = pasteboard.changeCount()

        application.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(APP_ACTIVATION_DELAY_SECONDS)

        error_code = accessibility.AXUIElementSetAttributeValue(
            target.focused_element, accessibility.kAXFocusedAttribute, True
        )
        if error_code != accessibility.kAXErrorSuccess:
            raise TextInsertionError(
                f"Could not restore focus to the captured field in {target.name}."
            )

        _verify_target_focus(accessibility, CFEqual, target)

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


def _verify_target_focus(accessibility, elements_equal, target) -> None:
    """Refuse to paste unless the original app and element have focus."""
    system_wide = accessibility.AXUIElementCreateSystemWide()
    application_element = _required_ax_attribute(
        accessibility,
        system_wide,
        accessibility.kAXFocusedApplicationAttribute,
        "the restored focused application",
    )
    error_code, process_id = accessibility.AXUIElementGetPid(
        application_element, None
    )
    if (
        error_code != accessibility.kAXErrorSuccess
        or int(process_id) != target.process_id
    ):
        raise TextInsertionError(
            f"Focus did not return to the captured application {target.name}."
        )

    focused_element = _required_ax_attribute(
        accessibility,
        application_element,
        accessibility.kAXFocusedUIElementAttribute,
        "the restored focused element",
    )
    if not elements_equal(focused_element, target.focused_element):
        raise TextInsertionError(
            f"Focus did not return to the captured field in {target.name}."
        )


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
