#ifndef __VISIONINTELLIGENCE_H__
#define __VISIONINTELLIGENCE_H__

//========================================================================================
//  VisionIntelligence — Unified C-callable interface for ML vision operations
//
//  Common abstraction layer over platform-specific backends:
//    - Apple Vision (macOS, Neural Engine when available)
//    - ONNX Runtime (cross-platform, Phase 2)
//
//  All functions are extern "C" for easy linking from C++ modules.
//========================================================================================

#ifdef __cplusplus
extern "C" {
#endif

// --- Backend detection ---
typedef enum {
    VI_BACKEND_NONE          = 0,
    VI_BACKEND_APPLE_VISION  = 1,
    VI_BACKEND_ONNX_CUDA     = 2,
    VI_BACKEND_ONNX_COREML   = 3,
    VI_BACKEND_ONNX_DIRECTML = 4,
    VI_BACKEND_ONNX_CPU      = 5
} VIBackend;

VIBackend VIGetActiveBackend(void);
bool VIHasNeuralEngine(void);
bool VIHasContourDetection(void);
bool VIHasInstanceSegmentation(void);
bool VIHasPoseDetection(void);
bool VIHasDepthEstimation(void);

// --- Lifecycle ---
bool VIInitialize(void);
void VIShutdown(void);

// --- Contour Detection ---
typedef struct {
    double* points;     // interleaved x,y pairs (normalized 0-1)
    int pointCount;
    bool closed;
} VIContour;

/// Detect contours in an image. Returns number of contours found.
/// Caller must free with VIFreeContours().
int VIDetectContours(
    const char* imagePath,
    float contrastAdjustment,  // 0.0-3.0 (1.0 = no change)
    float contrastPivot,       // 0.0-1.0 (0.5 = mid gray)
    bool detectDarkOnLight,    // true for dark lines on light background
    VIContour** outContours
);
void VIFreeContours(VIContour* contours, int count);

// --- Instance Segmentation ---
typedef struct {
    unsigned char* mask;   // grayscale (0/255), width*height bytes
    int width, height;
    int instanceIndex;
    float score;
} VIInstanceMask;

/// Detect foreground instances. Returns number of instances.
int VIDetectInstances(const char* imagePath, VIInstanceMask** outMasks);
void VIFreeInstanceMasks(VIInstanceMask* masks, int count);

/// Get mask for the instance at normalized point (x,y).
int VISelectInstanceAtPoint(const char* imagePath, float x, float y, VIInstanceMask** outMask);

// --- Subject mask (legacy, wraps VisionCutout) ---
bool VIExtractSubjectMask(const char* inputImagePath, const char* outputMaskPath);

// --- Body Pose ---
typedef struct {
    const char* jointName;
    float x, y;           // normalized 0-1
    float confidence;
} VIJoint;

int VIDetectBodyPose(const char* imagePath, VIJoint** outJoints);
void VIFreeJoints(VIJoint* joints, int count);

// --- Face Landmarks ---
typedef struct { float x, y; } VIFacePoint;
int VIDetectFaceLandmarks(const char* imagePath, VIFacePoint** outPoints);
void VIFreeFacePoints(VIFacePoint* points, int count);

// --- Hand Pose ---
int VIDetectHandPose(const char* imagePath, VIJoint** outJoints);

// --- Depth Estimation (ONNX only, Phase 2.5) ---
bool VIEstimateDepth(const char* imagePath, float** outDepthMap, int* outWidth, int* outHeight);
void VIFreeDepthMap(float* depthMap);

// --- Metric Depth + Surface Normals (Metric3D v2, ONNX only) ---
// Returns true on success. Caller must free *outDepth, *outNormals, *outConfidence with free().
// outDepth:      float array [outH * outW], values in meters
// outNormals:    float array [outH * outW * 3], CHW layout (x,y,z planes), components -1 to 1
// outConfidence: float array [outH * outW], per-pixel confidence 0-1 (can be NULL if not needed)
bool VIEstimateMetricDepth(const char* imagePath,
                           float** outDepth, int* outW, int* outH,
                           float** outNormals,
                           float** outConfidence);

// Convert metric depth to a grayscale PNG for visualization.
// minDepth/maxDepth: range for normalization (0 = auto-detect from data)
bool VISaveDepthMapPNG(const float* depth, int w, int h,
                       const char* outPath,
                       float minDepth, float maxDepth);

// Convert predicted normals to a standard normal map PNG (128-centered RGB).
// confidence can be NULL; if non-NULL, pixels below confidenceThreshold are set to flat normal.
bool VISaveNormalMapPNG(const float* normals, int w, int h,
                        const char* outPath,
                        const float* confidence, float confidenceThreshold);

bool VIHasMetricDepth(void);

#ifdef __cplusplus
}
#endif

#endif // __VISIONINTELLIGENCE_H__
