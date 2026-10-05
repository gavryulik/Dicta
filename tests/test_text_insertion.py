import unittest
from types import SimpleNamespace

from voice_translator.text_insertion import (
    MAC_KEY_CODE_LEFT_COMMAND,
    MAC_KEY_CODE_V,
    TargetApplication,
    TextInsertionError,
    _capture_accessibility_target,
    _post_paste_shortcut,
    _restore_pasteboard,
    _restore_pasteboard_if_owned,
    _snapshot_pasteboard,
    _verify_target_focus,
)


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


class FakeAccessibility:
    kAXErrorSuccess = 0
    kAXFocusedApplicationAttribute = "focused_application"
    kAXFocusedUIElementAttribute = "focused_element"
    kAXRoleAttribute = "role"
    kAXSubroleAttribute = "subrole"
    kAXTitleAttribute = "title"
    kAXDescriptionAttribute = "description"

    def __init__(self, focused_application, focused_element, process_id=222):
        self.system_wide = object()
        self.focused_application = focused_application
        self.focused_element = focused_element
        self.process_id = process_id

    def AXUIElementCreateSystemWide(self):
        return self.system_wide

    def AXUIElementCopyAttributeValue(self, element, attribute, unused):
        del unused
        if element is self.system_wide and attribute == "focused_application":
            return self.kAXErrorSuccess, self.focused_application
        if element is self.focused_application and attribute == "focused_element":
            return self.kAXErrorSuccess, self.focused_element
        if element is self.focused_element and attribute == "role":
            return self.kAXErrorSuccess, "AXTextField"
        return 1, None

    def AXUIElementGetPid(self, element, unused):
        del unused
        if element is self.focused_application:
            return self.kAXErrorSuccess, self.process_id
        return 1, None


class ChangingFocusAccessibility(FakeAccessibility):
    def __init__(self, focused_application, first_element, second_element):
        super().__init__(focused_application, first_element)
        self._elements = iter((first_element, second_element))

    def AXUIElementCopyAttributeValue(self, element, attribute, unused):
        if element is self.focused_application and attribute == "focused_element":
            return self.kAXErrorSuccess, next(self._elements)
        return super().AXUIElementCopyAttributeValue(element, attribute, unused)


class FakeRunningApplication:
    application = SimpleNamespace(localizedName=lambda: "Google Chrome")

    @classmethod
    def runningApplicationWithProcessIdentifier_(cls, process_id):
        return cls.application if process_id == 222 else None


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
        _restore_pasteboard(
            pasteboard, snapshot, FakeRestoredItem, FakeData
        )

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


class FocusTargetTests(unittest.TestCase):
    def test_capture_uses_system_wide_focused_application_and_element(self) -> None:
        chrome_application = object()
        chrome_field = object()
        accessibility = FakeAccessibility(chrome_application, chrome_field)

        target = _capture_accessibility_target(
            accessibility, FakeRunningApplication
        )

        self.assertEqual(target.process_id, 222)
        self.assertEqual(target.name, "Google Chrome")
        self.assertIs(target.focused_element, chrome_field)
        self.assertEqual(target.element_description, "role=AXTextField")

    def test_capture_fails_instead_of_falling_back_without_focused_element(self):
        accessibility = FakeAccessibility(object(), None)

        with self.assertRaisesRegex(
            TextInsertionError, "focused editable element"
        ):
            _capture_accessibility_target(accessibility, FakeRunningApplication)

    def test_verification_rejects_a_different_focused_field(self) -> None:
        captured_field = object()
        current_field = object()
        accessibility = FakeAccessibility(object(), current_field)
        target = TargetApplication(
            process_id=222,
            name="Google Chrome",
            focused_element=captured_field,
        )

        with self.assertRaisesRegex(TextInsertionError, "captured field"):
            _verify_target_focus(
                accessibility,
                lambda first, second: first is second,
                target,
            )

    def test_capture_rejects_focus_that_changes_during_capture(self) -> None:
        accessibility = ChangingFocusAccessibility(
            object(), object(), object()
        )

        with self.assertRaisesRegex(TextInsertionError, "focus changed"):
            _capture_accessibility_target(
                accessibility,
                FakeRunningApplication,
                lambda first, second: first is second,
            )


if __name__ == "__main__":
    unittest.main()
