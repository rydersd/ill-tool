//========================================================================================
//
//  OnnxVisionBridge.cpp — ONNX Runtime backend for VisionIntelligence
//
//  Loads Depth Anything V2 (int8 quantized) model via ONNX Runtime C API.
//  Performs depth estimation on input images, returning a normalized depth map.
//  On macOS, attempts CoreML execution provider for Neural Engine acceleration.
//
//  Compiled as C++ — included from IllToolPanels.mm (ObjC++ translation unit).
//  stb_image functions are already linked from VisionEngine.cpp / TraceModule.cpp.
//
//========================================================================================

#include "OnnxVisionBridge.h"
#include <onnxruntime/onnxruntime_c_api.h>
#include <onnxruntime/coreml_provider_factory.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>

// stb_image / stb_image_write — already linked; just declare the functions we need
extern "C" {
    unsigned char* stbi_load(const char*, int*, int*, int*, int);
    void stbi_image_free(void*);
    int stbi_write_png(const char*, int, int, int, const void*, int);
}

//========================================================================================
//  Module state
//========================================================================================

static const OrtApi* gOrtApi = nullptr;
static OrtEnv* gOrtEnv = nullptr;
static OrtSession* gDepthSession = nullptr;       // Depth Anything V2
static OrtSession* gMetric3dSession = nullptr;     // Metric3D v2
static OrtSessionOptions* gSessionOpts = nullptr;
static bool gOnnxAvailable = false;
static std::string gModelDir;

//========================================================================================
//  ONNX_Initialize — load ONNX Runtime, create env, load depth model
//========================================================================================

bool ONNX_Initialize(const char* modelDir)
{
    gModelDir = modelDir ? modelDir : "";

    gOrtApi = OrtGetApiBase()->GetApi(ORT_API_VERSION);
    if (!gOrtApi) {
        fprintf(stderr, "[ONNX] Failed to get ONNX Runtime API\n");
        return false;
    }

    OrtStatus* status = gOrtApi->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "IllTool", &gOrtEnv);
    if (status) {
        fprintf(stderr, "[ONNX] CreateEnv failed: %s\n", gOrtApi->GetErrorMessage(status));
        gOrtApi->ReleaseStatus(status);
        return false;
    }

    gOrtApi->CreateSessionOptions(&gSessionOpts);

    // Attempt CoreML execution provider on macOS (uses Apple Neural Engine when available)
#ifdef __APPLE__
    {
        uint32_t coreml_flags = COREML_FLAG_USE_NONE;  // Let CoreML choose optimal device
        status = OrtSessionOptionsAppendExecutionProvider_CoreML(gSessionOpts, coreml_flags);
        if (status) {
            fprintf(stderr, "[ONNX] CoreML provider not available, using CPU: %s\n",
                    gOrtApi->GetErrorMessage(status));
            gOrtApi->ReleaseStatus(status);
        } else {
            fprintf(stderr, "[ONNX] CoreML execution provider enabled\n");
        }
    }
