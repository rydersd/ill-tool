"""Premiere Pro-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
