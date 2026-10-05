"""Generate a standard macOS .icns file from Dicta's source PNG."""

from pathlib import Path
import shutil
import struct
import subprocess


ICON_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)

ICNS_REPRESENTATIONS = (
    (b"icp4", "icon_16x16.png"),
    (b"icp5", "icon_32x32.png"),
    (b"icp6", "icon_32x32@2x.png"),
    (b"ic07", "icon_128x128.png"),
    (b"ic08", "icon_128x128@2x.png"),
    (b"ic09", "icon_256x256@2x.png"),
    (b"ic10", "icon_512x512@2x.png"),
)


def _add_alpha_channel(path: Path, size: int) -> None:
    """Render a PNG into an RGBA bitmap required by iconutil."""
    from AppKit import (
        NSBitmapImageFileTypePNG,
        NSBitmapImageRep,
        NSCalibratedRGBColorSpace,
        NSCompositingOperationCopy,
        NSGraphicsContext,
        NSImage,
        NSZeroRect,
    )

    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        size,
        size,
        8,
        4,
        True,
        False,
        NSCalibratedRGBColorSpace,
        0,
        0,
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(context)
        image.drawInRect_fromRect_operation_fraction_(
            ((0, 0), (size, size)),
            NSZeroRect,
            NSCompositingOperationCopy,
            1.0,
        )
    finally:
        NSGraphicsContext.restoreGraphicsState()

    data = bitmap.representationUsingType_properties_(
        NSBitmapImageFileTypePNG, {}
    )
    if not data.writeToFile_atomically_(str(path), True):
        raise RuntimeError(f"Could not add an alpha channel to {path}")


def _write_modern_icns(iconset: Path, output: Path) -> None:
    """Write modern PNG-backed ICNS chunks when iconutil cannot pack them."""
    chunks = []
    for chunk_type, filename in ICNS_REPRESENTATIONS:
        png_data = (iconset / filename).read_bytes()
        chunks.append(
            chunk_type + struct.pack(">I", len(png_data) + 8) + png_data
        )
    body = b"".join(chunks)
    output.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def generate_icon(source: Path, output: Path, iconset: Path) -> None:
    """Validate the source and create the iconset and compiled ICNS."""
    details = subprocess.run(
        [
            "sips",
            "-g",
            "pixelWidth",
            "-g",
            "pixelHeight",
            "-g",
            "format",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "format: png" not in details.lower():
        raise RuntimeError(f"The icon source is not a PNG: {source}")

    dimensions = {}
    for line in details.splitlines():
        if ":" in line:
            key, value = line.strip().split(":", 1)
            dimensions[key] = value.strip()
    width = int(dimensions["pixelWidth"])
    height = int(dimensions["pixelHeight"])
    if width != height or width < 1024:
        raise RuntimeError(
            f"The icon must be square and at least 1024 px; got {width}x{height}."
        )

    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    for filename, size in ICON_SIZES:
        generated_path = iconset / filename
        subprocess.run(
            [
                "sips",
                "-z",
                str(size),
                str(size),
                str(source),
                "--out",
                str(generated_path),
            ],
            check=True,
            capture_output=True,
        )
        _add_alpha_channel(generated_path, size)

    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        _write_modern_icns(iconset, output)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    generate_icon(
        project_root / "assets/dicta-icon.png",
        project_root / "build/packaging/Dicta.icns",
        project_root / "build/packaging/Dicta.iconset",
    )
