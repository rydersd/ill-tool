#ifndef __ONNXVISIONBRIDGE_H__
#define __ONNXVISIONBRIDGE_H__

//========================================================================================
//  OnnxVisionBridge — ONNX Runtime backend for VisionIntelligence
//
//  Provides cross-platform ML inference via ONNX Runtime C API.
//  Currently implements Depth Anything V2 depth estimation.
//  On macOS, uses CoreML execution provider for Apple Neural Engine acceleration.
//
//  Pure C++ (no ObjC) — compiled via #include from IllToolPanels.mm.
//========================================================================================

#include "VisionIntelligence.h"

extern "C" {
    bool ONNX_Initialize(const char* modelDir);
    void ONNX_Shutdown(void);
    bool ONNX_IsAvailable(void);

    // Depth estimation via Depth Anything V2
    // Returns normalized depth map (0=near, 1=far) at model resolution
    bool ONNX_EstimateDepth(const char* imagePath, float** outDepthMap, int* outWidth, int* outHeight);
    void ONNX_FreeDepthMap(float* depthMap);
}

#endif // __ONNXVISIONBRIDGE_H__
