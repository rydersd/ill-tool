"""InDesign-specific input models."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
