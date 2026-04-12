//========================================================================================
//
//  VisionIntelligence.cpp — Platform dispatcher for ML vision operations
//
//  Routes all VI* calls to the active backend (Apple Vision on macOS,
//  ONNX Runtime on other platforms in Phase 2).
//
//========================================================================================

#include "VisionIntelligence.h"
#include <cstdlib>
#include <cstdio>
#include <string>

#ifdef __APPLE__
#include "AppleVisionBridge.h"
#endif

// ONNX Runtime backend — provides depth estimation on all platforms
#include "OnnxVisionBridge.h"

static VIBackend sActiveBackend = VI_BACKEND_NONE;

//========================================================================================
//  Lifecycle
//========================================================================================

bool VIInitialize(void)
{
#ifdef __APPLE__
    sActiveBackend = AVB_GetBackend();
    AVB_Initialize();
#else
    fprintf(stderr, "[VisionIntelligence] No Apple Vision backend on this platform\n");
#endif

    // Initialize ONNX Runtime backend (provides depth estimation on all platforms)
    // Look for models in the plugin's models directory
    {
        std::string modelDir;
#ifdef __APPLE__
        // Dev path — at runtime, could also check plugin bundle Resources
        modelDir = "/Users/ryders/Developer/GitHub/ill_tool/plugin/models";
#endif
        ONNX_Initialize(modelDir.c_str());
    }

    return sActiveBackend != VI_BACKEND_NONE || ONNX_IsAvailable();
}

void VIShutdown(void)
{
    ONNX_Shutdown();
#ifdef __APPLE__
    AVB_Shutdown();
#endif
    sActiveBackend = VI_BACKEND_NONE;
}

//========================================================================================
//  Capability queries
//========================================================================================

VIBackend VIGetActiveBackend(void) { return sActiveBackend; }

bool VIHasNeuralEngine(void)
{
#ifdef __APPLE__
    return AVB_HasNeuralEngine();
#else
    return false;
#endif
}

bool VIHasContourDetection(void)       { return sActiveBackend != VI_BACKEND_NONE; }
bool VIHasInstanceSegmentation(void)   { return VIHasNeuralEngine(); }
bool VIHasPoseDetection(void)          { return sActiveBackend != VI_BACKEND_NONE; }
bool VIHasDepthEstimation(void)        { return ONNX_IsAvailable(); }

//========================================================================================
//  Contour Detection
//========================================================================================

int VIDetectContours(const char* imagePath, float contrast, float pivot,
                     bool darkOnLight, VIContour** outContours)
{
#ifdef __APPLE__
    return AVB_DetectContours(imagePath, contrast, pivot, darkOnLight, outContours);
#else
    *outContours = NULL;
    return 0;
#endif
}

void VIFreeContours(VIContour* c, int n)
{
#ifdef __APPLE__
    AVB_FreeContours(c, n);
#else
    if (!c) return;
    for (int i = 0; i < n; i++) free(c[i].points);
    free(c);
#endif
}

//========================================================================================
//  Subject Mask (legacy wrapper)
//========================================================================================

bool VIExtractSubjectMask(const char* in, const char* out)
{
#ifdef __APPLE__
    return AVB_ExtractSubjectMask(in, out);
#else
    return false;
#endif
}

//========================================================================================
//  Instance Segmentation
//========================================================================================

int VIDetectInstances(const char* p, VIInstanceMask** m)
{
#ifdef __APPLE__
    return AVB_DetectInstances(p, m);
#else
    *m = NULL;
    return 0;
#endif
}

void VIFreeInstanceMasks(VIInstanceMask* m, int n)
{
#ifdef __APPLE__
    AVB_FreeInstanceMasks(m, n);
#else
    if (!m) return;
    for (int i = 0; i < n; i++) free(m[i].mask);
    free(m);
#endif
}

int VISelectInstanceAtPoint(const char* p, float x, float y, VIInstanceMask** m)
{
    *m = NULL;
    return 0; // Phase 3
}

//========================================================================================
//  Body Pose
//========================================================================================

int VIDetectBodyPose(const char* p, VIJoint** j)
{
#ifdef __APPLE__
    return AVB_DetectBodyPose(p, j);
#else
    *j = NULL;
    return 0;
#endif
}

void VIFreeJoints(VIJoint* j, int n)
{
#ifdef __APPLE__
    AVB_FreeJoints(j, n);
#else
    free(j);
#endif
}

//========================================================================================
//  Face Landmarks
//========================================================================================

int VIDetectFaceLandmarks(const char* p, VIFacePoint** pts)
{
#ifdef __APPLE__
    return AVB_DetectFaceLandmarks(p, pts);
#else
    *pts = NULL;
    return 0;
#endif
}

void VIFreeFacePoints(VIFacePoint* p, int n)
{
#ifdef __APPLE__
    AVB_FreeFacePoints(p, n);
#else
    free(p);
#endif
}

//========================================================================================
//  Hand Pose
//========================================================================================

int VIDetectHandPose(const char* p, VIJoint** j)
{
#ifdef __APPLE__
    return AVB_DetectHandPose(p, j);
#else
    *j = NULL;
    return 0;
#endif
}

//========================================================================================
//  Depth Estimation — via ONNX Runtime (Depth Anything V2)
//========================================================================================

bool VIEstimateDepth(const char* p, float** d, int* w, int* h)
{
    return ONNX_EstimateDepth(p, d, w, h);
}

void VIFreeDepthMap(float* d)
{
    ONNX_FreeDepthMap(d);
}

//========================================================================================
//  Metric Depth + Surface Normals — via ONNX Runtime (Metric3D v2)
//========================================================================================

bool VIEstimateMetricDepth(const char* imagePath,
                           float** outDepth, int* outW, int* outH,
                           float** outNormals,
                           float** outConfidence)
{
    return ONNX_EstimateMetricDepth(imagePath, outDepth, outW, outH, outNormals, outConfidence);
}

bool VISaveDepthMapPNG(const float* depth, int w, int h,
                       const char* outPath,
                       float minDepth, float maxDepth)
{
    return ONNX_SaveDepthMapPNG(depth, w, h, outPath, minDepth, maxDepth);
}

bool VISaveNormalMapPNG(const float* normals, int w, int h,
                        const char* outPath,
                        const float* confidence, float confidenceThreshold)
{
    return ONNX_SaveNormalMapPNG(normals, w, h, outPath, confidence, confidenceThreshold);
}

bool VIHasMetricDepth(void)
{
    return ONNX_HasMetricDepth();
}
