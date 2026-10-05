"""Checks for macOS permissions required by the background service."""

import sys

from voice_translator.config import PRODUCT_NAME


class PermissionSetupError(RuntimeError):
    """Raised when a required dependency or macOS permission is missing."""


def require_macos_permissions() -> None:
    """Check Input Monitoring and Accessibility before starting the service."""
    if sys.platform != "darwin":
        raise PermissionSetupError(f"{PRODUCT_NAME} currently supports macOS only.")

    try:
        import Quartz
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except ImportError as error:
        raise PermissionSetupError(
            "The macOS integration packages are not installed. Activate the "
            "virtual environment and install requirements.txt."
        ) from error

    missing: list[str] = []

    if not Quartz.CGPreflightListenEventAccess():
        Quartz.CGRequestListenEventAccess()
        missing.append(
            "Input Monitoring (needed to detect the global shortcut)"
        )

    if not AXIsProcessTrustedWithOptions(
        {kAXTrustedCheckOptionPrompt: True}
    ):
        missing.append(
            "Accessibility (needed to paste into the focused application)"
        )

    if missing:
        permission_list = "\n- ".join(missing)
        raise PermissionSetupError(
            f"{PRODUCT_NAME} needs these macOS permissions:\n"
            f"- {permission_list}\n"
            f"Open System Settings > Privacy & Security, enable {PRODUCT_NAME} "
            "in each listed section, then restart it. When running from source, "
            "enable the terminal application instead."
        )
