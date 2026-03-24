"""Illustrator integration smoke tests — requires live Adobe Illustrator.

Run with: uv run pytest tests/test_ai_smoke.py -v
Skip with: uv run pytest tests/ -k "not ai" -v
"""

import inspect
import json
import os

import pytest

from adobe_mcp.server import mcp

pytestmark = pytest.mark.ai

# ---------------------------------------------------------------------------
# Reference image fixture
# ---------------------------------------------------------------------------

GIR_REF = "/Users/ryders/Documents/Designs/Claude Experiments/GIR-DR-Poster/reference/gir_dogsuit_selected.png"


@pytest.fixture
def gir_ref():
    """Path to the GIR reference image, skipped if file is absent."""
    if not os.path.exists(GIR_REF):
        pytest.skip("GIR reference image not found")
    return GIR_REF


# ---------------------------------------------------------------------------
# Helper: call an MCP tool by name with a params dict
# ---------------------------------------------------------------------------

async def call_tool(name: str, params_dict: dict | None = None) -> str:
    """Invoke an MCP tool function by name and return its string result.

    Looks up the tool in the FastMCP internal registry, constructs the
    Pydantic model from *params_dict*, and awaits the tool function.
    """
    tool = mcp._tool_manager._tools[name]
    sig = inspect.signature(tool.fn)
    param_types = list(sig.parameters.values())

    if param_types and params_dict is not None:
        model_cls = param_types[0].annotation
        params = model_cls(**params_dict)
        result = await tool.fn(params)
    else:
        result = await tool.fn()

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_smart_shape_hexagon():
    """Create a hexagon at (400, -300) and verify the result JSON."""
    result = await call_tool("adobe_ai_smart_shape", {
        "shape_type": "hexagon",
        "center_x": 400,
        "center_y": -300,
        "width": 200,
        "height": 200,
        "name": "test_hexagon",
        "layer_name": "TestSmoke",
    })
    data = json.loads(result)
    assert "error" not in data, f"Tool returned error: {data}"
    assert data.get("shape_type") == "hexagon"
    assert data.get("point_count", 0) >= 6


async def test_reference_underlay(gir_ref):
    """Place the GIR reference as a background underlay."""
    result = await call_tool("adobe_ai_reference_underlay", {
        "image_path": gir_ref,
        "opacity": 40,
        "fit_to_artboard": True,
    })
    assert "Reference" in result, f"Expected 'Reference' in result: {result}"


async def test_analyze_reference(gir_ref):
    """Analyze the GIR reference and verify shapes are detected."""
    result = await call_tool("adobe_ai_analyze_reference", {
        "image_path": gir_ref,
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in data, f"Analysis returned error: {data}"
    assert data.get("shapes_returned", 0) > 0, "No shapes detected"
    assert isinstance(data.get("shapes"), list)


async def test_contour_to_path(gir_ref):
    """Analyze reference, take first shape, create a path from its contour."""
    # Step 1: analyze to get a shape manifest entry
    analysis = await call_tool("adobe_ai_analyze_reference", {
        "image_path": gir_ref,
    })
    data = json.loads(analysis) if isinstance(analysis, str) else analysis
    assert data.get("shapes_returned", 0) > 0, "No shapes to convert"

    first_shape = data["shapes"][0]
    image_size = data.get("image_size", [800, 600])

    # Step 2: create path from contour
    result = await call_tool("adobe_ai_contour_to_path", {
        "shape_json": json.dumps(first_shape),
        "image_size": json.dumps(image_size),
        "path_name": "test_contour",
        "layer_name": "TestSmoke",
    })
    result_data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in result_data, f"Contour to path failed: {result_data}"


async def test_anchor_edit_get_points():
    """Create a shape then retrieve its anchor points."""
    # Step 1: create a shape to have a known named path
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "triangle",
        "center_x": 200,
        "center_y": -200,
        "width": 100,
        "height": 100,
        "name": "test_anchor_shape",
        "layer_name": "TestSmoke",
    })

    # Step 2: get_points for the named shape
    result = await call_tool("adobe_ai_anchor_edit", {
        "action": "get_points",
        "name": "test_anchor_shape",
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"get_points failed: {data}"
    # Should have an array of points (triangle = 3)
    points = data.get("points", data.get("pathPoints", []))
    assert len(points) >= 3, f"Expected at least 3 points, got {len(points)}"


async def test_proportion_grid_manual():
    """Create a manual proportion grid with specific positions."""
    result = await call_tool("adobe_ai_proportion_grid", {
        "action": "manual",
        "h_positions": "[25, 50, 75]",
        "v_positions": "[25, 50, 75]",
    })
    assert "error" not in result.lower(), f"Grid creation failed: {result}"
    # The tool creates a Grid layer and returns info about it
    assert "grid" in result.lower() or "Grid" in result, f"Expected grid info: {result}"


async def test_silhouette(gir_ref):
    """Extract silhouette from the reference and verify placement."""
    result = await call_tool("adobe_ai_silhouette", {
        "image_path": gir_ref,
        "place_in_ai": True,
        "layer_name": "TestSmoke",
    })
    result_lower = result.lower()
    assert "error" not in result_lower, f"Silhouette failed: {result}"
    # Should mention placement or path creation
    assert "path" in result_lower or "placed" in result_lower or "point" in result_lower, (
        f"Expected placement info in result: {result}"
    )


async def test_vtrace(gir_ref):
    """Trace the reference image to SVG paths with vtracer."""
    result = await call_tool("adobe_ai_vtrace", {
        "image_path": gir_ref,
        "mode": "polygon",
        "place_in_ai": False,  # just get SVG, don't modify doc
    })
    result_lower = result.lower()
    assert "error" not in result_lower, f"vtrace failed: {result}"
    # Should contain SVG path data or mention svg
    assert "svg" in result_lower or "<path" in result_lower or "path" in result_lower, (
        f"Expected SVG/path info: {result[:200]}"
    )


async def test_compare_drawing(gir_ref):
    """Create a shape and compare the artboard to the reference."""
    # Ensure there's at least one shape on the artboard
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "ellipse",
        "center_x": 400,
        "center_y": -300,
        "width": 150,
        "height": 200,
        "name": "test_compare_shape",
        "layer_name": "TestSmoke",
    })

    result = await call_tool("adobe_ai_compare_drawing", {
        "reference_path": gir_ref,
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"Compare failed: {data}"
    # Should have a convergence score (0..1)
    score = data.get("convergence_score", data.get("convergence", data.get("overall_convergence", -1)))
    assert score >= 0, f"Expected convergence score >= 0, got: {data}"


async def test_bezier_optimize():
    """Create a polygon and optimize it to smooth bezier curves."""
    # Create a polygon (jagged by nature)
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "polygon",
        "center_x": 300,
        "center_y": -400,
        "width": 120,
        "height": 120,
        "sides": 8,
        "name": "test_bezier_target",
        "layer_name": "TestSmoke",
    })

    result = await call_tool("adobe_ai_bezier_optimize", {
        "name": "test_bezier_target",
        "smoothness": 70,
    })
    result_lower = result.lower()
    assert "error" not in result_lower, f"Bezier optimize failed: {result}"
    assert "smooth" in result_lower or "handle" in result_lower or "point" in result_lower, (
        f"Expected smoothing info: {result}"
    )


