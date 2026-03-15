#!/usr/bin/env python3
"""
Adobe MCP Server — Full automation for all Adobe Creative Cloud apps.

Provides Claude/Claude Code with complete control over:
- Adobe Photoshop (2026)
- Adobe Illustrator (30)
- Adobe Premiere Pro (26)
- Adobe After Effects (26)
- Adobe InDesign
- Adobe Animate (2024)
- Adobe Character Animator
- Adobe Media Encoder

Communication methods:
1. COM automation via PowerShell (Windows primary)
2. ExtendScript (.jsx) execution via command line
3. UXP plugin communication for modern apps
4. CEP panel scripting for legacy support
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Server Init ──────────────────────────────────────────────────────────

mcp = FastMCP("adobe_mcp")

# ── Constants ────────────────────────────────────────────────────────────

ADOBE_APPS = {
    "photoshop": {
        "com_id": "Photoshop.Application",
        "process": "Photoshop.exe",
        "extendscript": True,
        "jsx_target": "photoshop",
        "display": "Adobe Photoshop",
    },
    "illustrator": {
        "com_id": "Illustrator.Application",
        "process": "Illustrator.exe",
        "extendscript": True,
        "jsx_target": "illustrator",
        "display": "Adobe Illustrator",
    },
    "premierepro": {
        "com_id": "Premiere.Application",
        "process": "Adobe Premiere Pro.exe",
        "extendscript": True,
        "jsx_target": "premierepro",
        "display": "Adobe Premiere Pro",
    },
    "aftereffects": {
        "com_id": "AfterEffects.Application",
        "process": "AfterFX.exe",
        "extendscript": True,
        "jsx_target": "aftereffects",
        "display": "Adobe After Effects",
    },
    "indesign": {
        "com_id": "InDesign.Application",
        "process": "InDesign.exe",
        "extendscript": True,
        "jsx_target": "indesign",
        "display": "Adobe InDesign",
    },
    "animate": {
        "com_id": "Animate.Application",
        "process": "Animate.exe",
        "extendscript": True,
        "jsx_target": "animate",
        "display": "Adobe Animate",
    },
    "characteranimator": {
        "com_id": None,
        "process": "Character Animator.exe",
        "extendscript": False,
        "jsx_target": None,
        "display": "Adobe Character Animator",
    },
    "mediaencoder": {
        "com_id": "MediaEncoder.Application",
        "process": "Adobe Media Encoder.exe",
        "extendscript": True,
        "jsx_target": "ame",
        "display": "Adobe Media Encoder",
    },
}

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# ── Enums ────────────────────────────────────────────────────────────────


class AdobeApp(str, Enum):
    PHOTOSHOP = "photoshop"
    ILLUSTRATOR = "illustrator"
    PREMIEREPRO = "premierepro"
    AFTEREFFECTS = "aftereffects"
    INDESIGN = "indesign"
    ANIMATE = "animate"
    CHARACTERANIMATOR = "characteranimator"
    MEDIAENCODER = "mediaencoder"


class PhotoshopBlendMode(str, Enum):
    NORMAL = "NORMAL"
    MULTIPLY = "MULTIPLY"
    SCREEN = "SCREEN"
    OVERLAY = "OVERLAY"
    SOFTLIGHT = "SOFTLIGHT"
    HARDLIGHT = "HARDLIGHT"
    COLORDODGE = "COLORDODGE"
    COLORBURN = "COLORBURN"
    DARKEN = "DARKEN"
    LIGHTEN = "LIGHTEN"
    DIFFERENCE = "DIFFERENCE"
    EXCLUSION = "EXCLUSION"
    HUE = "HUE"
    SATURATION = "SATURATIONBLEND"
    COLOR = "COLORBLEND"
    LUMINOSITY = "LUMINOSITY"
    DISSOLVE = "DISSOLVE"


class ImageFormat(str, Enum):
    PNG = "png"
    JPEG = "jpeg"
    PSD = "psd"
    TIFF = "tiff"
    BMP = "bmp"
    GIF = "gif"
    PDF = "pdf"
    SVG = "svg"
    EPS = "eps"
    WEBP = "webp"


class ColorSpace(str, Enum):
    RGB = "RGB"
    CMYK = "CMYK"
    LAB = "LAB"
    GRAYSCALE = "GRAYSCALE"


# ── Core Execution Engine ────────────────────────────────────────────────


def _run_powershell(script: str, timeout: int = 120) -> dict:
    """Execute a PowerShell script and return stdout/stderr/returncode."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout expired", "returncode": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "powershell.exe not found", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


def _run_jsx(app: str, jsx_code: str, timeout: int = 120) -> dict:
    """Execute ExtendScript JSX code in the target Adobe app via COM."""
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    # Escape the JSX for PowerShell embedding
    escaped_jsx = jsx_code.replace("'", "''").replace('"', '`"')

    ps_script = f"""
$app = New-Object -ComObject '{app_info["com_id"]}'
$jsx = @'
{jsx_code}
'@
try {{
    $result = $app.DoJavaScript($jsx)
    Write-Output $result
}} catch {{
    Write-Error $_.Exception.Message
}}
"""
    return _run_powershell(ps_script, timeout)


def _run_jsx_file(app: str, jsx_path: str, timeout: int = 120) -> dict:
    """Execute a .jsx file in the target Adobe app."""
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    ps_script = f"""
$app = New-Object -ComObject '{app_info["com_id"]}'
try {{
    $result = $app.DoJavaScriptFile('{jsx_path}')
    Write-Output $result
}} catch {{
    Write-Error $_.Exception.Message
}}
"""
    return _run_powershell(ps_script, timeout)


async def _async_run_jsx(app: str, jsx_code: str, timeout: int = 120) -> dict:
    """Async wrapper for JSX execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_jsx, app, jsx_code, timeout)


async def _async_run_powershell(script: str, timeout: int = 120) -> dict:
    """Async wrapper for PowerShell execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_powershell, script, timeout)


# ── Input Models ─────────────────────────────────────────────────────────


class AppStatusInput(BaseModel):
    """Check if an Adobe app is running."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Adobe application to check")


class RunJSXInput(BaseModel):
    """Execute arbitrary ExtendScript/JSX code in any Adobe app."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    code: str = Field(..., description="ExtendScript/JSX code to execute", min_length=1)
    timeout: Optional[int] = Field(default=120, description="Timeout in seconds", ge=5, le=600)


class RunJSXFileInput(BaseModel):
    """Execute a .jsx file in an Adobe app."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    file_path: str = Field(..., description="Full path to the .jsx file", min_length=1)
    timeout: Optional[int] = Field(default=120, description="Timeout in seconds", ge=5, le=600)


class LaunchAppInput(BaseModel):
    """Launch an Adobe application."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Adobe application to launch")


class OpenFileInput(BaseModel):
    """Open a file in an Adobe application."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    file_path: str = Field(..., description="Full path to the file to open", min_length=1)


class SaveFileInput(BaseModel):
    """Save the active document in an Adobe application."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    file_path: Optional[str] = Field(default=None, description="Save path (None = save in place)")
    format: Optional[ImageFormat] = Field(default=None, description="Export format")


class CloseDocInput(BaseModel):
    """Close a document in an Adobe app."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    save: bool = Field(default=True, description="Save before closing")


# ── Photoshop-Specific Models ────────────────────────────────────────────


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
    action: str = Field(..., description="Action: create, delete, rename, duplicate, merge, flatten, hide, show, reorder, set_opacity, set_blendmode")
    layer_name: Optional[str] = Field(default=None, description="Target layer name")
    new_name: Optional[str] = Field(default=None, description="New name for rename action")
    opacity: Optional[float] = Field(default=None, description="Opacity 0-100", ge=0, le=100)
    blend_mode: Optional[PhotoshopBlendMode] = Field(default=None, description="Blend mode")
    position: Optional[int] = Field(default=None, description="Position index for reorder")


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
    text: str = Field(..., description="Text content", min_length=1)
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


class PsSmartObjectInput(BaseModel):
    """Smart Object operations in Photoshop."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: convert_to, edit_contents, rasterize, replace_contents, export_contents")
    layer_name: Optional[str] = Field(default=None, description="Target layer name")
    file_path: Optional[str] = Field(default=None, description="File path for replace/export")


# ── Illustrator-Specific Models ──────────────────────────────────────────


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


# ── Premiere Pro Models ──────────────────────────────────────────────────


class PrProjectInput(BaseModel):
    """Premiere Pro project operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: new, open, save, save_as, close, get_info")
    file_path: Optional[str] = Field(default=None, description="Project file path")
    name: Optional[str] = Field(default=None, description="Project name")


class PrSequenceInput(BaseModel):
    """Premiere Pro sequence operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create, delete, duplicate, get_info, list, set_active, set_in_out, clear_in_out")
    name: Optional[str] = Field(default=None, description="Sequence name")
    width: Optional[int] = Field(default=1920, description="Sequence width")
    height: Optional[int] = Field(default=1080, description="Sequence height")
    framerate: Optional[float] = Field(default=29.97, description="Frame rate")
    preset: Optional[str] = Field(default=None, description="Sequence preset name")


