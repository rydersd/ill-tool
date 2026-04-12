//========================================================================================
//
//  AppleVisionBridge.mm — macOS Vision framework backend for VisionIntelligence
//
//  Implements contour detection using VNDetectContoursRequest (macOS 11+),
//  subject segmentation via VisionCutout wrapper, body pose detection via
//  VNDetectHumanBodyPoseRequest (macOS 11+), face landmarks via
//  VNDetectFaceLandmarksRequest (macOS 11+), and hand pose via
//  VNDetectHumanHandPoseRequest (macOS 12+).
//
//  Compiled as Objective-C++ (.mm) — included from IllToolPanels.mm which is in the
//  ObjC++ translation unit.
//
//  Memory: Manual retain-release (MRR) — no ARC in the Illustrator SDK project.
//
//========================================================================================

#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <AppKit/AppKit.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "AppleVisionBridge.h"
#include "VisionCutout.h"

//========================================================================================
//  AVB_GetBackend
//========================================================================================

extern "C" VIBackend AVB_GetBackend(void)
{
    return VI_BACKEND_APPLE_VISION;
}

//========================================================================================
//  AVB_HasNeuralEngine — ARM-based Macs have Neural Engine
//========================================================================================

extern "C" bool AVB_HasNeuralEngine(void)
{
#ifdef __aarch64__
    return true;
#else
    return false;
#endif
}

//========================================================================================
//  AVB_Initialize / AVB_Shutdown
//========================================================================================

extern "C" bool AVB_Initialize(void)
{
    fprintf(stderr, "[AppleVision] Backend initialized (Neural Engine: %s)\n",
            AVB_HasNeuralEngine() ? "yes" : "no");
    return true;
}

extern "C" void AVB_Shutdown(void)
{
    fprintf(stderr, "[AppleVision] Backend shutdown\n");
}

//========================================================================================
//  AVB_DetectContours — Apple Vision contour detection (macOS 11+)
//
//  Uses VNDetectContoursRequest to find edge contours in an image.
//  Returns normalized (0-1) point coordinates in VIContour structs.
//========================================================================================

