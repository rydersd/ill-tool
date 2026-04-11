#ifndef __VISIONCUTOUT_H__
#define __VISIONCUTOUT_H__

//========================================================================================
//  VisionCutout — macOS Vision framework subject segmentation (macOS 14+)
//
//  Extracts foreground subject mask using VNGenerateForegroundInstanceMaskRequest.
//  Output is a grayscale PNG mask (white = subject, black = background).
//  Callable from C++ via extern "C" linkage.
//========================================================================================

/// Extract foreground subject mask using macOS Vision framework.
/// @param inputImagePath  Path to the source image (JPEG, PNG, TIFF, etc.)
/// @param outputMaskPath  Path where the grayscale mask PNG will be written
/// @return true on success, false on failure (errors logged to stderr)
extern "C" bool VisionExtractSubjectMask(const char* inputImagePath, const char* outputMaskPath);

#endif // __VISIONCUTOUT_H__
