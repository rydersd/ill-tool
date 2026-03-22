"""After Effects-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
    action: str = Field(..., description="Action: add_solid, add_text, add_shape, add_null, add_adjustment, add_camera, add_light, add_media, duplicate, delete, rename, set_parent, precompose, get_info, enable, disable, solo, shy, lock, collapse")
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
    parent_name: Optional[str] = Field(default=None, description="Parent layer name for set_parent action")
    layer_indices: Optional[str] = Field(default=None, description="Comma-separated layer indices for precompose (1-based)")
    precomp_name: Optional[str] = Field(default=None, description="Name for the new precomp (for precompose)")


class AePropertyInput(BaseModel):
    """Set After Effects layer properties (transform, effects, etc)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="set", description="Action: set (set property value), get (read property value and keyframes), delete_keyframe (remove keyframe by index), get_keyframes (dump all keyframes)")
    key_index: Optional[int] = Field(default=None, description="Keyframe index for delete_keyframe action (1-based)")
    comp_name: Optional[str] = Field(default=None, description="Composition name")
    layer_name: str = Field(..., description="Layer name or index")
    property_path: str = Field(..., description="Property path e.g. 'Transform.Position', 'Transform.Opacity', 'Effects.Gaussian Blur.Blurriness'")
    value: Optional[str] = Field(default=None, description="Value as JSON — number, array, or string (required for set action)")
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
