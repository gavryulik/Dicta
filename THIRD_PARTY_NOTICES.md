# Third-Party Notices

Dicta is distributed under the MIT License in `LICENSE`. A packaged
`Dicta.app` also contains the components below. Full license texts are in
`third_party_licenses/` and are copied into the app at build time.

## Runtime components

| Component | Version used by the current build | License | Project / source |
| --- | --- | --- | --- |
| whisper.cpp, including ggml | v1.9.4 | MIT | <https://github.com/ggml-org/whisper.cpp> |
| OpenAI Whisper `medium` model, converted to ggml format | `ggml-medium.bin`, SHA-256 `6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208` | MIT | <https://github.com/openai/whisper> and <https://huggingface.co/ggerganov/whisper.cpp> |
| CPython and Python standard library | 3.14.6 | Python Software Foundation License Version 2 and bundled notices | <https://www.python.org/> |
| PyObjC (`pyobjc-core`, Cocoa, ApplicationServices, CoreText, Quartz) | 12.2.2 | MIT | <https://github.com/ronaldoussoren/pyobjc> |
| pynput | 1.8.2 | GNU LGPL v3 | <https://github.com/moses-palmer/pynput> |
| six | 1.17.0 | MIT | <https://github.com/benjaminp/six> |
| python-sounddevice | 0.5.6 | MIT | <https://github.com/spatialaudio/python-sounddevice> |
| CFFI | 2.1.1 | MIT No Attribution (MIT-0) | <https://github.com/python-cffi/cffi> |
| PortAudio binary supplied by python-sounddevice | 19.7.0-devel | MIT | <https://github.com/PortAudio/portaudio> and <https://github.com/spatialaudio/portaudio-binaries> |
| OpenSSL (`libssl` and `libcrypto`) | 3.6.5 | Apache License 2.0 | <https://github.com/openssl/openssl> |
| XZ Utils `liblzma` | 5.8.4 | BSD Zero Clause (0BSD) | <https://github.com/tukaani-project/xz> |
| Zstandard `libzstd` | 1.5.7 | BSD 3-Clause | <https://github.com/facebook/zstd> |
| mpdecimal `libmpdec` | 4.0.1 | BSD 2-Clause | <https://www.bytereef.org/mpdecimal/> |

The macOS system frameworks and system libraries used by Dicta are supplied by
Apple and are not redistributed as third-party files by this project.

### pynput / LGPL note

Dicta uses the unmodified pynput library for its global keyboard shortcut.
The corresponding pynput source is available from the project link above and
from the exact `pynput==1.8.2` source distribution on PyPI. Dicta's own source,
dependency pins, and build instructions are published so recipients can
replace or modify pynput and rebuild the application. The complete LGPL v3 and
GPL v3 texts accompany the distribution in `third_party_licenses/`.

## Build tooling represented in the packaged application

PyInstaller 6.22.3 creates the application bundle. Its bootloader is covered
by GPL v2-or-later with PyInstaller's exception permitting distribution of the
resulting application. PyInstaller Community Hooks may contribute runtime
hooks; its applicable GPL / Apache license text is included. Source projects:

- <https://github.com/pyinstaller/pyinstaller>
- <https://github.com/pyinstaller/pyinstaller-hooks-contrib>

`altgraph`, `macholib`, `packaging`, `pip`, `pycparser`, and `setuptools` are
development/build dependencies in the current environment but were not found
as separately distributed runtime components in the inspected app bundle.

## PortAudio / ASIO clarification

Only the macOS `libportaudio.dylib` is needed and included by the current
packaging configuration. Windows PortAudio/ASIO DLLs shipped in the upstream
python-sounddevice wheel are deliberately excluded from Dicta's macOS bundle.
Dicta therefore does not redistribute the Steinberg ASIO SDK binaries.

This inventory should be rechecked whenever dependencies, the Python build, or
the packaging environment changes. It records the components found in the
inspected Apple Silicon build and is not a substitute for legal advice.
