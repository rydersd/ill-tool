"""Illustrator-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AiNewDocInput(BaseModel):
    """Create new Illustrator document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    width: float = Field(default=800, description="Width in points", ge=1)
    height: float = Field(default=600, description="Height in points", ge=1)
    name: str = Field(default="Untitled", description="Document name")
    color_mode: Optional[str] = Field(default="RGB", description="RGB or CMYK")
    artboard_count: int = Field(default=1, description="Number of artboards", ge=1, le=1000)


class AiShapeInput(BaseModel):
    """Create shapes in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    shape: str = Field(..., description="Shape: rectangle, ellipse, polygon, star, line, arc, spiral")
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    width: Optional[float] = Field(default=100, description="Width")
    height: Optional[float] = Field(default=100, description="Height")
    sides: Optional[int] = Field(default=5, description="Sides for polygon")
    points: Optional[int] = Field(default=5, description="Points for star")
    fill_r: Optional[int] = Field(default=None, ge=0, le=255, description="Fill red")
    fill_g: Optional[int] = Field(default=None, ge=0, le=255, description="Fill green")
    fill_b: Optional[int] = Field(default=None, ge=0, le=255, description="Fill blue")
    stroke_r: Optional[int] = Field(default=0, ge=0, le=255, description="Stroke red")
    stroke_g: Optional[int] = Field(default=0, ge=0, le=255, description="Stroke green")
    stroke_b: Optional[int] = Field(default=0, ge=0, le=255, description="Stroke blue")
    stroke_width: Optional[float] = Field(default=1, description="Stroke width", ge=0)


class AiTextInput(BaseModel):
    """Add text in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(..., description="Text content")
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    font: Optional[str] = Field(default="ArialMT", description="Font name")
    size: Optional[float] = Field(default=24, description="Font size in points")
    color_r: Optional[int] = Field(default=0, ge=0, le=255)
    color_g: Optional[int] = Field(default=0, ge=0, le=255)
    color_b: Optional[int] = Field(default=0, ge=0, le=255)


class AiPathInput(BaseModel):
    """Create/manipulate paths in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create, join, offset, simplify, smooth, outline_stroke, expand, compound")
    points: Optional[str] = Field(default=None, description="JSON array of [x,y] points for create action")
    closed: bool = Field(default=False, description="Close the path")
    fill_r: Optional[int] = Field(default=None, ge=0, le=255)
    fill_g: Optional[int] = Field(default=None, ge=0, le=255)
    fill_b: Optional[int] = Field(default=None, ge=0, le=255)
    stroke_width: Optional[float] = Field(default=1, ge=0)


class AiExportInput(BaseModel):
    """Export Illustrator document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Output file path")
    format: str = Field(default="svg", description="Format: svg, png, pdf, eps, ai, jpg")
    artboard_index: Optional[int] = Field(default=None, description="Specific artboard to export")
    scale: Optional[float] = Field(default=1.0, description="Export scale factor")


class AiInspectInput(BaseModel):
    """Inspect Illustrator document — list items, layers, artboards, get details."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: list_all, list_layers, get_item, get_selection, get_artboards")
    name: Optional[str] = Field(default=None, description="Item name for get_item action")
    index: Optional[int] = Field(default=None, description="Item index for get_item action (0-based)")
    offset: Optional[int] = Field(default=0, description="Pagination offset for list_all", ge=0)
    limit: Optional[int] = Field(default=100, description="Max items to return for list_all", ge=1, le=500)


class AiModifyInput(BaseModel):
    """Modify existing Illustrator objects — move, resize, recolor, rename, delete, etc."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: select, move, resize, rotate, recolor_fill, recolor_stroke, rename, delete, opacity, arrange, duplicate, group, ungroup")
    name: Optional[str] = Field(default=None, description="Target item name (uses getByName)")
    index: Optional[int] = Field(default=None, description="Target item index (0-based, for unnamed items)")
    # Move params
    x: Optional[float] = Field(default=None, description="Absolute X position or delta X for move")
    y: Optional[float] = Field(default=None, description="Absolute Y position or delta Y for move")
    absolute: bool = Field(default=True, description="If true, x/y are absolute position; if false, they are deltas")
    # Resize params
    scale_x: Optional[float] = Field(default=None, description="Horizontal scale percentage for resize (100 = no change)", ge=1)
    scale_y: Optional[float] = Field(default=None, description="Vertical scale percentage for resize (100 = no change)", ge=1)
    # Rotate params
    angle: Optional[float] = Field(default=None, description="Rotation angle in degrees")
    # Color params
    fill_r: Optional[int] = Field(default=None, ge=0, le=255, description="Fill red (0-255)")
    fill_g: Optional[int] = Field(default=None, ge=0, le=255, description="Fill green (0-255)")
    fill_b: Optional[int] = Field(default=None, ge=0, le=255, description="Fill blue (0-255)")
    stroke_r: Optional[int] = Field(default=None, ge=0, le=255, description="Stroke red (0-255)")
    stroke_g: Optional[int] = Field(default=None, ge=0, le=255, description="Stroke green (0-255)")
    stroke_b: Optional[int] = Field(default=None, ge=0, le=255, description="Stroke blue (0-255)")
    stroke_width: Optional[float] = Field(default=None, ge=0, description="Stroke width in points")
    # Other params
    new_name: Optional[str] = Field(default=None, description="New name for rename action")
    opacity: Optional[float] = Field(default=None, ge=0, le=100, description="Opacity 0-100")
    arrange: Optional[str] = Field(default=None, description="Z-order: bring_to_front, bring_forward, send_backward, send_to_back")
    items: Optional[str] = Field(default=None, description="Comma-separated item names for group action")


