"""Surface classification utility for path-level geometry analysis.

Loads normal map sidecar JSON and provides per-path surface intelligence.
Used by Smart Merge (form-aware scoring) and Shape Averager (surface hints).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SURFACE_TYPE_NAMES = {
    0: "flat",
    1: "convex",
    2: "concave",
    3: "saddle",
    4: "cylindrical",
}


@dataclass
class PathSurfaceInfo:
    """Surface classification for a single path."""

    name: str
    layer: str
    dominant_surface: str
    mean_curvature: float
    is_silhouette: bool
    mean_depth_facing: float
    anchor_count: int


@dataclass
class SidecarData:
    """Parsed sidecar JSON."""

    image_hash: str
    paths: list[PathSurfaceInfo]

    def get_path(self, name: str) -> Optional[PathSurfaceInfo]:
        """Find path info by name."""
        for p in self.paths:
            if p.name == name:
                return p
        return None

    def paths_on_surface(self, surface_type: str) -> list[PathSurfaceInfo]:
        """Get all paths on a given surface type."""
        return [p for p in self.paths if p.dominant_surface == surface_type]

    def surface_similarity(self, path_a: str, path_b: str) -> float:
        """Compute surface similarity score between two paths (0-1).

        1.0 = same surface type and similar curvature
        0.0 = completely different surfaces
        """
        a = self.get_path(path_a)
        b = self.get_path(path_b)
        if not a or not b:
            return 0.5  # unknown -- neutral score

        # Same surface type = 0.7 base score
        type_score = 0.7 if a.dominant_surface == b.dominant_surface else 0.0

        # Similar curvature magnitude = up to 0.3 bonus
        curv_diff = abs(a.mean_curvature - b.mean_curvature)
        curv_score = max(0, 0.3 - curv_diff * 10)

        return min(1.0, type_score + curv_score)

    def suggest_shape_type(self, path_name: str) -> Optional[str]:
        """Suggest a shape classification based on surface type.

        Returns: suggested shape type string or None.
        """
        info = self.get_path(path_name)
        if not info:
            return None

        mapping = {
            "flat": "line",
            "cylindrical": "arc",
            "convex": "arc",
            "concave": "arc",
            "saddle": "scurve",
        }
        return mapping.get(info.dominant_surface)


def load_sidecar(sidecar_path: str | Path) -> Optional[SidecarData]:
    """Load and parse a normal map sidecar JSON file."""
    path = Path(sidecar_path)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    paths = []
    for p in data.get("paths", []):
        paths.append(
            PathSurfaceInfo(
                name=p.get("name", ""),
                layer=p.get("layer", ""),
                dominant_surface=p.get("dominant_surface", "flat"),
                mean_curvature=p.get("mean_curvature", 0.0),
                is_silhouette=p.get("is_silhouette", False),
                mean_depth_facing=p.get("mean_depth_facing", 1.0),
                anchor_count=p.get("anchor_count", 0),
            )
        )

    return SidecarData(image_hash=data.get("image_hash", ""), paths=paths)


def find_sidecar(
    doc_name: str, cache_dir: str | Path = "/tmp/illtool_cache"
) -> Optional[Path]:
    """Find the sidecar file for a document."""
    cache = Path(cache_dir)
    candidate = cache / f"{doc_name}_normals.json"
    if candidate.exists():
        return candidate
    return None
