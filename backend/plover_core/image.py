from __future__ import annotations

from io import BytesIO

from .detection import grayscale_dhash


def normalize_screenshot_png(image_bytes: bytes, *, width: int, height: int) -> bytes:
    """Re-encode a screenshot as a PNG with the requested display dimensions."""
    if width <= 0 or height <= 0:
        raise ValueError("screenshot dimensions must be positive")
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - dependency is declared
        raise RuntimeError("Pillow is required to normalize screenshots") from error

    with Image.open(BytesIO(image_bytes)) as image:
        normalized = image.convert("RGB")
        if normalized.size != (width, height):
            normalized = normalized.resize((width, height), Image.Resampling.LANCZOS)
        output = BytesIO()
        normalized.save(output, format="PNG")
    return output.getvalue()


def dhash_from_image_bytes(image_bytes: bytes) -> int:
    """Compute the paper's dHash from an encoded screenshot."""
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - dependency is declared
        raise RuntimeError("Pillow is required for screenshot dHash") from error

    with Image.open(BytesIO(image_bytes)) as image:
        grayscale = image.convert("L").resize((9, 8))
        pixels = [
            [grayscale.getpixel((column, row)) for column in range(9)]
            for row in range(8)
        ]
    return grayscale_dhash(pixels)
