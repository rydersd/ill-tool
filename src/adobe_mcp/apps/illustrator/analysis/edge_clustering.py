"""Cross-layer edge clustering engine.

Two-level clustering hierarchy:
  Level 1 -- Edge Identity: Group paths by boundary signature (what 3D boundary they represent)
  Level 2 -- Spatial Instance: DBSCAN within each identity group (which specific instance)

Outputs color-coded cluster assignments for ExtendScript visualization.
"""

import collections
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LayerPath:
    """A path from an extraction layer with all its metadata."""

    path_name: str
    layer_name: str
    points: list  # list of (x, y) tuples
    dominant_surface: str  # from sidecar
    mean_curvature: float  # from sidecar
    is_silhouette: bool
    boundary_signature: Optional[object] = None  # BoundarySignature, set after computation


@dataclass
class EdgeCluster:
    """A group of paths representing the same structural edge."""

    cluster_id: int
    members: list  # list of LayerPath
    identity_key: str  # from boundary signature
    confidence: float  # 0-1
    source_layer_count: int  # distinct layers that contributed
    quality_score: float  # spatial continuity + surface consistency
    color: list = field(default_factory=lambda: [200, 200, 200])  # RGB for visualization

    @property
    def confidence_tier(self) -> str:
        if self.source_layer_count >= 3:
            return "high"
        if self.source_layer_count >= 2:
            return "medium"
        return "low"


# 7 distinct colors cycling for cluster visualization
CLUSTER_COLORS = [
    [255, 68, 68],    # red
    [68, 170, 68],    # green
    [68, 136, 255],   # blue
    [255, 136, 0],    # orange
    [170, 68, 255],   # purple
    [0, 170, 170],    # teal
    [255, 68, 170],   # pink
]


# ---------------------------------------------------------------------------
# Path enumeration
# ---------------------------------------------------------------------------