#endif

    // Load depth model if available
    std::string depthModelPath = gModelDir + "/depth_anything_v2_small_int8.onnx";
    FILE* f = fopen(depthModelPath.c_str(), "r");
    if (f) {
        fclose(f);
        status = gOrtApi->CreateSession(gOrtEnv, depthModelPath.c_str(), gSessionOpts, &gDepthSession);
        if (status) {
            fprintf(stderr, "[ONNX] Failed to load depth model: %s\n", gOrtApi->GetErrorMessage(status));
            gOrtApi->ReleaseStatus(status);
            gDepthSession = nullptr;
        } else {
            fprintf(stderr, "[ONNX] Depth Anything V2 model loaded: %s\n", depthModelPath.c_str());
        }
    } else {
        fprintf(stderr, "[ONNX] Depth model not found at: %s\n", depthModelPath.c_str());
    }

    // Load Metric3D v2 model if available (lazy: session created but model loaded on first call)
    // We create the session eagerly to report availability, but it's a separate session from DA V2
    std::string metric3dPath = gModelDir + "/metric3d_v2_vit_small.onnx";
    FILE* f2 = fopen(metric3dPath.c_str(), "r");
    if (f2) {
        fclose(f2);
        // Metric3D needs its own session options (CoreML may not support all ops)
        OrtSessionOptions* metricOpts = nullptr;
        gOrtApi->CreateSessionOptions(&metricOpts);
#ifdef __APPLE__
        {
            uint32_t coreml_flags = COREML_FLAG_USE_NONE;
            OrtStatus* m3Status = OrtSessionOptionsAppendExecutionProvider_CoreML(metricOpts, coreml_flags);
            if (m3Status) {
                fprintf(stderr, "[ONNX] Metric3D: CoreML not available, using CPU: %s\n",
                        gOrtApi->GetErrorMessage(m3Status));
                gOrtApi->ReleaseStatus(m3Status);
            }
        }
#endif
        status = gOrtApi->CreateSession(gOrtEnv, metric3dPath.c_str(), metricOpts, &gMetric3dSession);
        gOrtApi->ReleaseSessionOptions(metricOpts);
        if (status) {
            fprintf(stderr, "[ONNX] Failed to load Metric3D model: %s\n", gOrtApi->GetErrorMessage(status));
            gOrtApi->ReleaseStatus(status);
            gMetric3dSession = nullptr;
        } else {
            fprintf(stderr, "[ONNX] Metric3D v2 model loaded: %s\n", metric3dPath.c_str());
        }
    } else {
        fprintf(stderr, "[ONNX] Metric3D model not found at: %s\n", metric3dPath.c_str());
    }

    gOnnxAvailable = true;
    fprintf(stderr, "[ONNX] Initialized (depth=%s, metric3d=%s)\n",
            gDepthSession ? "yes" : "no", gMetric3dSession ? "yes" : "no");
    return true;
}

//========================================================================================
//  ONNX_Shutdown — release all ONNX Runtime resources
//========================================================================================

void ONNX_Shutdown(void)
{
    if (gMetric3dSession) { gOrtApi->ReleaseSession(gMetric3dSession); gMetric3dSession = nullptr; }
    if (gDepthSession) { gOrtApi->ReleaseSession(gDepthSession); gDepthSession = nullptr; }
    if (gSessionOpts)  { gOrtApi->ReleaseSessionOptions(gSessionOpts); gSessionOpts = nullptr; }
    if (gOrtEnv)       { gOrtApi->ReleaseEnv(gOrtEnv); gOrtEnv = nullptr; }
    gOnnxAvailable = false;
    fprintf(stderr, "[ONNX] Shutdown complete\n");
}

//========================================================================================
//  ONNX_IsAvailable — true if runtime initialized and depth model loaded
//========================================================================================

bool ONNX_IsAvailable(void) { return gOnnxAvailable && gDepthSession != nullptr; }

//========================================================================================
//  ONNX_EstimateDepth — run Depth Anything V2 inference on an image
//
//  Input:  Image file path (any format stb_image supports)
//  Output: Normalized depth map (0.0=near, 1.0=far) at model resolution
//
//  The model expects [1, 3, H, W] float32 input with ImageNet normalization.
//  H and W must be multiples of 14 (DINOv2 patch size). We use 518x518.
//  Output shape is [1, 518, 518] or [1, 1, 518, 518].
//========================================================================================

