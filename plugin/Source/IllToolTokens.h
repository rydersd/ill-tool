#ifndef __ILLTOOL_TOKENS_H__
#define __ILLTOOL_TOKENS_H__

//========================================================================================
//
//  IllTool Design Tokens — centralized colors, widths, and sizes for all overlays
//
//  ALL modules should use these tokens for annotator drawing, handle rendering,
//  and overlay colors. No hardcoded AIRGBColor values in modules.
//
//  Color naming: ITK_ prefix, semantic name (what it means, not what it looks like)
//  Width naming: ITK_WIDTH_ prefix
//  Size naming:  ITK_SIZE_ prefix
//
//========================================================================================

#include "IllustratorSDK.h"

//----------------------------------------------------------------------------------------
//  Annotator Overlay Colors
//----------------------------------------------------------------------------------------

// Primary tool color — active path being drawn or previewed
inline AIRGBColor ITK_COLOR_PRIMARY() {
    return { 0, (ai::uint16)(0.9 * 65535), 65535 };  // bright cyan
}

// Primary shadow — dark outline behind primary for contrast
inline AIRGBColor ITK_COLOR_PRIMARY_SHADOW() {
    return { 0, 0, 0 };  // black
}

// Secondary — supporting elements (rubber band, ghost lines)
inline AIRGBColor ITK_COLOR_SECONDARY() {
    return { 0, (ai::uint16)(0.5 * 65535), (ai::uint16)(0.8 * 65535) };  // dim cyan
}

// Selection highlight — selected art or handles
inline AIRGBColor ITK_COLOR_SELECTION() {
    return { 0, (ai::uint16)(0.6 * 65535), 65535 };  // medium cyan
}

// Anchor handle fill
inline AIRGBColor ITK_COLOR_HANDLE_FILL() {
    return { 65535, 65535, 65535 };  // white
}

// Anchor handle stroke
inline AIRGBColor ITK_COLOR_HANDLE_STROKE() {
    return { 0, (ai::uint16)(0.4 * 65535), 65535 };  // blue
}

// Bezier direction handle
inline AIRGBColor ITK_COLOR_BEZIER_HANDLE() {
    return { (ai::uint16)(0.5 * 65535), (ai::uint16)(0.7 * 65535), 65535 };  // light blue
}

// Cutout / mask preview
inline AIRGBColor ITK_COLOR_MASK() {
    return { (ai::uint16)(0.85 * 65535), 0, (ai::uint16)(0.85 * 65535) };  // magenta
}

// Skeleton / pose joints
inline AIRGBColor ITK_COLOR_SKELETON() {
    return { 0, (ai::uint16)(0.9 * 65535), (ai::uint16)(0.9 * 65535) };  // cyan
}

// Skeleton joint markers
inline AIRGBColor ITK_COLOR_JOINT() {
    return { (ai::uint16)(0.9 * 65535), (ai::uint16)(0.4 * 65535), 0 };  // orange
}

// Face landmark points
inline AIRGBColor ITK_COLOR_FACE() {
    return { 0, (ai::uint16)(0.85 * 65535), (ai::uint16)(0.4 * 65535) };  // green
}

// Hand pose markers
inline AIRGBColor ITK_COLOR_HAND() {
    return { 65535, (ai::uint16)(0.85 * 65535), 0 };  // yellow
}

// Perspective grid colors (VP-specific, kept distinct for readability)
inline AIRGBColor ITK_COLOR_VP1() {
    return { (ai::uint16)(0.9 * 65535), (ai::uint16)(0.3 * 65535), (ai::uint16)(0.3 * 65535) };  // red
}

inline AIRGBColor ITK_COLOR_VP2() {
    return { (ai::uint16)(0.3 * 65535), (ai::uint16)(0.8 * 65535), (ai::uint16)(0.3 * 65535) };  // green
}

inline AIRGBColor ITK_COLOR_VP3() {
    return { (ai::uint16)(0.35 * 65535), (ai::uint16)(0.55 * 65535), (ai::uint16)(0.95 * 65535) };  // blue
}

inline AIRGBColor ITK_COLOR_HORIZON() {
    return { 65535, (ai::uint16)(0.6 * 65535), 0 };  // orange
}

inline AIRGBColor ITK_COLOR_GRID() {
    return { 0, (ai::uint16)(0.7 * 65535), (ai::uint16)(0.9 * 65535) };  // cyan
}

// Error / warning
inline AIRGBColor ITK_COLOR_ERROR() {
    return { 65535, (ai::uint16)(0.2 * 65535), (ai::uint16)(0.2 * 65535) };  // red
}

// Success / confirmation
inline AIRGBColor ITK_COLOR_SUCCESS() {
    return { (ai::uint16)(0.3 * 65535), (ai::uint16)(0.85 * 65535), (ai::uint16)(0.4 * 65535) };  // green
}

//----------------------------------------------------------------------------------------
//  Line Widths
//----------------------------------------------------------------------------------------

static constexpr AIReal ITK_WIDTH_PRIMARY       = 1.5;   // main path stroke
static constexpr AIReal ITK_WIDTH_SHADOW        = 3.0;   // shadow behind primary
static constexpr AIReal ITK_WIDTH_SECONDARY     = 1.0;   // supporting lines
static constexpr AIReal ITK_WIDTH_HANDLE        = 0.75;  // bezier handle lines
static constexpr AIReal ITK_WIDTH_GRID          = 0.5;   // grid/guide lines
static constexpr AIReal ITK_WIDTH_SKELETON      = 2.0;   // pose skeleton bones
static constexpr AIReal ITK_WIDTH_MASK          = 2.0;   // cutout preview

//----------------------------------------------------------------------------------------
//  Handle / Marker Sizes (in view pixels)
//----------------------------------------------------------------------------------------

static constexpr double ITK_SIZE_ANCHOR         = 4.0;   // anchor point square half-width
static constexpr double ITK_SIZE_BEZIER_HANDLE  = 3.0;   // bezier handle circle radius
static constexpr double ITK_SIZE_VP_MARKER      = 6.0;   // vanishing point marker
static constexpr double ITK_SIZE_JOINT_MARKER   = 5.0;   // pose joint cross size
static constexpr double ITK_SIZE_FACE_DOT       = 2.0;   // face landmark dot radius

//----------------------------------------------------------------------------------------
//  Opacity values (0.0 - 1.0)
//----------------------------------------------------------------------------------------

static constexpr double ITK_OPACITY_FULL        = 1.0;
static constexpr double ITK_OPACITY_PREVIEW     = 0.85;  // preview overlays
static constexpr double ITK_OPACITY_DIM         = 0.5;   // dimmed/inactive elements
static constexpr double ITK_OPACITY_GHOST       = 0.3;   // ghost/hint elements

#endif // __ILLTOOL_TOKENS_H__
