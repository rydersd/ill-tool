#!/bin/bash
# fetch-sdk-headers.sh — Download Illustrator SDK headers from public GitHub repos.
#
# Source: WestonThayer/Bloks (CC2017-era SDK headers checked into a public repo)
# Path:   BloksAIPlugin/Vendor/illustratorapi/
#
# This fetches the FULL illustratorapi/ tree (illustrator/ + pica_sp/ subdirs)
# so that include chains resolve. Our plugin only uses a subset, but the headers
# cross-reference each other heavily (AITypes.h -> AIBasicTypes.h -> ASTypes.h
# -> SPTypes.h etc).
#
# Usage:
#   ./scripts/fetch-sdk-headers.sh            # fetch all headers
#   ./scripts/fetch-sdk-headers.sh --minimal  # fetch only our required subset
#
# Idempotent — safe to run multiple times. Overwrites existing files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
SDK_DIR="${PLUGIN_DIR}/sdk"

BASE_URL="https://raw.githubusercontent.com/WestonThayer/Bloks/master/BloksAIPlugin/Vendor/illustratorapi"

# Counters
FETCHED=0
FAILED=0
SKIPPED=0

# --------------------------------------------------------------------------
# Our minimum required headers (the ones ai_sdk_compat.h was shimming)
# --------------------------------------------------------------------------
REQUIRED_HEADERS=(
    # Sweet Pea (PICA) — plugin lifecycle and suite acquisition
    "pica_sp/SPBasic.h"
    "pica_sp/SPInterf.h"
    "pica_sp/SPAccess.h"
    "pica_sp/SPTypes.h"
    "pica_sp/SPConfig.h"
    "pica_sp/SPErrors.h"
    "pica_sp/SPErrorCodes.h"
    "pica_sp/SPFiles.h"
    "pica_sp/SPPlugs.h"
    "pica_sp/SPHeaderBegin.h"
    "pica_sp/SPHeaderEnd.h"
    "pica_sp/SPAdapts.h"
    "pica_sp/SPBlocks.h"
    "pica_sp/SPCaches.h"
    "pica_sp/SPHost.h"
    "pica_sp/SPMData.h"
    "pica_sp/SPPiPL.h"
    "pica_sp/SPProps.h"
    "pica_sp/SPRuntme.h"
    "pica_sp/SPStrngs.h"
    "pica_sp/SPSuites.h"
    "pica_sp/SPBckDbg.h"
    "pica_sp/SPRuntmeV6.h"
    "pica_sp/SPSTSPrp.h"

    # Core AI types and error codes
    "illustrator/AITypes.h"
    "illustrator/AIBasicTypes.h"
    "illustrator/AIErrorCodes.h"
    "illustrator/ASTypes.h"
    "illustrator/ADMStdTypes.h"
    "illustrator/ASConfig.h"
    "illustrator/AIHeaderBegin.h"
    "illustrator/AIHeaderEnd.h"
    "illustrator/AIPragma.h"
    "illustrator/ASPragma.h"
    "illustrator/AIWinDef.h"
    "illustrator/AIExternDef.h"
    "illustrator/config/AIConfig.h"
    "illustrator/config/AIAssertConfig.h"
    "illustrator/config/compiler/AIConfigClang.h"
    "illustrator/config/compiler/AIConfigMSVC.h"

    # Plugin framework
    "illustrator/AIPlugin.h"

    # Annotator (overlay drawing)
    "illustrator/AIAnnotator.h"
    "illustrator/AIAnnotatorDrawer.h"

    # Tool registration and mouse events
    "illustrator/AITool.h"
    "illustrator/AIToolNames.h"
    "illustrator/AITabletData.h"

    # Document and view
    "illustrator/AIDocument.h"
    "illustrator/AIDocumentView.h"
    "illustrator/AIDocumentBasicTypes.h"

    # User interaction utilities
    "illustrator/AIUser.h"

    # Math and geometry (dependency of annotator/tool headers)
    "illustrator/AIFixedMath.h"
    "illustrator/AIRealMath.h"
    "illustrator/AIRealBezier.h"

    # Commonly pulled in by the above
    "illustrator/AIColor.h"
    "illustrator/AIColorSpace.h"
    "illustrator/AICustomColor.h"
    "illustrator/AIRuntime.h"
    "illustrator/AIContext.h"
    "illustrator/AIFilePath.h"
    "illustrator/AIFolders.h"
    "illustrator/AIArt.h"
    "illustrator/AIArtboard.h"
    "illustrator/AILimits.h"
    "illustrator/AIEntry.h"
    "illustrator/AIDictionary.h"
    "illustrator/AINotifier.h"
    "illustrator/AITimer.h"
    "illustrator/AIHitTest.h"
    "illustrator/AIMatchingArt.h"
    "illustrator/AIPath.h"
    "illustrator/AIPathStyle.h"
    "illustrator/AIGradient.h"
    "illustrator/AIPattern.h"
    "illustrator/AILayer.h"
    "illustrator/AIMenu.h"
    "illustrator/AIBlock.h"
    "illustrator/AIUnicodeString.h"
    "illustrator/AIStringPool.h"
    "illustrator/AICountedObject.h"
    "illustrator/AINameSpace.h"
    "illustrator/AIFont.h"
    "illustrator/AIRaster.h"
    "illustrator/AIRasterTypes.h"
    "illustrator/AIPlacedTypes.h"
    "illustrator/AIGroup.h"
    "illustrator/AITextFrame.h"

    # Wrapper / utility headers
    "illustrator/IAIUnicodeString.h"
    "illustrator/IAIRef.h"
    "illustrator/IAIRect.h"
    "illustrator/IAIPoint.h"
    "illustrator/IAIAutoBuffer.h"
    "illustrator/IAILiteralString.h"
    "illustrator/IAILocale.h"
    "illustrator/IAICharacterEncoding.h"
    "illustrator/AutoSuite.h"
)

