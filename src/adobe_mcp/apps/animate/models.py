"""Adobe Animate-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
