from pathlib import Path


project_root = Path(SPECPATH).resolve()
build_resources = project_root / "build/packaging"
whisper_bin = build_resources / "whisper-bin"
model = project_root / "vendor/whisper.cpp/models/ggml-medium.bin"
icon = build_resources / "Dicta.icns"
license_dir = project_root / "third_party_licenses"

datas = [
    (str(model), "vendor/whisper.cpp/models"),
    (str(project_root / "LICENSE"), "licenses"),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "licenses"),
]
datas.extend(
    (str(path), "licenses/third_party")
    for path in sorted(license_dir.iterdir())
)
datas.extend(
    (str(path), "vendor/whisper.cpp/build/bin")
    for path in sorted(whisper_bin.iterdir())
)

a = Analysis(
    [str(project_root / "packaging/dicta_entry.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "AppKit",
        "ApplicationServices",
        "CoreFoundation",
        "Foundation",
        "PyObjCTools.MachSignals",
        "Quartz",
        "_sounddevice",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "sounddevice",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyObjCTest", "tkinter"],
    noarchive=False,
    optimize=0,
)

# sounddevice's cross-platform wheel contains Windows DLLs, including ASIO
# variants. They are unusable on macOS and should not be redistributed in Dicta.
a.datas = [entry for entry in a.datas if not entry[0].lower().endswith(".dll")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dicta",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Dicta",
)

app = BUNDLE(
    collection,
    name="Dicta.app",
    icon=str(icon),
    bundle_identifier="com.dicta.app",
    info_plist={
        "CFBundleDisplayName": "Dicta",
        "CFBundleGetInfoString": "Speak in Russian. Type in English.",
        "CFBundleName": "Dicta",
        "LSMinimumSystemVersion": "26.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": (
            "Dicta needs microphone access to convert your Russian speech "
            "into English text."
        ),
    },
)
