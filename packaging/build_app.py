"""Prepare native resources and build the local Dicta.app with PyInstaller."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

from generate_icon import generate_icon


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = PROJECT_ROOT / "build/packaging"
STAGED_WHISPER = BUILD_ROOT / "whisper-bin"
SOURCE_WHISPER = PROJECT_ROOT / "vendor/whisper.cpp/build/bin"
SOURCE_MODEL = PROJECT_ROOT / "vendor/whisper.cpp/models/ggml-medium.bin"
SOURCE_ICON = PROJECT_ROOT / "assets/dicta-icon.png"
GENERATED_ICON = BUILD_ROOT / "Dicta.icns"
GENERATED_ICONSET = BUILD_ROOT / "Dicta.iconset"
APP_PATH = PROJECT_ROOT / "dist/Dicta.app"
APP_INFO_PLIST = APP_PATH / "Contents/Info.plist"


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def prepare_whisper_runtime() -> None:
    """Copy only whisper-cli's local dylibs and make their rpaths portable."""
    if STAGED_WHISPER.exists():
        shutil.rmtree(STAGED_WHISPER)
    STAGED_WHISPER.mkdir(parents=True)

    sources = [SOURCE_WHISPER / "whisper-cli"]
    sources.extend(sorted(SOURCE_WHISPER.glob("libwhisper*.dylib")))
    sources.extend(sorted(SOURCE_WHISPER.glob("libggml*.dylib")))

    for source in sources:
        destination = STAGED_WHISPER / source.name
        if source.is_symlink():
            destination.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, destination)

    for binary in STAGED_WHISPER.iterdir():
        if binary.is_symlink() or not _is_macho(binary):
            continue
        _make_rpath_portable(binary)


def _is_macho(path: Path) -> bool:
    result = subprocess.run(
        ["file", str(path)], check=True, capture_output=True, text=True
    )
    return "Mach-O" in result.stdout


def _make_rpath_portable(path: Path) -> None:
    output = subprocess.run(
        ["otool", "-l", str(path)], check=True, capture_output=True, text=True
    ).stdout
    rpaths = re.findall(r"\n\s*path (\S+) \(offset \d+\)", output)
    for rpath in rpaths:
        if rpath.startswith("/"):
            run(["install_name_tool", "-delete_rpath", rpath, str(path)])
    if "@loader_path" not in rpaths:
        run(["install_name_tool", "-add_rpath", "@loader_path", str(path)])


def validate_inputs() -> None:
    required = (
        SOURCE_ICON,
        SOURCE_WHISPER / "whisper-cli",
        SOURCE_MODEL,
        PROJECT_ROOT / "Dicta.spec",
        PROJECT_ROOT / "LICENSE",
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Missing build inputs:\n- " + "\n- ".join(missing))


def build() -> None:
    validate_inputs()
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(
        PROJECT_ROOT / "build/pyinstaller-cache"
    )
    generate_icon(SOURCE_ICON, GENERATED_ICON, GENERATED_ICONSET)
    prepare_whisper_runtime()

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(PROJECT_ROOT / "build/pyinstaller"),
            "--distpath",
            str(PROJECT_ROOT / "dist"),
            str(PROJECT_ROOT / "Dicta.spec"),
        ]
    )
    # PyInstaller always writes a marketing version. Dicta intentionally has
    # no user-facing version number, so remove it before the final signature.
    run(["plutil", "-remove", "CFBundleShortVersionString", str(APP_INFO_PLIST)])
    run(["codesign", "--force", "--deep", "--sign", "-", str(APP_PATH)])
    run(["codesign", "--verify", "--deep", "--strict", str(APP_PATH)])
    print(f"Built {APP_PATH}", flush=True)


if __name__ == "__main__":
    build()
