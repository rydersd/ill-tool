"""Rive-ready SVG export preparation.

Strips unsupported SVG features, converts CSS styles to presentation
attributes, and validates the result for Rive compatibility.

Pure Python — uses only standard library for SVG/XML processing.
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiRiveExportInput(BaseModel):
    """Prepare SVG for Rive import."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: prepare_svg, status"
    )
    svg_string: Optional[str] = Field(
        default=None, description="SVG content to process"
    )
    input_path: Optional[str] = Field(
        default=None, description="Path to SVG file to process"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path for processed SVG"
    )


# ---------------------------------------------------------------------------
# SVG processing functions
# ---------------------------------------------------------------------------

# CSS properties that map directly to SVG presentation attributes
CSS_TO_PRESENTATION = {
    "fill": "fill",
    "fill-opacity": "fill-opacity",
    "fill-rule": "fill-rule",
    "stroke": "stroke",
    "stroke-width": "stroke-width",
    "stroke-opacity": "stroke-opacity",
    "stroke-linecap": "stroke-linecap",
    "stroke-linejoin": "stroke-linejoin",
    "stroke-dasharray": "stroke-dasharray",
    "stroke-dashoffset": "stroke-dashoffset",
    "stroke-miterlimit": "stroke-miterlimit",
    "opacity": "opacity",
    "display": "display",
    "visibility": "visibility",
    "font-family": "font-family",
    "font-size": "font-size",
    "font-weight": "font-weight",
    "font-style": "font-style",
    "text-anchor": "text-anchor",
    "text-decoration": "text-decoration",
    "letter-spacing": "letter-spacing",
}

# Patterns for features Rive doesn't support
UNSUPPORTED_PATTERNS = [
    # Gradient strokes (Rive supports gradient fills but not gradient strokes)
    (r'stroke\s*=\s*"url\(#[^"]*\)"', "gradient stroke"),
    # SVG filters
    (r'<filter\b[^>]*>.*?</filter>', "SVG filter"),
    (r'filter\s*=\s*"[^"]*"', "filter attribute"),
    # Masks (Rive has limited mask support)
    (r'<mask\b[^>]*>.*?</mask>', "SVG mask"),
    (r'mask\s*=\s*"[^"]*"', "mask attribute"),
    # Skew transforms
    (r'skewX\s*\([^)]*\)', "skewX transform"),
    (r'skewY\s*\([^)]*\)', "skewY transform"),
    # feBlend, feComposite and other filter primitives
    (r'<fe\w+\b[^>]*/?>(?:</fe\w+>)?', "filter primitive"),
    # clip-path with complex shapes
    (r'clip-rule\s*=\s*"evenodd"', "evenodd clip-rule"),
]


def strip_unsupported_rive(svg_string: str) -> str:
    """Remove SVG features that Rive doesn't support.

    Strips:
    - Gradient strokes (converts to flat color)
    - SVG filter elements and attributes
    - Mask elements and attributes
    - Skew transforms
    - Filter primitives (feBlend, feComposite, etc.)

    Args:
        svg_string: raw SVG markup

    Returns:
        Cleaned SVG string with unsupported features removed.
    """
    result = svg_string

    # Remove filter elements (multiline)
    result = re.sub(
        r'<filter\b[^>]*>.*?</filter>',
        '', result, flags=re.DOTALL
    )

    # Remove mask elements (multiline)
    result = re.sub(
        r'<mask\b[^>]*>.*?</mask>',
        '', result, flags=re.DOTALL
    )

    # Remove filter primitives
    result = re.sub(
        r'<fe\w+\b[^>]*/>',
        '', result
    )
    result = re.sub(
        r'<fe\w+\b[^>]*>.*?</fe\w+>',
        '', result, flags=re.DOTALL
    )

    # Remove filter attributes
    result = re.sub(
        r'\s*filter\s*=\s*"[^"]*"',
        '', result
    )

    # Remove mask attributes
    result = re.sub(
        r'\s*mask\s*=\s*"[^"]*"',
        '', result
    )

    # Replace gradient strokes with a flat fallback
    result = re.sub(
        r'stroke\s*=\s*"url\(#[^"]*\)"',
        'stroke="#000000"',
        result
    )

    # Remove skew transforms (replace with empty string in transform attr)
    result = re.sub(r'skewX\s*\([^)]*\)', '', result)
    result = re.sub(r'skewY\s*\([^)]*\)', '', result)

    # Clean up empty transform attributes left behind
    result = re.sub(r'\s*transform\s*=\s*"\s*"', '', result)

    # Remove evenodd clip-rule (Rive uses nonzero)
    result = re.sub(
        r'clip-rule\s*=\s*"evenodd"',
        'clip-rule="nonzero"',
        result
    )

    return result


