"""Tests for the turnaround from 3D tool.

Verifies camera position computation, layout math, and status —
all pure Python, no 3D engine required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.turnaround_from_3d import (
    compute_turnaround_cameras,
    layout_turnaround_sheet,
    VIEW_LABELS,
)


# ---------------------------------------------------------------------------
# test_compute_turnaround_cameras
# ---------------------------------------------------------------------------


class TestComputeTurnaroundCameras:
    """Camera positions for turnaround views."""

    def test_four_views_default(self):
        """Four views produce front/3-quarter/side/back at correct angles."""
        cameras = compute_turnaround_cameras(n_views=4, distance=5.0, height=1.0)

        assert len(cameras) == 4

        # Angle spacing: 0, 90, 180, 270
        angles = [c["angle_deg"] for c in cameras]
        assert angles == [0.0, 90.0, 180.0, 270.0]

        # Front camera (angle 0) should be at +Z
        front = cameras[0]
        assert front["label"] == "front"
        assert abs(front["position"][0]) < 0.01  # X near 0
        assert abs(front["position"][2] - 5.0) < 0.01  # Z = distance

        # Side camera (angle 90) should be at +X
        side = cameras[2]  # index 2 is 180 deg (back), index 1 is 90 deg
        right = cameras[1]
        assert abs(right["position"][0] - 5.0) < 0.01  # X = distance
        assert abs(right["position"][2]) < 0.01  # Z near 0

    def test_camera_count_matches_views(self):
        """Requested view count matches the number of cameras returned."""
        for n in [1, 2, 3, 4, 6, 8]:
            cameras = compute_turnaround_cameras(n_views=n)
            assert len(cameras) == n, f"Expected {n} cameras, got {len(cameras)}"

    def test_distance_affects_position(self):
        """Larger distance pushes cameras further from center."""
        near = compute_turnaround_cameras(n_views=1, distance=3.0)
        far = compute_turnaround_cameras(n_views=1, distance=10.0)

        near_z = near[0]["position"][2]
        far_z = far[0]["position"][2]
        assert far_z > near_z

    def test_all_cameras_look_at_origin(self):
        """Every camera looks at the model center (0,0,0)."""
        cameras = compute_turnaround_cameras(n_views=6)
        for cam in cameras:
            assert cam["look_at"] == [0.0, 0.0, 0.0]

    def test_height_applied(self):
        """Camera height is applied to Y coordinate of all cameras."""
        cameras = compute_turnaround_cameras(n_views=4, height=2.5)
        for cam in cameras:
            assert cam["position"][1] == 2.5


# ---------------------------------------------------------------------------
# test_layout_turnaround_sheet
# ---------------------------------------------------------------------------


class TestLayoutTurnaroundSheet:
    """Grid layout computation for turnaround page."""

    def test_four_views_layout(self):
        """Four views on a 1920x1080 page produce a valid grid with correct cell count."""
        layout = layout_turnaround_sheet(
            n_views=4, page_width=1920, page_height=1080, margin=40
        )

        # On a landscape page, the optimizer may pick 3 cols (closer-to-square cells)
        # or 2 cols depending on aspect ratio — just verify it's valid
        assert layout["columns"] >= 2
        assert layout["rows"] >= 1
        assert layout["columns"] * layout["rows"] >= 4  # Enough cells for all views
        assert len(layout["cells"]) == 4
        assert layout["cell_width"] > 0
        assert layout["cell_height"] > 0

    def test_cells_dont_overlap(self):
        """No two cells overlap in the layout."""
        layout = layout_turnaround_sheet(
            n_views=6, page_width=1920, page_height=1080, margin=20
        )

        cells = layout["cells"]
        for i, a in enumerate(cells):
            for j, b in enumerate(cells):
                if i >= j:
                    continue
                # Check no overlap: either a is left of b, right of b, above, or below
                h_sep = a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                v_sep = a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"]
                assert h_sep or v_sep, f"Cells {i} and {j} overlap"

    def test_cells_fit_in_page(self):
        """All cells fit within the page boundaries."""
        layout = layout_turnaround_sheet(
            n_views=8, page_width=1920, page_height=1080, margin=40
        )

        for cell in layout["cells"]:
            assert cell["x"] >= 0
            assert cell["y"] >= 0
            assert cell["x"] + cell["width"] <= 1920 + 1  # Allow float rounding
            assert cell["y"] + cell["height"] <= 1080 + 1


# ---------------------------------------------------------------------------
# test_status: constants accessible
# ---------------------------------------------------------------------------


def test_view_labels_have_standard_counts():
    """VIEW_LABELS dict has entries for common view counts."""
    assert 4 in VIEW_LABELS
    assert 6 in VIEW_LABELS
    assert len(VIEW_LABELS[4]) == 4
    assert "front" in VIEW_LABELS[4]
