import unittest
from types import SimpleNamespace

from voice_translator.text_insertion import (
    MAC_KEY_CODE_LEFT_COMMAND,
    MAC_KEY_CODE_V,
    TargetContext,
    TextInsertionError,
    _capture_target_context,
    _post_paste_shortcut,
    _restore_pasteboard,
    _restore_pasteboard_if_owned,
    _snapshot_pasteboard,
    _verify_target_context,
)


class FakeWorkspaceApplication:
    def __init__(self, process_id, name="Example"):
        self._process_id = process_id
        self._name = name

    def processIdentifier(self):
        return self._process_id

    def localizedName(self):
        return self._name


class FakeWorkspace:
    def __init__(self, process_ids):
        self._process_ids = list(process_ids)
        self.call_count = 0

    def frontmostApplication(self):
        index = min(self.call_count, len(self._process_ids) - 1)
        self.call_count += 1
        process_id = self._process_ids[index]
        if process_id is None:
            return None
        return FakeWorkspaceApplication(process_id)


class FakeRunningApplication:
    @classmethod
    def runningApplicationWithProcessIdentifier_(cls, process_id):
        if process_id != 222:
            return None
        return SimpleNamespace(localizedName=lambda: "Example")


class FakeAccessibility:
    kAXErrorSuccess = 0
    kAXErrorCannotComplete = -25204
    kAXErrorAPIDisabled = -25211
    kAXErrorNoValue = -25212
    kAXFocusedApplicationAttribute = "focused_application"
    kAXFocusedWindowAttribute = "focused_window"

    def __init__(
        self,
        *,
        process_id=222,
        windows=None,
        systemwide_error=kAXErrorNoValue,
    ):
        self.process_id = process_id
        self.systemwide_error = systemwide_error
        self.system_wide = object()
        self.application_element = object()
        self.windows = list(windows or [None])
        self.window_query_count = 0
        self.queried_attributes = []
        self.known_windows = {window for window in self.windows if window is not None}

    def AXUIElementCreateSystemWide(self):
        return self.system_wide

    def AXUIElementCreateApplication(self, process_id):
        return self.application_element if process_id == self.process_id else None

    def AXUIElementCopyAttributeValue(self, element, attribute, unused):
        del unused
        self.queried_attributes.append(attribute)
        if attribute in {"focused_element", "children"}:
            raise AssertionError("Exact-field Accessibility must not be queried")
        if element is self.system_wide and attribute == "focused_application":
            if self.systemwide_error == self.kAXErrorSuccess:
                return self.kAXErrorSuccess, self.application_element
            return self.systemwide_error, None
        if element is self.application_element and attribute == "focused_window":
            index = min(self.window_query_count, len(self.windows) - 1)
            self.window_query_count += 1
            window = self.windows[index]
            if window is None:
                return self.kAXErrorNoValue, None
            return self.kAXErrorSuccess, window
        return self.kAXErrorNoValue, None

    def AXUIElementGetPid(self, element, unused):
        del unused
        if element is self.application_element or element in self.known_windows:
            return self.kAXErrorSuccess, self.process_id
        return self.kAXErrorNoValue, None


class FakeQuartz:
    kCGEventSourceStateHIDSystemState = 1
    kCGEventFlagMaskCommand = 1 << 20
    kCGHIDEventTap = 0

    def __init__(self, fail_on_post=None):
        self.created = []
        self.posted = []
        self.fail_on_post = fail_on_post

    def CGEventSourceCreate(self, state):
        self.source_state = state
        return "event-source"

    def CGEventCreateKeyboardEvent(self, source, key_code, is_key_down):
        event = {
            "source": source,
            "key_code": key_code,
            "is_key_down": is_key_down,
            "flags": None,
        }
        self.created.append(event)
        return event

    @staticmethod
    def CGEventSetFlags(event, flags):
        event["flags"] = flags

    def CGEventPost(self, tap, event):
        self.posted.append((tap, event))
        if len(self.posted) == self.fail_on_post:
            raise RuntimeError("event posting failed")


class FakeExistingItem:
    def __init__(self, values):
        self.values = values

    def types(self):
        return list(self.values)

    def dataForType_(self, type_name):
        return self.values[type_name]


class FakeRestoredItem:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        self.values = {}
        return self

    def setData_forType_(self, data, type_name):
        self.values[type_name] = data


class FakeData:
    @staticmethod
    def dataWithBytes_length_(data, length):
        return bytes(data[:length])


