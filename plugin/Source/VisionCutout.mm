//========================================================================================
//
//  VisionCutout.mm — macOS Vision framework subject segmentation
//
//  Uses VNGenerateForegroundInstanceMaskRequest (macOS 14+) to extract the foreground
//  subject from an image and save the result as a grayscale PNG mask.
//  White pixels = subject, black pixels = background.
//
//  Compiled as Objective-C++ (.mm) — included from IllToolPanels.mm which is in the
//  ObjC++ translation unit. TraceModule.cpp calls via extern "C" linkage.
//
//  Memory: Manual retain-release (MRR) — no ARC in the Illustrator SDK project.
//
//========================================================================================

#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <AppKit/AppKit.h>
#import <CoreImage/CoreImage.h>
#import <ImageIO/ImageIO.h>
#import <CoreServices/CoreServices.h>  // for kUTTypePNG
#include <cstdio>
#include <string>

#include "VisionCutout.h"

extern "C" bool VisionExtractSubjectMask(const char* inputImagePath, const char* outputMaskPath)
{
    @autoreleasepool {
        // --- Load image ---
        NSURL *imageURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:inputImagePath]];
        NSImage *nsImage = [[NSImage alloc] initWithContentsOfURL:imageURL];
        if (!nsImage) {
            fprintf(stderr, "[VisionCutout] Failed to load image: %s\n", inputImagePath);
            return false;
        }

        // Convert to CGImage (borrowed reference — do NOT release)
        CGImageRef cgImage = [nsImage CGImageForProposedRect:nil context:nil hints:nil];
        if (!cgImage) {
            fprintf(stderr, "[VisionCutout] Failed to get CGImage from: %s\n", inputImagePath);
            [nsImage release];
            return false;
        }

        size_t imgWidth  = CGImageGetWidth(cgImage);
        size_t imgHeight = CGImageGetHeight(cgImage);
        fprintf(stderr, "[VisionCutout] Input image: %zux%zu\n", imgWidth, imgHeight);

        // --- Check macOS version (VNGenerateForegroundInstanceMaskRequest requires 14.0+) ---
        if (@available(macOS 14.0, *)) {
            // OK — proceed below
        } else {
            fprintf(stderr, "[VisionCutout] macOS 14+ required for subject segmentation\n");
            [nsImage release];
            return false;
        }

        // --- Create and run Vision request ---
        bool result = false;

        if (@available(macOS 14.0, *)) {
            VNGenerateForegroundInstanceMaskRequest *request =
                [[VNGenerateForegroundInstanceMaskRequest alloc] init];

            VNImageRequestHandler *handler =
                [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];

            NSError *error = nil;
            BOOL success = [handler performRequests:@[request] error:&error];

            if (!success || error) {
                fprintf(stderr, "[VisionCutout] Vision request failed: %s\n",
                        error ? [[error localizedDescription] UTF8String] : "unknown error");
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            // --- Extract result ---
            VNInstanceMaskObservation *observation =
                (VNInstanceMaskObservation *)request.results.firstObject;
            if (!observation) {
                fprintf(stderr, "[VisionCutout] No mask observation returned\n");
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            NSIndexSet *allIndices = observation.allInstances;
            if (allIndices.count == 0) {
                fprintf(stderr, "[VisionCutout] No foreground instances found in image\n");
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            fprintf(stderr, "[VisionCutout] Found %lu foreground instance(s)\n",
                    (unsigned long)allIndices.count);

            // Generate a scaled mask matching the original image dimensions
            error = nil;
            CVPixelBufferRef maskBuffer = [observation
                generateScaledMaskForImageForInstances:allIndices
                fromRequestHandler:handler
                error:&error];

            if (error || !maskBuffer) {
                fprintf(stderr, "[VisionCutout] Failed to generate scaled mask: %s\n",
                        error ? [[error localizedDescription] UTF8String] : "null buffer");
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            // --- Convert mask CVPixelBuffer to CGImage ---
            CIImage *ciImage = [CIImage imageWithCVPixelBuffer:maskBuffer];
            CIContext *ciContext = [CIContext contextWithOptions:nil];
            CGImageRef maskCGImage = [ciContext createCGImage:ciImage
                                                    fromRect:ciImage.extent];

            if (!maskCGImage) {
                fprintf(stderr, "[VisionCutout] Failed to create mask CGImage\n");
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            // --- Save as PNG ---
            NSURL *outputURL = [NSURL fileURLWithPath:
                [NSString stringWithUTF8String:outputMaskPath]];

            CGImageDestinationRef dest = CGImageDestinationCreateWithURL(
                (__bridge CFURLRef)outputURL,
                kUTTypePNG,
                1, NULL);

            if (!dest) {
                fprintf(stderr, "[VisionCutout] Failed to create image destination at: %s\n",
                        outputMaskPath);
                CGImageRelease(maskCGImage);
                [handler release];
                [request release];
                [nsImage release];
                return false;
            }

            CGImageDestinationAddImage(dest, maskCGImage, NULL);
            bool written = CGImageDestinationFinalize(dest);
            CFRelease(dest);
            CGImageRelease(maskCGImage);

            if (written) {
                fprintf(stderr, "[VisionCutout] Subject mask saved to: %s (%.0fx%.0f)\n",
                        outputMaskPath, ciImage.extent.size.width, ciImage.extent.size.height);
                result = true;
            } else {
                fprintf(stderr, "[VisionCutout] Failed to write mask PNG\n");
            }

            [handler release];
            [request release];
        }

        [nsImage release];
        return result;
    }
}