extern "C" int AVB_DetectContours(const char* imagePath, float contrast, float pivot,
                                   bool darkOnLight, VIContour** outContours)
{
    @autoreleasepool {
        *outContours = NULL;

        // Load image
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:imagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:url];
        if (!nsImage) {
            fprintf(stderr, "[AppleVision] DetectContours: failed to load image: %s\n", imagePath);
            return 0;
        }

        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[AppleVision] DetectContours: failed to get CGImage\n");
            [nsImage release];
            return 0;
        }

        if (@available(macOS 11.0, *)) {
            VNDetectContoursRequest *request = [[VNDetectContoursRequest alloc] init];
            request.contrastAdjustment = contrast;
            request.contrastPivot = @(pivot);
            request.detectsDarkOnLight = darkOnLight;

            VNImageRequestHandler *handler = [[VNImageRequestHandler alloc]
                initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            [handler performRequests:@[request] error:&error];

            if (error) {
                fprintf(stderr, "[AppleVision] Contour detection failed: %s\n",
                        [[error localizedDescription] UTF8String]);
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            VNContoursObservation *obs = (VNContoursObservation *)request.results.firstObject;
            if (!obs) {
                fprintf(stderr, "[AppleVision] DetectContours: no observation returned\n");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            // Log total contour count for diagnostics
            NSInteger contourCount = obs.contourCount;
            fprintf(stderr, "[AppleVision] Detected %ld total contours\n", (long)contourCount);

            // Collect top-level contours + their children (holes, inner shapes)
            NSInteger topLevelCount = obs.topLevelContourCount;
            NSMutableArray<VNContour *> *allContours = [[NSMutableArray alloc] init];

            for (NSInteger i = 0; i < topLevelCount; i++) {
                NSError *err = nil;
                VNContour *c = [obs contourAtIndex:i error:&err];
                if (c && !err) {
                    [allContours addObject:c];
                    // Also add child contours (holes, inner shapes)
                    for (NSInteger j = 0; j < c.childContourCount; j++) {
                        VNContour *child = [c childContourAtIndex:j error:&err];
                        if (child && !err) {
                            [allContours addObject:child];
                        }
                    }
                }
            }

            int count = (int)allContours.count;
            if (count == 0) {
                fprintf(stderr, "[AppleVision] DetectContours: no contours collected\n");
                [allContours release];
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            fprintf(stderr, "[AppleVision] Collecting %d contours (top-level + children)\n", count);

            VIContour* contours = (VIContour*)calloc(count, sizeof(VIContour));

            for (int i = 0; i < count; i++) {
                VNContour *c = allContours[i];
                // Get the normalized path
                CGPathRef path = c.normalizedPath;

                // Extract points from CGPath using CGPathApplyWithBlock
                NSMutableArray<NSValue *> *points = [[NSMutableArray alloc] init];

                CGPathApplyWithBlock(path, ^(const CGPathElement *element) {
                    switch (element->type) {
                        case kCGPathElementMoveToPoint:
                        case kCGPathElementAddLineToPoint:
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[0].x, element->points[0].y)]];
                            break;
                        case kCGPathElementAddCurveToPoint:
                            // For cubic bezier: add control points and endpoint
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[0].x, element->points[0].y)]];
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[1].x, element->points[1].y)]];
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[2].x, element->points[2].y)]];
                            break;
                        case kCGPathElementAddQuadCurveToPoint:
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[0].x, element->points[0].y)]];
                            [points addObject:[NSValue valueWithPoint:
                                NSMakePoint(element->points[1].x, element->points[1].y)]];
                            break;
                        case kCGPathElementCloseSubpath:
                            break;
                    }
                });

                contours[i].pointCount = (int)points.count;
                contours[i].points = (double*)calloc(points.count * 2, sizeof(double));
                contours[i].closed = true;  // contours are always closed

                for (int j = 0; j < (int)points.count; j++) {
                    NSPoint p = [points[j] pointValue];
                    contours[i].points[j * 2]     = p.x;  // normalized 0-1
                    contours[i].points[j * 2 + 1] = p.y;  // normalized 0-1
                }

                [points release];
            }

            *outContours = contours;
            [allContours release];
            [handler release];
            [request release];
            [nsImage release];
            return count;
        }

        // macOS < 11.0 — contour detection not available
        fprintf(stderr, "[AppleVision] DetectContours: requires macOS 11.0+\n");
        [nsImage release];
        return 0;
    }
}

//========================================================================================
//  AVB_FreeContours
//========================================================================================

extern "C" void AVB_FreeContours(VIContour* contours, int count)
{
    if (!contours) return;
    for (int i = 0; i < count; i++) {
        free(contours[i].points);
    }
    free(contours);
}

//========================================================================================
//  AVB_ExtractSubjectMask — wraps existing VisionCutout functionality
//========================================================================================

extern "C" bool AVB_ExtractSubjectMask(const char* inputPath, const char* outputPath)
{
    return VisionExtractSubjectMask(inputPath, outputPath);
}

//========================================================================================
//  AVB_DetectInstances — per-instance foreground masks via VNGenerateForegroundInstanceMaskRequest
//
//  Returns one VIInstanceMask per detected foreground instance.  Each mask is a uint8
//  buffer (width*height bytes) with 0 = background, 255 = instance.
//  Requires macOS 14.0+ (Apple Silicon Neural Engine).
//========================================================================================

