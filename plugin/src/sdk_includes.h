/**
 * sdk_includes.h — Bridge header between the real Illustrator SDK and our plugin code.
 *
 * Includes the real SDK headers in the correct order (SP/PICA first, then AI headers)
 * and provides any compatibility shims needed to bridge between the SDK's CC2017-era
 * conventions and our code.
 *
 * This replaces the temporary ai_sdk_compat.h that defined stub types.
 */

#ifndef SDK_INCLUDES_H
#define SDK_INCLUDES_H

/* Suppress deprecation warnings from old SDK headers on modern Clang. */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated"
#pragma clang diagnostic ignored "-Wfour-char-constants"
#pragma clang diagnostic ignored "-Wnon-virtual-dtor"
#pragma clang diagnostic ignored "-Wunused-parameter"
#pragma clang diagnostic ignored "-Wgnu-anonymous-struct"
#pragma clang diagnostic ignored "-Wnested-anon-types"
#pragma clang diagnostic ignored "-Wc++11-narrowing"

/* ========================================================================== */
/*  1. SP/PICA headers (foundation layer)                                     */
/* ========================================================================== */

#include "SPTypes.h"
#include "SPBasic.h"
#include "SPInterf.h"

/* ========================================================================== */
/*  2. AI base types and core headers                                         */
/* ========================================================================== */

#include "AITypes.h"
#include "AIPlugin.h"

/* ========================================================================== */
/*  3. AI utility types needed before feature headers                         */
/*     (AIDocument.h, AIDocumentView.h, AITool.h etc. reference these)        */
/* ========================================================================== */

#include "IAIFilePath.hpp"     /* ai::FilePath — used by AIDocumentSuite, AIFontSuite */
#include "IAIUnicodeString.h"  /* ai::UnicodeString — used by AIAddToolData, AIDocumentSuite, AIAnnotatorDrawerSuite */
#include "IAIColorSpace.hpp"   /* ai::ColorSpace — used by AIDocumentViewSuite */
#include "AIColor.h"           /* AIColor struct — used by AIDocumentViewSuite::GetGPUPixel, AIToolMessage */

/* ========================================================================== */
/*  4. AI feature headers used by this plugin                                 */
/* ========================================================================== */

#include "AIAnnotator.h"
#include "AIAnnotatorDrawer.h"
#include "AITool.h"
#include "AIDocumentView.h"

#pragma clang diagnostic pop

/* ========================================================================== */
/*  Compatibility layer — bridge between SDK conventions and our code         */
/* ========================================================================== */

/**
 * The real SDK uses AIErr (which is ASErr = ai::int32), and kNoErr is defined
 * in ASTypes.h. Our code also uses kUnhandledMsgErr which the SDK doesn't
 * define as a named constant — only as a selector mismatch return.
 * The SP convention is to return kSPUnimplementedError ('!IMP') for unhandled messages.
 */
#ifndef kUnhandledMsgErr
#define kUnhandledMsgErr  'UNHN'
#endif

/**
 * The real SDK defines selector strings differently from our compat header.
 * Map our old names to the real SDK defines where they differ.
 *
 * kSPInterfaceCaller / kSPInterfaceStartupSelector / kSPInterfaceShutdownSelector
 * are already #defined in SPInterf.h with the same string values.
 *
 * kCallerAIAnnotation is already #defined in AIAnnotator.h.
 * kCallerAITool is already #defined in AITool.h.
 *
 * However, the annotator selector strings are different:
 *   Real SDK: kSelectorAIDrawAnnotation = "AI Draw"
 *   Our stub: kSelectorAIDrawAnnotation = "AI Draw Annotation"
 *   Real SDK: kSelectorAIInvalAnnotation = "AI Invalidate"
 *   Our stub: kSelectorAIInvalAnnotation = "AI Inval Annotation"
 *
 * Similarly, the tool selectors:
 *   Real SDK: kSelectorAIToolMouseDown = "AI Mouse Down"
 *   Our stub: kSelectorAIToolMouseDown = "AI Tool Mouse Down"
 *   Real SDK: kSelectorAIToolMouseDrag = "AI Mouse Drag"
 *   Our stub: kSelectorAIToolMouseDrag = "AI Tool Mouse Drag"
 *   Real SDK: kSelectorAIToolMouseUp = "AI Mouse Up"
 *   Our stub: kSelectorAIToolMouseUp = "AI Tool Mouse Up"
 *   Real SDK: kSelectorAITrackToolCursor = "AI Track Cursor"
 *   Our stub: kSelectorAITrackToolCursor = "AI Track Tool Cursor"
 *
 * The real defines are already provided by the SDK headers. No compat needed.
 *
 * SP Interface selector strings:
 *   Real SDK: kSPInterfaceStartupSelector = "Startup"
 *   Our stub: kSPInterfaceStartupSelector = "SP Interface Startup"
 *   Real SDK: kSPInterfaceShutdownSelector = "Shutdown"
 *   Our stub: kSPInterfaceShutdownSelector = "SP Interface Shutdown"
 *
 * These also come from the real SDK headers — no compat needed.
 */

/**
 * Cursor constants — the real SDK doesn't define kCursorCrosshair/kCursorArrow
 * as named constants. These are resource IDs for cursor resources.
 * We define them here for our tool code.
 */
#ifndef kCursorCrosshair
#define kCursorCrosshair  1
#endif

#ifndef kCursorArrow
#define kCursorArrow  0
#endif

#endif /* SDK_INCLUDES_H */
