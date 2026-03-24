"""Tests for the one-click character pipeline orchestrator.

Verifies pipeline planning with/without ML, report generation,
step ordering, capability detection, and resume logic —
all pure Python, no Adobe or ML required.
"""

import pytest

from adobe_mcp.apps.illustrator.one_click_character import (
    plan_pipeline,
    pipeline_report,
    compute_resume_plan,
    PIPELINE_STEPS,
)


# ---------------------------------------------------------------------------
# test_plan_pipeline: with and without ML/3D capabilities
# ---------------------------------------------------------------------------


class TestPlanPipeline:
    """Pipeline planning based on available capabilities."""

    def test_plan_no_deps(self):
        """With no ML or 3D, only core steps are included."""
        plan = plan_pipeline(
            image_path="/test/image.png",
            capabilities={"ml": False, "3d": False, "opencv": True},
        )

        included_ids = [s["id"] for s in plan["included_steps"]]
        skipped_ids = [s["id"] for s in plan["skipped_steps"]]

        # Core steps always included
        assert "validate_image" in included_ids
        assert "threshold_trace" in included_ids
        assert "contour_detection" in included_ids
        assert "build_skeleton" in included_ids
        assert "bind_parts" in included_ids
        assert "export_rig" in included_ids

        # ML steps skipped
        assert "sdpose_landmarks" in skipped_ids
        assert "cartoonseg_parts" in skipped_ids

        # 3D steps skipped
        assert "triposr_mesh" in skipped_ids
        assert "generate_turnaround" in skipped_ids

    def test_plan_with_ml(self):
        """With ML available, ML analysis steps are included."""
        plan = plan_pipeline(
            capabilities={"ml": True, "3d": False, "opencv": True},
        )

        included_ids = [s["id"] for s in plan["included_steps"]]

        assert "sdpose_landmarks" in included_ids
        assert "cartoonseg_parts" in included_ids
        # 3D still skipped
        assert "triposr_mesh" not in included_ids

    def test_plan_with_all(self):
        """With all capabilities, all steps are included."""
        plan = plan_pipeline(
            capabilities={"ml": True, "3d": True, "opencv": True},
        )

        included_ids = [s["id"] for s in plan["included_steps"]]

        # All steps should be included
        assert plan["included_count"] == len(PIPELINE_STEPS)
        assert plan["skipped_count"] == 0
        for step in PIPELINE_STEPS:
            assert step["id"] in included_ids

    def test_plan_phases(self):
        """Plan includes the correct phases based on capabilities."""
        plan = plan_pipeline(
            capabilities={"ml": False, "3d": False, "opencv": True},
        )

        # Should have input, tracing, rigging, output but NOT analysis or 3d
        assert "input" in plan["phases"]
        assert "tracing" in plan["phases"]
        assert "rigging" in plan["phases"]
        assert "output" in plan["phases"]
        assert "3d" not in plan["phases"]


# ---------------------------------------------------------------------------
# test_pipeline_report
# ---------------------------------------------------------------------------


class TestPipelineReport:
    """Structured progress report for the pipeline."""

    def test_full_completion(self):
        """All steps completed shows 100% progress."""
        all_ids = [s["id"] for s in PIPELINE_STEPS]
        report = pipeline_report(
            completed_steps=all_ids,
            skipped_steps=[],
        )

        assert report["completion_pct"] == 100.0
        assert report["completed"] == len(PIPELINE_STEPS)
        assert report["errors"] == 0
        assert report["next_step"] is None

    def test_partial_completion(self):
        """Partially completed pipeline shows correct percentage."""
        report = pipeline_report(
            completed_steps=["validate_image", "threshold_trace"],
            skipped_steps=["sdpose_landmarks", "cartoonseg_parts",
                           "triposr_mesh", "generate_turnaround"],
        )

        # 2 completed out of (10 total - 4 skipped = 6 actionable)
        assert report["completed"] == 2
        assert report["total_actionable"] == 6
        assert report["completion_pct"] == pytest.approx(33.3, abs=0.1)
        assert report["next_step"] is not None

    def test_errors_in_report(self):
        """Steps with errors are reported."""
        report = pipeline_report(
            completed_steps=["validate_image"],
            skipped_steps=[],
            errors={"threshold_trace": "OpenCV not found"},
        )

        assert report["errors"] == 1

        # Find the error step
        error_step = next(s for s in report["steps"] if s["id"] == "threshold_trace")
        assert error_step["status"] == "error"
        assert error_step["error_message"] == "OpenCV not found"


# ---------------------------------------------------------------------------
# test_step_ordering: dependencies are respected
# ---------------------------------------------------------------------------


def test_step_dependencies_valid():
    """Every step's depends_on references only steps defined earlier in the list."""
    step_ids_so_far = set()
    for step in PIPELINE_STEPS:
        for dep in step["depends_on"]:
            assert dep in step_ids_so_far or dep in [s["id"] for s in PIPELINE_STEPS], (
                f"Step '{step['id']}' depends on '{dep}' which is not a valid step ID"
            )
        step_ids_so_far.add(step["id"])


# ---------------------------------------------------------------------------
# test_capability_detection
# ---------------------------------------------------------------------------


def test_plan_pipeline_accepts_capabilities_dict():
    """plan_pipeline accepts a capabilities dict and uses it correctly."""
    # Test that passing explicit capabilities works without error
    plan = plan_pipeline(capabilities={"ml": False, "3d": False, "opencv": False})
    assert plan["capabilities"]["ml"] is False
    assert plan["capabilities"]["3d"] is False
    assert plan["included_count"] > 0  # Core steps always included


# ---------------------------------------------------------------------------
# test_compute_resume_plan
# ---------------------------------------------------------------------------


class TestResumePlan:
    """Resume logic for partially completed pipelines."""

    def test_resume_from_midpoint(self):
        """Resuming skips completed steps and returns remaining ones."""
        completed = ["validate_image", "threshold_trace", "contour_detection"]
        resume = compute_resume_plan(
            completed_steps=completed,
            capabilities={"ml": False, "3d": False, "opencv": True},
        )

        remaining_ids = [s["id"] for s in resume["remaining_steps"]]

        # Completed steps should not be in remaining
        for c in completed:
            assert c not in remaining_ids

        # Some steps should still remain
        assert resume["remaining_count"] > 0
        assert "build_skeleton" in remaining_ids

    def test_resume_empty_completed(self):
        """Resume with nothing completed returns the full plan."""
        resume = compute_resume_plan(
            completed_steps=[],
            capabilities={"ml": False, "3d": False, "opencv": True},
        )

        plan = plan_pipeline(capabilities={"ml": False, "3d": False, "opencv": True})
        assert resume["remaining_count"] == plan["included_count"]