bool ONNX_EstimateDepth(const char* imagePath, float** outDepthMap, int* outWidth, int* outHeight)
{
    if (!gDepthSession || !gOrtApi || !outDepthMap || !outWidth || !outHeight) return false;
    *outDepthMap = nullptr;
    *outWidth = *outHeight = 0;

    // Load image as RGB
    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* img = stbi_load(imagePath, &imgW, &imgH, &imgC, 3);
    if (!img) {
        fprintf(stderr, "[ONNX] Failed to load image: %s\n", imagePath);
        return false;
    }

    // Guard against buffer overflow in bilinear interpolation: need at least 2x2
    if (imgW < 2 || imgH < 2) {
        fprintf(stderr, "[OnnxVision] Image too small for depth estimation: %dx%d\n", imgW, imgH);
        stbi_image_free(img);
        return false;
    }

    fprintf(stderr, "[ONNX] Depth estimation: loaded %dx%d image (%d channels)\n", imgW, imgH, imgC);

    // Depth Anything V2 expects: [1, 3, H, W] float32
    // H, W must be multiples of 14. Standard: 518 = 14 * 37
    const int modelSize = 518;
    std::vector<float> inputTensor(1 * 3 * modelSize * modelSize);

    // ImageNet normalization constants
    static const float mean[] = {0.485f, 0.456f, 0.406f};
    static const float std_[] = {0.229f, 0.224f, 0.225f};

    // Bilinear resize + normalize to CHW format with ImageNet stats
    for (int c = 0; c < 3; c++) {
        for (int y = 0; y < modelSize; y++) {
            for (int x = 0; x < modelSize; x++) {
                float srcX = (float)x / modelSize * imgW;
                float srcY = (float)y / modelSize * imgH;
                int sx = (int)srcX;
                int sy = (int)srcY;
                if (sx >= imgW - 1) sx = imgW - 2;
                if (sy >= imgH - 1) sy = imgH - 2;
                if (sx < 0) sx = 0;
                if (sy < 0) sy = 0;

                float fx = srcX - sx;
                float fy = srcY - sy;

                // Bilinear interpolation of the channel value
                float v00 = img[(sy * imgW + sx) * 3 + c] / 255.0f;
                float v10 = img[(sy * imgW + sx + 1) * 3 + c] / 255.0f;
                float v01 = img[((sy + 1) * imgW + sx) * 3 + c] / 255.0f;
                float v11 = img[((sy + 1) * imgW + sx + 1) * 3 + c] / 255.0f;

                float val = v00 * (1-fx) * (1-fy) + v10 * fx * (1-fy) +
                            v01 * (1-fx) * fy + v11 * fx * fy;

                // ImageNet normalization: (val - mean) / std
                val = (val - mean[c]) / std_[c];

                inputTensor[c * modelSize * modelSize + y * modelSize + x] = val;
            }
        }
    }
    stbi_image_free(img);

    // Create input tensor
    OrtMemoryInfo* memInfo = nullptr;
    gOrtApi->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memInfo);

    int64_t inputShape[] = {1, 3, modelSize, modelSize};
    OrtValue* inputVal = nullptr;
    OrtStatus* status = gOrtApi->CreateTensorWithDataAsOrtValue(
        memInfo, inputTensor.data(), inputTensor.size() * sizeof(float),
        inputShape, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &inputVal);
    gOrtApi->ReleaseMemoryInfo(memInfo);

    if (status) {
        fprintf(stderr, "[ONNX] CreateTensor failed: %s\n", gOrtApi->GetErrorMessage(status));
        gOrtApi->ReleaseStatus(status);
        return false;
    }

    // Run inference
    // Model I/O names verified via onnx protobuf: input="pixel_values", output="predicted_depth"
    const char* inputNames[] = {"pixel_values"};
    const char* outputNames[] = {"predicted_depth"};
    OrtValue* outputVal = nullptr;

    fprintf(stderr, "[ONNX] Running depth inference...\n");
    status = gOrtApi->Run(gDepthSession, nullptr, inputNames, (const OrtValue* const*)&inputVal,
                          1, outputNames, 1, &outputVal);
    gOrtApi->ReleaseValue(inputVal);

    if (status) {
        fprintf(stderr, "[ONNX] Run failed: %s\n", gOrtApi->GetErrorMessage(status));
        gOrtApi->ReleaseStatus(status);
        return false;
    }

    // Validate output tensor type and shape before accessing data
    OrtTensorTypeAndShapeInfo* outputInfo = nullptr;
    gOrtApi->GetTensorTypeAndShape(outputVal, &outputInfo);

    ONNXTensorElementDataType elemType;
    gOrtApi->GetTensorElementType(outputInfo, &elemType);
    if (elemType != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
        fprintf(stderr, "[OnnxVision] Unexpected depth output type: %d (expected FLOAT)\n", (int)elemType);
        gOrtApi->ReleaseTensorTypeAndShapeInfo(outputInfo);
        gOrtApi->ReleaseValue(outputVal);
        return false;
    }

    size_t numDims = 0;
    gOrtApi->GetDimensionsCount(outputInfo, &numDims);
    if (numDims < 2 || numDims > 4) {
        fprintf(stderr, "[OnnxVision] Unexpected depth output rank: %zu (expected 2-4)\n", numDims);
        gOrtApi->ReleaseTensorTypeAndShapeInfo(outputInfo);
        gOrtApi->ReleaseValue(outputVal);
        return false;
    }

    std::vector<int64_t> outputShape(numDims);
    gOrtApi->GetDimensions(outputInfo, outputShape.data(), numDims);
    gOrtApi->ReleaseTensorTypeAndShapeInfo(outputInfo);

    // Get output tensor data
    float* outputData = nullptr;
    gOrtApi->GetTensorMutableData(outputVal, (void**)&outputData);
    if (!outputData) {
        fprintf(stderr, "[OnnxVision] Depth output tensor data is null\n");
        gOrtApi->ReleaseValue(outputVal);
        return false;
    }

    // Extract spatial dimensions from the last two axes
    int outH = (int)outputShape[numDims - 2];
    int outW = (int)outputShape[numDims - 1];
    if (outH <= 0 || outW <= 0) {
        fprintf(stderr, "[OnnxVision] Invalid depth output dimensions: %dx%d\n", outW, outH);
        gOrtApi->ReleaseValue(outputVal);
        return false;
    }

    fprintf(stderr, "[ONNX] Output shape: [");
    for (size_t i = 0; i < numDims; i++) {
        fprintf(stderr, "%lld%s", outputShape[i], i < numDims-1 ? ", " : "");
    }
    fprintf(stderr, "] => %dx%d depth map\n", outW, outH);

    int totalPixels = outW * outH;

    // Normalize depth to 0-1 range
    float minD = 1e30f, maxD = -1e30f;
    for (int i = 0; i < totalPixels; i++) {
        if (outputData[i] < minD) minD = outputData[i];
        if (outputData[i] > maxD) maxD = outputData[i];
    }

    float range = maxD - minD;
    if (range < 1e-6f) range = 1.0f;

    float* depthMap = (float*)calloc(totalPixels, sizeof(float));
    if (!depthMap) {
        fprintf(stderr, "[ONNX] Failed to allocate depth map (%d pixels)\n", totalPixels);
        gOrtApi->ReleaseValue(outputVal);
        return false;
    }

    for (int i = 0; i < totalPixels; i++) {
        depthMap[i] = (outputData[i] - minD) / range;  // 0=near, 1=far
    }

    gOrtApi->ReleaseValue(outputVal);

    *outDepthMap = depthMap;
    *outWidth = outW;
    *outHeight = outH;

    fprintf(stderr, "[ONNX] Depth estimated: %dx%d, range=[%.2f, %.2f]\n", outW, outH, minD, maxD);
    return true;
}

