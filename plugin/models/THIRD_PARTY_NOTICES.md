# Third-Party Licenses

This document lists all third-party dependencies bundled with or linked by IllTool.

---

## Models

### Depth Anything V2
- **License**: Apache 2.0
- **Source**: https://github.com/DepthAnything/Depth-Anything-V2
- **ONNX export**: https://huggingface.co/onnx-community/depth-anything-v2-small
- **Files**: `depth_anything_v2_small_int8.onnx`
- **Citation**: Yang et al., "Depth Anything V2", 2024

### Metric3D v2
- **Upstream code license**: BSD-2-Clause
- **Upstream source**: https://github.com/YvanYin/Metric3D
- **ONNX model license**: CC0-1.0 (public domain dedication)
- **ONNX model source**: https://huggingface.co/onnx-community/metric3d-vit-small
- **Files**: `metric3d_v2_vit_small.onnx`
- **Citation**: Yin et al., "Metric3D v2: A Versatile Monocular Geometric Foundation Model", CVPR 2024

---

## Libraries

### ONNX Runtime
- **License**: MIT
- **Source**: https://github.com/microsoft/onnxruntime
- **Usage**: Linked dynamically via libonnxruntime.dylib, bundled in Resources/ for distribution
- **Note**: ONNX Runtime includes transitive third-party dependencies (Eigen, FlatBuffers, protobuf, etc.) covered under their respective licenses. See https://github.com/microsoft/onnxruntime/blob/main/ThirdPartyNotices.txt for the full list.

### cpp-httplib (httplib.h)
- **License**: MIT
- **Version**: 0.18.3
- **Source**: https://github.com/yhirose/cpp-httplib
- **Copyright**: (c) 2024 Yuji Hirose
- **Files**: `plugin/Source/vendor/httplib.h`

### nlohmann/json (json.hpp)
- **License**: MIT
- **Version**: 3.11.3
- **Source**: https://github.com/nlohmann/json
- **Copyright**: (c) 2013-2023 Niels Lohmann
- **Files**: `plugin/Source/vendor/json.hpp`

### stb_image / stb_image_write
- **License**: MIT / Public Domain (dual-licensed)
- **Source**: https://github.com/nothings/stb
- **Files**: `plugin/Source/vendor/stb_image.h`, `plugin/Source/vendor/stb_image_write.h`

### vtracer
- **License**: MIT
- **Source**: https://github.com/nicedraw/vtracer
- **Usage**: Called via subprocess for SVG vectorization