class PrMediaInput(BaseModel):
    """Import/manage media in Premiere Pro."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: import, import_folder, list_bin, create_bin, move_to_bin, get_clip_info, set_in_out")
    file_paths: Optional[str] = Field(default=None, description="JSON array of file paths to import")
    folder_path: Optional[str] = Field(default=None, description="Folder to import")
    bin_name: Optional[str] = Field(default=None, description="Target bin name")
    clip_name: Optional[str] = Field(default=None, description="Clip name")


class PrTimelineInput(BaseModel):
    """Premiere Pro timeline editing operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: insert, overwrite, ripple_delete, razor, lift, extract, move_clip, trim, add_transition, set_clip_speed, nest, unlink")
    clip_name: Optional[str] = Field(default=None, description="Source clip name")
    track_index: Optional[int] = Field(default=0, description="Track index (0-based)")
    start_time: Optional[float] = Field(default=None, description="Start time in seconds")
    end_time: Optional[float] = Field(default=None, description="End time in seconds")
    duration: Optional[float] = Field(default=None, description="Duration in seconds")
    transition: Optional[str] = Field(default=None, description="Transition name")
    speed: Optional[float] = Field(default=None, description="Speed percentage")


class PrExportInput(BaseModel):
    """Export from Premiere Pro."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Output file path")
    preset: Optional[str] = Field(default="H.264 - Match Source - High bitrate", description="AME export preset")
    format: Optional[str] = Field(default="H.264", description="Export format")
    use_ame: bool = Field(default=True, description="Use Adobe Media Encoder queue")
    in_point: Optional[float] = Field(default=None, description="In point seconds")
    out_point: Optional[float] = Field(default=None, description="Out point seconds")


class PrEffectInput(BaseModel):
    """Apply effects in Premiere Pro."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: apply, remove, list, get_params, set_param, add_keyframe")
    effect_name: Optional[str] = Field(default=None, description="Effect name")
    clip_name: Optional[str] = Field(default=None, description="Target clip")
    track_index: Optional[int] = Field(default=0, description="Track index")
    param_name: Optional[str] = Field(default=None, description="Effect parameter name")
    param_value: Optional[str] = Field(default=None, description="Parameter value")
    time: Optional[float] = Field(default=None, description="Keyframe time in seconds")


# ── After Effects Models ─────────────────────────────────────────────────


class AeCompInput(BaseModel):
    """After Effects composition operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create, duplicate, delete, get_info, list, set_active")
    name: Optional[str] = Field(default=None, description="Composition name")
    width: Optional[int] = Field(default=1920, description="Width", ge=1)
    height: Optional[int] = Field(default=1080, description="Height", ge=1)
    duration: Optional[float] = Field(default=10, description="Duration in seconds")
    framerate: Optional[float] = Field(default=29.97, description="Frame rate")


class AeLayerInput(BaseModel):
    """After Effects layer operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: add_solid, add_text, add_shape, add_null, add_adjustment, add_camera, add_light, add_media, duplicate, delete, rename, set_parent, precompose, enable, disable, solo, shy, lock, collapse")
    comp_name: Optional[str] = Field(default=None, description="Target composition")
    layer_name: Optional[str] = Field(default=None, description="Layer name/index")
    new_name: Optional[str] = Field(default=None, description="New name")
    file_path: Optional[str] = Field(default=None, description="Media file path for add_media")
    color_r: Optional[int] = Field(default=128, ge=0, le=255)
    color_g: Optional[int] = Field(default=128, ge=0, le=255)
    color_b: Optional[int] = Field(default=128, ge=0, le=255)
    text: Optional[str] = Field(default=None, description="Text content for text layers")
    width: Optional[int] = Field(default=None, description="Solid/shape width")
    height: Optional[int] = Field(default=None, description="Solid/shape height")


class AePropertyInput(BaseModel):
    """Set After Effects layer properties (transform, effects, etc)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    comp_name: Optional[str] = Field(default=None, description="Composition name")
    layer_name: str = Field(..., description="Layer name or index")
    property_path: str = Field(..., description="Property path e.g. 'Transform.Position', 'Transform.Opacity', 'Effects.Gaussian Blur.Blurriness'")
    value: str = Field(..., description="Value as JSON — number, array, or string")
    time: Optional[float] = Field(default=None, description="Time in seconds for keyframe (None = static)")


class AeExpressionInput(BaseModel):
    """Apply expressions to After Effects properties."""
    model_config = ConfigDict(str_strip_whitespace=True)
    comp_name: Optional[str] = Field(default=None, description="Composition name")
    layer_name: str = Field(..., description="Layer name or index")
    property_path: str = Field(..., description="Property path")
    expression: str = Field(..., description="Expression code")


class AeRenderInput(BaseModel):
    """Render After Effects composition."""
    model_config = ConfigDict(str_strip_whitespace=True)
    comp_name: Optional[str] = Field(default=None, description="Composition to render (None = active)")
    output_path: str = Field(..., description="Output file path")
    template: Optional[str] = Field(default=None, description="Render settings template")
    output_module: Optional[str] = Field(default=None, description="Output module template")


class AeEffectInput(BaseModel):
    """Apply effects to After Effects layers."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: apply, remove, list, enable, disable")
    comp_name: Optional[str] = Field(default=None, description="Composition name")
    layer_name: str = Field(..., description="Layer name or index")
    effect_name: Optional[str] = Field(default=None, description="Effect match name or display name")


# ── InDesign Models ──────────────────────────────────────────────────────


class IdDocInput(BaseModel):
    """InDesign document operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: new, open, save, save_as, close, export_pdf, export_epub, export_html, package, preflight, get_info")
    file_path: Optional[str] = Field(default=None, description="File path")
    width: Optional[float] = Field(default=None, description="Page width in points")
    height: Optional[float] = Field(default=None, description="Page height in points")
    pages: Optional[int] = Field(default=1, description="Number of pages")
    preset: Optional[str] = Field(default=None, description="Document/export preset")


class IdTextInput(BaseModel):
    """InDesign text operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create_frame, insert_text, format_text, find_replace, place_text, set_style, create_style, list_styles, apply_grep")
    page_index: Optional[int] = Field(default=0, description="Page index")
    x: Optional[float] = Field(default=None, description="X position")
    y: Optional[float] = Field(default=None, description="Y position")
    width: Optional[float] = Field(default=None, description="Frame width")
    height: Optional[float] = Field(default=None, description="Frame height")
    text: Optional[str] = Field(default=None, description="Text content")
    font: Optional[str] = Field(default=None, description="Font name")
    size: Optional[float] = Field(default=None, description="Font size")
    find_what: Optional[str] = Field(default=None, description="Find text")
    replace_with: Optional[str] = Field(default=None, description="Replace text")
    style_name: Optional[str] = Field(default=None, description="Paragraph/character style name")


class IdImageInput(BaseModel):
    """Place images in InDesign."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Image file path")
    page_index: Optional[int] = Field(default=0, description="Page index")
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    width: Optional[float] = Field(default=None, description="Frame width")
    height: Optional[float] = Field(default=None, description="Frame height")
    fit: Optional[str] = Field(default="proportionally", description="Fit: proportionally, fill, frame, center")


# ── Media Encoder Models ─────────────────────────────────────────────────


class AmeEncodeInput(BaseModel):
    """Adobe Media Encoder queue and encode."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: add_to_queue, start_queue, stop_queue, clear_queue, get_status, list_presets")
    source_path: Optional[str] = Field(default=None, description="Source file path")
    output_path: Optional[str] = Field(default=None, description="Output file path")
    preset: Optional[str] = Field(default=None, description="Encoding preset name")
    format: Optional[str] = Field(default=None, description="Output format")


# ── Animate Models ───────────────────────────────────────────────────────


class AnDocInput(BaseModel):
    """Adobe Animate document operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: new, open, save, save_as, close, publish, test_movie, get_info, export_swf, export_html5, export_video")
    file_path: Optional[str] = Field(default=None, description="File path")
    width: Optional[int] = Field(default=None, description="Stage width")
    height: Optional[int] = Field(default=None, description="Stage height")
    fps: Optional[float] = Field(default=None, description="Frame rate")
    doc_type: Optional[str] = Field(default="html5canvas", description="Document type: html5canvas, webgl, actionscript3, createjs")


class AnTimelineInput(BaseModel):
    """Animate timeline operations."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: add_frame, insert_keyframe, insert_blank_keyframe, remove_frame, create_motion_tween, create_shape_tween, create_classic_tween, add_layer, delete_layer, rename_layer, set_frame_label, goto_frame, extend_timeline")
    layer_name: Optional[str] = Field(default=None, description="Layer name")
    frame: Optional[int] = Field(default=None, description="Frame number")
    duration: Optional[int] = Field(default=None, description="Duration in frames")
    label: Optional[str] = Field(default=None, description="Frame label")


# ── Generic/Cross-App Models ─────────────────────────────────────────────


class RunPowerShellInput(BaseModel):
    """Execute arbitrary PowerShell for Adobe COM automation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    script: str = Field(..., description="PowerShell script to execute", min_length=1)
    timeout: Optional[int] = Field(default=120, description="Timeout in seconds", ge=5, le=600)


class GetDocInfoInput(BaseModel):
    """Get info about the active document in any Adobe app."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")


class ListFontsInput(BaseModel):
    """List available fonts in an Adobe app."""
    model_config = ConfigDict(str_strip_whitespace=True)
    app: AdobeApp = Field(..., description="Target Adobe application")
    filter: Optional[str] = Field(default=None, description="Filter fonts by name substring")


# ═══════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

# ── General / Cross-App Tools ────────────────────────────────────────────


