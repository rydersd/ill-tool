"""Photoshop-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.enums import ColorSpace, ImageFormat, PhotoshopBlendMode


class PsNewDocInput(BaseModel):
    """Create a new Photoshop document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    width: int = Field(..., description="Width in pixels", ge=1, le=300000)
    height: int = Field(..., description="Height in pixels", ge=1, le=300000)
    resolution: int = Field(default=300, description="Resolution in PPI", ge=1, le=10000)
    name: str = Field(default="Untitled", description="Document name")
    color_mode: ColorSpace = Field(default=ColorSpace.RGB, description="Color mode")
    bit_depth: int = Field(default=8, description="Bit depth (8, 16, or 32)", ge=8, le=32)
    background: str = Field(default="WHITE", description="Background: WHITE, BLACK, TRANSPARENT")


class PsLayerInput(BaseModel):
    """Manipulate Photoshop layers."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create, delete, rename, duplicate, merge, flatten, hide, show, reorder, set_opacity, set_blendmode, list, move, resize, get_info")
    layer_name: Optional[str] = Field(default=None, description="Target layer name")
    new_name: Optional[str] = Field(default=None, description="New name for rename action")
    opacity: Optional[float] = Field(default=None, description="Opacity 0-100", ge=0, le=100)
    blend_mode: Optional[PhotoshopBlendMode] = Field(default=None, description="Blend mode")
    position: Optional[int] = Field(default=None, description="Position index for reorder")
    # Spatial operations (for move/resize/get_info actions)
    dx: Optional[float] = Field(default=None, description="Horizontal translation in pixels (for move)")
    dy: Optional[float] = Field(default=None, description="Vertical translation in pixels (for move)")
    scale_x: Optional[float] = Field(default=None, description="Horizontal scale % (for resize)", ge=1)
    scale_y: Optional[float] = Field(default=None, description="Vertical scale % (for resize)", ge=1)


class PsFilterInput(BaseModel):
    """Apply Photoshop filters."""
    model_config = ConfigDict(str_strip_whitespace=True)
    filter_name: str = Field(..., description="Filter: gaussianBlur, unsharpMask, motionBlur, radialBlur, smartSharpen, noise, median, highPass, emboss, findEdges, oilPaint")
    amount: Optional[float] = Field(default=None, description="Filter amount/radius")
    threshold: Optional[float] = Field(default=None, description="Filter threshold")
    angle: Optional[float] = Field(default=None, description="Angle for directional filters")


class PsSelectionInput(BaseModel):
    """Create/modify selections in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: select_all, deselect, inverse, rect, ellipse, color_range, feather, expand, contract, smooth, by_layer")
    x: Optional[int] = Field(default=None, description="X coordinate")
    y: Optional[int] = Field(default=None, description="Y coordinate")
    width: Optional[int] = Field(default=None, description="Width")
    height: Optional[int] = Field(default=None, description="Height")
    feather: Optional[float] = Field(default=0, description="Feather radius", ge=0)
    tolerance: Optional[int] = Field(default=None, description="Color range tolerance", ge=0, le=255)


class PsTransformInput(BaseModel):
    """Transform operations in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: resize_canvas, resize_image, rotate, flip_horizontal, flip_vertical, crop, trim, auto_crop")
    width: Optional[int] = Field(default=None, description="Width in pixels")
    height: Optional[int] = Field(default=None, description="Height in pixels")
    angle: Optional[float] = Field(default=None, description="Rotation angle in degrees")
    resolution: Optional[int] = Field(default=None, description="Resolution PPI")
    resample: Optional[str] = Field(default="BICUBIC", description="Resample: BICUBIC, BILINEAR, NEARESTNEIGHBOR, BICUBICSHARPER, BICUBICSMOOTHER")
    x: Optional[int] = Field(default=None, description="X for crop")
    y: Optional[int] = Field(default=None, description="Y for crop")


class PsAdjustmentInput(BaseModel):
    """Color/tone adjustments in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    adjustment: str = Field(..., description="Adjustment: brightness_contrast, levels, curves, hue_saturation, color_balance, vibrance, exposure, invert, desaturate, auto_tone, auto_contrast, auto_color, black_and_white, posterize, threshold, gradient_map, channel_mixer")
    brightness: Optional[int] = Field(default=None, description="Brightness -150 to 150", ge=-150, le=150)
    contrast: Optional[int] = Field(default=None, description="Contrast -100 to 100", ge=-100, le=100)
    hue: Optional[int] = Field(default=None, description="Hue -180 to 180", ge=-180, le=180)
    saturation: Optional[int] = Field(default=None, description="Saturation -100 to 100", ge=-100, le=100)
    lightness: Optional[int] = Field(default=None, description="Lightness -100 to 100", ge=-100, le=100)
    exposure: Optional[float] = Field(default=None, description="Exposure value")
    vibrance: Optional[int] = Field(default=None, description="Vibrance -100 to 100", ge=-100, le=100)


