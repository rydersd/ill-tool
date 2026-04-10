#!/usr/bin/env python3
"""Standalone runner for IllTool trace backends (normal_ref, form_edge).

Called by the C++ TraceModule via popen(). Imports the existing MCP Python
modules and runs them without the async MCP engine layer.

Usage:
    .venv/bin/python plugin/tools/run_trace_backend.py \
        --backend normal_ref \
        --image /path/to/image.png \
        --output-dir /tmp/illtool_normal_ref_output

    .venv/bin/python plugin/tools/run_trace_backend.py \
        --backend form_edge \
        --image /path/to/image.png \
        --output-dir /tmp/illtool_form_edge_output

Output (stdout): JSON manifest with files to place as layers:
    {
        "files": [
            {"name": "Normal: Form Lines", "path": "/tmp/.../form_lines.png"},
            {"name": "Normal: Flat Planes", "path": "/tmp/.../flat_planes.png"},
            ...
        ]
    }

Errors are printed to stderr. On failure, stdout contains:
    {"error": "description of what went wrong"}
"""

import argparse
import json
import os
import sys


def run_normal_ref(image_path: str, output_dir: str) -> dict:
    """Run DSINE normal estimation + rendering pipeline.

    Generates multiple analysis renderings from predicted surface normals:
    form_lines, flat_planes, curvature, depth_edges, silhouette.
    """
    try:
        from adobe_mcp.apps.illustrator.drawing.normal_reference import (
            _generate,
            DISPLAY_NAMES,
        )
    except ImportError as e:
        return {"error": f"Cannot import normal_reference module: {e}"}

    # Use a subset of the most useful renderings (not all 15)
    # to avoid overwhelming the user and keep execution time reasonable
    selected_renderings = [
        "form_lines",
        "flat_planes",
        "curvature",
        "depth_edges",
        "silhouette",
        "surface_type",
        "ridge_valley",
        "line_weight",
    ]

    result = _generate(
        image_path=image_path,
        model="auto",
        renderings=selected_renderings,
        k_planes=6,
        light_dir=(0.0, 0.0, 1.0),
    )

    if "error" in result:
        return {"error": result["error"]}

    # Build file manifest for C++ to place as layers
    files = []
    rendering_paths = result.get("rendering_paths", {})
    for name, path in rendering_paths.items():
        display_name = DISPLAY_NAMES.get(name, name)
        layer_name = f"Normal: {display_name}"
        files.append({"name": layer_name, "path": path})

    # Also include the normal map itself
    normal_map_path = result.get("normal_map_path")
    if normal_map_path and os.path.isfile(normal_map_path):
        files.append({"name": "Normal: Normal Map", "path": normal_map_path})

    return {
        "files": files,
        "timings": result.get("timings", {}),
    }


def run_form_edge(image_path: str, output_dir: str) -> dict:
    """Run form edge extraction pipeline.

    Generates edge mask PNG(s) showing structural form edges
    (ignoring shadows and reflections).
    """
    try:
        from adobe_mcp.apps.illustrator.drawing.form_edge_extract import _extract
    except ImportError as e:
        return {"error": f"Cannot import form_edge_extract module: {e}"}

    result = _extract(
        image_path=image_path,
        backend="auto",
        edge_threshold=0.5,
        simplify_tolerance=2.0,
        min_contour_length=30,
        max_contours=50,
    )

    if "error" in result:
        return {"error": result["error"]}

    files = []

    # The primary output is the edge mask image
    mask_path = result.get("mask_path")
    if mask_path and os.path.isfile(mask_path):
        files.append({"name": "Form Edges: Edge Mask", "path": mask_path})

    # If DSINE backend was used, there may also be additional renderings
    # from the normal map that were saved
    normal_map_path = result.get("normal_map_path")
    if normal_map_path and os.path.isfile(normal_map_path):
        # Generate a few useful renderings from the saved normal map
        try:
            import cv2
            import numpy as np
            from adobe_mcp.apps.illustrator.normal_renderings import (
                form_lines,
                silhouette_contours,
                curvature_line_weight,
            )

            npy_path = normal_map_path
            normal_map = np.load(npy_path)

            # Form lines rendering
            fl = form_lines(normal_map)
            if fl.ndim == 2:
                fl = cv2.cvtColor(fl, cv2.COLOR_GRAY2BGR)
            fl_path = os.path.join(output_dir, "form_lines.png")
            cv2.imwrite(fl_path, fl)
            files.append({"name": "Form Edges: Form Lines", "path": fl_path})

            # Silhouette contours
            sil = silhouette_contours(normal_map)
            if sil.ndim == 2:
                sil = cv2.cvtColor(sil, cv2.COLOR_GRAY2BGR)
            sil_path = os.path.join(output_dir, "silhouette.png")
            cv2.imwrite(sil_path, sil)
            files.append({"name": "Form Edges: Silhouette", "path": sil_path})

            # Line weight map
            lw = curvature_line_weight(normal_map)
            lw_img = (lw * 255).clip(0, 255).astype(np.uint8)
            lw_img = cv2.cvtColor(lw_img, cv2.COLOR_GRAY2BGR)
            lw_path = os.path.join(output_dir, "line_weight.png")
            cv2.imwrite(lw_path, lw_img)
            files.append({"name": "Form Edges: Line Weight", "path": lw_path})

        except Exception as ex:
            # Non-fatal — we still have the edge mask
            print(f"[run_trace_backend] Extra renderings failed: {ex}", file=sys.stderr)

    return {
        "files": files,
        "backend": result.get("backend", "unknown"),
        "contour_count": result.get("contour_count", 0),
        "timings": result.get("timings", {}),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run IllTool trace backends (normal_ref, form_edge)"
    )
    parser.add_argument(
        "--backend",
        required=True,
        choices=["normal_ref", "form_edge"],
        help="Backend to run",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Absolute path to input image (PNG/JPG)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for output files",
    )
    args = parser.parse_args()

    # Validate inputs
    if not os.path.isfile(args.image):
        print(json.dumps({"error": f"Image not found: {args.image}"}))
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Dispatch to the appropriate backend
    if args.backend == "normal_ref":
        result = run_normal_ref(args.image, args.output_dir)
    elif args.backend == "form_edge":
        result = run_form_edge(args.image, args.output_dir)
    else:
        result = {"error": f"Unknown backend: {args.backend}"}

    # Output JSON manifest to stdout (C++ reads this via popen)
    print(json.dumps(result, indent=2))

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
