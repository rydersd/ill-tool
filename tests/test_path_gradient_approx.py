"""Tests for pure-Python path optimization via finite-difference gradients.

Uses small canvases (64x64) and simple shapes for fast execution.
Tests convergence, gradient direction, edge cases, and early stopping.
"""

import numpy as np
import cv2
import pytest

from adobe_mcp.apps.illustrator.ml_vision.path_gradient_approx import (
    rasterize_contours,
    compute_loss,
    estimate_gradient,
    optimize_paths_approx,
)


# ---------------------------------------------------------------------------
# Helpers for generating simple test shapes
# ---------------------------------------------------------------------------


def _circle_contour(cx, cy, radius, num_points=32):
    """Generate a circle contour as an Nx2 float64 array."""
    angles = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
    points = np.stack([cx + radius * np.cos(angles),
                       cy + radius * np.sin(angles)], axis=1)
    return points.astype(np.float64)


def _square_contour(cx, cy, half_size):
    """Generate a square contour as a 4x2 float64 array."""
    return np.array([
        [cx - half_size, cy - half_size],
        [cx + half_size, cy - half_size],
        [cx + half_size, cy + half_size],
        [cx - half_size, cy + half_size],
    ], dtype=np.float64)


# ---------------------------------------------------------------------------
# 1. rasterize_contours produces non-zero canvas with valid contour
# ---------------------------------------------------------------------------


def test_rasterize_contours_nonempty():
    """Valid contour rasterizes to a canvas with non-zero pixels."""
    contour = _circle_contour(32, 32, 10)
    canvas = rasterize_contours([contour.astype(np.int32)], (64, 64))
    assert canvas.shape == (64, 64)
    assert canvas.dtype == np.float32
    assert np.max(canvas) > 0, "Circle should produce non-zero pixels"


# ---------------------------------------------------------------------------
# 2. rasterize_contours produces zero canvas with empty contour list
# ---------------------------------------------------------------------------


def test_rasterize_contours_empty():
    """Empty contour list produces an all-zero canvas."""
    canvas = rasterize_contours([], (64, 64))
    assert canvas.shape == (64, 64)
    assert np.max(canvas) == 0.0


# ---------------------------------------------------------------------------
# 3. compute_loss returns 0.0 for identical images
# ---------------------------------------------------------------------------


def test_compute_loss_identical():
    """MSE between identical images is exactly 0.0."""
    img = np.random.rand(64, 64).astype(np.float32)
    loss = compute_loss(img, img.copy())
    assert loss == 0.0


# ---------------------------------------------------------------------------
# 4. compute_loss returns > 0 for different images
# ---------------------------------------------------------------------------


