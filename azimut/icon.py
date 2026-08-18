from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw


SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def create_icon(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    master = _draw_master(2048)
    images = [master.resize((size, size), Image.Resampling.LANCZOS) for size in reversed(SIZES)]
    _write_ico(path, images)
    images[0].save(path.with_suffix(".png"), format="PNG")
    return path


def _write_ico(path: Path, images: list[Image.Image]) -> None:
    blobs = []
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        blobs.append(buffer.getvalue())
    offset = 6 + 16 * len(images)
    parts = [struct.pack("<HHH", 0, 1, len(images))]
    payload = b""
    for image, blob in zip(images, blobs):
        width = 0 if image.width >= 256 else image.width
        height = 0 if image.height >= 256 else image.height
        parts.append(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset))
        payload += blob
        offset += len(blob)
    path.write_bytes(b"".join(parts) + payload)


def _draw_master(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    cx = cy = size / 2

    pad = int(size * 0.06)
    draw.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=(10, 16, 24, 255))

    ring = max(8, size // 11)
    draw.ellipse(
        (pad, pad, size - pad - 1, size - pad - 1),
        outline=(58, 168, 255, 255),
        width=ring,
    )

    inner = pad + ring + int(size * 0.02)
    draw.ellipse(
        (inner, inner, size - inner - 1, size - inner - 1),
        outline=(30, 48, 64, 255),
        width=max(4, size // 80),
    )

    north = size * 0.33
    south = size * 0.26
    half = size * 0.10
    draw.polygon(
        [
            (cx, cy - north),
            (cx + half, cy + size * 0.04),
            (cx, cy + size * 0.02),
            (cx - half, cy + size * 0.04),
        ],
        fill=(58, 168, 255, 255),
    )
    draw.polygon(
        [
            (cx, cy + south),
            (cx + half * 0.72, cy),
            (cx, cy - size * 0.01),
            (cx - half * 0.72, cy),
        ],
        fill=(236, 242, 248, 255),
    )

    hub = size * 0.09
    draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=(236, 242, 248, 255))
    core = size * 0.04
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=(58, 168, 255, 255))
    return image