class FakePasteboard:
    def __init__(self, items):
        self.items = items
        self._change_count = 0

    def pasteboardItems(self):
        return self.items

    def clearContents(self):
        self.items = []
        self._change_count += 1

    def writeObjects_(self, items):
        self.items = items
        self._change_count += 1
        return True

    def setString_forType_(self, text, type_name):
        self.items = [FakeExistingItem({type_name: text.encode()})]
        self._change_count += 1
        return True

    def changeCount(self):
        return self._change_count


class TargetContextTests(unittest.TestCase):
    def test_capture_keeps_stable_reliable_window(self) -> None:
        window = object()
        accessibility = FakeAccessibility(windows=[window, window])

        target = _capture_target_context(
            accessibility,
            FakeRunningApplication,
            lambda first, second: first is second,
            workspace=FakeWorkspace([222, 222]),
            retry_delays=(0.0,),
        )

        self.assertEqual(target.process_id, 222)
        self.assertIs(target.window_element, window)

    def test_same_application_and_window_are_allowed(self) -> None:
        window = object()
        accessibility = FakeAccessibility(windows=[window])
        target = TargetContext(222, "Example", window)

        _verify_target_context(
            accessibility,
            lambda first, second: first is second,
            target,
            workspace=FakeWorkspace([222]),
        )

    def test_different_application_is_refused(self) -> None:
        target = TargetContext(222, "Example")

        with self.assertRaisesRegex(TextInsertionError, "no longer Example"):
            _verify_target_context(
                FakeAccessibility(),
                lambda first, second: first is second,
                target,
                workspace=FakeWorkspace([333]),
            )

    def test_same_application_with_different_window_is_refused(self) -> None:
        captured_window = object()
        current_window = object()
        accessibility = FakeAccessibility(windows=[current_window])
        target = TargetContext(222, "Example", captured_window)

        with self.assertRaisesRegex(TextInsertionError, "different window"):
            _verify_target_context(
                accessibility,
                lambda first, second: first is second,
                target,
                workspace=FakeWorkspace([222]),
            )

    def test_same_application_without_window_identity_is_allowed(self) -> None:
        accessibility = FakeAccessibility(windows=[None, None, None])
        target = _capture_target_context(
            accessibility,
            FakeRunningApplication,
            workspace=FakeWorkspace([222, 222]),
            retry_delays=(0.0,),
        )

        self.assertIsNone(target.window_element)
        _verify_target_context(
            accessibility,
            lambda first, second: first is second,
            target,
            workspace=FakeWorkspace([222]),
        )

    def test_changed_field_in_same_app_and_window_is_allowed(self) -> None:
        window = object()
        accessibility = FakeAccessibility(windows=[window])

        _verify_target_context(
            accessibility,
            lambda first, second: first is second,
            TargetContext(222, "Example", window),
            workspace=FakeWorkspace([222]),
        )

        self.assertNotIn("focused_element", accessibility.queried_attributes)

    def test_no_focused_element_does_not_prevent_capture_or_verification(self):
        accessibility = FakeAccessibility(windows=[None, None, None])
        target = _capture_target_context(
            accessibility,
            FakeRunningApplication,
            workspace=FakeWorkspace([222, 222]),
            retry_delays=(0.0,),
        )
        _verify_target_context(
            accessibility,
            lambda first, second: first is second,
            target,
            workspace=FakeWorkspace([222]),
        )

        self.assertNotIn("focused_element", accessibility.queried_attributes)

    def test_chatgpt_like_nested_groups_are_never_inspected(self) -> None:
        window = object()
        accessibility = FakeAccessibility(
            windows=[window, window],
            systemwide_error=FakeAccessibility.kAXErrorNoValue,
        )

        target = _capture_target_context(
            accessibility,
            FakeRunningApplication,
            lambda first, second: first is second,
            workspace=FakeWorkspace([222, 222]),
            retry_delays=(0.0,),
        )

        self.assertIs(target.window_element, window)
        self.assertNotIn("children", accessibility.queried_attributes)
        self.assertNotIn("focused_element", accessibility.queried_attributes)

    def test_dicta_cannot_be_its_own_target(self) -> None:
        with self.assertRaisesRegex(TextInsertionError, "cannot use itself"):
            _capture_target_context(
                FakeAccessibility(),
                FakeRunningApplication,
                workspace=FakeWorkspace([222]),
                current_process_id=222,
                retry_delays=(0.0,),
            )

    def test_application_change_during_capture_retries(self) -> None:
        workspace = FakeWorkspace([111, 222, 222])

        target = _capture_target_context(
            FakeAccessibility(),
            FakeRunningApplication,
            workspace=workspace,
            retry_delays=(0.0, 0.0),
        )

        self.assertEqual(target.process_id, 222)

    def test_api_disabled_fails_with_permission_reason(self) -> None:
        accessibility = FakeAccessibility(
            systemwide_error=FakeAccessibility.kAXErrorAPIDisabled
        )

        with self.assertRaisesRegex(TextInsertionError, "permission is disabled"):
            _capture_target_context(
                accessibility,
                FakeRunningApplication,
                workspace=FakeWorkspace([222]),
                retry_delays=(0.0,),
            )


