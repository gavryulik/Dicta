"""Install the exact whisper.cpp runtime and model used to build Dicta."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WHISPER_DIR = PROJECT_ROOT / "vendor/whisper.cpp"
WHISPER_REPOSITORY = "https://github.com/ggml-org/whisper.cpp.git"
WHISPER_TAG = "v1.9.4"
WHISPER_COMMIT = "927cfce34f31707e17f2bff35c349632fb9e2c3a"
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    "ggml-medium.bin"
)
MODEL_SHA256 = "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"
MODEL_PATH = WHISPER_DIR / "models/ggml-medium.bin"
CLI_PATH = WHISPER_DIR / "build/bin/whisper-cli"


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def command_output(command: list[str], *, cwd: Path = PROJECT_ROOT) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required developer tool is not installed: {name}")


def prepare_checkout() -> None:
    if not WHISPER_DIR.exists():
        WHISPER_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git",
                "clone",
                "--branch",
                WHISPER_TAG,
                "--depth",
                "1",
                "--single-branch",
                WHISPER_REPOSITORY,
                str(WHISPER_DIR),
            ]
        )


def validate_checkout() -> None:
    if not WHISPER_DIR.exists():
        raise RuntimeError(
            f"whisper.cpp is missing: {WHISPER_DIR}. Run this script without "
            "--check to install it."
        )
    if not (WHISPER_DIR / ".git").is_dir():
        raise RuntimeError(
            f"{WHISPER_DIR} exists but is not a Git checkout. "
            "Move it aside and run this script again."
        )

    commit = command_output(["git", "rev-parse", "HEAD"], cwd=WHISPER_DIR)
    if commit != WHISPER_COMMIT:
        raise RuntimeError(
            f"Expected whisper.cpp {WHISPER_TAG} at {WHISPER_COMMIT}, "
            f"but {WHISPER_DIR} is at {commit}. Move it aside and run this "
            "script again."
        )

    changed = command_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=WHISPER_DIR,
    )
    if changed:
        raise RuntimeError(
            f"{WHISPER_DIR} contains tracked local changes. Move it aside or "
            "restore the pinned upstream checkout before building."
        )


def build_whisper() -> None:
    run(
        [
            "cmake",
            "-S",
            str(WHISPER_DIR),
            "-B",
            str(WHISPER_DIR / "build"),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWHISPER_BUILD_TESTS=OFF",
            "-DWHISPER_BUILD_SERVER=OFF",
        ]
    )
    run(
        [
            "cmake",
            "--build",
            str(WHISPER_DIR / "build"),
            "--config",
            "Release",
            "--target",
            "whisper-cli",
            "--parallel",
        ]
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model() -> None:
    if not MODEL_PATH.is_file():
        raise RuntimeError(f"Whisper model is missing: {MODEL_PATH}")
    actual_hash = sha256(MODEL_PATH)
    if actual_hash != MODEL_SHA256:
        raise RuntimeError(
            f"Checksum mismatch for {MODEL_PATH}: expected {MODEL_SHA256}, "
            f"got {actual_hash}"
        )


def download_model() -> None:
    if MODEL_PATH.is_file():
        verify_model()
        print(f"Model already present and verified: {MODEL_PATH}")
        return

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    partial_path = MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".part")
    print(f"Downloading {MODEL_URL}", flush=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, partial_path)
        actual_hash = sha256(partial_path)
        if actual_hash != MODEL_SHA256:
            raise RuntimeError(
                f"Downloaded model checksum mismatch: expected {MODEL_SHA256}, "
                f"got {actual_hash}"
            )
        partial_path.replace(MODEL_PATH)
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise
    print(f"Downloaded and verified: {MODEL_PATH}")


def check_ready() -> None:
    validate_checkout()
    if not CLI_PATH.is_file():
        raise RuntimeError(f"whisper-cli is missing: {CLI_PATH}")
    architecture = command_output(["file", str(CLI_PATH)])
    if "arm64" not in architecture:
        raise RuntimeError(f"whisper-cli is not an arm64 binary: {architecture}")
    verify_model()
    print(f"whisper.cpp {WHISPER_TAG}, whisper-cli, and ggml-medium.bin are ready.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate existing files without building or downloading",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Dicta's whisper.cpp setup requires Apple Silicon macOS")
    require_tool("git")
    if args.check:
        check_ready()
        return 0

    require_tool("cmake")
    prepare_checkout()
    validate_checkout()
    build_whisper()
    download_model()
    check_ready()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