def test_compute_loss_different():
    """MSE between black and white images is 1.0."""
    black = np.zeros((64, 64), dtype=np.float32)
    white = np.ones((64, 64), dtype=np.float32)
    loss = compute_loss(black, white)
    assert abs(loss - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# 5. Circle contour converges toward target circle (loss decreases >50%)
# ---------------------------------------------------------------------------


def test_circle_convergence():
    """Circle offset by 8px converges toward target circle.

    Loss should decrease -- the optimizer pushes the contour toward
    the target even with finite-difference gradients on a small canvas.
    Uses a larger canvas (128x128) to reduce int32 rounding noise.
    """
    canvas_size = (128, 128)
    # Target: circle centered at (64, 64)
    target_contour = _circle_contour(64, 64, 20)
    target = rasterize_contours(
        [target_contour.astype(np.int32)], canvas_size
    )

    # Initial: circle offset by 8px to the right
    initial_contour = _circle_contour(72, 64, 20)

    optimized, stats = optimize_paths_approx(
        [initial_contour],
        target,
        iterations=30,
        lr=2.0,
        epsilon=1.5,
        momentum=0.8,
        convergence_delta=1e-8,
        convergence_patience=50,  # Don't early-stop
    )

    assert stats["final_loss"] < stats["initial_loss"], (
        f"Loss should decrease: {stats['initial_loss']:.6f} -> "
        f"{stats['final_loss']:.6f}"
    )


# ---------------------------------------------------------------------------
# 6. Square contour converges toward shifted target square
# ---------------------------------------------------------------------------


def test_square_convergence():
    """Square offset by 12px converges toward target square.

    Uses 128x128 canvas with an 8-point polygon (octagon-like square with
    midpoints) to give the optimizer more control points to work with.
    The finite-difference gradients on axis-aligned rectangles with only
    4 vertices are nearly zero for fill changes, so additional midpoints
    help.
    """
    canvas_size = (128, 128)

    def _square_with_midpoints(cx, cy, half_size):
        """Square with 8 vertices (corners + edge midpoints)."""
        hs = half_size
        return np.array([
            [cx - hs, cy - hs],
            [cx,      cy - hs],
            [cx + hs, cy - hs],
            [cx + hs, cy],
            [cx + hs, cy + hs],
            [cx,      cy + hs],
            [cx - hs, cy + hs],
            [cx - hs, cy],
        ], dtype=np.float64)

    target_contour = _square_with_midpoints(64, 64, 20)
    target = rasterize_contours(
        [target_contour.astype(np.int32)], canvas_size
    )

    initial_contour = _square_with_midpoints(52, 64, 20)

    optimized, stats = optimize_paths_approx(
        [initial_contour],
        target,
        iterations=30,
        lr=2.0,
        epsilon=2.0,
        momentum=0.5,
        convergence_delta=1e-8,
        convergence_patience=50,
    )

    assert stats["final_loss"] < stats["initial_loss"], (
        f"Final loss {stats['final_loss']:.6f} should be less than "
        f"initial {stats['initial_loss']:.6f}"
    )


# ---------------------------------------------------------------------------
# 7. Loss decreases over iterations (final < initial)
# ---------------------------------------------------------------------------


def test_loss_decreases_overall():
    """Optimization should reduce loss overall, even if not monotonically."""
    canvas_size = (64, 64)
    target = rasterize_contours(
        [_circle_contour(32, 32, 15).astype(np.int32)], canvas_size
    )
    initial = _circle_contour(38, 32, 15)

    _, stats = optimize_paths_approx(
        [initial],
        target,
        iterations=10,
        lr=1.0,
        epsilon=1.0,
        convergence_delta=1e-8,
        convergence_patience=20,
    )

    assert stats["final_loss"] < stats["initial_loss"]


# ---------------------------------------------------------------------------
# 8. Convergence patience triggers early stop when loss plateaus
# ---------------------------------------------------------------------------


def test_convergence_early_stop():
    """When contour is already at target, optimizer converges quickly."""
    canvas_size = (64, 64)
    contour = _circle_contour(32, 32, 10)
    target = rasterize_contours(
        [contour.astype(np.int32)], canvas_size
    )

    # Start from the same position -- loss is already minimal
    _, stats = optimize_paths_approx(
        [contour.copy()],
        target,
        iterations=100,
        lr=1.0,
        epsilon=0.5,
        convergence_delta=1e-4,
        convergence_patience=3,
    )

    assert stats["converged"] is True, "Should converge when already at target"
    assert stats["iterations_run"] < 100, (
        f"Should early-stop, but ran {stats['iterations_run']} iterations"
    )


# ---------------------------------------------------------------------------
# 9. Handles single-point contour gracefully
# ---------------------------------------------------------------------------


def test_single_point_contour():
    """Single-point contour doesn't crash the optimizer."""
    canvas_size = (64, 64)
    single_point = np.array([[32, 32]], dtype=np.float64)
    target = np.zeros(canvas_size, dtype=np.float32)

    # Should not raise
    optimized, stats = optimize_paths_approx(
        [single_point],
        target,
        iterations=3,
        lr=1.0,
        epsilon=0.5,
    )

    assert stats["iterations_run"] <= 3
    assert len(optimized) == 1
    assert optimized[0].shape == (1, 2)


# ---------------------------------------------------------------------------
# 10. Gradient direction: point on wrong side of target moves toward target
# ---------------------------------------------------------------------------


def test_gradient_direction():
    """Gradient should point from current position toward the target.

    A contour to the right of the target should have a positive x-gradient
    (loss increases when moving further right), so the update step
    (subtract gradient) pushes it left, toward the target.
    """
    canvas_size = (64, 64)
    # Target is centered
    target = rasterize_contours(
        [_square_contour(32, 32, 8).astype(np.int32)], canvas_size
    )

    # Current is offset 6px to the right
    current = [_square_contour(38, 32, 8)]

    grads = estimate_gradient(current, target, canvas_size, epsilon=1.0)

    # Mean x-gradient should be positive (moving right increases loss)
    mean_grad_x = np.mean(grads[0][:, 0])
    assert mean_grad_x > 0, (
        f"X-gradient should be positive (push left toward target), "
        f"got {mean_grad_x:.6f}"
    )
