"""ML backends for illustration analysis (optional dependencies).

Each backend module handles its own graceful fallback when ML
dependencies are not installed.

Backends:
- normal_estimator: DSINE surface normal prediction (torch)
- edge_classifier: RINDNet++ edge type classification (torch + rindnet research repo)
- informative_draw: Informative Drawings line extraction (onnxruntime)
"""