@mcp.tool(
    name="adobe_list_apps",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_list_apps() -> str:
    """List all supported Adobe applications and their status (running/stopped)."""
    ps = """
$apps = @{}
$procs = Get-Process -ErrorAction SilentlyContinue | Select-Object -Property Name
$mapping = @{
    'Photoshop'='Photoshop'; 'Illustrator'='Illustrator';
    'Adobe Premiere Pro'='Premiere Pro'; 'AfterFX'='After Effects';
    'InDesign'='InDesign'; 'Animate'='Animate';
    'Character Animator'='Character Animator'; 'Adobe Media Encoder'='Media Encoder'
}
foreach ($key in $mapping.Keys) {
    $running = $procs | Where-Object { $_.Name -like "*$key*" }
    $apps[$mapping[$key]] = if ($running) { 'running' } else { 'stopped' }
}
$apps | ConvertTo-Json
"""
    result = await _async_run_powershell(ps)
    if result["success"]:
        return result["stdout"]
    return json.dumps({"apps": {v["display"]: "unknown" for v in ADOBE_APPS.values()}, "note": result["stderr"]})


@mcp.tool(
    name="adobe_app_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_app_status(params: AppStatusInput) -> str:
    """Check if a specific Adobe application is running and get its version."""
    info = ADOBE_APPS[params.app.value]
    ps = f"""
$proc = Get-Process -Name '{info["process"].replace(".exe", "")}' -ErrorAction SilentlyContinue
if ($proc) {{
    $version = $proc[0].FileVersion
    @{{ status='running'; version=$version; pid=$proc[0].Id }} | ConvertTo-Json
}} else {{
    @{{ status='stopped'; version=$null; pid=$null }} | ConvertTo-Json
}}
"""
    result = await _async_run_powershell(ps)
    return result["stdout"] if result["success"] else json.dumps({"status": "error", "error": result["stderr"]})


@mcp.tool(
    name="adobe_launch_app",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_launch_app(params: LaunchAppInput) -> str:
    """Launch an Adobe application if not already running."""
    info = ADOBE_APPS[params.app.value]
    if info["com_id"]:
        ps = f"""
try {{
    $app = New-Object -ComObject '{info["com_id"]}'
    @{{ success=$true; message='{info["display"]} launched/connected via COM' }} | ConvertTo-Json
}} catch {{
    # Fallback: start the process directly
    $paths = @(
        'C:\\Program Files\\Adobe\\*\\{info["process"]}',
        'C:\\Program Files\\Adobe\\*\\Support Files\\{info["process"]}'
    )
    $exe = Get-ChildItem -Path $paths -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) {{
        Start-Process $exe.FullName
        Start-Sleep -Seconds 3
        @{{ success=$true; message='{info["display"]} started via process' }} | ConvertTo-Json
    }} else {{
        @{{ success=$false; error='Could not find {info["process"]}' }} | ConvertTo-Json
    }}
}}
"""
    else:
        ps = f"""
$paths = @(
    'C:\\Program Files\\Adobe\\*\\{info["process"]}',
    'C:\\Program Files\\Adobe\\*\\Support Files\\{info["process"]}'
)
$exe = Get-ChildItem -Path $paths -ErrorAction SilentlyContinue | Select-Object -First 1
if ($exe) {{
    Start-Process $exe.FullName
    @{{ success=$true; message='{info["display"]} starting' }} | ConvertTo-Json
}} else {{
    @{{ success=$false; error='Could not find {info["process"]}' }} | ConvertTo-Json
}}
"""
    result = await _async_run_powershell(ps)
    return result["stdout"] if result["success"] else json.dumps({"success": False, "error": result["stderr"]})


@mcp.tool(
    name="adobe_run_jsx",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_run_jsx(params: RunJSXInput) -> str:
    """Execute arbitrary ExtendScript/JSX code in any supported Adobe application.
    This is the most powerful tool — you can do ANYTHING the app supports via scripting.
    Returns the script result or error message."""
    result = await _async_run_jsx(params.app.value, params.code, params.timeout)
    if result["success"]:
        return result["stdout"] if result["stdout"] else "Script executed successfully (no output)"
    return f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_run_jsx_file",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_run_jsx_file(params: RunJSXFileInput) -> str:
    """Execute a .jsx script file in any supported Adobe application."""
    result = await _async_run_jsx(params.app.value, f'$.evalFile("{params.file_path}")', params.timeout)
    if result["success"]:
        return result["stdout"] if result["stdout"] else "Script file executed successfully"
    return f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_run_powershell",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def adobe_run_powershell(params: RunPowerShellInput) -> str:
    """Execute arbitrary PowerShell for advanced Adobe COM automation.
    Use this when you need low-level COM access or complex multi-app workflows."""
    result = await _async_run_powershell(params.script, params.timeout)
    if result["success"]:
        return result["stdout"] if result["stdout"] else "PowerShell executed successfully"
    return f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_open_file",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_open_file(params: OpenFileInput) -> str:
    """Open a file in any Adobe application."""
    info = ADOBE_APPS[params.app.value]
    path = params.file_path.replace("\\", "\\\\").replace("'", "\\'")

    if params.app.value == "photoshop":
        jsx = f'var f = new File("{path}"); app.open(f); app.activeDocument.name;'
    elif params.app.value == "illustrator":
        jsx = f'var f = new File("{path}"); app.open(f); app.activeDocument.name;'
    elif params.app.value == "aftereffects":
        jsx = f'var f = new File("{path}"); app.open(f); app.project.file.name;'
    elif params.app.value == "premierepro":
        jsx = f'app.openDocument("{path}");'
    elif params.app.value == "indesign":
        jsx = f'var f = new File("{path}"); app.open(f); app.activeDocument.name;'
    elif params.app.value == "animate":
        jsx = f'fl.openDocument("{path}"); fl.getDocumentDOM().name;'
    else:
        jsx = f'var f = new File("{path}"); app.open(f);'

    result = await _async_run_jsx(params.app.value, jsx)
    if result["success"]:
        return f"Opened: {result['stdout']}" if result["stdout"] else "File opened successfully"
    return f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_save_file",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_save_file(params: SaveFileInput) -> str:
    """Save the active document in any Adobe application."""
    if params.file_path:
        path = params.file_path.replace("\\", "\\\\")
        if params.app.value == "photoshop":
            jsx = f'var f = new File("{path}"); app.activeDocument.saveAs(f); "Saved"'
        elif params.app.value == "illustrator":
            jsx = f'var f = new File("{path}"); app.activeDocument.saveAs(f); "Saved"'
        elif params.app.value == "indesign":
            jsx = f'var f = new File("{path}"); app.activeDocument.save(f); "Saved"'
        elif params.app.value == "animate":
            jsx = f'fl.saveDocument(fl.getDocumentDOM(), "{path}"); "Saved"'
        else:
            jsx = f'app.activeDocument.save(); "Saved"'
    else:
        if params.app.value == "animate":
            jsx = 'fl.saveDocument(fl.getDocumentDOM()); "Saved"'
        else:
            jsx = 'app.activeDocument.save(); "Saved"'

    result = await _async_run_jsx(params.app.value, jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_close_document",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_close_document(params: CloseDocInput) -> str:
    """Close the active document in any Adobe application."""
    save_opt = "SaveOptions.YES" if params.save else "SaveOptions.NO"
    if params.app.value == "animate":
        jsx = f'fl.closeDocument(fl.getDocumentDOM(), {"true" if params.save else "false"}); "Closed"'
    else:
        jsx = f'app.activeDocument.close({save_opt}); "Closed"'
    result = await _async_run_jsx(params.app.value, jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_get_doc_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_get_doc_info(params: GetDocInfoInput) -> str:
    """Get detailed info about the active document in any Adobe app."""
    if params.app.value == "photoshop":
        jsx = """
var d = app.activeDocument;
var info = {
    name: d.name, path: d.path.fsName, width: d.width.value, height: d.height.value,
    resolution: d.resolution, colorMode: String(d.mode), bitDepth: d.bitsPerChannel,
    layerCount: d.layers.length, channels: d.channels.length,
    artLayerCount: d.artLayers.length, layerSetCount: d.layerSets.length
};
JSON.stringify(info, null, 2);
"""
    elif params.app.value == "illustrator":
        jsx = """
var d = app.activeDocument;
var info = {
    name: d.name, path: d.path.fsName, width: d.width, height: d.height,
    colorMode: String(d.documentColorSpace), artboards: d.artboards.length,
    layers: d.layers.length, pathItems: d.pathItems.length,
    textFrames: d.textFrames.length, symbolItems: d.symbolItems.length
};
JSON.stringify(info, null, 2);
"""
    elif params.app.value == "aftereffects":
        jsx = """
var p = app.project;
var c = p.activeItem;
var info = { projectName: p.file ? p.file.name : 'Unsaved', items: p.numItems };
if (c && c instanceof CompItem) {
    info.comp = { name: c.name, width: c.width, height: c.height,
        duration: c.duration, frameRate: c.frameRate, layers: c.numLayers };
}
JSON.stringify(info, null, 2);
"""
    elif params.app.value == "premierepro":
        jsx = """
var p = app.project;
var s = p.activeSequence;
var info = { projectName: p.name, sequences: p.sequences.numSequences };
if (s) {
    info.activeSequence = { name: s.name, id: s.sequenceID,
        videoTracks: s.videoTracks.numTracks, audioTracks: s.audioTracks.numTracks };
}
JSON.stringify(info, null, 2);
"""
    elif params.app.value == "indesign":
        jsx = """
var d = app.activeDocument;
var info = {
    name: d.name, path: d.filePath.fsName, pages: d.pages.length,
    spreads: d.spreads.length, stories: d.stories.length,
    textFrames: d.textFrames.length, images: d.allGraphics.length,
    layers: d.layers.length, masterSpreads: d.masterSpreads.length
};
JSON.stringify(info, null, 2);
"""
    elif params.app.value == "animate":
        jsx = """
var d = fl.getDocumentDOM();
var info = {
    name: d.name, width: d.width, height: d.height,
    frameRate: d.frameRate, currentTimeline: d.currentTimeline,
    layers: d.getTimeline().layerCount, frames: d.getTimeline().frameCount
};
JSON.stringify(info);
"""
    else:
        jsx = 'try { JSON.stringify({name: app.activeDocument.name}); } catch(e) { "No document open"; }'

    result = await _async_run_jsx(params.app.value, jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_list_fonts",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def adobe_list_fonts(params: ListFontsInput) -> str:
    """List available fonts in an Adobe application."""
    filter_str = params.filter or ""
    if params.app.value == "photoshop":
        jsx = f"""
var fonts = []; var filter = '{filter_str}'.toLowerCase();
for (var i = 0; i < app.fonts.length; i++) {{
    var f = app.fonts[i];
    if (!filter || f.name.toLowerCase().indexOf(filter) >= 0 || f.postScriptName.toLowerCase().indexOf(filter) >= 0) {{
        fonts.push({{ name: f.name, postScriptName: f.postScriptName, family: f.family, style: f.style }});
    }}
    if (fonts.length >= 100) break;
}}
JSON.stringify({{ count: fonts.length, fonts: fonts }}, null, 2);
"""
    elif params.app.value == "illustrator":
        jsx = f"""
var fonts = []; var filter = '{filter_str}'.toLowerCase();
for (var i = 0; i < app.textFonts.length; i++) {{
    var f = app.textFonts[i];
    if (!filter || f.name.toLowerCase().indexOf(filter) >= 0) {{
        fonts.push({{ name: f.name, family: f.family, style: f.style }});
    }}
    if (fonts.length >= 100) break;
}}
JSON.stringify({{ count: fonts.length, fonts: fonts }}, null, 2);
"""
    else:
        return json.dumps({"error": f"Font listing not available for {params.app.value}. Use Photoshop or Illustrator."})

    result = await _async_run_jsx(params.app.value, jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Photoshop Tools ──────────────────────────────────────────────────────


@mcp.tool(
    name="adobe_ps_new_document",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_new_document(params: PsNewDocInput) -> str:
    """Create a new Photoshop document with specified dimensions, resolution, color mode."""
    color_map = {"RGB": "NewDocumentMode.RGB", "CMYK": "NewDocumentMode.CMYK", "LAB": "NewDocumentMode.LAB", "GRAYSCALE": "NewDocumentMode.GRAYSCALE"}
    bg_map = {"WHITE": "DocumentFill.WHITE", "BLACK": "DocumentFill.BLACK", "TRANSPARENT": "DocumentFill.TRANSPARENT"}
    color_mode = color_map.get(params.color_mode.value, "NewDocumentMode.RGB")
    bg = bg_map.get(params.background.upper(), "DocumentFill.WHITE")
    bit = {8: "BitsPerChannelType.EIGHT", 16: "BitsPerChannelType.SIXTEEN", 32: "BitsPerChannelType.THIRTYTWO"}.get(params.bit_depth, "BitsPerChannelType.EIGHT")

    jsx = f"""
var doc = app.documents.add(
    UnitValue({params.width}, 'px'), UnitValue({params.height}, 'px'),
    {params.resolution}, '{params.name}', {color_mode}, {bg}, 1, {bit}
);
JSON.stringify({{ name: doc.name, width: doc.width.value, height: doc.height.value, resolution: doc.resolution }});
"""
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_layers",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_layers(params: PsLayerInput) -> str:
    """Manage Photoshop layers — create, delete, rename, duplicate, merge, flatten, hide, show, reorder, set opacity/blendmode."""
    actions = {
        "create": f'var l = app.activeDocument.artLayers.add(); l.name = "{params.new_name or "New Layer"}"; l.name;',
        "delete": f'app.activeDocument.activeLayer = app.activeDocument.artLayers.getByName("{params.layer_name}"); app.activeDocument.activeLayer.remove(); "Deleted";',
        "rename": f'app.activeDocument.artLayers.getByName("{params.layer_name}").name = "{params.new_name}"; "Renamed";',
        "duplicate": f'app.activeDocument.artLayers.getByName("{params.layer_name}").duplicate(); "Duplicated";',
        "merge": 'app.activeDocument.mergeVisibleLayers(); "Merged visible";',
        "flatten": 'app.activeDocument.flatten(); "Flattened";',
        "hide": f'app.activeDocument.artLayers.getByName("{params.layer_name}").visible = false; "Hidden";',
        "show": f'app.activeDocument.artLayers.getByName("{params.layer_name}").visible = true; "Shown";',
        "set_opacity": f'app.activeDocument.artLayers.getByName("{params.layer_name}").opacity = {params.opacity or 100}; "Opacity set";',
        "set_blendmode": f'app.activeDocument.artLayers.getByName("{params.layer_name}").blendMode = BlendMode.{params.blend_mode.value if params.blend_mode else "NORMAL"}; "Blend mode set";',
    }

    if params.action == "reorder" and params.position is not None:
        jsx = f'var l = app.activeDocument.artLayers.getByName("{params.layer_name}"); l.move(app.activeDocument.artLayers[{params.position}], ElementPlacement.PLACEBEFORE); "Reordered";'
    elif params.action == "list":
        jsx = """
var layers = [];
for (var i = 0; i < app.activeDocument.artLayers.length; i++) {
    var l = app.activeDocument.artLayers[i];
    layers.push({ name: l.name, visible: l.visible, opacity: l.opacity,
        kind: String(l.kind), blendMode: String(l.blendMode), bounds: [l.bounds[0].value, l.bounds[1].value, l.bounds[2].value, l.bounds[3].value] });
}
JSON.stringify({ count: layers.length, layers: layers }, null, 2);
"""
    else:
        jsx = actions.get(params.action, f'"Unknown action: {params.action}"')

    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_filter",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_filter(params: PsFilterInput) -> str:
    """Apply filters to the active layer in Photoshop."""
    amt = params.amount or 5
    filters = {
        "gaussianBlur": f'app.activeDocument.activeLayer.applyGaussianBlur({amt}); "Applied Gaussian Blur radius={amt}";',
        "unsharpMask": f'app.activeDocument.activeLayer.applyUnSharpMask({amt}, {params.threshold or 1}, 0); "Applied Unsharp Mask";',
        "motionBlur": f'app.activeDocument.activeLayer.applyMotionBlur({params.angle or 0}, {amt}); "Applied Motion Blur";',
        "radialBlur": f'app.activeDocument.activeLayer.applyRadialBlur({amt}, RadialBlurMethod.SPIN, RadialBlurQuality.GOOD); "Applied Radial Blur";',
        "smartSharpen": f'app.activeDocument.activeLayer.applySharpen(); "Applied Sharpen";',
        "noise": f'app.activeDocument.activeLayer.applyAddNoise({amt}, NoiseDistribution.GAUSSIAN, false); "Applied Noise";',
        "median": f'app.activeDocument.activeLayer.applyMedianNoise({amt}); "Applied Median";',
        "highPass": f'app.activeDocument.activeLayer.applyHighPass({amt}); "Applied High Pass";',
        "findEdges": 'app.activeDocument.activeLayer.applyStyleize(SmartBlurQuality.HIGH); "Applied Find Edges";',
    }
    jsx = filters.get(params.filter_name, f'"Unknown filter: {params.filter_name}"')
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_selection",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_selection(params: PsSelectionInput) -> str:
    """Create and modify selections in Photoshop."""
    actions = {
        "select_all": 'app.activeDocument.selection.selectAll(); "Selected all";',
        "deselect": 'app.activeDocument.selection.deselect(); "Deselected";',
        "inverse": 'app.activeDocument.selection.invert(); "Inverted selection";',
        "feather": f'app.activeDocument.selection.feather({params.feather or 5}); "Feathered";',
        "expand": f'app.activeDocument.selection.expand(UnitValue({params.width or 5}, "px")); "Expanded";',
        "contract": f'app.activeDocument.selection.contract(UnitValue({params.width or 5}, "px")); "Contracted";',
        "smooth": f'app.activeDocument.selection.smooth({params.width or 5}); "Smoothed";',
    }
    if params.action == "rect" and all(v is not None for v in [params.x, params.y, params.width, params.height]):
        x2, y2 = params.x + params.width, params.y + params.height
        jsx = f'var r = [[{params.x},{params.y}],[{x2},{params.y}],[{x2},{y2}],[{params.x},{y2}]]; app.activeDocument.selection.select(r, SelectionType.REPLACE, {params.feather}, false); "Rectangular selection created";'
    elif params.action == "ellipse" and all(v is not None for v in [params.x, params.y, params.width, params.height]):
        jsx = f'app.activeDocument.selection.selectEllipse([{params.x},{params.y},{params.x+params.width},{params.y+params.height}], SelectionType.REPLACE, {params.feather}, false); "Elliptical selection created";'
    else:
        jsx = actions.get(params.action, f'"Unknown selection action: {params.action}"')

    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_transform",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_transform(params: PsTransformInput) -> str:
    """Transform operations — resize, rotate, flip, crop, trim."""
    resample_map = {
        "BICUBIC": "ResampleMethod.BICUBIC",
        "BILINEAR": "ResampleMethod.BILINEAR",
        "NEARESTNEIGHBOR": "ResampleMethod.NEARESTNEIGHBOR",
        "BICUBICSHARPER": "ResampleMethod.BICUBICSHARPER",
        "BICUBICSMOOTHER": "ResampleMethod.BICUBICSMOOTHER",
    }
    rs = resample_map.get(params.resample, "ResampleMethod.BICUBIC")

    actions = {
        "resize_image": f'app.activeDocument.resizeImage(UnitValue({params.width},"px"), UnitValue({params.height},"px"), {params.resolution or "app.activeDocument.resolution"}, {rs}); "Resized image";',
        "resize_canvas": f'app.activeDocument.resizeCanvas(UnitValue({params.width},"px"), UnitValue({params.height},"px")); "Resized canvas";',
        "rotate": f'app.activeDocument.rotateCanvas({params.angle or 0}); "Rotated {params.angle}°";',
        "flip_horizontal": 'app.activeDocument.flipCanvas(Direction.HORIZONTAL); "Flipped horizontal";',
        "flip_vertical": 'app.activeDocument.flipCanvas(Direction.VERTICAL); "Flipped vertical";',
        "crop": f'app.activeDocument.crop([{params.x or 0},{params.y or 0},{params.width or "app.activeDocument.width.value"},{params.height or "app.activeDocument.height.value"}]); "Cropped";',
        "trim": 'app.activeDocument.trim(TrimType.TRANSPARENT); "Trimmed";',
    }
    jsx = actions.get(params.action, f'"Unknown transform: {params.action}"')
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_adjustment",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_adjustment(params: PsAdjustmentInput) -> str:
    """Apply color/tone adjustments in Photoshop — levels, curves, hue/sat, brightness/contrast, etc."""
    adjustments = {
        "brightness_contrast": f'app.activeDocument.activeLayer.adjustBrightnessContrast({params.brightness or 0}, {params.contrast or 0}); "Applied B/C";',
        "hue_saturation": f'app.activeDocument.activeLayer.adjustColorBalance(undefined, undefined, undefined, undefined, {params.hue or 0}, {params.saturation or 0}, {params.lightness or 0}); "Applied Hue/Sat";',
        "auto_tone": 'app.activeDocument.autoLevels(); "Auto Tone applied";',
        "auto_contrast": 'app.activeDocument.autoContrast(); "Auto Contrast applied";',
        "auto_color": 'app.activeDocument.autoColor(); "Auto Color applied";',
        "invert": 'app.activeDocument.activeLayer.invert(); "Inverted";',
        "desaturate": 'app.activeDocument.activeLayer.desaturate(); "Desaturated";',
        "posterize": f'app.activeDocument.activeLayer.posterize({params.brightness or 4}); "Posterized";',
        "threshold": f'app.activeDocument.activeLayer.threshold({params.brightness or 128}); "Threshold applied";',
    }
    jsx = adjustments.get(params.adjustment, f'"Unknown adjustment: {params.adjustment}"')
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_text",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_text(params: PsTextInput) -> str:
    """Add a text layer in Photoshop with font, size, color, and position."""
    escaped_text = params.text.replace(chr(34), chr(92) + chr(34)).replace(chr(10), chr(92) + chr(110))
    jsx = f"""
var doc = app.activeDocument;
var layer = doc.artLayers.add();
layer.kind = LayerKind.TEXT;
var txt = layer.textItem;
txt.contents = "{escaped_text}";
txt.position = [UnitValue({params.x}, 'px'), UnitValue({params.y}, 'px')];
txt.font = "{params.font}";
txt.size = UnitValue({params.size}, 'pt');
var c = new SolidColor();
c.rgb.red = {params.color_r}; c.rgb.green = {params.color_g}; c.rgb.blue = {params.color_b};
txt.color = c;
txt.antiAliasMethod = AntiAlias.{params.anti_alias};
txt.justification = Justification.{params.justification};
layer.name;
"""
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_export",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_export(params: PsExportInput) -> str:
    """Export the active Photoshop document to PNG, JPEG, PSD, TIFF, PDF, etc."""
    path = params.file_path.replace("\\", "\\\\")
    fmt = params.format.value

    if fmt == "png":
        jsx = f"""
var opts = new PNGSaveOptions();
opts.interlaced = false; opts.compression = 6;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PNG";
"""
    elif fmt == "jpeg":
        jsx = f"""
var opts = new JPEGSaveOptions();
opts.quality = {params.quality}; opts.embedColorProfile = true;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported JPEG quality={params.quality}";
"""
    elif fmt == "tiff":
        jsx = f"""
var opts = new TiffSaveOptions();
opts.imageCompression = TIFFEncoding.TIFFLZW;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported TIFF";
"""
    elif fmt == "pdf":
        jsx = f"""
var opts = new PDFSaveOptions();
opts.compatibility = PDFCompatibility.PDF17;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PDF";
"""
    elif fmt == "psd":
        jsx = f"""
var opts = new PhotoshopSaveOptions();
opts.layers = true;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PSD";
"""
    else:
        jsx = f'app.activeDocument.saveAs(new File("{path}")); "Exported";'

    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_batch",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_batch(params: PsBatchInput) -> str:
    """Batch process files — open each file in input_folder, run JSX code, save to output_folder."""
    in_dir = params.input_folder.replace("\\", "\\\\")
    out_dir = params.output_folder.replace("\\", "\\\\")
    user_code = params.jsx_code.replace('"', '\\"')
    jsx = f"""
var inFolder = new Folder("{in_dir}");
var outFolder = new Folder("{out_dir}");
if (!outFolder.exists) outFolder.create();
var files = inFolder.getFiles("{params.file_filter}");
var processed = 0;
for (var i = 0; i < files.length; i++) {{
    try {{
        app.open(files[i]);
        {params.jsx_code}
        var outFile = new File(outFolder.fsName + "/" + files[i].name.replace(/\\.[^.]+$/, ".{params.format.value}"));
        app.activeDocument.saveAs(outFile);
        app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
        processed++;
    }} catch(e) {{ /* skip */ }}
}}
"Processed " + processed + " of " + files.length + " files";
"""
    result = await _async_run_jsx("photoshop", jsx, timeout=600)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_action",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_action(params: PsActionInput) -> str:
    """Run a pre-recorded Photoshop Action."""
    jsx = f'app.doAction("{params.action_name}", "{params.action_set}"); "Action executed";'
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ps_smart_object",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ps_smart_object(params: PsSmartObjectInput) -> str:
    """Smart Object operations — convert, rasterize, replace contents."""
    if params.layer_name:
        prefix = f'app.activeDocument.activeLayer = app.activeDocument.artLayers.getByName("{params.layer_name}");'
    else:
        prefix = ""

    actions = {
        "convert_to": f'{prefix} var idnewPlacedLayer = stringIDToTypeID("newPlacedLayer"); executeAction(idnewPlacedLayer, undefined, DialogModes.NO); "Converted to Smart Object";',
        "rasterize": f'{prefix} app.activeDocument.activeLayer.rasterize(RasterizeType.ENTIRELAYER); "Rasterized";',
        "replace_contents": f"""{prefix}
var idplacedLayerReplaceContents = stringIDToTypeID("placedLayerReplaceContents");
var desc = new ActionDescriptor();
safe_path = (params.file_path or '').replace(chr(92), '/')
desc.putPath(charIDToTypeID("null"), new File("{safe_path}"));
executeAction(idplacedLayerReplaceContents, desc, DialogModes.NO);
"Replaced contents";""",
    }
    jsx = actions.get(params.action, f'"Unknown smart object action: {params.action}"')
    result = await _async_run_jsx("photoshop", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Illustrator Tools ────────────────────────────────────────────────────


@mcp.tool(
    name="adobe_ai_new_document",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ai_new_document(params: AiNewDocInput) -> str:
    """Create a new Illustrator document."""
    color = "DocumentColorSpace.RGB" if params.color_mode == "RGB" else "DocumentColorSpace.CMYK"
    jsx = f"""
var preset = new DocumentPreset();
preset.width = {params.width}; preset.height = {params.height};
preset.colorMode = {color}; preset.numArtboards = {params.artboard_count};
preset.title = "{params.name}";
var doc = app.documents.addDocument("{params.color_mode}", preset);
JSON.stringify({{ name: doc.name, width: doc.width, height: doc.height, artboards: doc.artboards.length }});
"""
    result = await _async_run_jsx("illustrator", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ai_shapes",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ai_shapes(params: AiShapeInput) -> str:
    """Create shapes in Illustrator — rectangles, ellipses, polygons, stars, lines."""
    fill_setup = ""
    if params.fill_r is not None:
        fill_setup = f"""
var fillColor = new RGBColor();
fillColor.red = {params.fill_r}; fillColor.green = {params.fill_g}; fillColor.blue = {params.fill_b};
"""
    stroke_setup = f"""
var strokeColor = new RGBColor();
strokeColor.red = {params.stroke_r}; strokeColor.green = {params.stroke_g}; strokeColor.blue = {params.stroke_b};
"""
    shapes = {
        "rectangle": f'var shape = doc.pathItems.rectangle({params.y}, {params.x}, {params.width}, {params.height});',
        "ellipse": f'var shape = doc.pathItems.ellipse({params.y}, {params.x}, {params.width}, {params.height});',
        "polygon": f'var shape = doc.pathItems.polygon({params.x}, {params.y}, {(params.width or 100)/2}, {params.sides});',
        "star": f'var shape = doc.pathItems.star({params.x}, {params.y}, {(params.width or 100)/2}, {(params.width or 100)/4}, {params.points});',
        "line": f'var shape = doc.pathItems.add(); shape.setEntirePath([[{params.x},{params.y}],[{params.x+(params.width or 100)},{params.y+(params.height or 0)}]]);',
    }
    shape_code = shapes.get(params.shape, f'"Unknown shape: {params.shape}"')

    jsx = f"""
var doc = app.activeDocument;
{fill_setup}
{stroke_setup}
{shape_code}
{"shape.fillColor = fillColor;" if params.fill_r is not None else "shape.filled = false;"}
shape.strokeColor = strokeColor;
shape.strokeWidth = {params.stroke_width};
"Created {params.shape}";
"""
    result = await _async_run_jsx("illustrator", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ai_text",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ai_text(params: AiTextInput) -> str:
    """Add text in Illustrator."""
    escaped_text = params.text.replace(chr(34), chr(92) + chr(34))
    jsx = f"""
var doc = app.activeDocument;
var tf = doc.textFrames.add();
tf.contents = "{escaped_text}";
tf.top = {params.y}; tf.left = {params.x};
var attr = tf.textRange.characterAttributes;
attr.size = {params.size};
try {{ attr.textFont = app.textFonts.getByName("{params.font}"); }} catch(e) {{}}
var c = new RGBColor(); c.red = {params.color_r}; c.green = {params.color_g}; c.blue = {params.color_b};
attr.fillColor = c;
JSON.stringify({{ name: tf.contents, x: tf.left, y: tf.top }});
"""
    result = await _async_run_jsx("illustrator", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ai_path",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ai_path(params: AiPathInput) -> str:
    """Create and manipulate paths in Illustrator."""
    if params.action == "create" and params.points:
        jsx = f"""
var doc = app.activeDocument;
var path = doc.pathItems.add();
var pts = {params.points};
path.setEntirePath(pts);
path.closed = {str(params.closed).lower()};
{"var fc = new RGBColor(); fc.red=" + str(params.fill_r) + "; fc.green=" + str(params.fill_g) + "; fc.blue=" + str(params.fill_b) + "; path.fillColor = fc;" if params.fill_r is not None else "path.filled = false;"}
path.strokeWidth = {params.stroke_width};
"Path created with " + pts.length + " points";
"""
    else:
        jsx = f'"Action {params.action} requires direct JSX — use adobe_run_jsx for complex path operations";'
    result = await _async_run_jsx("illustrator", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ai_export",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ai_export(params: AiExportInput) -> str:
    """Export Illustrator document to SVG, PNG, PDF, EPS, JPG."""
    path = params.file_path.replace("\\", "\\\\")
    fmt = params.format.lower()
    if fmt == "svg":
        jsx = f"""
var opts = new ExportOptionsSVG();
app.activeDocument.exportFile(new File("{path}"), ExportType.SVG, opts);
"Exported SVG";
"""
    elif fmt == "png":
        jsx = f"""
var opts = new ExportOptionsPNG24();
opts.horizontalScale = {(params.scale or 1) * 100}; opts.verticalScale = {(params.scale or 1) * 100};
opts.transparency = true; opts.antiAliasing = true;
app.activeDocument.exportFile(new File("{path}"), ExportType.PNG24, opts);
"Exported PNG";
"""
    elif fmt == "pdf":
        jsx = f"""
var opts = new PDFSaveOptions();
app.activeDocument.saveAs(new File("{path}"), opts);
"Exported PDF";
"""
    elif fmt == "eps":
        jsx = f"""
var opts = new EPSSaveOptions();
app.activeDocument.saveAs(new File("{path}"), opts);
"Exported EPS";
"""
    elif fmt in ("jpg", "jpeg"):
        jsx = f"""
var opts = new ExportOptionsJPEG();
opts.qualitySetting = 100; opts.horizontalScale = {(params.scale or 1) * 100}; opts.verticalScale = {(params.scale or 1) * 100};
app.activeDocument.exportFile(new File("{path}"), ExportType.JPEG, opts);
"Exported JPEG";
"""
    else:
        jsx = f'app.activeDocument.saveAs(new File("{path}")); "Exported";'

    result = await _async_run_jsx("illustrator", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Premiere Pro Tools ───────────────────────────────────────────────────


@mcp.tool(
    name="adobe_pr_project",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_project(params: PrProjectInput) -> str:
    """Premiere Pro project operations — new, open, save, close, get info."""
    actions = {
        "save": 'app.project.save(); "Project saved";',
        "get_info": 'JSON.stringify({ name: app.project.name, path: app.project.path, sequences: app.project.sequences.numSequences });',
        "close": 'app.project.closeDocument(); "Project closed";',
    }
    if params.action == "open" and params.file_path:
        safe_path = params.file_path.replace(chr(92), "/")
        jsx = f'app.openDocument("{safe_path}"); "Project opened";'
    elif params.action == "save_as" and params.file_path:
        safe_path = params.file_path.replace(chr(92), "/")
        jsx = f'app.project.saveAs("{safe_path}"); "Saved as";'
    else:
        jsx = actions.get(params.action, f'"Unknown project action: {params.action}"')
    result = await _async_run_jsx("premierepro", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_pr_sequence",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_sequence(params: PrSequenceInput) -> str:
    """Premiere Pro sequence operations — create, list, get info, set active."""
    if params.action == "create":
        jsx = f'app.project.createNewSequence("{params.name or "New Sequence"}", "sequenceID"); "Sequence created";'
    elif params.action == "list":
        jsx = """
var seqs = [];
for (var i = 0; i < app.project.sequences.numSequences; i++) {
    var s = app.project.sequences[i];
    seqs.push({ name: s.name, id: s.sequenceID });
}
JSON.stringify({ count: seqs.length, sequences: seqs }, null, 2);
"""
    elif params.action == "get_info":
        jsx = """
var s = app.project.activeSequence;
JSON.stringify({
    name: s.name, id: s.sequenceID,
    videoTracks: s.videoTracks.numTracks, audioTracks: s.audioTracks.numTracks,
    inPoint: s.getInPoint(), outPoint: s.getOutPoint(),
    zeroPoint: s.zeroPoint, end: s.end
}, null, 2);
"""
    elif params.action == "set_active":
        jsx = f"""
for (var i = 0; i < app.project.sequences.numSequences; i++) {{
    if (app.project.sequences[i].name === "{params.name}") {{
        app.project.activeSequence = app.project.sequences[i];
        break;
    }}
}}
"Active sequence set to {params.name}";
"""
    else:
        jsx = f'"Unknown sequence action: {params.action}"'
    result = await _async_run_jsx("premierepro", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_pr_media",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_media(params: PrMediaInput) -> str:
    """Import and manage media in Premiere Pro."""
    if params.action == "import" and params.file_paths:
        jsx = f"""
var paths = {params.file_paths};
app.project.importFiles(paths);
"Imported " + paths.length + " files";
"""
    elif params.action == "import_folder" and params.folder_path:
        safe_path = params.folder_path.replace(chr(92), "/")
        jsx = f'app.project.importFiles(["{safe_path}"], true); "Folder imported";'
    elif params.action == "list_bin":
        jsx = """
var items = [];
var root = app.project.rootItem;
for (var i = 0; i < root.children.numItems; i++) {
    var item = root.children[i];
    items.push({ name: item.name, type: String(item.type), treePath: item.treePath });
}
JSON.stringify({ count: items.length, items: items }, null, 2);
"""
    elif params.action == "create_bin":
        jsx = f'app.project.rootItem.createBin("{params.bin_name}"); "Bin created";'
    else:
        jsx = f'"Action {params.action} — use adobe_run_jsx for complex media operations";'
    result = await _async_run_jsx("premierepro", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_pr_timeline",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_timeline(params: PrTimelineInput) -> str:
    """Premiere Pro timeline editing — insert, overwrite, razor, trim, transitions, speed."""
    jsx_code = f'"Timeline action {params.action} — use adobe_run_jsx with specific Premiere Pro ExtendScript for complex timeline operations";'
    if params.action == "insert" and params.clip_name:
        jsx_code = f"""
var seq = app.project.activeSequence;
var root = app.project.rootItem;
for (var i = 0; i < root.children.numItems; i++) {{
    if (root.children[i].name === "{params.clip_name}") {{
        seq.videoTracks[{params.track_index}].insertClip(root.children[i], {params.start_time or 0});
        break;
    }}
}}
"Clip inserted";
"""
    result = await _async_run_jsx("premierepro", jsx_code)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_pr_export",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_export(params: PrExportInput) -> str:
    """Export from Premiere Pro via AME or direct render."""
    path = params.file_path.replace("\\", "/")
    if params.use_ame:
        jsx = f"""
var seq = app.project.activeSequence;
var outputFile = new File("{path}");
app.encoder.launchEncoder();
app.encoder.encodeSequence(seq, outputFile.fsName, "{params.preset}", 0, 1);
"Export queued in AME";
"""
    else:
        jsx = f"""
var seq = app.project.activeSequence;
seq.exportAsMediaDirect("{path}", "{params.preset}", 0);
"Direct export started";
"""
    result = await _async_run_jsx("premierepro", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_pr_effects",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_pr_effects(params: PrEffectInput) -> str:
    """Apply and manage effects in Premiere Pro."""
    jsx = f'"Effect action {params.action} — use adobe_run_jsx for Premiere Pro effect operations. Effects API varies by version.";'
    if params.action == "list":
        jsx = """
var effects = [];
var seq = app.project.activeSequence;
var clip = seq.videoTracks[0].clips[0];
if (clip) {
    for (var i = 0; i < clip.components.numItems; i++) {
        effects.push({ name: clip.components[i].displayName, matchName: clip.components[i].matchName });
    }
}
JSON.stringify({ count: effects.length, effects: effects }, null, 2);
"""
    result = await _async_run_jsx("premierepro", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── After Effects Tools ──────────────────────────────────────────────────


@mcp.tool(
    name="adobe_ae_comp",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_comp(params: AeCompInput) -> str:
    """After Effects composition operations — create, list, duplicate, delete."""
    if params.action == "create":
        jsx = f"""
var comp = app.project.items.addComp("{params.name or 'Comp 1'}", {params.width}, {params.height}, 1, {params.duration}, {params.framerate});
JSON.stringify({{ name: comp.name, width: comp.width, height: comp.height, duration: comp.duration, fps: comp.frameRate }});
"""
    elif params.action == "list":
        jsx = """
var comps = [];
for (var i = 1; i <= app.project.numItems; i++) {
    if (app.project.item(i) instanceof CompItem) {
        var c = app.project.item(i);
        comps.push({ name: c.name, width: c.width, height: c.height, duration: c.duration, fps: c.frameRate, layers: c.numLayers });
    }
}
JSON.stringify({ count: comps.length, comps: comps }, null, 2);
"""
    elif params.action == "get_info":
        jsx = """
var c = app.project.activeItem;
if (c && c instanceof CompItem) {
    var layers = [];
    for (var i = 1; i <= c.numLayers; i++) {
        layers.push({ index: i, name: c.layer(i).name, enabled: c.layer(i).enabled });
    }
    JSON.stringify({ name: c.name, width: c.width, height: c.height, duration: c.duration,
        fps: c.frameRate, layers: layers }, null, 2);
} else { "No active composition"; }
"""
    elif params.action == "set_active" and params.name:
        jsx = f"""
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.name}") {{
        app.project.item(i).openInViewer();
        break;
    }}
}}
"Set active: {params.name}";
"""
    else:
        jsx = f'"Unknown comp action: {params.action}"'
    result = await _async_run_jsx("aftereffects", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ae_layer",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_layer(params: AeLayerInput) -> str:
    """After Effects layer operations — add solid, text, shape, null, adjustment, camera, light, media; manage layers."""
    comp_sel = f'var comp = app.project.activeItem;' if not params.comp_name else f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.comp_name}") {{
        comp = app.project.item(i); break;
    }}
}}
"""
    if params.action == "add_solid":
        jsx = f"""
{comp_sel}
var layer = comp.layers.addSolid([{params.color_r}/255, {params.color_g}/255, {params.color_b}/255], "{params.new_name or 'Solid'}", {params.width or 'comp.width'}, {params.height or 'comp.height'}, 1);
layer.name;
"""
    elif params.action == "add_text":
        escaped_ae_text = (params.text or "Text").replace(chr(34), chr(92) + chr(34))
        jsx = f"""
{comp_sel}
var layer = comp.layers.addText("{escaped_ae_text}");
layer.name = "{params.new_name or params.text or 'Text'}";
layer.name;
"""
    elif params.action == "add_null":
        jsx = f'{comp_sel} var layer = comp.layers.addNull(); layer.name = "{params.new_name or "Null"}"; layer.name;'
    elif params.action == "add_adjustment":
        jsx = f'{comp_sel} var layer = comp.layers.addSolid([1,1,1], "{params.new_name or "Adjustment"}", comp.width, comp.height, 1); layer.adjustmentLayer = true; layer.name;'
    elif params.action == "add_camera":
        jsx = f'{comp_sel} var layer = comp.layers.addCamera("{params.new_name or "Camera"}", [comp.width/2, comp.height/2]); layer.name;'
    elif params.action == "add_light":
        jsx = f'{comp_sel} var layer = comp.layers.addLight("{params.new_name or "Light"}", [comp.width/2, comp.height/2]); layer.name;'
    elif params.action == "add_media" and params.file_path:
        jsx = f"""
{comp_sel}
var item = app.project.importFile(new ImportOptions(new File("{params.file_path.replace(chr(92), "/")}")));
var layer = comp.layers.add(item);
layer.name;
"""
    elif params.action == "add_shape":
        jsx = f'{comp_sel} var layer = comp.layers.addShape(); layer.name = "{params.new_name or "Shape"}"; layer.name;'
    elif params.action == "delete" and params.layer_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").remove(); "Deleted";'
    elif params.action == "rename" and params.layer_name and params.new_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").name = "{params.new_name}"; "Renamed";'
    elif params.action == "duplicate" and params.layer_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").duplicate(); "Duplicated";'
    elif params.action in ("enable", "disable") and params.layer_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").enabled = {"true" if params.action == "enable" else "false"}; "{params.action}d";'
    elif params.action == "solo" and params.layer_name:
        jsx = f'{comp_sel} var l = comp.layer("{params.layer_name}"); l.solo = !l.solo; "Solo toggled";'
    else:
        jsx = f'"Use adobe_run_jsx for advanced AE layer operations: {params.action}";'

    result = await _async_run_jsx("aftereffects", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ae_property",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_property(params: AePropertyInput) -> str:
    """Set After Effects layer properties — transform, effects params, with optional keyframing."""
    comp_sel = 'var comp = app.project.activeItem;' if not params.comp_name else f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.comp_name}") {{ comp = app.project.item(i); break; }}
}}
"""
    prop_path = ".".join([f'property("{p}")' for p in params.property_path.split(".")])
    if params.time is not None:
        jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.setValueAtTime({params.time}, {params.value});
"Keyframe set at t={params.time}";
"""
    else:
        jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.setValue({params.value});
"Property set";
"""
    result = await _async_run_jsx("aftereffects", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ae_expression",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_expression(params: AeExpressionInput) -> str:
    """Apply expressions to After Effects layer properties."""
    comp_sel = 'var comp = app.project.activeItem;' if not params.comp_name else f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.comp_name}") {{ comp = app.project.item(i); break; }}
}}
"""
    prop_path = ".".join([f'property("{p}")' for p in params.property_path.split(".")])
    expr = params.expression.replace('"', '\\"').replace("\n", "\\n")
    jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.expression = "{expr}";
"Expression applied";
"""
    result = await _async_run_jsx("aftereffects", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ae_effect",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_effect(params: AeEffectInput) -> str:
    """Apply/manage effects on After Effects layers."""
    comp_sel = 'var comp = app.project.activeItem;' if not params.comp_name else f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.comp_name}") {{ comp = app.project.item(i); break; }}
}}
"""
    if params.action == "apply" and params.effect_name:
        jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var effect = layer.property("Effects").addProperty("{params.effect_name}");
effect.name;
"""
    elif params.action == "remove" and params.effect_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").property("Effects").property("{params.effect_name}").remove(); "Removed";'
    elif params.action == "list":
        jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var effects = [];
var fx = layer.property("Effects");
for (var i = 1; i <= fx.numProperties; i++) {{
    effects.push({{ name: fx.property(i).name, matchName: fx.property(i).matchName, enabled: fx.property(i).enabled }});
}}
JSON.stringify({{ count: effects.length, effects: effects }}, null, 2);
"""
    elif params.action in ("enable", "disable") and params.effect_name:
        jsx = f'{comp_sel} comp.layer("{params.layer_name}").property("Effects").property("{params.effect_name}").enabled = {"true" if params.action == "enable" else "false"}; "{params.action}d";'
    else:
        jsx = f'"Unknown effect action: {params.action}"'
    result = await _async_run_jsx("aftereffects", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_ae_render",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ae_render(params: AeRenderInput) -> str:
    """Add composition to After Effects render queue and start rendering."""
    path = params.output_path.replace("\\", "/")
    comp_sel = 'var comp = app.project.activeItem;' if not params.comp_name else f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.comp_name}") {{ comp = app.project.item(i); break; }}
}}
"""
    jsx = f"""
{comp_sel}
var rq = app.project.renderQueue;
var item = rq.items.add(comp);
{"item.applyTemplate('" + params.template + "');" if params.template else ""}
var om = item.outputModule(1);
{"om.applyTemplate('" + params.output_module + "');" if params.output_module else ""}
om.file = new File("{path}");
rq.render();
"Render complete: {path}";
"""
    result = await _async_run_jsx("aftereffects", jsx, timeout=600)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── InDesign Tools ───────────────────────────────────────────────────────


@mcp.tool(
    name="adobe_id_document",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_id_document(params: IdDocInput) -> str:
    """InDesign document operations — new, open, save, export PDF/EPUB/HTML, package, preflight."""
    if params.action == "new":
        w = params.width or 612
        h = params.height or 792
        jsx = f"""
var doc = app.documents.add();
doc.documentPreferences.pageWidth = "{w}pt";
doc.documentPreferences.pageHeight = "{h}pt";
doc.documentPreferences.pagesPerDocument = {params.pages or 1};
JSON.stringify({{ name: doc.name, pages: doc.pages.length, width: "{w}pt", height: "{h}pt" }});
"""
    elif params.action == "export_pdf" and params.file_path:
        path = params.file_path.replace("\\", "/")
        preset = params.preset or "[High Quality Print]"
        jsx = f"""
var doc = app.activeDocument;
var preset = app.pdfExportPresets.item("{preset}");
doc.exportFile(ExportFormat.PDF_TYPE, new File("{path}"), false, preset);
"PDF exported";
"""
    elif params.action == "export_epub" and params.file_path:
        path = params.file_path.replace("\\", "/")
        jsx = f'app.activeDocument.exportFile(ExportFormat.EPUB, new File("{path}")); "EPUB exported";'
    elif params.action == "package" and params.file_path:
        path = params.file_path.replace("\\", "/")
        jsx = f'app.activeDocument.packageForPrint("{path}", true, true, true, true, true, true); "Packaged";'
    elif params.action == "preflight":
        jsx = """
var doc = app.activeDocument;
var profile = app.preflightProfiles[0];
var process = app.preflightProcesses.add(doc, profile);
process.waitForProcess();
var results = process.processResults;
JSON.stringify({ results: results });
"""
    elif params.action == "get_info":
        jsx = """
var d = app.activeDocument;
JSON.stringify({
    name: d.name, pages: d.pages.length, spreads: d.spreads.length,
    stories: d.stories.length, layers: d.layers.length,
    masterSpreads: d.masterSpreads.length, textFrames: d.textFrames.length
}, null, 2);
"""
    else:
        jsx = f'"Use adobe_open_file/adobe_save_file for basic operations, or adobe_run_jsx for: {params.action}";'
    result = await _async_run_jsx("indesign", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_id_text",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_id_text(params: IdTextInput) -> str:
    """InDesign text operations — create frames, insert text, format, find/replace, styles."""
    if params.action == "create_frame":
        jsx = f"""
var doc = app.activeDocument;
var page = doc.pages[{params.page_index or 0}];
var tf = page.textFrames.add();
tf.geometricBounds = ["{params.y or 0}pt", "{params.x or 0}pt", "{(params.y or 0) + (params.height or 200)}pt", "{(params.x or 0) + (params.width or 300)}pt"];
if ("{params.text or ""}") tf.contents = "{escaped_text}";
"Text frame created";
"""
    elif params.action == "insert_text" and params.text:
        escaped_text = params.text.replace('"', '\\"')
        jsx = f"""
var doc = app.activeDocument;
var tf = doc.textFrames[0];
tf.insertionPoints[-1].contents = "{escaped_text}";
"Text inserted";
"""
    elif params.action == "find_replace" and params.find_what:
        jsx = f"""
app.findTextPreferences = NothingEnum.NOTHING;
app.changeTextPreferences = NothingEnum.NOTHING;
app.findTextPreferences.findWhat = "{params.find_what}";
app.changeTextPreferences.changeTo = "{params.replace_with or ""}";
var found = app.activeDocument.changeText();
"Replaced " + found.length + " instances";
"""
    elif params.action == "list_styles":
        jsx = """
var doc = app.activeDocument;
var pStyles = [], cStyles = [];
for (var i = 0; i < doc.paragraphStyles.length; i++) pStyles.push(doc.paragraphStyles[i].name);
for (var i = 0; i < doc.characterStyles.length; i++) cStyles.push(doc.characterStyles[i].name);
JSON.stringify({ paragraphStyles: pStyles, characterStyles: cStyles }, null, 2);
"""
    elif params.action == "apply_grep" and params.find_what:
        jsx = f"""
app.findGrepPreferences = NothingEnum.NOTHING;
app.changeGrepPreferences = NothingEnum.NOTHING;
app.findGrepPreferences.findWhat = "{params.find_what}";
app.changeGrepPreferences.changeTo = "{params.replace_with or ""}";
var found = app.activeDocument.changeGrep();
"GREP replaced " + found.length + " instances";
"""
    else:
        jsx = f'"Use adobe_run_jsx for advanced text operations: {params.action}";'
    result = await _async_run_jsx("indesign", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_id_image",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_id_image(params: IdImageInput) -> str:
    """Place images in InDesign documents."""
    path = params.file_path.replace("\\", "/")
    jsx = f"""
var doc = app.activeDocument;
var page = doc.pages[{params.page_index or 0}];
var frame = page.rectangles.add();
frame.geometricBounds = ["{params.y}pt", "{params.x}pt", "{params.y + (params.height or 300)}pt", "{params.x + (params.width or 400)}pt"];
frame.place(new File("{path}"));
{"frame.fit(FitOptions.PROPORTIONALLY); " if params.fit == "proportionally" else ""}
{"frame.fit(FitOptions.FILL_PROPORTIONALLY); " if params.fit == "fill" else ""}
{"frame.fit(FitOptions.FRAME_TO_CONTENT); " if params.fit == "frame" else ""}
{"frame.fit(FitOptions.CENTER_CONTENT); " if params.fit == "center" else ""}
"Image placed";
"""
    result = await _async_run_jsx("indesign", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Media Encoder Tools ──────────────────────────────────────────────────


@mcp.tool(
    name="adobe_ame_encode",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_ame_encode(params: AmeEncodeInput) -> str:
    """Adobe Media Encoder — queue management and encoding."""
    if params.action == "add_to_queue" and params.source_path:
        src = params.source_path.replace("\\", "/")
        out = (params.output_path or "").replace("\\", "/")
        jsx = f"""
var enc = app;
enc.addItemToQueue("{src}", "{params.preset or "H.264 - Match Source - High bitrate"}", "{out}");
"Added to queue";
"""
    elif params.action == "start_queue":
        jsx = 'app.startBatch(); "Queue started";'
    elif params.action == "stop_queue":
        jsx = 'app.stopBatch(); "Queue stopped";'
    elif params.action == "get_status":
        jsx = 'JSON.stringify({ status: app.getBatchStatus(), items: app.getEncoderHost().numItems });'
    elif params.action == "list_presets":
        jsx = """
var presets = app.getPresetList();
JSON.stringify({ presets: presets });
"""
    else:
        jsx = f'"Unknown AME action: {params.action}"'
    result = await _async_run_jsx("mediaencoder", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Animate Tools ────────────────────────────────────────────────────────


@mcp.tool(
    name="adobe_an_document",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_an_document(params: AnDocInput) -> str:
    """Adobe Animate document operations — new, publish, test, export."""
    if params.action == "new":
        jsx = f"""
fl.createDocument("{params.doc_type or 'html5canvas'}");
var doc = fl.getDocumentDOM();
{"doc.width = " + str(params.width) + ";" if params.width else ""}
{"doc.height = " + str(params.height) + ";" if params.height else ""}
{"doc.frameRate = " + str(params.fps) + ";" if params.fps else ""}
JSON.stringify({{ name: doc.name, width: doc.width, height: doc.height, fps: doc.frameRate }});
"""
    elif params.action == "publish":
        jsx = 'fl.getDocumentDOM().publish(); "Published";'
    elif params.action == "test_movie":
        jsx = 'fl.getDocumentDOM().testMovie(); "Testing movie";'
    elif params.action == "get_info":
        jsx = """
var d = fl.getDocumentDOM();
var tl = d.getTimeline();
JSON.stringify({
    name: d.name, width: d.width, height: d.height, fps: d.frameRate,
    layers: tl.layerCount, frames: tl.frameCount, currentFrame: tl.currentFrame
});
"""
    elif params.action == "export_html5" and params.file_path:
        safe_path = params.file_path.replace(chr(92), "/")
        jsx = f'fl.getDocumentDOM().exportPublishProfile("{safe_path}"); "HTML5 exported";'
    elif params.action == "export_video" and params.file_path:
        safe_path = params.file_path.replace(chr(92), "/")
        jsx = f'fl.getDocumentDOM().exportVideo("{safe_path}"); "Video exported";'
    else:
        jsx = f'"Use adobe_open_file/adobe_save_file or adobe_run_jsx for: {params.action}";'
    result = await _async_run_jsx("animate", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


@mcp.tool(
    name="adobe_an_timeline",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def adobe_an_timeline(params: AnTimelineInput) -> str:
    """Adobe Animate timeline operations — frames, keyframes, tweens, layers."""
    tl = "fl.getDocumentDOM().getTimeline()"
    if params.action == "insert_keyframe":
        jsx = f'{tl}.insertKeyframe({params.frame or 0}); "Keyframe inserted";'
    elif params.action == "insert_blank_keyframe":
        jsx = f'{tl}.insertBlankKeyframe({params.frame or 0}); "Blank keyframe inserted";'
    elif params.action == "add_frame":
        jsx = f'{tl}.insertFrames({params.duration or 1}, true, {params.frame or 0}); "Frames added";'
    elif params.action == "remove_frame":
        jsx = f'{tl}.removeFrames({params.frame or 0}, {(params.frame or 0) + (params.duration or 1)}); "Frames removed";'
    elif params.action == "create_motion_tween":
        jsx = f'{tl}.createMotionTween({params.frame or 0}); "Motion tween created";'
    elif params.action == "add_layer":
        jsx = f'{tl}.addNewLayer("{params.layer_name or "Layer"}"); "Layer added";'
    elif params.action == "delete_layer":
        jsx = f'{tl}.deleteLayer(); "Layer deleted";'
    elif params.action == "rename_layer":
        jsx = f'{tl}.layers[{tl}.currentLayer].name = "{params.layer_name}"; "Layer renamed";'
    elif params.action == "set_frame_label":
        jsx = f'{tl}.layers[{tl}.currentLayer].frames[{params.frame or 0}].name = "{params.label}"; "Label set";'
    elif params.action == "goto_frame":
        jsx = f'{tl}.currentFrame = {params.frame or 0}; "Moved to frame {params.frame}";'
    else:
        jsx = f'"Use adobe_run_jsx for advanced Animate operations: {params.action}";'
    result = await _async_run_jsx("animate", jsx)
    return result["stdout"] if result["success"] else f"Error: {result['stderr']}"


# ── Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