class AiLayerInput(BaseModel):
    """Manage Illustrator layers — list, create, delete, rename, show, hide, lock, unlock, reorder."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: list, create, delete, rename, show, hide, lock, unlock, reorder")
    name: Optional[str] = Field(default=None, description="Layer name (for targeting existing layer)")
    new_name: Optional[str] = Field(default=None, description="New name for create/rename")
    target: Optional[str] = Field(default=None, description="Target layer name for reorder (place before this layer)")


class AiImageTraceInput(BaseModel):
    """Trace a raster image to vector paths in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    image_path: str = Field(..., description="Absolute path to PNG/JPG image file")
    preset: str = Field(
        default="6 Colors",
        description=(
            "Trace preset: '3 Colors', '6 Colors', '16 Colors', "
            "'High Fidelity Photo', 'Low Fidelity Photo', "
            "'Black and White Logo', 'Shades of Gray', "
            "'Silhouettes', 'Line Art', 'Technical Drawing'"
        ),
    )
    max_colors: Optional[int] = Field(
        default=None, description="Override preset max colors (2-256)", ge=2, le=256
    )
    expand: bool = Field(default=True, description="Expand trace to editable vector paths")
    recolor_to_dna: bool = Field(
        default=False,
        description="Recolor traced paths to current design token palette",
    )
    layer_name: Optional[str] = Field(default="traced", description="Name for the result group/layer")
    x: Optional[float] = Field(default=None, description="X position after tracing")
    y: Optional[float] = Field(default=None, description="Y position after tracing")


class AiAnalyzeReferenceInput(BaseModel):
    """Analyze a reference image for geometric form — returns measured shapes, not guesses."""
    model_config = ConfigDict(str_strip_whitespace=True)
    image_path: str = Field(..., description="Absolute path to reference PNG/JPG image")
    min_area_pct: float = Field(default=0.5, description="Ignore contours smaller than this % of image area", ge=0.01, le=50)
    max_contours: int = Field(default=20, description="Maximum number of shapes to return", ge=1, le=100)
    canny_low: int = Field(default=50, description="Canny edge detection low threshold", ge=1, le=255)
    canny_high: int = Field(default=150, description="Canny edge detection high threshold", ge=1, le=255)
    multi_scale: bool = Field(default=False, description="Run at 3 Canny thresholds and merge results with scale tags (bold/medium/fine)")
    decompose: bool = Field(default=False, description="Use RETR_TREE to detect parent-child nesting, suggest layer structure and z-order")


class AiReferenceUnderlayInput(BaseModel):
    """Place a reference image as a locked background layer in Illustrator for tracing."""
    model_config = ConfigDict(str_strip_whitespace=True)
    image_path: str = Field(..., description="Absolute path to reference PNG/JPG image")
    opacity: float = Field(default=40, description="Reference layer opacity 0-100", ge=0, le=100)
    fit_to_artboard: bool = Field(default=True, description="Scale image to fit current artboard")
    drawing_layer_name: str = Field(default="Drawing", description="Name for the active drawing layer above reference")


