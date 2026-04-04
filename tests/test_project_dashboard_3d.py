"""Tests for the enhanced project dashboard with 3D status.

Verifies 3D status collection, pipeline completion percentage,
and HTML output — all pure Python, no Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.production.project_dashboard_3d import (
    collect_3d_status,
    collect_pipeline_status,
    generate_dashboard_html,
    PIPELINE_STEPS_2D,
    PIPELINE_STEPS_3D,
)


# ---------------------------------------------------------------------------
# test_collect_3d_status
# ---------------------------------------------------------------------------


class TestCollect3dStatus:
    """Check 3D mesh status, quality, and export info."""

    def test_no_mesh(self):
        """Rig without 3D data reports no mesh."""
        rig = {"character_name": "hero"}
        status = collect_3d_status(rig)

        assert status["has_mesh"] is False
        assert status["quality_score"] == 0
        assert status["export_count"] == 0
        assert status["has_turnaround"] is False

    def test_with_mesh(self):
        """Rig with mesh_3d data reports mesh present with quality score."""
        rig = {
            "mesh_3d": {
                "vertex_count": 5000,
                "face_count": 3000,
                "has_uvs": True,
                "has_normals": True,
                "has_texture": True,
            },
        }
        status = collect_3d_status(rig)

        assert status["has_mesh"] is True
        assert status["quality_score"] > 0
        # With all features present, score should be high
        assert status["quality_score"] >= 80

    def test_quality_score_components(self):
        """Quality score increases with each feature present."""
        # Minimal mesh: just vertices
        rig_min = {"mesh_3d": {"vertex_count": 10, "face_count": 0}}
        # Full mesh
        rig_full = {
            "mesh_3d": {
                "vertex_count": 5000,
                "face_count": 3000,
                "has_uvs": True,
                "has_normals": True,
                "has_texture": True,
            },
        }

        score_min = collect_3d_status(rig_min)["quality_score"]
        score_full = collect_3d_status(rig_full)["quality_score"]

        assert score_full > score_min

    def test_exports_counted(self):
        """3D export formats are counted correctly."""
        rig = {
            "exports_3d": {
                "usdz": {"path": "/out/model.usdz", "exported": True},
                "obj": "/out/model.obj",
            },
        }
        status = collect_3d_status(rig)
        assert status["export_count"] == 2

    def test_turnaround_detected(self):
        """Turnaround data is detected."""
        rig = {
            "turnaround": {"view_count": 6, "cameras": []},
        }
        status = collect_3d_status(rig)
        assert status["has_turnaround"] is True
        assert status["turnaround_views"] == 6


# ---------------------------------------------------------------------------
# test_collect_pipeline_status
# ---------------------------------------------------------------------------


class TestCollectPipelineStatus:
    """Pipeline completion tracking for 2D and 3D tracks."""

    def test_empty_rig_zero_percent(self):
        """Empty rig produces 0% completion on both tracks."""
        rig = {}
        status = collect_pipeline_status(rig)

        assert status["pipeline_2d"]["percentage"] == 0.0
        assert status["pipeline_3d"]["percentage"] == 0.0
        assert status["overall"]["percentage"] == 0.0

    def test_partial_2d_completion(self):
        """Rig with some 2D data shows correct partial completion."""
        rig = {
            "source_image": "/art/hero.png",
            "contours": [{"id": 1}],
            "skeleton": {"joints": []},
        }
        status = collect_pipeline_status(rig)

        # image_loaded=True, threshold_traced=True (contours implies it),
        # contours_detected=True, skeleton_built=True
        assert status["pipeline_2d"]["completed"] >= 3
        assert status["pipeline_2d"]["percentage"] > 0.0
        assert status["pipeline_2d"]["total"] == len(PIPELINE_STEPS_2D)

    def test_full_completion(self):
        """Rig with all data shows 100% on both tracks."""
        rig = {
            "source_image": "/art/hero.png",
            "traced": True,
            "contours": [{"id": 1}],
            "skeleton": {"joints": []},
            "bindings": {"arm": "joint_1"},
            "poses": [{"name": "idle"}],
            "timeline": {"fps": 24},
            "mesh_3d": {"vertex_count": 100, "has_texture": True},
            "texture": {"width": 1024},
            "turnaround": {"view_count": 4},
            "rig_3d": {"bones": []},
            "exports_3d": {"usdz": "/out.usdz"},
        }
        status = collect_pipeline_status(rig)

        assert status["pipeline_2d"]["percentage"] == 100.0
        assert status["pipeline_3d"]["percentage"] == 100.0
        assert status["overall"]["percentage"] == 100.0

    def test_percentage_math(self):
        """Completion percentage is calculated correctly."""
        rig = {"source_image": "/img.png"}  # Only image_loaded = True
        status = collect_pipeline_status(rig)

        total_2d = len(PIPELINE_STEPS_2D)
        expected_pct = round(100.0 * 1 / total_2d, 1)
        assert status["pipeline_2d"]["percentage"] == expected_pct


# ---------------------------------------------------------------------------
# test_generate_dashboard_html
# ---------------------------------------------------------------------------


class TestGenerateDashboardHtml:
    """HTML output contains key sections."""

    def test_html_contains_key_sections(self):
        """Generated HTML includes 2D pipeline, 3D pipeline, and mesh status."""
        data = {
            "character_name": "TestHero",
            "timestamp": "2025-01-15 12:00:00",
            "pipeline_status": {
                "pipeline_2d": {
                    "completed": 3,
                    "total": 7,
                    "percentage": 42.9,
                    "steps": {
                        "image_loaded": True,
                        "threshold_traced": True,
                        "contours_detected": True,
                        "skeleton_built": False,
                        "parts_bound": False,
                        "poses_defined": False,
                        "timeline_set": False,
                    },
                },
                "pipeline_3d": {
                    "completed": 1,
                    "total": 5,
                    "percentage": 20.0,
                    "steps": {
                        "mesh_generated": True,
                        "mesh_textured": False,
                        "turnaround_rendered": False,
                        "3d_rig_created": False,
                        "animations_exported": False,
                    },
                },
                "overall": {
                    "completed": 4,
                    "total": 12,
                    "percentage": 33.3,
                },
            },
            "status_3d": {
                "has_mesh": True,
                "quality_score": 40,
                "has_turnaround": False,
                "turnaround_views": 0,
                "export_count": 0,
            },
        }

        html = generate_dashboard_html(data)

        # Should contain character name
        assert "TestHero" in html

        # Should contain key section headers
        assert "2D Pipeline" in html
        assert "3D Pipeline" in html
        assert "3D Mesh Status" in html
        assert "Overall Progress" in html

        # Should contain percentage values
        assert "42.9%" in html
        assert "20.0%" in html

        # Should be valid HTML structure
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_html_empty_data(self):
        """Dashboard renders even with minimal/empty data."""
        data = {
            "character_name": "empty",
            "pipeline_status": {},
            "status_3d": {},
        }

        html = generate_dashboard_html(data)
        assert "<!DOCTYPE html>" in html
        assert "empty" in html

    def test_html_step_checkmarks(self):
        """Completed steps show checkmarks, pending show circles."""
        data = {
            "character_name": "test",
            "pipeline_status": {
                "pipeline_2d": {
                    "steps": {"image_loaded": True, "skeleton_built": False},
                },
                "pipeline_3d": {"steps": {}},
                "overall": {},
            },
            "status_3d": {},
        }

        html = generate_dashboard_html(data)

        # Completed step should have checkmark class
        assert "step-done" in html
        # Pending step should have pending class
        assert "step-pending" in html
