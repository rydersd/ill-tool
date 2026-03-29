"""Pure-Python path optimization via finite-difference gradients.

Fallback for diffvg_correct when DiffVG cannot be compiled.
Uses OpenCV for rasterization and numpy for gradient approximation.
Slower but always available (needs only numpy + opencv-python-headless).
"""

import numpy as np
import cv2
from typing import Optional


def rasterize_contours(contours, canvas_size, fill=True):
    """Render contours onto a canvas using OpenCV.

    Args:
        contours: list of Nx2 numpy arrays (int32). Each array is a polygon.
        canvas_size: (height, width) tuple.
        fill: if True, use fillPoly; else use polylines.

    Returns:
        float32 array [H, W] normalized to [0, 1].
    """
    canvas = np.zeros(canvas_size, dtype=np.uint8)
    if not contours:
        return canvas.astype(np.float32)
    # Filter out empty or degenerate contours
    valid = [c.astype(np.int32) for c in contours if len(c) > 0]
    if not valid:
        return canvas.astype(np.float32)
    if fill:
        cv2.fillPoly(canvas, valid, 255)
    else:
        cv2.polylines(canvas, valid, isClosed=True, color=255, thickness=1)
    return canvas.astype(np.float32) / 255.0


def compute_loss(rendered, target):
    """MSE loss between rendered and target images.

    Both should be float32 arrays normalized to [0, 1].

    Returns:
        float scalar.
    """
    return float(np.mean((rendered - target) ** 2))


def estimate_gradient(contours, target, canvas_size, epsilon=0.5):
    """Estimate gradient of loss w.r.t. control point positions via finite differences.

    For each control point, perturb x and y by +/-epsilon, measure loss change.

    Args:
        contours: list of Nx2 float64 numpy arrays (working copies).
        target: float32 [H, W] target image normalized to [0, 1].
        canvas_size: (height, width) tuple.
        epsilon: perturbation magnitude in pixels.

    Returns:
        list of Nx2 gradient arrays, one per contour.
    """
    gradients = []
    for c_idx, contour in enumerate(contours):
        grad = np.zeros_like(contour, dtype=np.float64)
        for p_idx in range(len(contour)):
            for dim in range(2):  # x, y
                # Forward perturbation
                perturbed_plus = [c.copy() for c in contours]
                perturbed_plus[c_idx][p_idx, dim] += epsilon
                rendered_plus = rasterize_contours(
                    [c.astype(np.int32) for c in perturbed_plus], canvas_size
                )
                loss_plus = compute_loss(rendered_plus, target)

                # Backward perturbation
                perturbed_minus = [c.copy() for c in contours]
                perturbed_minus[c_idx][p_idx, dim] -= epsilon
                rendered_minus = rasterize_contours(
                    [c.astype(np.int32) for c in perturbed_minus], canvas_size
                )
                loss_minus = compute_loss(rendered_minus, target)

                grad[p_idx, dim] = (loss_plus - loss_minus) / (2 * epsilon)
        gradients.append(grad)
    return gradients


def optimize_paths_approx(
    contours,
    target_image,
    iterations=50,
    lr=1.0,
    epsilon=0.5,
    momentum=0.9,
    convergence_delta=1e-4,
    convergence_patience=5,
):
    """Optimize contour positions against target image via gradient approximation.

    Uses finite-difference gradient estimation with momentum-based updates.
    O(2 * num_control_points) renders per iteration -- adequate for 10-50
    control points, impractical above 200.

    Args:
        contours: list of Nx2 float64 numpy arrays (polygon vertices).
        target_image: float32 [H, W] normalized to [0, 1].
        iterations: maximum number of optimization iterations.
        lr: learning rate for gradient descent.
        epsilon: perturbation magnitude for finite differences (pixels).
        momentum: momentum coefficient for velocity updates.
        convergence_delta: minimum loss change to consider progress.
        convergence_patience: consecutive stale iterations before early stop.

    Returns:
        (optimized_contours, stats_dict) where stats_dict contains:
            initial_loss, final_loss, iterations_run, converged.
    """
    canvas_size = target_image.shape[:2]
    working = [c.astype(np.float64).copy() for c in contours]
    velocities = [np.zeros_like(c, dtype=np.float64) for c in working]

    initial_loss = compute_loss(
        rasterize_contours([c.astype(np.int32) for c in working], canvas_size),
        target_image,
    )

    prev_loss = initial_loss
    current_loss = initial_loss
    patience_counter = 0
    iterations_run = 0

    for i in range(iterations):
        grads = estimate_gradient(working, target_image, canvas_size, epsilon)

        for c_idx in range(len(working)):
            velocities[c_idx] = momentum * velocities[c_idx] + grads[c_idx]
            working[c_idx] -= lr * velocities[c_idx]

        current_loss = compute_loss(
            rasterize_contours([c.astype(np.int32) for c in working], canvas_size),
            target_image,
        )
        iterations_run = i + 1

        if abs(prev_loss - current_loss) < convergence_delta:
            patience_counter += 1
            if patience_counter >= convergence_patience:
                break
        else:
            patience_counter = 0
        prev_loss = current_loss

    return working, {
        "initial_loss": initial_loss,
        "final_loss": current_loss,
        "iterations_run": iterations_run,
        "converged": patience_counter >= convergence_patience,
    }
