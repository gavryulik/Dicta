"""User-changeable settings for Dicta."""


PRODUCT_NAME = "Dicta"
PRODUCT_TAGLINE = "Speak in Russian. Type in English."


# Hold this chord to record. Recording stops when any key in the chord is released.
PUSH_TO_TALK_MODIFIERS = frozenset({"alt"})
PUSH_TO_TALK_TRIGGER = "space"
PUSH_TO_TALK_LABEL = "Option+Space"

# macOS virtual key code for Space. Used only to keep the shortcut from reaching
# the foreground application; all other keyboard events pass through normally.
PUSH_TO_TALK_VIRTUAL_KEY_CODE = 49

# Small delays let macOS reactivate the target application and consume the paste
# before the user's clipboard is restored.
APP_ACTIVATION_DELAY_SECONDS = 0.15
PASTE_COMPLETION_DELAY_SECONDS = 0.20
