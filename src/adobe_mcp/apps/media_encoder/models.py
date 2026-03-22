"""Adobe Media Encoder-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AmeEncodeInput(BaseModel):
    """Adobe Media Encoder queue and encode."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: add_to_queue, start_queue, stop_queue, clear_queue, get_status, list_presets")
    source_path: Optional[str] = Field(default=None, description="Source file path")
    output_path: Optional[str] = Field(default=None, description="Output file path")
    preset: Optional[str] = Field(default=None, description="Encoding preset name")
    format: Optional[str] = Field(default=None, description="Output format")