class AiVtraceInput(BaseModel):
    """Trace a raster image to clean vector paths using vtracer (better than Image Trace for cartoon/graphic art)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    image_path: str = Field(..., description="Absolute path to PNG/JPG image")
    mode: str = Field(default="polygon", description="Tracing mode: polygon or spline")
    color_precision: int = Field(default=6, description="Color quantization precision 1-8 (lower = fewer colors)", ge=1, le=8)
    filter_speckle: int = Field(default=4, description="Remove artifacts smaller than this many pixels", ge=0, le=100)
    corner_threshold: int = Field(default=60, description="Angle threshold for corner detection (degrees)", ge=0, le=180)
    path_precision: int = Field(default=3, description="Decimal places in SVG path coordinates", ge=1, le=8)
    place_in_ai: bool = Field(default=False, description="Place resulting paths directly in Illustrator")
    layer_name: str = Field(default="vtrace", description="Layer name when placing in Illustrator")


class AiAutoCorrectInput(BaseModel):
    """Closed-loop correction: compare drawing vs reference and apply anchor point adjustments automatically."""
    model_config = ConfigDict(str_strip_whitespace=True)
    reference_path: str = Field(..., description="Absolute path to reference PNG/JPG image")
    drawing_layer: str = Field(default="Drawing", description="Layer containing the drawing to correct")
    max_iterations: int = Field(default=1, description="Number of correction passes per call", ge=1, le=5)
    convergence_target: float = Field(default=0.85, description="Stop correcting when convergence exceeds this", ge=0, le=1)
    min_area_pct: float = Field(default=0.5, description="Ignore contours smaller than this % of image area", ge=0.01, le=50)
    correction_strength: float = Field(default=0.5, description="Damping factor 0-1 (1=full correction, 0.5=half step to avoid overshoot)", ge=0.1, le=1.0)


class AiAnchorEditInput(BaseModel):
    """Get or set individual anchor points and bezier handles on pathItems."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: get_points, set_point, set_handles, add_point, remove_point, simplify")
    name: Optional[str] = Field(default=None, description="Target pathItem name (uses getByName)")
    index: Optional[int] = Field(default=None, description="Target pathItem index (0-based, for unnamed items)")
    point_index: Optional[int] = Field(default=None, description="Anchor point index for set_point/set_handles/remove_point (0-based)")
    x: Optional[float] = Field(default=None, description="New X coordinate for set_point or add_point")
    y: Optional[float] = Field(default=None, description="New Y coordinate for set_point or add_point")
    left_x: Optional[float] = Field(default=None, description="Left bezier handle X for set_handles")
    left_y: Optional[float] = Field(default=None, description="Left bezier handle Y for set_handles")
    right_x: Optional[float] = Field(default=None, description="Right bezier handle X for set_handles")
    right_y: Optional[float] = Field(default=None, description="Right bezier handle Y for set_handles")
    tolerance: Optional[float] = Field(default=2.0, description="Simplification tolerance in points (for simplify action)", ge=0.1, le=50)


class AiProportionGridInput(BaseModel):
    """Place a measurement grid on the artboard based on reference analysis or manual key positions."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="from_manifest", description="Action: from_manifest (auto from shape data), manual (from positions), clear (remove grid)")
    shape_manifest: Optional[str] = Field(default=None, description="JSON shape manifest from analyze_reference (for from_manifest action)")
    h_positions: Optional[str] = Field(default=None, description="JSON array of Y positions as % of artboard height for manual horizontal guides")
    v_positions: Optional[str] = Field(default=None, description="JSON array of X positions as % of artboard width for manual vertical guides")
    show_bounding_boxes: bool = Field(default=True, description="Draw bounding rectangles for each shape in the manifest")
    grid_opacity: float = Field(default=30, description="Grid layer opacity 0-100", ge=0, le=100)


class AiSilhouetteInput(BaseModel):
    """Extract the overall silhouette from a reference image as a single clean closed path."""
    model_config = ConfigDict(str_strip_whitespace=True)
    image_path: str = Field(..., description="Absolute path to reference PNG/JPG image")
    simplification: float = Field(default=0.01, description="approxPolyDP epsilon as fraction of arc length (lower=more points, higher=simpler)", ge=0.001, le=0.1)
    place_in_ai: bool = Field(default=True, description="Place the silhouette path in Illustrator")
    layer_name: str = Field(default="Drawing", description="Layer to place the silhouette on")
    stroke_width: float = Field(default=2.0, description="Stroke width for the placed path", ge=0.1)


class AiStyleTransferInput(BaseModel):
    """Copy visual style (stroke, fill, opacity, effects) from one pathItem to others."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="transfer", description="Action: transfer (copy style), extract (get style JSON), apply (apply style JSON)")
    source_name: Optional[str] = Field(default=None, description="Source pathItem name to extract style from (for transfer/extract)")
    target_names: Optional[str] = Field(default=None, description="Comma-separated target pathItem names (for transfer/apply)")
    style_json: Optional[str] = Field(default=None, description="JSON style spec for apply action")
