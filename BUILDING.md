# Building Dicta

Dicta is a local-only Apple Silicon macOS application. End users receive
`Dicta.app` and do not need Python, Homebrew, CMake, Git, or the model download.
The tools below are only for developers building from source.

## Developer prerequisites

- Apple Silicon Mac running macOS 26 or later
- Python 3.14
- Git
- CMake
- Xcode Command Line Tools

The current release build uses the Homebrew Python 3.14 distribution. This is
why PyInstaller collects CPython and its OpenSSL, XZ, Zstandard, and mpdecimal
libraries into the standalone app.

## Python environment

From the repository root:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
```

All runtime processing is local. No API key or cloud service is used.

## Install whisper.cpp and the model

Run the bootstrap script:

```bash
.venv/bin/python packaging/setup_whisper.py
```

It performs these reproducible steps:

1. clones whisper.cpp tag `v1.9.4` into the ignored
   `vendor/whisper.cpp/` directory;
2. verifies that the checkout is commit
   `927cfce34f31707e17f2bff35c349632fb9e2c3a`;
3. builds the `whisper-cli` target in Release mode; and
4. downloads `ggml-medium.bin` from the upstream whisper.cpp model repository
   and verifies SHA-256
   `6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208`.

The checkout, compiled files, and approximately 1.5 GB model remain local and
must not be committed. The paths match Dicta's runtime and packaging defaults.
The script refuses an existing checkout at a different revision instead of
silently building it.

To validate an existing setup without building or downloading anything:

```bash
.venv/bin/python packaging/setup_whisper.py --check
```

## Run from source

```bash
.venv/bin/python -m voice_translator
.venv/bin/python -m voice_translator --terminal
```

## Build Dicta.app

PyInstaller is pinned in `requirements-build.txt`.

```bash
.venv/bin/python packaging/setup_whisper.py --check
.venv/bin/python packaging/build_app.py
```

The finished app is written to `dist/Dicta.app`. The model, whisper.cpp native
runtime, dependency notices, and license texts are bundled in the app.
Generated iconsets, staged native libraries, and PyInstaller work files remain
under ignored `build/` and `dist/` directories.

The build script ad-hoc signs the complete bundle and verifies the resulting
signature. It does not use a Developer ID certificate and does not notarize the
app. This is intentional for the initial open-source distribution.

When preparing a release archive, preserve the application bundle with:

```bash
ditto -c -k --keepParent dist/Dicta.app Dicta.zip
```

Do not commit `Dicta.zip`; it is a release artifact.

## Gatekeeper behavior

A zip downloaded through a browser is normally quarantined by macOS. Because
this app is ad-hoc signed rather than Developer ID signed and notarized,
Gatekeeper will not identify a verified developer and will normally block the
first launch.

The eventual user documentation should tell users to try opening Dicta once,
then open **System Settings → Privacy & Security**, find the blocked-app
message, click **Open Anyway**, and confirm **Open**. Users should do this only
for a release downloaded from Dicta's official GitHub repository. This is a
per-app override supported by macOS; users should never disable Gatekeeper
globally.

Ad-hoc signing still provides code-directory integrity for that exact build,
but it provides no verified publisher identity and cannot satisfy Gatekeeper's
online notarization check. A frictionless first launch would require Developer
ID signing and notarization, which are intentionally out of scope.