extern "C" int AVB_DetectInstances(const char* imagePath, VIInstanceMask** outMasks)
{
    @autoreleasepool {
        *outMasks = NULL;

        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:imagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:url];
        if (!nsImage) {
            fprintf(stderr, "[AppleVision] DetectInstances: failed to load image: %s\n", imagePath);
            return 0;
        }

        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[AppleVision] DetectInstances: failed to get CGImage\n");
            [nsImage release];
            return 0;
        }

        if (@available(macOS 14.0, *)) {
            VNGenerateForegroundInstanceMaskRequest *request =
                [[VNGenerateForegroundInstanceMaskRequest alloc] init];
            VNImageRequestHandler *handler =
                [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            [handler performRequests:@[request] error:&error];

            if (error || request.results.count == 0) {
                fprintf(stderr, "[AppleVision] DetectInstances: Vision request failed%s%s\n",
                        error ? ": " : "",
                        error ? [[error localizedDescription] UTF8String] : "");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            VNInstanceMaskObservation *observation = request.results.firstObject;
            NSIndexSet *allIndices = observation.allInstances;
            int count = (int)allIndices.count;

            if (count == 0) {
                fprintf(stderr, "[AppleVision] DetectInstances: no foreground instances\n");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            fprintf(stderr, "[AppleVision] DetectInstances: found %d instance(s)\n", count);

            VIInstanceMask* masks = (VIInstanceMask*)calloc(count, sizeof(VIInstanceMask));

            __block int idx = 0;
            [allIndices enumerateIndexesUsingBlock:^(NSUInteger instanceIdx, BOOL *stop) {
                NSError *err = nil;
                NSIndexSet *singleInstance = [NSIndexSet indexSetWithIndex:instanceIdx];

                CVPixelBufferRef maskBuffer = [observation
                    generateScaledMaskForImageForInstances:singleInstance
                    fromRequestHandler:handler
                    error:&err];

                if (err || !maskBuffer) {
                    fprintf(stderr, "[AppleVision] Instance %d: mask generation failed\n",
                            (int)instanceIdx);
                    masks[idx].mask = NULL;
                    masks[idx].width = 0;
                    masks[idx].height = 0;
                    masks[idx].instanceIndex = (int)instanceIdx;
                    masks[idx].score = 0.0f;
                    idx++;
                    return;
                }

                CVPixelBufferLockBaseAddress(maskBuffer, kCVPixelBufferLock_ReadOnly);
                size_t maskW = CVPixelBufferGetWidth(maskBuffer);
                size_t maskH = CVPixelBufferGetHeight(maskBuffer);
                void* baseAddr = CVPixelBufferGetBaseAddress(maskBuffer);
                size_t bytesPerRow = CVPixelBufferGetBytesPerRow(maskBuffer);

                // Allocate uint8 mask and threshold from pixel buffer
                unsigned char* maskData = (unsigned char*)calloc(maskW * maskH, 1);

                OSType pixelFormat = CVPixelBufferGetPixelFormatType(maskBuffer);
                if (pixelFormat == kCVPixelFormatType_OneComponent8) {
                    for (size_t y = 0; y < maskH; y++) {
                        unsigned char* row = (unsigned char*)baseAddr + y * bytesPerRow;
                        for (size_t x = 0; x < maskW; x++) {
                            maskData[y * maskW + x] = (row[x] > 128) ? 255 : 0;
                        }
                    }
                } else if (pixelFormat == kCVPixelFormatType_OneComponent32Float) {
                    for (size_t y = 0; y < maskH; y++) {
                        float* row = (float*)((unsigned char*)baseAddr + y * bytesPerRow);
                        for (size_t x = 0; x < maskW; x++) {
                            maskData[y * maskW + x] = (row[x] > 0.5f) ? 255 : 0;
                        }
                    }
                }

                CVPixelBufferUnlockBaseAddress(maskBuffer, kCVPixelBufferLock_ReadOnly);

                masks[idx].mask = maskData;
                masks[idx].width = (int)maskW;
                masks[idx].height = (int)maskH;
                masks[idx].instanceIndex = (int)instanceIdx;
                masks[idx].score = 1.0f;

                fprintf(stderr, "[AppleVision] Instance %d: %dx%d mask\n",
                        (int)instanceIdx, (int)maskW, (int)maskH);
                idx++;
            }];

            *outMasks = masks;
            [handler release];
            [request release];
            [nsImage release];
            return count;
        }

        fprintf(stderr, "[AppleVision] DetectInstances: requires macOS 14.0+\n");
        [nsImage release];
        return 0;
    }
}

extern "C" void AVB_FreeInstanceMasks(VIInstanceMask* masks, int count)
{
    if (!masks) return;
    for (int i = 0; i < count; i++) {
        free(masks[i].mask);
    }
    free(masks);
}

//========================================================================================
//  AVB_DetectBodyPose — VNDetectHumanBodyPoseRequest (macOS 11+)
//
//  Extracts COCO-compatible body keypoints. Returns normalized (0-1) coordinates.
//  Vision uses bottom-left origin — consumer must flip Y if needed.
//========================================================================================

extern "C" int AVB_DetectBodyPose(const char* imagePath, VIJoint** outJoints)
{
    @autoreleasepool {
        *outJoints = NULL;

        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:imagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:url];
        if (!nsImage) {
            fprintf(stderr, "[AppleVision] DetectBodyPose: failed to load image: %s\n", imagePath);
            return 0;
        }

        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[AppleVision] DetectBodyPose: failed to get CGImage\n");
            [nsImage release];
            return 0;
        }

        if (@available(macOS 11.0, *)) {
            VNDetectHumanBodyPoseRequest *request = [[VNDetectHumanBodyPoseRequest alloc] init];
            VNImageRequestHandler *handler = [[VNImageRequestHandler alloc]
                initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            [handler performRequests:@[request] error:&error];

            if (error || request.results.count == 0) {
                fprintf(stderr, "[AppleVision] No body pose detected%s%s\n",
                        error ? ": " : "",
                        error ? [[error localizedDescription] UTF8String] : "");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            VNHumanBodyPoseObservation *obs = request.results.firstObject;

            // COCO-compatible keypoint names we want to extract
            NSArray<VNHumanBodyPoseObservationJointName> *jointNames = @[
                VNHumanBodyPoseObservationJointNameNose,
                VNHumanBodyPoseObservationJointNameNeck,
                VNHumanBodyPoseObservationJointNameLeftShoulder,
                VNHumanBodyPoseObservationJointNameRightShoulder,
                VNHumanBodyPoseObservationJointNameLeftElbow,
                VNHumanBodyPoseObservationJointNameRightElbow,
                VNHumanBodyPoseObservationJointNameLeftWrist,
                VNHumanBodyPoseObservationJointNameRightWrist,
                VNHumanBodyPoseObservationJointNameLeftHip,
                VNHumanBodyPoseObservationJointNameRightHip,
                VNHumanBodyPoseObservationJointNameLeftKnee,
                VNHumanBodyPoseObservationJointNameRightKnee,
                VNHumanBodyPoseObservationJointNameLeftAnkle,
                VNHumanBodyPoseObservationJointNameRightAnkle,
                VNHumanBodyPoseObservationJointNameLeftEar,
                VNHumanBodyPoseObservationJointNameRightEar,
                VNHumanBodyPoseObservationJointNameLeftEye,
                VNHumanBodyPoseObservationJointNameRightEye,
                VNHumanBodyPoseObservationJointNameRoot  // center of hips
            ];

            // C string names for each joint (must match order above)
            static const char* jointCNames[] = {
                "nose", "neck",
                "left_shoulder", "right_shoulder",
                "left_elbow", "right_elbow",
                "left_wrist", "right_wrist",
                "left_hip", "right_hip",
                "left_knee", "right_knee",
                "left_ankle", "right_ankle",
                "left_ear", "right_ear",
                "left_eye", "right_eye",
                "root"
            };

            int maxJoints = (int)jointNames.count;
            VIJoint* joints = (VIJoint*)calloc(maxJoints, sizeof(VIJoint));
            int found = 0;

            for (int i = 0; i < maxJoints; i++) {
                NSError *err = nil;
                VNRecognizedPoint *point = [obs recognizedPointForJointName:jointNames[i] error:&err];
                if (point && !err && point.confidence > 0.1) {
                    // strdup so AVB_FreeJoints can safely free all joint names
                    joints[found].jointName = strdup(jointCNames[i]);
                    joints[found].x = point.location.x;      // normalized 0-1
                    joints[found].y = point.location.y;      // normalized 0-1, bottom-left origin
                    joints[found].confidence = point.confidence;
                    found++;
                }
            }

            fprintf(stderr, "[AppleVision] Body pose: %d/%d joints detected\n", found, maxJoints);
            *outJoints = joints;
            [handler release];
            [request release];
            [nsImage release];
            return found;
        }

        fprintf(stderr, "[AppleVision] DetectBodyPose: requires macOS 11.0+\n");
        [nsImage release];
        return 0;
    }
}

//========================================================================================
//  AVB_FreeJoints — free joint array with strdup'd names
//========================================================================================

extern "C" void AVB_FreeJoints(VIJoint* joints, int count)
{
    if (!joints) return;
    for (int i = 0; i < count; i++) {
        free((void*)joints[i].jointName);  // strdup'd in detect functions
    }
    free(joints);
}

//========================================================================================
//  AVB_DetectFaceLandmarks — VNDetectFaceLandmarksRequest (macOS 11+)
//
//  Returns all face landmark points for the first detected face.
//  Points are converted from face-bounding-box-relative to image-level normalized coords.
//========================================================================================

extern "C" int AVB_DetectFaceLandmarks(const char* imagePath, VIFacePoint** outPoints)
{
    @autoreleasepool {
        *outPoints = NULL;

        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:imagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:url];
        if (!nsImage) {
            fprintf(stderr, "[AppleVision] DetectFaceLandmarks: failed to load image: %s\n", imagePath);
            return 0;
        }

        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[AppleVision] DetectFaceLandmarks: failed to get CGImage\n");
            [nsImage release];
            return 0;
        }

        if (@available(macOS 11.0, *)) {
            VNDetectFaceLandmarksRequest *request = [[VNDetectFaceLandmarksRequest alloc] init];
            VNImageRequestHandler *handler = [[VNImageRequestHandler alloc]
                initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            [handler performRequests:@[request] error:&error];

            if (error || request.results.count == 0) {
                fprintf(stderr, "[AppleVision] No face detected%s%s\n",
                        error ? ": " : "",
                        error ? [[error localizedDescription] UTF8String] : "");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            // Get first face
            VNFaceObservation *face = request.results.firstObject;
            VNFaceLandmarks2D *landmarks = face.landmarks;
            if (!landmarks) {
                fprintf(stderr, "[AppleVision] DetectFaceLandmarks: no landmarks on face observation\n");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            // Get all points from allPoints region
            VNFaceLandmarkRegion2D *allPoints = landmarks.allPoints;
            if (!allPoints) {
                fprintf(stderr, "[AppleVision] DetectFaceLandmarks: allPoints region is nil\n");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            NSUInteger pointCount = allPoints.pointCount;
            const CGPoint *rawPoints = allPoints.normalizedPoints;

            // Face landmarks are in face bounding box coordinates — convert to image coordinates
            CGRect faceBounds = face.boundingBox;  // normalized 0-1 in image coords

            VIFacePoint* points = (VIFacePoint*)calloc(pointCount, sizeof(VIFacePoint));
            for (NSUInteger i = 0; i < pointCount; i++) {
                // rawPoints are normalized within the face bounding box
                // Convert to image-level normalized coordinates
                points[i].x = faceBounds.origin.x + rawPoints[i].x * faceBounds.size.width;
                points[i].y = faceBounds.origin.y + rawPoints[i].y * faceBounds.size.height;
            }

            fprintf(stderr, "[AppleVision] Face landmarks: %lu points (face bbox: %.2f,%.2f %.2fx%.2f)\n",
                    (unsigned long)pointCount,
                    faceBounds.origin.x, faceBounds.origin.y,
                    faceBounds.size.width, faceBounds.size.height);
            *outPoints = points;
            [handler release];
            [request release];
            [nsImage release];
            return (int)pointCount;
        }

        fprintf(stderr, "[AppleVision] DetectFaceLandmarks: requires macOS 11.0+\n");
        [nsImage release];
        return 0;
    }
}

//========================================================================================
//  AVB_FreeFacePoints
//========================================================================================

extern "C" void AVB_FreeFacePoints(VIFacePoint* points, int count)
{
    free(points);
}

//========================================================================================
//  AVB_DetectHandPose — VNDetectHumanHandPoseRequest (macOS 12+)
//
//  Detects up to 2 hands with 21 keypoints each (wrist + 4 joints x 5 fingers).
//  Joint names are prefixed with hand index: "hand0_VNHLJ...", "hand1_VNHLJ..."
//  Uses strdup for names — AVB_FreeJoints will free them.
//========================================================================================

extern "C" int AVB_DetectHandPose(const char* imagePath, VIJoint** outJoints)
{
    @autoreleasepool {
        *outJoints = NULL;

        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:imagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:url];
        if (!nsImage) {
            fprintf(stderr, "[AppleVision] DetectHandPose: failed to load image: %s\n", imagePath);
            return 0;
        }

        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[AppleVision] DetectHandPose: failed to get CGImage\n");
            [nsImage release];
            return 0;
        }

        if (@available(macOS 12.0, *)) {
            VNDetectHumanHandPoseRequest *request = [[VNDetectHumanHandPoseRequest alloc] init];
            request.maximumHandCount = 2;

            VNImageRequestHandler *handler = [[VNImageRequestHandler alloc]
                initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            [handler performRequests:@[request] error:&error];

            if (error || request.results.count == 0) {
                fprintf(stderr, "[AppleVision] No hand pose detected%s%s\n",
                        error ? ": " : "",
                        error ? [[error localizedDescription] UTF8String] : "");
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            // Collect joints from all detected hands into temp arrays
            NSMutableArray<NSValue *> *allPoints = [[NSMutableArray alloc] init];
            NSMutableArray<NSString *> *allNames = [[NSMutableArray alloc] init];
            NSMutableArray<NSNumber *> *allConfs = [[NSMutableArray alloc] init];

            int handIdx = 0;
            for (VNHumanHandPoseObservation *hand in request.results) {
                NSString *prefix = [NSString stringWithFormat:@"hand%d_", handIdx];

                // Get all recognized points for this hand
                NSError *jointsError = nil;
                NSDictionary<VNHumanHandPoseObservationJointName, VNRecognizedPoint *> *points =
                    [hand recognizedPointsForJointsGroupName:VNHumanHandPoseObservationJointsGroupNameAll
                                                       error:&jointsError];

                if (jointsError || !points) {
                    fprintf(stderr, "[AppleVision] Hand %d joint extraction failed\n", handIdx);
                    handIdx++;
                    continue;
                }

                for (NSString *jointName in points) {
                    VNRecognizedPoint *pt = points[jointName];
                    if (pt.confidence > 0.1) {
                        NSString *name = [prefix stringByAppendingString:jointName];
                        [allNames addObject:name];
                        [allPoints addObject:[NSValue valueWithPoint:
                            NSMakePoint(pt.location.x, pt.location.y)]];
                        [allConfs addObject:@(pt.confidence)];
                    }
                }
                handIdx++;
            }

            int count = (int)allPoints.count;
            if (count == 0) {
                fprintf(stderr, "[AppleVision] Hand pose: no joints above confidence threshold\n");
                [allPoints release];
                [allNames release];
                [allConfs release];
                [handler release];
                [request release];
                [nsImage release];
                return 0;
            }

            VIJoint* joints = (VIJoint*)calloc(count, sizeof(VIJoint));

            for (int i = 0; i < count; i++) {
                NSPoint p = [allPoints[i] pointValue];
                joints[i].jointName = strdup([allNames[i] UTF8String]);
                joints[i].x = p.x;
                joints[i].y = p.y;
                joints[i].confidence = [allConfs[i] floatValue];
            }

            fprintf(stderr, "[AppleVision] Hand pose: %d joints from %d hand(s)\n", count, handIdx);
            *outJoints = joints;

            [allPoints release];
            [allNames release];
            [allConfs release];
            [handler release];
            [request release];
            [nsImage release];
            return count;
        }

        fprintf(stderr, "[AppleVision] DetectHandPose: requires macOS 12.0+\n");
        [nsImage release];
        return 0;
    }
}
