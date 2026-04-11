#ifndef __APPLEVISIONBRIDGE_H__
#define __APPLEVISIONBRIDGE_H__

//========================================================================================
//  AppleVisionBridge — macOS Vision framework backend for VisionIntelligence
//
//  These are called by VisionIntelligence.cpp dispatcher on macOS.
//  Implementation lives in AppleVisionBridge.mm (Objective-C++).
//========================================================================================

#include "VisionIntelligence.h"

extern "C" {
    VIBackend AVB_GetBackend(void);
    bool AVB_HasNeuralEngine(void);
    bool AVB_Initialize(void);
    void AVB_Shutdown(void);

    int AVB_DetectContours(const char* imagePath, float contrast, float pivot,
                           bool darkOnLight, VIContour** outContours);
    void AVB_FreeContours(VIContour* contours, int count);

    bool AVB_ExtractSubjectMask(const char* inputPath, const char* outputPath);
    int AVB_DetectInstances(const char* imagePath, VIInstanceMask** outMasks);
    void AVB_FreeInstanceMasks(VIInstanceMask* masks, int count);

    int AVB_DetectBodyPose(const char* imagePath, VIJoint** outJoints);
    void AVB_FreeJoints(VIJoint* joints, int count);

    int AVB_DetectFaceLandmarks(const char* imagePath, VIFacePoint** outPoints);
    void AVB_FreeFacePoints(VIFacePoint* points, int count);

    int AVB_DetectHandPose(const char* imagePath, VIJoint** outJoints);
}

#endif // __APPLEVISIONBRIDGE_H__