# --------------------------------------------------------------------------
# Full header lists (all headers in the repo)
# --------------------------------------------------------------------------
ALL_ILLUSTRATOR_HEADERS=(
    ADMStdTypes.h AIAGMTypes.h AIATECurrTextFeatures.h AIATEPaint.h
    AIATETextUtil.h AIActionManager.h AIAnnotator.h AIAnnotatorDrawer.h
    AIApplication.h AIArray.h AIArt.h AIArtConverter.h AIArtSet.h
    AIArtSetGenerator.h AIArtStyle.h AIArtStyleParser.h AIArtboard.h
    AIArtboardRange.h AIAssertion.h AIAssetMgmt.h AIAutoCoordinateSystem.h
    AIBasicTypes.h AIBasicUtilities.h AIBeautifulStrokes.h AIBlock.h
    AICMS.h AICSXS.h AICSXSExtension.h AICharacterEncoding.h AIClipboard.h
    AICloudDocument.h AIColor.h AIColorConversion.h AIColorHarmony.h
    AIColorSpace.h AICommandManager.h AIContext.h AIControlBar.h
    AICountedObject.h AICursorSnap.h AICurveFittingSuite.h AICustomColor.h
    AIDataFilter.h AIDeviceInfo.h AIDictionary.h AIDocument.h
    AIDocumentBasicTypes.h AIDocumentList.h AIDocumentView.h AIDrawArt.h
    AIDxfDwgPrefs.h AIDynamicSymbol.h AIEntry.h AIEnvelope.h AIEraserTool.h
    AIErrorCodes.h AIErrorHandler.h AIEvent.h AIExpand.h AIExternDef.h
    AIFOConversion.h AIFXGFileFormat.h AIFileFormat.h AIFilePath.h
    AIFilter.h AIFixedMath.h AIFolders.h AIFont.h AIForeignObject.h
    AIGeometry.h AIGlobalUnicodeString.h AIGradient.h AIGrid.h AIGroup.h
    AIHTMLConversion.h AIHardSoft.h AIHeaderBegin.h AIHeaderEnd.h AIHitTest.h
    AIImageOptimization.h AIIsolationMode.h AILayer.h AILayerList.h
    AILegacyTextConversion.h AILimits.h AILiveEdit.h AILiveEditConstants.h
    AILiveEffect.h AIMask.h AIMaskFlattener.h AIMatchingArt.h AIMdMemory.h
    AIMenu.h AIMenuCommandNotifiers.h AIMenuCommandString.h AIMenuGroups.h
    AIMesh.h AIModalParent.h AINameSpace.h AINotifier.h AIObjectSet.h
    AIOverrideColorConversion.h AIPSDKeys.h AIPaintStyle.h AIPanel.h AIPath.h
    AIPathConstruction.h AIPathInterpolate.h AIPathStyle.h AIPathfinder.h
    AIPattern.h AIPerspectiveGrid.h AIPerspectiveTransform.h
    AIPhotoshopPrefs.h AIPlaced.h AIPlacedTypes.h AIPlanarObject.h
    AIPlatformMemory.h AIPlugin.h AIPluginGroup.h AIPluginNames.h
    AIPragma.h AIPreference.h AIPreferenceKeys.h AIRandom.h
    AIRandomBellCurve.h AIRaster.h AIRasterExport.h AIRasterTypes.h
    AIRasterize.h AIRealBezier.h AIRealMath.h AIRepeat.h AIRuntime.h
    AISFWUtilities.h AISVGFilter.h AISVGTypes.h AIScriptMessage.h
    AISelectionContextManager.h AIShapeConstruction.h AISliceTypes.h
    AISlicing.h AISmoothShadingStyle.h AIStringFormatUtils.h AIStringPool.h
    AISwatchLibraries.h AISwatchList.h AISymbol.h AITIFFKeys.h AITabletData.h
    AITag.h AITextFrame.h AITimer.h AITool.h AIToolNames.h AIToolbox.h
    AITransformAgain.h AITransformArt.h AITransformTypes.h AITypes.h AIUID.h
    AIUITheme.h AIURL.h AIUUID.h AIUndo.h AIUnicodeString.h AIUser.h
    AIVectorize.h AIWinDef.h AIWorkspace.h AIXMLElement.h AIXMLNameUtil.h
    ASConfig.h ASHelp.h ASPragma.h ASTypes.h ASUserInteraction.h AutoSuite.h
    IAIAutoBuffer.h IAICharacterEncoding.h IAICopyScope.h IAILiteralString.h
    IAILiveEdit.h IAILocale.h IAIPaint.h IAIPoint.h IAIRect.h IAIRef.h
    IAIStringFormatUtils.h IAIStringUtils.h IAIUUID.h IAIUnicodeString.h
    SloTextdomTypes.h
)

