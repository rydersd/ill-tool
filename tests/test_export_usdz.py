"""Tests for the USDZ export tool.

Verifies USDA text generation, status reporting, and input validation.
All tests are pure Python — no trimesh or 3D deps required.
"""

import pytest

from adobe_mcp.apps.illustrator.export_formats.export_usdz import generate_usda_text


# ---------------------------------------------------------------------------
# USDA text generation
# ---------------------------------------------------------------------------


def test_usda_text_generation_triangle():
    """Generate USDA text for a simple triangle mesh."""
    mesh_data = {
        "name": "Triangle",
        "vertices": [[0, 0, 0], [1, 0, 0], [0.5, 1, 0]],
        "faces": [[0, 1, 2]],
    }

    usda = generate_usda_text(mesh_data)

    # Check USDA header
    assert "#usda 1.0" in usda
    assert 'defaultPrim = "Triangle"' in usda
    assert 'upAxis = "Y"' in usda

    # Check mesh data is present
    assert "faceVertexCounts" in usda
    assert "faceVertexIndices" in usda
    assert "point3f[] points" in usda

    # Check vertex coordinates appear
    assert "(0, 0, 0)" in usda
    assert "(1, 0, 0)" in usda
    assert "(0.5, 1, 0)" in usda

    # Check face vertex counts (one triangle = 3 vertices)
    assert "[3]" in usda

    # Check face vertex indices
    assert "0, 1, 2" in usda


def test_usda_text_generation_quad():
    """Generate USDA text for a quad (4-vertex face) mesh."""
    mesh_data = {
        "name": "Quad",
        "vertices": [
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        ],
        "faces": [[0, 1, 2, 3]],
    }

    usda = generate_usda_text(mesh_data)

    # Quad face should have count of 4
    assert "[4]" in usda
    # All 4 vertices referenced
    assert "0, 1, 2, 3" in usda


def test_usda_input_validation():
    """Invalid mesh data raises ValueError."""
    # Missing vertices
    with pytest.raises(ValueError, match="vertices"):
        generate_usda_text({"faces": [[0, 1, 2]]})

    # Missing faces
    with pytest.raises(ValueError, match="faces"):
        generate_usda_text({"vertices": [[0, 0, 0]]})

    # Empty mesh_data
    with pytest.raises(ValueError, match="mesh_data"):
        generate_usda_text({})

    # None mesh_data
    with pytest.raises(ValueError, match="mesh_data"):
        generate_usda_text(None)

    # Invalid vertex format (only 2 coords)
    with pytest.raises(ValueError, match="Vertex 0"):
        generate_usda_text({
            "vertices": [[0, 0]],
            "faces": [[0]],
        })

    # Invalid face vertex index (out of range)
    with pytest.raises(ValueError, match="invalid vertex index"):
        generate_usda_text({
            "vertices": [[0, 0, 0]],
            "faces": [[0, 1, 2]],  # indices 1,2 don't exist
        })