//========================================================================================
//  ONNX_FreeDepthMap — free a depth map allocated by ONNX_EstimateDepth
//========================================================================================

void ONNX_FreeDepthMap(float* depthMap) { free(depthMap); }

//========================================================================================
//  ONNX_HasMetricDepth — true if Metric3D v2 session is loaded
//========================================================================================

bool ONNX_HasMetricDepth(void) { return gOnnxAvailable && gMetric3dSession != nullptr; }

//========================================================================================
//  ONNX_EstimateMetricDepth — run Metric3D v2 inference on an image
//
//  Input:  Image file path (any format stb_image supports)
//  Output: Metric depth in meters [outH * outW], surface normals [outH * outW * 3] (CHW),
//          and per-pixel confidence [outH * outW].
//
//  The model expects [1, 3, H, W] float32 input with ImageNet normalization.
//  H and W should be multiples of 14 (ViT patch size). We use 518x518.
//  Outputs: predicted_depth [1, H_out, W_out], predicted_normal [1, 3, H_out, W_out],
//           normal_confidence [1, H_out, W_out].
//========================================================================================

bool ONNX_EstimateMetricDepth(const char* imagePath,
                              float** outDepth, int* outW, int* outH,
                              float** outNormals,
                              float** outConfidence)
{
    if (!gMetric3dSession || !gOrtApi || !outDepth || !outW || !outH) return false;
    *outDepth = nullptr;
    *outW = *outH = 0;
    if (outNormals) *outNormals = nullptr;
    if (outConfidence) *outConfidence = nullptr;

    // Load image as RGB
    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* img = stbi_load(imagePath, &imgW, &imgH, &imgC, 3);
    if (!img) {
        fprintf(stderr, "[OnnxVision] Metric3D: Failed to load image: %s\n", imagePath);
        return false;
    }

    // Guard against buffer overflow in bilinear interpolation: need at least 2x2
    if (imgW < 2 || imgH < 2) {
        fprintf(stderr, "[OnnxVision] Image too small for depth estimation: %dx%d\n", imgW, imgH);
        stbi_image_free(img);
        return false;
    }

    fprintf(stderr, "[OnnxVision] Metric3D: loaded %dx%d image (%d channels)\n", imgW, imgH, imgC);

    // Metric3D v2 expects: [1, 3, H, W] float32, multiples of 14
    // Use 518x518 (14 * 37) as the model's native resolution
    const int modelSize = 518;
    std::vector<float> inputTensor(1 * 3 * modelSize * modelSize);

    // ImageNet normalization constants
    static const float mean[] = {0.485f, 0.456f, 0.406f};
    static const float std_[] = {0.229f, 0.224f, 0.225f};

    // Bilinear resize + normalize to CHW format with ImageNet stats
    for (int c = 0; c < 3; c++) {
        for (int y = 0; y < modelSize; y++) {
            for (int x = 0; x < modelSize; x++) {
                float srcX = (float)x / modelSize * imgW;
                float srcY = (float)y / modelSize * imgH;
                int sx = (int)srcX;
                int sy = (int)srcY;
                if (sx >= imgW - 1) sx = imgW - 2;
                if (sy >= imgH - 1) sy = imgH - 2;
                if (sx < 0) sx = 0;
                if (sy < 0) sy = 0;

                float fx = srcX - sx;
                float fy = srcY - sy;

                // Bilinear interpolation
                float v00 = img[(sy * imgW + sx) * 3 + c] / 255.0f;
                float v10 = img[(sy * imgW + sx + 1) * 3 + c] / 255.0f;
                float v01 = img[((sy + 1) * imgW + sx) * 3 + c] / 255.0f;
                float v11 = img[((sy + 1) * imgW + sx + 1) * 3 + c] / 255.0f;

                float val = v00 * (1-fx) * (1-fy) + v10 * fx * (1-fy) +
                            v01 * (1-fx) * fy + v11 * fx * fy;

                // ImageNet normalization: (val - mean) / std
                val = (val - mean[c]) / std_[c];

                inputTensor[c * modelSize * modelSize + y * modelSize + x] = val;
            }
        }
    }
    stbi_image_free(img);

    // Create input tensor
    OrtMemoryInfo* memInfo = nullptr;
    gOrtApi->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memInfo);

    int64_t inputShape[] = {1, 3, modelSize, modelSize};
    OrtValue* inputVal = nullptr;
    OrtStatus* status = gOrtApi->CreateTensorWithDataAsOrtValue(
        memInfo, inputTensor.data(), inputTensor.size() * sizeof(float),
        inputShape, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &inputVal);
    gOrtApi->ReleaseMemoryInfo(memInfo);

    if (status) {
        fprintf(stderr, "[OnnxVision] Metric3D: CreateTensor failed: %s\n", gOrtApi->GetErrorMessage(status));
        gOrtApi->ReleaseStatus(status);
        return false;
    }

    // Run inference — Metric3D v2 has 3 outputs
    const char* inputNames[] = {"pixel_values"};
    const char* outputNames[] = {"predicted_depth", "predicted_normal", "normal_confidence"};
    OrtValue* outputVals[3] = {nullptr, nullptr, nullptr};

    fprintf(stderr, "[OnnxVision] Running Metric3D inference...\n");
    status = gOrtApi->Run(gMetric3dSession, nullptr, inputNames, (const OrtValue* const*)&inputVal,
                          1, outputNames, 3, outputVals);
    gOrtApi->ReleaseValue(inputVal);

    if (status) {
        fprintf(stderr, "[OnnxVision] Metric3D: Run failed: %s\n", gOrtApi->GetErrorMessage(status));
        gOrtApi->ReleaseStatus(status);
        return false;
    }

    // --- Validate and parse predicted_depth output [1, H_out, W_out] ---
    {
        OrtTensorTypeAndShapeInfo* depthTypeInfo = nullptr;
        gOrtApi->GetTensorTypeAndShape(outputVals[0], &depthTypeInfo);
        ONNXTensorElementDataType depthElemType;
        gOrtApi->GetTensorElementType(depthTypeInfo, &depthElemType);
        size_t depthRank = 0;
        gOrtApi->GetDimensionsCount(depthTypeInfo, &depthRank);
        gOrtApi->ReleaseTensorTypeAndShapeInfo(depthTypeInfo);

        if (depthElemType != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected depth output type: %d (expected FLOAT)\n", (int)depthElemType);
            for (int i = 0; i < 3; i++) if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
            return false;
        }
        if (depthRank < 2 || depthRank > 4) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected depth output rank: %zu (expected 2-4)\n", depthRank);
            for (int i = 0; i < 3; i++) if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
            return false;
        }
    }

    float* depthData = nullptr;
    gOrtApi->GetTensorMutableData(outputVals[0], (void**)&depthData);
    if (!depthData) {
        fprintf(stderr, "[OnnxVision] Metric3D: Depth output tensor data is null\n");
        for (int i = 0; i < 3; i++) if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
        return false;
    }

    OrtTensorTypeAndShapeInfo* depthInfo = nullptr;
    gOrtApi->GetTensorTypeAndShape(outputVals[0], &depthInfo);
    size_t depthDims = 0;
    gOrtApi->GetDimensionsCount(depthInfo, &depthDims);
    std::vector<int64_t> depthShape(depthDims);
    gOrtApi->GetDimensions(depthInfo, depthShape.data(), depthDims);
    gOrtApi->ReleaseTensorTypeAndShapeInfo(depthInfo);

    // Extract spatial dimensions from the last two axes
    int dH = (int)depthShape[depthDims - 2];
    int dW = (int)depthShape[depthDims - 1];
    if (dH <= 0 || dW <= 0) {
        fprintf(stderr, "[OnnxVision] Metric3D: Invalid depth output dimensions: %dx%d\n", dW, dH);
        for (int i = 0; i < 3; i++) if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
        return false;
    }

    fprintf(stderr, "[OnnxVision] Metric3D depth shape: [");
    for (size_t i = 0; i < depthDims; i++) {
        fprintf(stderr, "%lld%s", depthShape[i], i < depthDims-1 ? ", " : "");
    }
    fprintf(stderr, "] => %dx%d\n", dW, dH);

    int totalPixels = dW * dH;

    // Copy depth data (metric values in meters)
    float* depth = (float*)calloc(totalPixels, sizeof(float));
    if (!depth) {
        fprintf(stderr, "[OnnxVision] Metric3D: Failed to allocate depth (%d pixels)\n", totalPixels);
        for (int i = 0; i < 3; i++) if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
        return false;
    }
    memcpy(depth, depthData, totalPixels * sizeof(float));

    // --- Validate and parse predicted_normal output [1, 3, H_out, W_out] (CHW layout) ---
    float* normals = nullptr;
    if (outNormals && outputVals[1]) {
        OrtTensorTypeAndShapeInfo* normalTypeInfo = nullptr;
        gOrtApi->GetTensorTypeAndShape(outputVals[1], &normalTypeInfo);
        ONNXTensorElementDataType normalElemType;
        gOrtApi->GetTensorElementType(normalTypeInfo, &normalElemType);
        size_t normalRank = 0;
        gOrtApi->GetDimensionsCount(normalTypeInfo, &normalRank);
        gOrtApi->ReleaseTensorTypeAndShapeInfo(normalTypeInfo);

        if (normalElemType != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected normal output type: %d (expected FLOAT)\n", (int)normalElemType);
            // Non-fatal: skip normals but continue with depth
        } else if (normalRank < 3 || normalRank > 4) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected normal output rank: %zu (expected 3-4)\n", normalRank);
        } else {
            float* normalData = nullptr;
            gOrtApi->GetTensorMutableData(outputVals[1], (void**)&normalData);

            OrtTensorTypeAndShapeInfo* normalInfo = nullptr;
            gOrtApi->GetTensorTypeAndShape(outputVals[1], &normalInfo);
            size_t normalDims = 0;
            gOrtApi->GetDimensionsCount(normalInfo, &normalDims);
            std::vector<int64_t> normalShape(normalDims);
            gOrtApi->GetDimensions(normalInfo, normalShape.data(), normalDims);
            gOrtApi->ReleaseTensorTypeAndShapeInfo(normalInfo);

            fprintf(stderr, "[OnnxVision] Metric3D normal shape: [");
            for (size_t i = 0; i < normalDims; i++) {
                fprintf(stderr, "%lld%s", normalShape[i], i < normalDims-1 ? ", " : "");
            }
            fprintf(stderr, "]\n");

            if (normalData) {
                // Output is [1, 3, H, W] — 3 channels in CHW layout
                int normalPixels = dW * dH * 3;
                normals = (float*)calloc(normalPixels, sizeof(float));
                if (normals) {
                    memcpy(normals, normalData, normalPixels * sizeof(float));
                }
            } else {
                fprintf(stderr, "[OnnxVision] Metric3D: Normal output tensor data is null\n");
            }
        }
    }

    // --- Validate and parse normal_confidence output [1, H_out, W_out] ---
    float* confidence = nullptr;
    if (outConfidence && outputVals[2]) {
        OrtTensorTypeAndShapeInfo* confTypeInfo = nullptr;
        gOrtApi->GetTensorTypeAndShape(outputVals[2], &confTypeInfo);
        ONNXTensorElementDataType confElemType;
        gOrtApi->GetTensorElementType(confTypeInfo, &confElemType);
        size_t confRank = 0;
        gOrtApi->GetDimensionsCount(confTypeInfo, &confRank);
        gOrtApi->ReleaseTensorTypeAndShapeInfo(confTypeInfo);

        if (confElemType != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected confidence output type: %d (expected FLOAT)\n", (int)confElemType);
            // Non-fatal: skip confidence but continue
        } else if (confRank < 2 || confRank > 4) {
            fprintf(stderr, "[OnnxVision] Metric3D: Unexpected confidence output rank: %zu (expected 2-4)\n", confRank);
        } else {
            float* confData = nullptr;
            gOrtApi->GetTensorMutableData(outputVals[2], (void**)&confData);

            if (confData) {
                confidence = (float*)calloc(totalPixels, sizeof(float));
                if (confidence) {
                    memcpy(confidence, confData, totalPixels * sizeof(float));
                }
            } else {
                fprintf(stderr, "[OnnxVision] Metric3D: Confidence output tensor data is null\n");
            }
        }
    }

    // Release ONNX output values
    for (int i = 0; i < 3; i++) {
        if (outputVals[i]) gOrtApi->ReleaseValue(outputVals[i]);
    }

    // Report depth stats
    float minD = 1e30f, maxD = -1e30f;
    for (int i = 0; i < totalPixels; i++) {
        if (depth[i] < minD) minD = depth[i];
        if (depth[i] > maxD) maxD = depth[i];
    }
    fprintf(stderr, "[OnnxVision] Metric3D: %dx%d, depth range=[%.3f, %.3f] meters\n",
            dW, dH, minD, maxD);

    *outDepth = depth;
    *outW = dW;
    *outH = dH;
    if (outNormals) *outNormals = normals;
    if (outConfidence) *outConfidence = confidence;

    return true;
}