class PasteShortcutTests(unittest.TestCase):
    def test_uses_physical_v_key_code_independent_of_layout(self) -> None:
        quartz = FakeQuartz()

        _post_paste_shortcut(quartz)

        self.assertEqual(
            [
                (event["key_code"], event["is_key_down"], event["flags"])
                for event in quartz.created
            ],
            [
                (
                    MAC_KEY_CODE_LEFT_COMMAND,
                    True,
                    quartz.kCGEventFlagMaskCommand,
                ),
                (MAC_KEY_CODE_V, True, quartz.kCGEventFlagMaskCommand),
                (MAC_KEY_CODE_V, False, quartz.kCGEventFlagMaskCommand),
                (MAC_KEY_CODE_LEFT_COMMAND, False, 0),
            ],
        )
        self.assertEqual(
            [event for unused_tap, event in quartz.posted],
            quartz.created,
        )

    def test_releases_command_if_posting_v_fails(self) -> None:
        quartz = FakeQuartz(fail_on_post=2)

        with self.assertRaisesRegex(RuntimeError, "event posting failed"):
            _post_paste_shortcut(quartz)

        posted_events = [event for unused_tap, event in quartz.posted]
        self.assertIs(posted_events[0], quartz.created[0])
        self.assertIs(posted_events[1], quartz.created[1])
        self.assertIs(posted_events[2], quartz.created[3])
        self.assertFalse(posted_events[-1]["is_key_down"])
        self.assertEqual(posted_events[-1]["flags"], 0)


class PasteboardTests(unittest.TestCase):
    def test_snapshot_and_restore_preserve_all_items_and_types(self) -> None:
        pasteboard = FakePasteboard(
            [
                FakeExistingItem(
                    {
                        "public.utf8-plain-text": "Привіт".encode(),
                        "public.html": b"<b>Hello</b>",
                    }
                ),
                FakeExistingItem({"public.file-url": b"file:///tmp/example"}),
            ]
        )

        snapshot = _snapshot_pasteboard(pasteboard)
        pasteboard.clearContents()
        _restore_pasteboard(pasteboard, snapshot, FakeRestoredItem, FakeData)

        self.assertEqual(len(pasteboard.items), 2)
        self.assertEqual(
            pasteboard.items[0].values["public.utf8-plain-text"],
            "Привіт".encode(),
        )
        self.assertEqual(
            pasteboard.items[0].values["public.html"], b"<b>Hello</b>"
        )
        self.assertEqual(
            pasteboard.items[1].values["public.file-url"],
            b"file:///tmp/example",
        )

    def test_restores_original_clipboard_while_dicta_still_owns_it(self) -> None:
        pasteboard = FakePasteboard(
            [FakeExistingItem({"public.utf8-plain-text": b"Original"})]
        )
        snapshot = _snapshot_pasteboard(pasteboard)
        pasteboard.clearContents()
        pasteboard.setString_forType_("Translation", "public.utf8-plain-text")
        dicta_change_count = pasteboard.changeCount()

        restored = _restore_pasteboard_if_owned(
            pasteboard,
            dicta_change_count,
            snapshot,
            FakeRestoredItem,
            FakeData,
        )

        self.assertTrue(restored)
        self.assertEqual(
            pasteboard.items[0].values["public.utf8-plain-text"], b"Original"
        )

    def test_preserves_newer_clipboard_when_dicta_no_longer_owns_it(self) -> None:
        pasteboard = FakePasteboard(
            [FakeExistingItem({"public.utf8-plain-text": b"Original"})]
        )
        snapshot = _snapshot_pasteboard(pasteboard)
        pasteboard.clearContents()
        pasteboard.setString_forType_("Translation", "public.utf8-plain-text")
        dicta_change_count = pasteboard.changeCount()
        newer_item = FakeExistingItem(
            {"public.utf8-plain-text": b"Newer user clipboard"}
        )
        pasteboard.writeObjects_([newer_item])

        restored = _restore_pasteboard_if_owned(
            pasteboard,
            dicta_change_count,
            snapshot,
            FakeRestoredItem,
            FakeData,
        )

        self.assertFalse(restored)
        self.assertEqual(pasteboard.items, [newer_item])


if __name__ == "__main__":
    unittest.main()