def convert_css_to_presentation(svg_string: str) -> str:
    """Convert CSS style attributes to SVG presentation attributes.

    Rive imports SVG presentation attributes more reliably than
    inline CSS style declarations.

    Converts:
        style="fill: red; stroke: blue; stroke-width: 2"
    To:
        fill="red" stroke="blue" stroke-width="2"

    Args:
        svg_string: SVG markup possibly containing style attributes

    Returns:
        SVG string with inline styles converted to presentation attributes.
    """

    def _style_to_attrs(match: re.Match) -> str:
        """Convert a single style="..." attribute to presentation attributes."""
        style_content = match.group(1)
        attrs = []
        unsupported = []

        # Parse CSS declarations
        declarations = [d.strip() for d in style_content.split(";") if d.strip()]
        for decl in declarations:
            if ":" not in decl:
                continue
            prop, _, value = decl.partition(":")
            prop = prop.strip().lower()
            value = value.strip()

            if prop in CSS_TO_PRESENTATION:
                attr_name = CSS_TO_PRESENTATION[prop]
                attrs.append(f'{attr_name}="{value}"')
            else:
                # Keep unsupported CSS properties in a reduced style attribute
                unsupported.append(f"{prop}: {value}")

        result_parts = []
        if attrs:
            result_parts.append(" ".join(attrs))
        if unsupported:
            result_parts.append(f'style="{"; ".join(unsupported)}"')

        return " ".join(result_parts) if result_parts else ""

    # Replace style="..." with presentation attributes
    result = re.sub(
        r'style="([^"]*)"',
        _style_to_attrs,
        svg_string,
    )

    return result


def validate_rive_svg(svg_string: str) -> dict:
    """Check SVG for remaining unsupported Rive features.

    Args:
        svg_string: SVG markup to validate

    Returns:
        Dict with 'valid' bool and 'issues' list of found problems.
    """
    issues = []

    for pattern, description in UNSUPPORTED_PATTERNS:
        matches = re.findall(pattern, svg_string, flags=re.DOTALL)
        if matches:
            issues.append({
                "feature": description,
                "count": len(matches),
                "sample": matches[0][:80] if matches else "",
            })

    # Check for <style> blocks (Rive prefers presentation attributes)
    style_blocks = re.findall(r'<style\b[^>]*>.*?</style>', svg_string, flags=re.DOTALL)
    if style_blocks:
        issues.append({
            "feature": "embedded <style> block",
            "count": len(style_blocks),
            "sample": style_blocks[0][:80],
        })

    # Check for inline style attributes (should have been converted)
    style_attrs = re.findall(r'style="[^"]*"', svg_string)
    if style_attrs:
        issues.append({
            "feature": "inline style attribute",
            "count": len(style_attrs),
            "sample": style_attrs[0][:80],
        })

    return {
        "valid": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_rive_export tool."""

    @mcp.tool(
        name="adobe_ai_rive_export",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_rive_export(params: AiRiveExportInput) -> str:
        """Prepare SVG for Rive import.

        Actions:
        - prepare_svg: strip unsupported features, convert CSS, validate
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "supported_actions": ["prepare_svg", "status"],
                "strips": [
                    "gradient strokes", "SVG filters", "masks",
                    "skew transforms", "filter primitives",
                ],
                "converts": ["CSS style → presentation attributes"],
            }, indent=2)

        # ── prepare_svg ─────────────────────────────────────────────
        if action == "prepare_svg":
            svg = params.svg_string

            # Load from file if path provided
            if not svg and params.input_path:
                import os
                if not os.path.exists(params.input_path):
                    return json.dumps({"error": f"File not found: {params.input_path}"})
                with open(params.input_path) as f:
                    svg = f.read()

            if not svg:
                return json.dumps({"error": "svg_string or input_path is required"})

            # Process pipeline
            original_len = len(svg)

            # Step 1: Strip unsupported features
            svg = strip_unsupported_rive(svg)

            # Step 2: Convert CSS to presentation attributes
            svg = convert_css_to_presentation(svg)

            # Step 3: Validate
            validation = validate_rive_svg(svg)

            # Save if output path provided
            if params.output_path:
                import os
                os.makedirs(os.path.dirname(params.output_path), exist_ok=True)
                with open(params.output_path, "w") as f:
                    f.write(svg)

            return json.dumps({
                "action": "prepare_svg",
                "original_size": original_len,
                "processed_size": len(svg),
                "size_reduction": original_len - len(svg),
                "validation": validation,
                "output_path": params.output_path,
                "processed_svg": svg if len(svg) < 10000 else "(too large, saved to output_path)",
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["prepare_svg", "status"],
        })
