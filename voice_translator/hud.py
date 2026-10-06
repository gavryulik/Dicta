"""Small non-activating status HUD for Dicta."""

try:
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSFont,
        NSPanel,
        NSScreen,
        NSStatusWindowLevel,
        NSTextAlignmentCenter,
        NSTextField,
        NSVisualEffectBlendingModeBehindWindow,
        NSVisualEffectMaterialHUDWindow,
        NSVisualEffectStateActive,
        NSVisualEffectView,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
    )
    from Foundation import NSMakeRect, NSObject, NSThread, NSTimer
except ImportError:
    # Keep imports harmless on non-macOS systems used for unit tests.
    objc = None
    NSPanel = object
    NSObject = object


_python_method = objc.python_method if objc is not None else lambda method: method


HUD_VISIBLE_SECONDS = 0.7
HUD_HEIGHT = 42.0
HUD_HORIZONTAL_PADDING = 18.0
HUD_BOTTOM_MARGIN = 64.0


class _NonActivatingPanel(NSPanel):
    """Panel that is structurally unable to become key or main."""

    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class StatusHUD(NSObject):
    """Show Dicta's current activity without activating Dicta."""

    if objc is not None:

        def init(self):
            self = objc.super(StatusHUD, self).init()
            if self is None:
                return None
            self._panel = None
            self._label = None
            self._effect_view = None
            self._hide_timer = None
            return self

    @_python_method
    def show_recording(self) -> None:
        self._show("Recording…")

    @_python_method
    def show_translating(self) -> None:
        self._show("Translating…")

    @_python_method
    def show_done(self) -> None:
        self._show("Done", hide_after=HUD_VISIBLE_SECONDS)

    @_python_method
    def show_error(self) -> None:
        self._show("Error", hide_after=HUD_VISIBLE_SECONDS)

    @_python_method
    def hide(self) -> None:
        self._require_main_thread()
        self._cancel_hide_timer()
        if self._panel is not None:
            self._panel.orderOut_(None)

    @_python_method
    def _show(self, text: str, hide_after: float | None = None) -> None:
        self._require_main_thread()
        self._cancel_hide_timer()
        self._build_panel_if_needed()
        self._label.setStringValue_(text)
        self._resize_and_position()

        # A nonactivating panel that cannot become key/main can be ordered above
        # other applications without changing the frontmost application.
        self._panel.orderFrontRegardless()

        if hide_after is not None:
            self._hide_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    hide_after, self, "hideAfterDelay:", None, False
                )
            )

    @_python_method
    def _build_panel_if_needed(self) -> None:
        if self._panel is not None:
            return

        style_mask = (
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        )
        panel = _NonActivatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0.0, 0.0, 160.0, HUD_HEIGHT),
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        effect_view = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0.0, 0.0, 160.0, HUD_HEIGHT)
        )
        effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect_view.setState_(NSVisualEffectStateActive)
        effect_view.setWantsLayer_(True)
        effect_view.layer().setCornerRadius_(10.0)
        effect_view.layer().setMasksToBounds_(True)

        label = NSTextField.labelWithString_("")
        label.setAlignment_(NSTextAlignmentCenter)
        label.setFont_(NSFont.systemFontOfSize_(15.0))
        label.setTextColor_(NSColor.whiteColor())
        label.setBackgroundColor_(NSColor.clearColor())
        label.setSelectable_(False)
        effect_view.addSubview_(label)
        panel.setContentView_(effect_view)

        self._panel = panel
        self._effect_view = effect_view
        self._label = label

    @_python_method
    def _resize_and_position(self) -> None:
        self._label.sizeToFit()
        fitted_size = self._label.frame().size
        text_width = fitted_size.width
        text_height = fitted_size.height
        panel_width = text_width + (HUD_HORIZONTAL_PADDING * 2.0)

        screen = NSScreen.mainScreen()
        if screen is None:
            screens = NSScreen.screens()
            screen = screens[0] if screens else None
        if screen is None:
            raise RuntimeError("No macOS screen is available for the status HUD.")

        visible_frame = screen.visibleFrame()
        x = visible_frame.origin.x + ((visible_frame.size.width - panel_width) / 2.0)
        y = visible_frame.origin.y + HUD_BOTTOM_MARGIN
        panel_frame = NSMakeRect(x, y, panel_width, HUD_HEIGHT)
        content_frame = NSMakeRect(0.0, 0.0, panel_width, HUD_HEIGHT)
        label_frame = NSMakeRect(
            (panel_width - text_width) / 2.0,
            (HUD_HEIGHT - text_height) / 2.0,
            text_width,
            text_height,
        )

        self._panel.setFrame_display_(panel_frame, True)
        self._effect_view.setFrame_(content_frame)
        self._label.setFrame_(label_frame)

    def hideAfterDelay_(self, timer) -> None:
        if timer is not self._hide_timer:
            return
        self._hide_timer = None
        if self._panel is not None:
            self._panel.orderOut_(None)

    @_python_method
    def _cancel_hide_timer(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.invalidate()
            self._hide_timer = None

    @staticmethod
    @_python_method
    def _require_main_thread() -> None:
        if not NSThread.isMainThread():
            raise RuntimeError("Status HUD updates must run on the macOS main thread.")
