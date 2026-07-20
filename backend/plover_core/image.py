from __future__ import annotations

from io import BytesIO

from .detection import grayscale_dhash


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

