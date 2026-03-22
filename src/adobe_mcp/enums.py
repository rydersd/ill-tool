"""Enumerations shared across Adobe MCP tools."""

from enum import Enum


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