ALL_ILLUSTRATOR_CONFIG_HEADERS=(
    config/AIConfig.h
    config/AIAssertConfig.h
    config/compiler/AIConfigClang.h
    config/compiler/AIConfigMSVC.h
)

ALL_PICA_HEADERS=(
    SPAccess.h SPAdapts.h SPBasic.h SPBckDbg.h SPBlocks.h SPCaches.h
    SPConfig.h SPErrorCodes.h SPErrors.h SPFiles.h SPHeaderBegin.h
    SPHeaderEnd.h SPHost.h SPInterf.h SPMData.h SPPiPL.h SPPlugs.h
    SPProps.h SPRuntme.h SPRuntmeV6.h SPSTSPrp.h SPStrngs.h SPSuites.h
    SPTypes.h
)

# --------------------------------------------------------------------------
# Fetch function
# --------------------------------------------------------------------------
fetch_header() {
    local remote_path="$1"    # e.g. "illustrator/AITypes.h" or "pica_sp/SPBasic.h"
    local local_path="${SDK_DIR}/${remote_path}"
    local url="${BASE_URL}/${remote_path}"

    # Ensure target directory exists
    mkdir -p "$(dirname "$local_path")"

    if curl -sfL --max-time 10 -o "$local_path" "$url"; then
        FETCHED=$((FETCHED + 1))
    else
        echo "  FAILED: ${remote_path}"
        rm -f "$local_path"
        FAILED=$((FAILED + 1))
    fi
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
MODE="${1:---full}"

echo "=== Illustrator SDK Header Fetch ==="
echo "Source: github.com/WestonThayer/Bloks (CC2017-era SDK)"
echo "Target: ${SDK_DIR}/"
echo ""

mkdir -p "${SDK_DIR}/illustrator/config/compiler"
mkdir -p "${SDK_DIR}/pica_sp"

if [[ "$MODE" == "--minimal" ]]; then
    echo "Mode: MINIMAL (required headers only — ~90 files)"
    echo ""

    for header in "${REQUIRED_HEADERS[@]}"; do
        fetch_header "$header"
    done

elif [[ "$MODE" == "--full" ]]; then
    echo "Mode: FULL (all illustrator + pica_sp headers — ~220 files)"
    echo ""

    echo "Fetching illustrator/ headers..."
    for header in "${ALL_ILLUSTRATOR_HEADERS[@]}"; do
        fetch_header "illustrator/${header}"
    done

    echo "Fetching illustrator/config/ headers..."
    for header in "${ALL_ILLUSTRATOR_CONFIG_HEADERS[@]}"; do
        fetch_header "illustrator/${header}"
    done

    echo "Fetching pica_sp/ headers..."
    for header in "${ALL_PICA_HEADERS[@]}"; do
        fetch_header "pica_sp/${header}"
    done

else
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [--full | --minimal]"
    exit 1
fi

echo ""
echo "=== Results ==="
echo "  Fetched: ${FETCHED}"
echo "  Failed:  ${FAILED}"
echo ""

# --------------------------------------------------------------------------
# Report gaps — headers NOT available in public repos
# --------------------------------------------------------------------------
MISSING_FROM_PUBLIC=(
    "AIAnnotatorDrawer.h — Available (v8 drawer API with SetColor, DrawLine, DrawRect, etc)"
)

# Verify our critical headers actually arrived
CRITICAL=(
    "pica_sp/SPBasic.h"
    "pica_sp/SPInterf.h"
    "pica_sp/SPAccess.h"
    "pica_sp/SPTypes.h"
    "illustrator/AITypes.h"
    "illustrator/AIPlugin.h"
    "illustrator/AIAnnotator.h"
    "illustrator/AIAnnotatorDrawer.h"
    "illustrator/AITool.h"
    "illustrator/AIDocument.h"
    "illustrator/AIDocumentView.h"
    "illustrator/AIUser.h"
)

echo "=== Critical Header Verification ==="
ALL_CRITICAL_OK=true
for header in "${CRITICAL[@]}"; do
    if [[ -f "${SDK_DIR}/${header}" ]]; then
        echo "  OK   ${header}"
    else
        echo "  MISS ${header}"
        ALL_CRITICAL_OK=false
    fi
done
echo ""

if $ALL_CRITICAL_OK; then
    echo "All critical headers present. The ai_sdk_compat.h shim can be retired."
else
    echo "Some critical headers missing. Keep ai_sdk_compat.h as fallback."
    echo ""
    echo "To get headers manually:"
    echo "  1. Download from Adobe Developer Console: https://developer.adobe.com/"
    echo "  2. Look for 'Adobe Illustrator CC SDK' in the downloads section"
    echo "  3. Extract headers from illustratorapi/ into plugin/sdk/"
fi

echo ""
echo "=== SDK Version Note ==="
echo "These headers are from the Illustrator CC 2017 SDK (via WestonThayer/Bloks)."
echo "Suite signatures are stable across AI versions — the major annotator, tool,"
echo "and document view APIs have not changed since CC 2014."
echo ""
echo "If you need CC 2024+ specific APIs, download the latest SDK from:"
echo "  https://developer.adobe.com/console/servicesandapis"
echo ""

# Always exit 0 — partial fetches are still useful
exit 0
