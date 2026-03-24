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


class AeGenRenderInput(BaseModel):
    """Generate and render procedural animation in After Effects.

    Creates a composition, adds a base layer, applies generative expression code
    to the target property, adds effects (filters), and optionally renders to file.
    Supports seamless looping via loopOut or time-modulo wrapping.
    """
    model_config = ConfigDict(str_strip_whitespace=True)
    code: str = Field(..., description="Generative expression code (AE expression syntax)")
    property_target: str = Field(
        default="position",
        description="Property to apply expression to: position, scale, rotation, opacity, or custom path like 'Effects.CC Particle World.Birth Rate'",
    )
    duration: float = Field(default=5.0, description="Duration in seconds", ge=0.5, le=300)
    fps: int = Field(default=30, description="Frame rate", ge=12, le=120)
    width: int = Field(default=1920, description="Composition width", ge=1)
    height: int = Field(default=1080, description="Composition height", ge=1)
    comp_name: str = Field(default="GenRender", description="Composition name")
    bg_color: Optional[list] = Field(
        default=None,
        description="Background color [r,g,b] 0-255, default black",
    )
    layer_type: str = Field(
        default="solid",
        description="Base layer type: solid, shape, or text",
    )
    layer_color: Optional[list] = Field(
        default=None,
        description="Layer color [r,g,b] 0-255 for solid layers",
    )
    filters: Optional[list] = Field(
        default=None,
        description="List of effect names to apply: ['Gaussian Blur', 'Glow', 'CC Particle World', etc.]",
    )
    filter_params: Optional[dict] = Field(
        default=None,
        description="Effect parameters as {effect_name: {param: value}}, e.g. {'Gaussian Blur': {'Blurriness': 20}}",
    )
    loop: bool = Field(
        default=True,
        description="Make expression seamlessly loopable using loopOut('cycle')",
    )
    render: bool = Field(
        default=False,
        description="Add to render queue and start render after setup",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Output file path (required if render=True)",
    )
    output_format: str = Field(
        default="mp4",
        description="Output format: mp4, mov, gif",
    )


# ── Character Animation Pipeline Models ────────────────────────


class AeCompFromCharacterInput(BaseModel):
    """Create an AE composition from a posable Illustrator character with separated layers."""
    model_config = ConfigDict(str_strip_whitespace=True)
    ai_file_path: str = Field(..., description="Path to the Illustrator file containing the character")
    character_name: str = Field(default="character", description="Character identifier matching the AI skeleton")
    comp_name: Optional[str] = Field(default=None, description="Composition name (auto from character if None)")
    width: int = Field(default=1920, description="Comp width", ge=100)
    height: int = Field(default=1080, description="Comp height", ge=100)
    fps: float = Field(default=24, description="Frame rate", ge=1)
    duration: float = Field(default=5, description="Duration in seconds", ge=0.1)


class AePuppetPinsInput(BaseModel):
    """Map skeleton joint positions to After Effects puppet pin positions on character layers."""
    model_config = ConfigDict(str_strip_whitespace=True)
    character_name: str = Field(default="character", description="Character identifier")
    comp_name: Optional[str] = Field(default=None, description="Target composition name")
    pin_stiffness: float = Field(default=50, description="Puppet pin stiffness 0-100", ge=0, le=100)


class AeKeyframeExportInput(BaseModel):
    """Export a keyframe timeline as After Effects keyframe data."""
    model_config = ConfigDict(str_strip_whitespace=True)
    character_name: str = Field(default="character", description="Character whose timeline to export")
    comp_name: Optional[str] = Field(default=None, description="Target AE composition")
    method: str = Field(default="puppet", description="Animation method: puppet (puppet pins), transform (layer transforms), expression")


class AeExpressionGenInput(BaseModel):
    """Generate After Effects expressions for bone-driven animation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    character_name: str = Field(default="character", description="Character identifier")
    joint_name: Optional[str] = Field(default=None, description="Specific joint (None=all joints)")
    expression_type: str = Field(default="rotation", description="Expression type: rotation, position, wiggle, loopOut")
    comp_name: Optional[str] = Field(default=None, description="Target composition")


class AeAnimaticExportInput(BaseModel):
    """Export storyboard panels as a timed After Effects sequence (animatic)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    character_name: str = Field(default="character", description="Character identifier")
    comp_name: str = Field(default="animatic", description="Animatic composition name")
    panel_transition: str = Field(default="cut", description="Transition between panels: cut, dissolve, wipe")
    transition_frames: int = Field(default=6, description="Transition duration in frames", ge=0)
    add_audio_markers: bool = Field(default=True, description="Add markers at panel boundaries for audio sync")