async def test_skeleton_annotate_add():
    """Add a joint to the skeleton rig and verify it's listed."""
    # Add a joint
    await call_tool("adobe_ai_skeleton_annotate", {
        "action": "add",
        "joint_name": "head",
        "x": 400,
        "y": -100,
        "character_name": "test_char",
    })

    # List joints and check it's there
    result = await call_tool("adobe_ai_skeleton_annotate", {
        "action": "list",
        "character_name": "test_char",
    })
    assert "head" in result.lower(), f"Expected 'head' joint in listing: {result}"


async def test_style_transfer_extract():
    """Create a stroked shape and extract its visual style as JSON."""
    # Create a shape with known styling
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "rectangle",
        "center_x": 500,
        "center_y": -200,
        "width": 80,
        "height": 80,
        "stroke_width": 3.0,
        "name": "test_style_source",
        "layer_name": "TestSmoke",
    })

    result = await call_tool("adobe_ai_style_transfer", {
        "action": "extract",
        "source_name": "test_style_source",
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"Style extract failed: {data}"
    # Should have stroke and/or fill info
    assert "stroked" in data or "stroke" in data, f"Expected stroke info: {data}"


async def test_path_boolean_unite():
    """Create two overlapping shapes and unite them."""
    # Shape A
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "rectangle",
        "center_x": 100,
        "center_y": -100,
        "width": 100,
        "height": 100,
        "name": "bool_shape_a",
        "layer_name": "TestSmoke",
    })
    # Shape B — overlapping
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "rectangle",
        "center_x": 150,
        "center_y": -100,
        "width": 100,
        "height": 100,
        "name": "bool_shape_b",
        "layer_name": "TestSmoke",
    })

    result = await call_tool("adobe_ai_path_boolean", {
        "operation": "unite",
        "front_name": "bool_shape_a",
        "back_name": "bool_shape_b",
        "result_name": "bool_united",
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"Boolean unite failed: {data}"


async def test_symmetry_mirror():
    """Create a shape and mirror it vertically."""
    # Create source shape
    await call_tool("adobe_ai_smart_shape", {
        "shape_type": "triangle",
        "center_x": 200,
        "center_y": -300,
        "width": 80,
        "height": 80,
        "name": "test_mirror_src",
        "layer_name": "TestSmoke",
    })

    result = await call_tool("adobe_ai_symmetry", {
        "name": "test_mirror_src",
        "axis": "vertical",
        "duplicate": True,
        "mirror_name": "test_mirror_copy",
    })
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"Symmetry mirror failed: {data}"