//========================================================================================
//  ONNX_SaveDepthMapPNG — convert metric depth to a grayscale PNG for visualization
//
//  Normalizes the depth range to 0-255. If minDepth/maxDepth are both 0, auto-detects
//  the range from the data.
//========================================================================================

bool ONNX_SaveDepthMapPNG(const float* depth, int w, int h,
                          const char* outPath, float minDepth, float maxDepth)
{
    if (!depth || w < 1 || h < 1 || !outPath) return false;

    // Auto-detect range if both are zero
    if (minDepth == 0.0f && maxDepth == 0.0f) {
        minDepth = 1e30f;
        maxDepth = -1e30f;
        for (int i = 0; i < w * h; i++) {
            if (depth[i] < minDepth) minDepth = depth[i];
            if (depth[i] > maxDepth) maxDepth = depth[i];
        }
    }

    float range = maxDepth - minDepth;
    if (range < 1e-6f) range = 1.0f;

    // Create grayscale image: near=bright (255), far=dark (0)
    std::vector<unsigned char> pixels(w * h);
    for (int i = 0; i < w * h; i++) {
        float normalized = (depth[i] - minDepth) / range;
        if (normalized < 0.0f) normalized = 0.0f;
        if (normalized > 1.0f) normalized = 1.0f;
        // Invert: near = bright, far = dark (more intuitive for visualization)
        pixels[i] = (unsigned char)((1.0f - normalized) * 255.0f);
    }

    int result = stbi_write_png(outPath, w, h, 1, pixels.data(), w);
    if (result) {
        fprintf(stderr, "[OnnxVision] Depth map saved: %s (%dx%d, range=[%.3f, %.3f]m)\n",
                outPath, w, h, minDepth, maxDepth);
    } else {
        fprintf(stderr, "[OnnxVision] Failed to save depth map: %s\n", outPath);
    }
    return result != 0;
}

