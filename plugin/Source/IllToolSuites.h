//========================================================================================
//
//  IllTool Plugin — Suite declarations
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Declares external suite pointers acquired by the SDK framework.
//
//========================================================================================

#ifndef __ILLTOOLSUITES_H__
#define __ILLTOOLSUITES_H__

#include "IllustratorSDK.h"
#include "AIAnnotator.h"
#include "AIAnnotatorDrawer.h"
#include "AIStringFormatUtils.h"
#include "AIArt.h"
#include "AIPath.h"
#include "AIMdMemory.h"
#include "AIPanel.h"
#include "AIMenu.h"
#include "AIIsolationMode.h"
#include "AIMask.h"   // AIBlendStyleSuite — GetOpacity/SetOpacity
#include "AILayer.h"  // AILayerSuite — layer creation and lookup
#include "AITimer.h"  // AITimerSuite — SDK-context timer dispatch
#include "AIPathStyle.h" // AIPathStyleSuite — read/write fill+stroke styles
#include "AIDictionary.h" // AIDictionarySuite — per-art metadata storage
#include "AIMesh.h"      // AIMeshSuite, AIMeshVertexIteratorSuite — mesh gradient creation

extern  "C" AIUnicodeStringSuite*       sAIUnicodeString;
extern  "C" SPBlocksSuite*              sSPBlocks;
extern  "C" AIAnnotatorSuite*           sAIAnnotator;
extern  "C" AIAnnotatorDrawerSuite*     sAIAnnotatorDrawer;
extern  "C" AIToolSuite*                sAITool;
extern  "C" AIArtSetSuite*              sAIArtSet;
extern  "C" AIArtSuite*                 sAIArt;
extern  "C" AIHitTestSuite*             sAIHitTest;
extern  "C" AIDocumentViewSuite*        sAIDocumentView;
extern  "C" AIDocumentSuite*            sAIDocument;
extern  "C" AIMatchingArtSuite*         sAIMatchingArt;
extern  "C" AIStringFormatUtilsSuite*   sAIStringFormatUtils;
extern  "C" AIPathSuite*                sAIPath;
extern  "C" AIMdMemorySuite*            sAIMdMemory;
extern  "C" AIPanelSuite*               sAIPanel;
extern  "C" AIPanelFlyoutMenuSuite*     sAIPanelFlyoutMenu;
extern  "C" AIMenuSuite*                sAIMenu;
extern  "C" AIIsolationModeSuite*       sAIIsolationMode;
extern  "C" AIBlendStyleSuite*          sAIBlendStyle;
extern  "C" AILayerSuite*               sAILayer;
extern  "C" AITimerSuite*               sAITimer;
extern  "C" AIPathStyleSuite*           sAIPathStyle;
extern  "C" AIDictionarySuite*          sAIDictionary;
extern  "C" AIMeshSuite*               sAIMesh;
extern  "C" AIMeshVertexIteratorSuite*  sAIMeshVertex;

#endif // __ILLTOOLSUITES_H__
