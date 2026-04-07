//========================================================================================
//
//  IllTool Plugin — Suite definitions
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Defines suite pointers and the gImportSuites table used by the SDK
//  framework to auto-acquire suites at startup.
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolSuites.h"

extern "C"
{
    AIUnicodeStringSuite*       sAIUnicodeString = NULL;
    SPBlocksSuite*              sSPBlocks = NULL;
    AIAnnotatorSuite*           sAIAnnotator = NULL;
    AIAnnotatorDrawerSuite*     sAIAnnotatorDrawer = NULL;
    AIToolSuite*                sAITool = NULL;
    AIArtSetSuite*              sAIArtSet = NULL;
    AIArtSuite*                 sAIArt = NULL;
    AIHitTestSuite*             sAIHitTest = NULL;
    AIDocumentViewSuite*        sAIDocumentView = NULL;
    AIDocumentSuite*            sAIDocument = NULL;
    AIMatchingArtSuite*         sAIMatchingArt = NULL;
    AIStringFormatUtilsSuite*   sAIStringFormatUtils = NULL;
    AIPathSuite*                sAIPath = NULL;
    AIMdMemorySuite*            sAIMdMemory = NULL;
    AIPanelSuite*               sAIPanel = NULL;
    AIPanelFlyoutMenuSuite*     sAIPanelFlyoutMenu = NULL;
    AIMenuSuite*                sAIMenu = NULL;
    AIIsolationModeSuite*       sAIIsolationMode = NULL;
    AIBlendStyleSuite*          sAIBlendStyle = NULL;
    AILayerSuite*               sAILayer = NULL;
    AITimerSuite*               sAITimer = NULL;
    AIPathStyleSuite*           sAIPathStyle = NULL;
    AIDictionarySuite*          sAIDictionary = NULL;
}

ImportSuite gImportSuites[] =
{
    kAIUnicodeStringSuite, kAIUnicodeStringSuiteVersion, &sAIUnicodeString,
    kSPBlocksSuite, kSPBlocksSuiteVersion, &sSPBlocks,
    kAIAnnotatorSuite, kAIAnnotatorSuiteVersion, &sAIAnnotator,
    kAIAnnotatorDrawerSuite, kAIAnnotatorDrawerSuiteVersion, &sAIAnnotatorDrawer,
    kAIToolSuite, kAIToolSuiteVersion, &sAITool,
    kAIArtSetSuite, kAIArtSetSuiteVersion, &sAIArtSet,
    kAIArtSuite, kAIArtSuiteVersion, &sAIArt,
    kAIHitTestSuite, kAIHitTestSuiteVersion, &sAIHitTest,
    kAIDocumentViewSuite, kAIDocumentViewSuiteVersion, &sAIDocumentView,
    kAIDocumentSuite, kAIDocumentSuiteVersion, &sAIDocument,
    kAIMatchingArtSuite, kAIMatchingArtSuiteVersion, &sAIMatchingArt,
    kAIStringFormatUtilsSuite, kAIStringFormatUtilsSuiteVersion, &sAIStringFormatUtils,
    kAIPathSuite, kAIPathSuiteVersion, &sAIPath,
    kAIMdMemorySuite, kAIMdMemorySuiteVersion, &sAIMdMemory,
    kAIPanelSuite, kAIPanelSuiteVersion, &sAIPanel,
    kAIPanelFlyoutMenuSuite, kAIPanelFlyoutMenuSuiteVersion, &sAIPanelFlyoutMenu,
    kAIMenuSuite, kAIMenuSuiteVersion, &sAIMenu,
    kAIIsolationModeSuite, kAIIsolationModeSuiteVersion, &sAIIsolationMode,
    kAIBlendStyleSuite, kAIBlendStyleSuiteVersion, &sAIBlendStyle,
    kAILayerSuite, kAILayerSuiteVersion, &sAILayer,
    kAITimerSuite, kAITimerSuiteVersion, &sAITimer,
    kAIPathStyleSuite, kAIPathStyleSuiteVersion, &sAIPathStyle,
    kAIDictionarySuite, kAIDictionarySuiteVersion, &sAIDictionary,
    nullptr, 0, nullptr
};
// End IllToolSuites.cpp
