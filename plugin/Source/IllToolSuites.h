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
#include "AITransformArt.h"
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
#include "AIUndo.h"      // AIUndoSuite — undo context management
#include "AIPlaced.h"    // AIPlacedSuite — placed image file path and transform
#include "AICursorSnap_Wrapper.h"  // AICursorSnapSuite — custom snap constraints
#include "AIPreference.h"  // AIPreferenceSuite — boolean preference get/put
#include "AIArtboard.h"    // AIArtboardSuite — artboard list, bounds, active index
#include "AIRaster.h"      // AIRasterSuite — raster pixel data access
#include "AIGroup.h"       // AIGroupSuite — clip groups, compound path normalization

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
extern  "C" AIUndoSuite*              sAIUndo;
extern  "C" AIPlacedSuite*            sAIPlaced;
extern  "C" AICursorSnapSuite*        sAICursorSnap;
extern  "C" AIPreferenceSuite*        sAIPreference;
extern  "C" AIArtboardSuite*         sAIArtboard;
extern  "C" AIRasterSuite*           sAIRaster;
extern  "C" AIGroupSuite*           sAIGroup;
extern  "C" AITransformArtSuite*    sAITransformArt;

#endif // __ILLTOOLSUITES_H__
