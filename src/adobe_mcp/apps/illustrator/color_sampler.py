"""Sample RGB color values from a reference image at specific positions or auto-grid.

Pure Python implementation using OpenCV. Loads the image, samples at given pixel
positions (or generates a 5x5 grid if positions="grid"), averages pixel values
within the specified radius, and returns a JSON array of color samples.
"""

import json
import os

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.models import AiColorSamplerInput


def _sample_at_position(
    img: np.ndarray,
    x: int,
    y: int,
    radius: int,
) -> dict:
    """Sample a region centered at (x, y) with the given radius and return averaged RGB + hex."""
    h, w = img.shape[:2]

    # Clamp the sampling window to image bounds
    x1 = max(0, x - radius)
    y1 = max(0, y - radius)
    x2 = min(w, x + radius + 1)
    y2 = min(h, y + radius + 1)

    if x1 >= x2 or y1 >= y2:
        # Fallback to single pixel if radius results in empty window
        x1, y1, x2, y2 = max(0, min(x, w - 1)), max(0, min(y, h - 1)), max(0, min(x, w - 1)) + 1, max(0, min(y, h - 1)) + 1

    region = img[y1:y2, x1:x2]
    # OpenCV stores as BGR, convert average to RGB
    avg_bgr = region.mean(axis=(0, 1))
    r = int(round(avg_bgr[2]))
    g = int(round(avg_bgr[1]))
    b = int(round(avg_bgr[0]))

    hex_color = f"#{r:02x}{g:02x}{b:02x}"

    return {
        "x": x,
        "y": y,
        "r": r,
        "g": g,
        "b": b,
        "hex": hex_color,
    }


def _generate_grid_positions(img_w: int, img_h: int, grid_size: int = 5) -> list[list[int]]:
    """Generate a grid_size x grid_size grid of evenly-spaced sample positions.

    Points are placed at the center of each grid cell to avoid edge artifacts.
    """
    positions = []
    step_x = img_w / grid_size
    step_y = img_h / grid_size

    for row in range(grid_size):
        for col in range(grid_size):
            x = int(step_x * col + step_x / 2)
            y = int(step_y * row + step_y / 2)
            positions.append([x, y])

    return positions


def register(mcp):
    """Register the adobe_ai_color_sampler tool."""

    @mcp.tool(
        name="adobe_ai_color_sampler",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_color_sampler(params: AiColorSamplerInput) -> str:
        """Sample RGB color values from a reference image at specific positions.

        Provide explicit [x, y] pixel positions as a JSON array, or pass "grid"
        to auto-sample at a 5x5 grid across the image. Each sample averages
        pixels within the specified radius for noise resistance.

        Returns a JSON array of {x, y, r, g, b, hex} color samples.
        """
        # Validate image exists
        if not os.path.isfile(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        img = cv2.imread(params.image_path)
        if img is None:
            return json.dumps({"error": f"Could not decode image: {params.image_path}"})

        img_h, img_w = img.shape[:2]

        # Determine sample positions
        if params.positions.strip().lower() == "grid":
            positions = _generate_grid_positions(img_w, img_h, grid_size=5)
        else:
            try:
                positions = json.loads(params.positions)
            except (json.JSONDecodeError, TypeError) as exc:
                return json.dumps({"error": f"Invalid positions JSON: {exc}"})

            if not isinstance(positions, list):
                return json.dumps({"error": "positions must be a JSON array of [x, y] pairs or 'grid'"})

        # Sample at each position
        samples = []
        for pos in positions:
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                continue

            x, y = int(pos[0]), int(pos[1])

            # Skip positions outside image bounds
            if x < 0 or x >= img_w or y < 0 or y >= img_h:
                samples.append({
                    "x": x,
                    "y": y,
                    "error": "position outside image bounds",
                })
                continue

            sample = _sample_at_position(img, x, y, params.radius)
            samples.append(sample)

        return json.dumps({
            "image_size": [img_w, img_h],
            "sample_count": len(samples),
            "radius": params.radius,
            "samples": samples,
        }, indent=2)
