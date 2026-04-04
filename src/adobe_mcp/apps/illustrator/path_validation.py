"""Path and image validation utilities.

Provides security-focused validation for file paths (traversal prevention)
and image dimensions (denial-of-service prevention).
"""

import os

import numpy as np


# ---------------------------------------------------------------------------
# Path traversal validation
# ---------------------------------------------------------------------------

def validate_safe_path(
    path: str,
    allowed_prefixes: list[str] | None = None,
) -> str:
    """Resolve and validate a file path against traversal attacks.

    - Resolves symlinks via os.path.realpath()
    - Rejects paths containing '..'
    - If allowed_prefixes given, checks resolved path starts with one
    - Returns resolved path or raises ValueError

    Args:
        path: The file path to validate.
        allowed_prefixes: Optional list of allowed directory prefixes.
            If provided, the resolved path must start with at least one.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the path fails validation.
    """
    if not path:
        raise ValueError("Path must not be empty")

    # Reject path traversal components before resolution
    if ".." in path.split(os.sep) or ".." in path.split("/"):
        raise ValueError(f"Path contains '..' traversal component: {path}")

    resolved = os.path.realpath(path)

    if allowed_prefixes is not None:
        resolved_prefix_match = any(
            resolved.startswith(os.path.realpath(prefix))
            for prefix in allowed_prefixes
        )
        if not resolved_prefix_match:
            raise ValueError(
                f"Path '{resolved}' is outside allowed directories: "
                f"{allowed_prefixes}"
            )

    return resolved


# ---------------------------------------------------------------------------
# Image size validation
# ---------------------------------------------------------------------------

MAX_IMAGE_DIM = 8192


def validate_image_size(
    img: np.ndarray,
    max_dim: int = MAX_IMAGE_DIM,
) -> None:
    """Validate that an image does not exceed maximum dimensions.

    Args:
        img: Image array with shape (H, W, ...) or (H, W).
        max_dim: Maximum allowed dimension for either height or width.

    Raises:
        ValueError: If either dimension exceeds max_dim.
    """
    h, w = img.shape[:2]
    if h > max_dim or w > max_dim:
        raise ValueError(
            f"Image too large ({w}x{h}), max {max_dim}x{max_dim}"
        )


def validate_image_path_size(
    image_path: str,
    max_dim: int = MAX_IMAGE_DIM,
) -> None:
    """Check image dimensions WITHOUT fully decoding the pixel data.

    Uses PIL to read only the image header, which is sufficient to
    determine width and height without allocating a full pixel buffer.
    This prevents denial-of-service from oversized images before any
    expensive decode (e.g. ``cv2.imread``) takes place.

    Args:
        image_path: Absolute path to the image file.
        max_dim: Maximum allowed dimension for either width or height.

    Raises:
        ValueError: If either dimension exceeds max_dim.
        FileNotFoundError: If the image file does not exist.
        PIL.UnidentifiedImageError: If the file is not a recognized image.
    """
    from PIL import Image

    with Image.open(image_path) as img:
        w, h = img.size  # reads header only, no full decode
        if w > max_dim or h > max_dim:
            raise ValueError(
                f"Image too large ({w}x{h}), max {max_dim}x{max_dim}"
            )
