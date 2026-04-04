"""Auto-create or resize an Illustrator artboard to match a reference image's aspect ratio.

Pipeline:
1. Read image dimensions with cv2 (shape only — no heavy processing)
2. Calculate target height from aspect ratio
3. Add margin on all sides
4. Via JSX: resize the active artboard or create a new document if none open
"""

import json
import os

import cv2

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiArtboardFromRefInput


def register(mcp):
    """Register the adobe_ai_artboard_from_ref tool."""

    @mcp.tool(
        name="adobe_ai_artboard_from_ref",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_artboard_from_ref(params: AiArtboardFromRefInput) -> str:
        """Create or resize the active artboard to match a reference image's aspect ratio.

        Reads image dimensions from the file, computes the target height to
        preserve the aspect ratio at the requested width, adds margin on all
        sides, then resizes the active artboard via JSX.

        Returns: artboard dimensions, aspect ratio, source image dimensions.
        """
        image_path = params.image_path
        target_width = params.target_width
        margin = params.margin

        # -----------------------------------------------------------
        # Step 1: Validate the image exists and read dimensions
        # -----------------------------------------------------------
        if not os.path.isfile(image_path):
            return json.dumps({"error": f"Image file not found: {image_path}"})

        img = cv2.imread(image_path)
        if img is None:
            return json.dumps({"error": f"Could not read image (corrupt or unsupported format): {image_path}"})

        img_h, img_w = img.shape[:2]

        if img_w == 0 or img_h == 0:
            return json.dumps({"error": f"Image has zero dimension: {img_w}x{img_h}"})

        # -----------------------------------------------------------
        # Step 2: Calculate target artboard dimensions
        # -----------------------------------------------------------
        aspect_ratio = img_h / img_w
        target_height = target_width * aspect_ratio

        # Total artboard size including margin on all sides
        total_width = target_width + 2 * margin
        total_height = target_height + 2 * margin

        # Round to clean values for artboard coordinates
        total_width = round(total_width, 2)
        total_height = round(total_height, 2)

        # -----------------------------------------------------------
        # Step 3: Resize the active artboard via JSX
        # -----------------------------------------------------------
        # Illustrator artboardRect is [left, top, right, bottom]
        # where top > bottom (Y axis is inverted from screen coords)
        jsx = f"""
(function() {{
    var doc;
    try {{
        doc = app.activeDocument;
    }} catch(e) {{
        // No document open — create one
        var preset = new DocumentPreset();
        preset.width = {total_width};
        preset.height = {total_height};
        preset.colorMode = DocumentColorSpace.RGB;
        doc = app.documents.addDocument("Print", preset);
    }}

    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx];

    // Set artboard rect: [left, top, right, bottom]
    // Origin at top-left, Y increases downward in artboard coords
    ab.artboardRect = [0, {total_height}, {total_width}, 0];

    JSON.stringify({{
        artboard_index: abIdx,
        artboard_width: {total_width},
        artboard_height: {total_height},
        image_area_width: {round(target_width, 2)},
        image_area_height: {round(target_height, 2)},
        margin: {margin},
        aspect_ratio: {round(aspect_ratio, 4)},
        source_image_width: {img_w},
        source_image_height: {img_h}
    }});
}})();
"""
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
