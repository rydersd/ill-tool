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

// stb_image — already linked; just declare the functions we need
extern "C" {
    unsigned char* stbi_load(const char*, int*, int*, int*, int);
    void stbi_image_free(void*);
}

//========================================================================================
//  Module state
//========================================================================================

static const OrtApi* gOrtApi = nullptr;
static OrtEnv* gOrtEnv = nullptr;
static OrtSession* gDepthSession = nullptr;
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

    gOnnxAvailable = true;
    fprintf(stderr, "[ONNX] Initialized (depth=%s)\n", gDepthSession ? "yes" : "no");
    return true;
}

//========================================================================================
//  ONNX_Shutdown — release all ONNX Runtime resources
//========================================================================================

void ONNX_Shutdown(void)
{
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

    // Get output tensor data
    float* outputData = nullptr;
    gOrtApi->GetTensorMutableData(outputVal, (void**)&outputData);

    // Get output shape — typically [1, 518, 518] or [1, 1, 518, 518]
    OrtTensorTypeAndShapeInfo* outputInfo = nullptr;
    gOrtApi->GetTensorTypeAndShape(outputVal, &outputInfo);
    size_t numDims = 0;
    gOrtApi->GetDimensionsCount(outputInfo, &numDims);
    std::vector<int64_t> outputShape(numDims);
    gOrtApi->GetDimensions(outputInfo, outputShape.data(), numDims);
    gOrtApi->ReleaseTensorTypeAndShapeInfo(outputInfo);

    // Extract spatial dimensions from the last two axes
    int outH = modelSize, outW = modelSize;
    if (numDims >= 2) {
        outH = (int)outputShape[numDims - 2];
        outW = (int)outputShape[numDims - 1];
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