//========================================================================================
//  ONNX_SaveNormalMapPNG — convert predicted normals to a standard normal map PNG
//
//  Input normals are in CHW layout: [3, H, W] with xyz components in range [-1, 1].
//  Output is standard normal map convention: R=x, G=y, B=z, centered at 128.
//  Pixels below confidence threshold get flat normal (128, 128, 255) = pointing straight up.
//========================================================================================

bool ONNX_SaveNormalMapPNG(const float* normals, int w, int h,
                           const char* outPath,
                           const float* confidence, float confidenceThreshold)
{
    if (!normals || w < 1 || h < 1 || !outPath) return false;

    int totalPixels = w * h;
    std::vector<unsigned char> pixels(totalPixels * 3);

    for (int i = 0; i < totalPixels; i++) {
        // Check confidence threshold
        if (confidence && confidence[i] < confidenceThreshold) {
            // Flat normal: (0, 0, 1) → RGB (128, 128, 255)
            pixels[i * 3]     = 128;
            pixels[i * 3 + 1] = 128;
            pixels[i * 3 + 2] = 255;
            continue;
        }

        // CHW layout: x at [0*H*W + i], y at [1*H*W + i], z at [2*H*W + i]
        float nx = normals[0 * totalPixels + i];
        float ny = normals[1 * totalPixels + i];
        float nz = normals[2 * totalPixels + i];

        // Clamp to [-1, 1]
        if (nx < -1.0f) nx = -1.0f; if (nx > 1.0f) nx = 1.0f;
        if (ny < -1.0f) ny = -1.0f; if (ny > 1.0f) ny = 1.0f;
        if (nz < -1.0f) nz = -1.0f; if (nz > 1.0f) nz = 1.0f;

        // Map [-1, 1] → [0, 255] (centered at 128)
        pixels[i * 3]     = (unsigned char)((nx * 0.5f + 0.5f) * 255.0f);
        pixels[i * 3 + 1] = (unsigned char)((ny * 0.5f + 0.5f) * 255.0f);
        pixels[i * 3 + 2] = (unsigned char)((nz * 0.5f + 0.5f) * 255.0f);
    }

    int result = stbi_write_png(outPath, w, h, 3, pixels.data(), w * 3);
    if (result) {
        fprintf(stderr, "[OnnxVision] Normal map saved: %s (%dx%d)\n", outPath, w, h);
    } else {
        fprintf(stderr, "[OnnxVision] Failed to save normal map: %s\n", outPath);
    }
    return result != 0;
}