def enumerate_layer_paths(
    jsx_path_data: list,
    sidecar_data: Optional[dict] = None,
) -> list:
    """Convert raw JSX path data + optional sidecar into LayerPath objects.

    Args:
        jsx_path_data: List of dicts from JSX. Each dict should have:
            - name (str): path item name
            - layer (str): layer name the path lives on
            - points (list): list of [x, y] coordinate pairs
        sidecar_data: Parsed sidecar JSON dict (with "paths" array),
            used to enrich paths with surface classification data.

    Returns:
        List of LayerPath objects ready for clustering.
    """
    # Build a lookup from sidecar path entries by name
    sidecar_lookup: dict = {}
    if sidecar_data and "paths" in sidecar_data:
        for p in sidecar_data["paths"]:
            name = p.get("name", "")
            if name:
                sidecar_lookup[name] = p

    result = []
    for item in jsx_path_data:
        name = item.get("name", "")
        layer = item.get("layer", "")
        raw_points = item.get("points", [])

        # Normalize points to list of tuples
        points = []
        for pt in raw_points:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                points.append((float(pt[0]), float(pt[1])))

        # Pull surface info from sidecar if available
        sidecar_entry = sidecar_lookup.get(name, {})
        dominant_surface = sidecar_entry.get("dominant_surface", "flat")
        mean_curvature = float(sidecar_entry.get("mean_curvature", 0.0))
        is_silhouette = bool(sidecar_entry.get("is_silhouette", False))

        result.append(
            LayerPath(
                path_name=name,
                layer_name=layer,
                points=points,
                dominant_surface=dominant_surface,
                mean_curvature=mean_curvature,
                is_silhouette=is_silhouette,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Spatial distance
# ---------------------------------------------------------------------------


def _mean_nearest_one_way(arr_from: np.ndarray, arr_to: np.ndarray) -> float:
    """Mean nearest-point distance from *arr_from* to *arr_to* (one direction)."""
    total_dist = 0.0
    for pt in arr_from:
        diffs = arr_to - pt
        dists = np.sqrt(np.sum(diffs * diffs, axis=1))
        total_dist += float(np.min(dists))
    return total_dist / len(arr_from)


def _spatial_distance(path_a: LayerPath, path_b: LayerPath) -> float:
    """Symmetric mean nearest-point distance between two paths.

    Computes the mean nearest-point distance in both directions
    (A->B and B->A) and returns the average, ensuring d(A,B)==d(B,A).

    Subsamples each path to max 20 points for performance.
    Returns infinity if either path has no points.
    """
    pts_a = path_a.points
    pts_b = path_b.points

    if not pts_a or not pts_b:
        return float("inf")

    # Subsample to max 20 points each
    max_pts = 20
    if len(pts_a) > max_pts:
        indices = np.linspace(0, len(pts_a) - 1, max_pts, dtype=int)
        pts_a = [pts_a[i] for i in indices]
    if len(pts_b) > max_pts:
        indices = np.linspace(0, len(pts_b) - 1, max_pts, dtype=int)
        pts_b = [pts_b[i] for i in indices]

    arr_a = np.array(pts_a, dtype=np.float64)
    arr_b = np.array(pts_b, dtype=np.float64)

    # Symmetric: average both directions so d(A,B) == d(B,A)
    d_a_to_b = _mean_nearest_one_way(arr_a, arr_b)
    d_b_to_a = _mean_nearest_one_way(arr_b, arr_a)
    return (d_a_to_b + d_b_to_a) / 2


# ---------------------------------------------------------------------------
# DBSCAN (self-contained, no sklearn dependency)
# ---------------------------------------------------------------------------


def _dbscan_cluster(paths: list, eps: float, min_samples: int = 1) -> list:
    """Simple DBSCAN clustering implementation.

    Uses a precomputed distance matrix + region query approach.
    No sklearn dependency required.

    Args:
        paths: List of LayerPath objects to cluster.
        eps: Maximum distance between two points to be considered neighbors.
        min_samples: Minimum number of points (including the point itself)
            to form a dense region.

    Returns:
        List of lists, where each inner list is a cluster of LayerPath objects.
        Noise points (not assigned to any cluster) are excluded.
    """
    n = len(paths)
    if n == 0:
        return []

    # Compute pairwise distance matrix
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = _spatial_distance(paths[i], paths[j])
            dist_matrix[i][j] = d
            dist_matrix[j][i] = d

    # DBSCAN labels: -1 = unvisited, -2 = noise, >= 0 = cluster id
    labels = [-1] * n
    cluster_id = 0

    for i in range(n):
        if labels[i] != -1:
            continue

        # Find neighbors within eps
        neighbors = [j for j in range(n) if dist_matrix[i][j] <= eps and j != i]

        if len(neighbors) + 1 < min_samples:
            labels[i] = -2  # noise
            continue

        # Start new cluster and expand using deque for O(1) popleft
        labels[i] = cluster_id
        seed_set = collections.deque(neighbors)
        in_seed = set(neighbors)  # deduplicate additions

        while seed_set:
            q = seed_set.popleft()
            if labels[q] == -2:
                labels[q] = cluster_id
            if labels[q] != -1:
                continue
            labels[q] = cluster_id
            q_neighbors = [j for j in range(n) if dist_matrix[q][j] <= eps and j != q]
            if len(q_neighbors) + 1 >= min_samples:
                for nb in q_neighbors:
                    if nb not in in_seed:
                        seed_set.append(nb)
                        in_seed.add(nb)

        cluster_id += 1

    # Group paths by cluster label (exclude noise)
    clusters: dict[int, list] = {}
    for i, label in enumerate(labels):
        if label >= 0:
            clusters.setdefault(label, []).append(paths[i])

    return list(clusters.values())


# ---------------------------------------------------------------------------
# Cluster scoring
# ---------------------------------------------------------------------------


def _score_cluster(cluster_members: list) -> tuple:
    """Compute (confidence, quality_score) for a cluster.

    Args:
        cluster_members: List of LayerPath objects in the cluster.

    Returns:
        (confidence, quality_score) tuple.

        confidence: based on the number of distinct source layers.
            3+ layers = 1.0, 2 layers = 0.7, 1 layer = 0.4

        quality_score: weighted combination of:
            - spatial_continuity (0.6 weight): how close are path endpoints
              to each other? Normalized by max observed distance.
            - surface_consistency (0.4 weight): how similar are curvature
              values across members? Low variance = high consistency.
    """
    if not cluster_members:
        return (0.0, 0.0)

    # --- Confidence from layer diversity ---
    distinct_layers = len(set(m.layer_name for m in cluster_members))
    if distinct_layers >= 3:
        confidence = 1.0
    elif distinct_layers >= 2:
        confidence = 0.7
    else:
        confidence = 0.4

    # --- Spatial continuity ---
    # Measure how close path endpoints are to each other
    # Lower mean distance = higher continuity
    if len(cluster_members) >= 2:
        endpoint_distances = []
        for i in range(len(cluster_members)):
            for j in range(i + 1, len(cluster_members)):
                d = _spatial_distance(cluster_members[i], cluster_members[j])
                if d < float("inf"):
                    endpoint_distances.append(d)

        if endpoint_distances:
            mean_dist = sum(endpoint_distances) / len(endpoint_distances)
            # Normalize: 0 distance -> 1.0, 50+ pt distance -> 0.0
            spatial_continuity = max(0.0, 1.0 - mean_dist / 50.0)
        else:
            spatial_continuity = 0.0
    else:
        spatial_continuity = 1.0  # single path = perfect continuity with itself

    # --- Surface consistency ---
    # Low curvature variance across members = high consistency
    curvatures = [m.mean_curvature for m in cluster_members]
    if len(curvatures) >= 2:
        mean_curv = sum(curvatures) / len(curvatures)
        variance = sum((c - mean_curv) ** 2 for c in curvatures) / len(curvatures)
        std_dev = math.sqrt(variance)
        # Normalize: 0 std -> 1.0, 0.1+ std -> 0.0
        surface_consistency = max(0.0, 1.0 - std_dev / 0.1)
    else:
        surface_consistency = 1.0  # single path = perfectly consistent

    quality_score = 0.6 * spatial_continuity + 0.4 * surface_consistency

    return (confidence, quality_score)


# ---------------------------------------------------------------------------
# Main clustering entry point
# ---------------------------------------------------------------------------


def cluster_paths(
    layer_paths: list,
    distance_threshold: float = 8.0,
    min_cluster_size: int = 2,
    learned_thresholds: dict = None,
) -> list:
    """Two-level clustering of paths across extraction layers.

    Level 1: Group by boundary_signature.identity_key() (O(n) dict groupby).
        Paths without a boundary_signature use a fallback key based on
        dominant_surface + is_silhouette.

    Level 2: Within each identity group, DBSCAN by spatial proximity.

    Each resulting cluster is scored by layer agreement and spatial/surface
    quality, then assigned a visualization color.

    Args:
        layer_paths: List of LayerPath objects (boundary_signature may be set).
        distance_threshold: DBSCAN eps in points (spatial distance threshold).
        min_cluster_size: Minimum number of paths to form a cluster.
        learned_thresholds: Optional dict keyed by identity_key, each value
            a dict with ``suggested_threshold``. When provided, the per-identity
            threshold is used as DBSCAN eps instead of the global
            distance_threshold. This closes the learning loop from
            correction_learning.learn_cluster_thresholds().

    Returns:
        List of EdgeCluster objects, sorted by confidence descending.
    """
    if not layer_paths:
        return []

    # --- Level 1: Group by identity key ---
    identity_groups: dict[str, list] = {}
    for lp in layer_paths:
        if lp.boundary_signature is not None and hasattr(lp.boundary_signature, "identity_key"):
            key = lp.boundary_signature.identity_key()
            # Guard: identity_key() may return None/empty for degenerate signatures
            if not key:
                sil_tag = "sil" if lp.is_silhouette else "int"
                key = f"{lp.dominant_surface}_{sil_tag}"
        else:
            # Fallback: group by surface type + silhouette status
            sil_tag = "sil" if lp.is_silhouette else "int"
            key = f"{lp.dominant_surface}_{sil_tag}"
        identity_groups.setdefault(key, []).append(lp)

    # --- Level 2: DBSCAN within each identity group ---
    all_clusters = []
    global_cluster_id = 0

    for identity_key, group_paths in identity_groups.items():
        if len(group_paths) < min_cluster_size:
            # Group too small for clustering -- still create a cluster
            # if we relax to allow single-path clusters when min_cluster_size=1
            if min_cluster_size <= 1:
                sub_clusters = [group_paths]
            else:
                continue
        else:
            # Use per-identity learned threshold if available (S4)
            eps = distance_threshold
            if learned_thresholds and identity_key in learned_thresholds:
                eps = learned_thresholds[identity_key].get(
                    "suggested_threshold", distance_threshold
                )
            # min_samples >= 2 enables proper density-based noise detection (C3)
            sub_clusters = _dbscan_cluster(
                group_paths, eps=eps, min_samples=max(2, min_cluster_size),
            )

        for members in sub_clusters:
            if len(members) < min_cluster_size:
                continue

            distinct_layers = len(set(m.layer_name for m in members))
            confidence, quality_score = _score_cluster(members)
            color = CLUSTER_COLORS[global_cluster_id % len(CLUSTER_COLORS)]

            cluster = EdgeCluster(
                cluster_id=global_cluster_id,
                members=members,
                identity_key=identity_key,
                confidence=confidence,
                source_layer_count=distinct_layers,
                quality_score=quality_score,
                color=color,
            )
            all_clusters.append(cluster)
            global_cluster_id += 1

    # Sort by confidence descending, then quality_score descending
    all_clusters.sort(key=lambda c: (-c.confidence, -c.quality_score))

    return all_clusters


# ---------------------------------------------------------------------------
# ExtendScript generation
# ---------------------------------------------------------------------------


def generate_color_jsx(clusters: list) -> str:
    """Generate ExtendScript code to color-code paths by cluster.

    Each cluster gets a distinct color from CLUSTER_COLORS (cycling).
    Stroke weight encodes confidence tier:
        - high (3+ layers): 2pt
        - medium (2 layers): 1pt
        - low (1 layer): 0.5pt, dashed

    Args:
        clusters: List of EdgeCluster objects.

    Returns:
        JSX string that can be evalScript'd in Illustrator.
    """
    if not clusters:
        return "// No clusters to visualize"

    lines = [
        "var doc = app.activeDocument;",
    ]

    stroke_weights = {
        "high": 2,
        "medium": 1,
        "low": 0.5,
    }

    for cluster in clusters:
        r, g, b = cluster.color
        tier = cluster.confidence_tier
        weight = stroke_weights.get(tier, 1)

        for member in cluster.members:
            # Escape path name for JSX string literal:
            # backslashes, quotes, newlines, carriage returns, and other control chars
            escaped_name = (
                member.path_name
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t")
            )
            lines.append("try {")
            lines.append(f'    var p = doc.pathItems.getByName("{escaped_name}");')
            lines.append(f"    var c = new RGBColor(); c.red = {r}; c.green = {g}; c.blue = {b};")
            lines.append("    p.strokeColor = c;")
            lines.append(f"    p.strokeWidth = {weight};")

            # Low confidence = dashed stroke
            if tier == "low":
                lines.append("    p.strokeDashes = [4, 2];")

            lines.append("} catch(e) {}")

    return "\n".join(lines)


def generate_cluster_json(clusters: list) -> str:
    """Generate JSON for sa_colorClusters() in ExtendScript.

    Produces the exact format the CEP panel expects:
    [{
        "cluster_id": int,
        "path_names": [str, ...],
        "color": [r, g, b],
        "stroke_width": float,
        "dashed": bool,
        "identity_key": str,
        "confidence_tier": str,
        "member_count": int
    }, ...]

    Single quotes in path_names are escaped because the panel wraps
    JSON in single-quoted evalScript calls.
    """
    result = []
    for i, cluster in enumerate(clusters):
        color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
        tier = cluster.confidence_tier
        stroke_width = 2.0 if tier == "high" else (1.0 if tier == "medium" else 0.5)
        dashed = tier == "low"
        result.append({
            "cluster_id": cluster.cluster_id,
            "path_names": [m.path_name.replace("'", "\\'") for m in cluster.members],
            "color": color,
            "stroke_width": stroke_width,
            "dashed": dashed,
            "identity_key": cluster.identity_key,
            "confidence_tier": tier,
            "member_count": len(cluster.members),
        })
    return json.dumps(result)


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register edge clustering MCP tools."""

    @mcp.tool(
        name="adobe_ai_cluster_paths",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cluster_paths_tool(
        layer_paths_json: str,
        distance_threshold: float = 8.0,
        sidecar_path: str = None,
        image_path: str = None,
    ) -> str:
        """Cluster paths across extraction layers into structural edge groups.

        Groups paths from different extraction layers (contour, silhouette,
        form edge, etc.) that represent the same underlying 3D boundary.
        Uses a two-level hierarchy: boundary signature identity, then
        spatial proximity (DBSCAN).

        Args:
            layer_paths_json: JSON string from sa_readLayerPaths(). Array of
                objects with ``name``, ``layer``, ``points`` (array of [x,y]).
            distance_threshold: DBSCAN eps in points. Paths closer than this
                are considered spatially adjacent. Default: 8.0
            sidecar_path: Optional path to the sidecar JSON file with
                surface classification data (dominant_surface, mean_curvature,
                is_silhouette per path).
            image_path: Optional path to the reference image, used to find
                the sidecar JSON when sidecar_path is not given.

        Returns:
            JSON with cluster assignments in sa_colorClusters() format,
            plus summary metadata.
        """
        from adobe_mcp.apps.illustrator.analysis.correction_learning import (
            learn_cluster_thresholds,
        )

        try:
            jsx_path_data = json.loads(layer_paths_json)
        except (json.JSONDecodeError, TypeError) as e:
            return json.dumps({"error": f"Invalid layer_paths_json: {e}"})

        if not isinstance(jsx_path_data, list) or not jsx_path_data:
            return json.dumps({"error": "layer_paths_json must be a non-empty array"})

        # Load sidecar data if available
        sidecar_data = None
        sidecar = sidecar_path
        if not sidecar and image_path:
            # Convention: sidecar lives next to the image with _sidecar.json suffix
            base, _ = os.path.splitext(image_path)
            candidate = base + "_sidecar.json"
            if os.path.isfile(candidate):
                sidecar = candidate
        if sidecar and os.path.isfile(sidecar):
            try:
                with open(sidecar) as f:
                    sidecar_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # proceed without sidecar

        # Parse into LayerPath objects
        layer_paths = enumerate_layer_paths(jsx_path_data, sidecar_data=sidecar_data)

        if not layer_paths:
            return json.dumps({
                "clusters": [],
                "cluster_count": 0,
                "path_count": 0,
            })

        # Compute boundary signatures if sidecar provides a normal map
        # (boundary signatures are optional — clustering works without them
        # using the fallback identity key from sidecar surface data)
        if sidecar_data and image_path:
            try:
                import numpy as np
                from adobe_mcp.apps.illustrator.analysis.boundary_signature import (
                    compute_boundary_signature,
                )
                # Load normal map and surface type map if cached alongside image
                base, _ = os.path.splitext(image_path)
                nmap_path = base + "_normal_map.npy"
                stmap_path = base + "_surface_type_map.npy"
                if os.path.isfile(nmap_path) and os.path.isfile(stmap_path):
                    normal_map = np.load(nmap_path)
                    surface_type_map = np.load(stmap_path)
                    for lp in layer_paths:
                        if lp.points:
                            lp.boundary_signature = compute_boundary_signature(
                                contour_points=lp.points,
                                normal_map=normal_map,
                                surface_type_map=surface_type_map,
                            )
            except (ImportError, OSError, ValueError):
                pass  # proceed without boundary signatures

        # Load learned thresholds for per-identity eps (S4)
        learned_thresholds = None
        try:
            learned_thresholds = learn_cluster_thresholds()
        except Exception:
            pass  # proceed without learned thresholds

        # Cluster
        clusters = cluster_paths(
            layer_paths,
            distance_threshold=distance_threshold,
            learned_thresholds=learned_thresholds,
        )

        # Build response in sa_colorClusters() JSON format
        cluster_json_str = generate_cluster_json(clusters)

        return json.dumps({
            "clusters": json.loads(cluster_json_str),
            "cluster_count": len(clusters),
            "path_count": len(layer_paths),
            "distance_threshold": distance_threshold,
            "jsx": generate_color_jsx(clusters),
        })