class PsTextInput(BaseModel):
    """Add/edit text in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="create", description="Action: create (new text layer) or edit (modify existing)")
    layer_name: Optional[str] = Field(default=None, description="Target text layer name (required for edit action)")
    text: Optional[str] = Field(default=None, description="Text content (required for create, optional for edit)")
    x: int = Field(default=0, description="X position")
    y: int = Field(default=0, description="Y position")
    font: Optional[str] = Field(default="ArialMT", description="Font postscript name")
    size: Optional[float] = Field(default=24, description="Font size in points", ge=1)
    color_r: Optional[int] = Field(default=0, description="Red 0-255", ge=0, le=255)
    color_g: Optional[int] = Field(default=0, description="Green 0-255", ge=0, le=255)
    color_b: Optional[int] = Field(default=0, description="Blue 0-255", ge=0, le=255)
    anti_alias: Optional[str] = Field(default="SHARP", description="NONE, SHARP, CRISP, STRONG, SMOOTH")
    justification: Optional[str] = Field(default="LEFT", description="LEFT, CENTER, RIGHT")


class PsExportInput(BaseModel):
    """Export Photoshop document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Output file path", min_length=1)
    format: ImageFormat = Field(default=ImageFormat.PNG, description="Export format")
    quality: Optional[int] = Field(default=100, description="JPEG quality 0-100", ge=0, le=100)
    resize_width: Optional[int] = Field(default=None, description="Resize width on export")
    resize_height: Optional[int] = Field(default=None, description="Resize height on export")


class PsBatchInput(BaseModel):
    """Batch process multiple files in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    input_folder: str = Field(..., description="Folder containing input files")
    output_folder: str = Field(..., description="Folder for output files")
    jsx_code: str = Field(..., description="JSX code to run on each open document")
    format: ImageFormat = Field(default=ImageFormat.PNG, description="Output format")
    file_filter: Optional[str] = Field(default="*.psd;*.png;*.jpg;*.tiff", description="File filter pattern")


class PsActionInput(BaseModel):
    """Run a Photoshop Action."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action_name: str = Field(..., description="Action name to run")
    action_set: str = Field(..., description="Action set containing the action")


class PsInspectInput(BaseModel):
    """Inspect Photoshop document — full layer tree, layer details, text contents, selection bounds."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: list_all, get_layer, get_selection_bounds, get_text")
    layer_name: Optional[str] = Field(default=None, description="Target layer name for get_layer/get_text")


class PsGroupInput(BaseModel):
    """Manage Photoshop layer groups (layer sets)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: list, create, add_layer, ungroup")
    group_name: Optional[str] = Field(default=None, description="Target group name")
    layer_name: Optional[str] = Field(default=None, description="Layer to add to group (for add_layer)")
    new_name: Optional[str] = Field(default=None, description="Name for new group (for create)")


class PsSmartObjectInput(BaseModel):
    """Smart Object operations in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: convert_to, edit_contents, rasterize, replace_contents, export_contents")
    layer_name: Optional[str] = Field(default=None, description="Target layer name")
    file_path: Optional[str] = Field(default=None, description="File path for replace/export")
