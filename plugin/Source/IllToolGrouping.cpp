//========================================================================================
//  IllTool — Group Operations
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <string>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Stage 5: Grouping Operations
//========================================================================================

void IllToolPlugin::CopyToGroup(const std::string& groupName)
{
    try {
        fprintf(stderr, "[IllTool] CopyToGroup: begin (name='%s')\n", groupName.c_str());

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] CopyToGroup: no path art found\n");
            return;
        }

        std::vector<AIArtHandle> selectedPaths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (hasSelected) selectedPaths.push_back(art);
        }

        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }

        if (selectedPaths.empty()) {
            fprintf(stderr, "[IllTool] CopyToGroup: no paths with selected segments\n");
            return;
        }

        fprintf(stderr, "[IllTool] CopyToGroup: %zu paths with selections\n", selectedPaths.size());

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) {
            fprintf(stderr, "[IllTool] CopyToGroup: NewArt(kGroupArt) failed: %d\n", (int)result);
            return;
        }

        ai::UnicodeString uName(groupName.c_str());
        sAIArt->SetArtName(groupArt, uName);

        int dupeCount = 0;
        for (AIArtHandle art : selectedPaths) {
            AIArtHandle dupArt = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, groupArt, &dupArt);
            if (result == kNoErr && dupArt) dupeCount++;
            else fprintf(stderr, "[IllTool] CopyToGroup: DuplicateArt failed: %d\n", (int)result);
        }

        fprintf(stderr, "[IllTool] CopyToGroup: duplicated %d paths into group '%s'\n", dupeCount, groupName.c_str());

        if (sAIIsolationMode && sAIIsolationMode->CanIsolateArt(groupArt)) {
            result = sAIIsolationMode->EnterIsolationMode(groupArt, false);
            if (result == kNoErr) fprintf(stderr, "[IllTool] CopyToGroup: entered isolation\n");
            else fprintf(stderr, "[IllTool] CopyToGroup: EnterIsolationMode failed: %d\n", (int)result);
        }

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] CopyToGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] CopyToGroup unknown error\n"); }
}

void IllToolPlugin::DetachFromGroup()
{
    try {
        fprintf(stderr, "[IllTool] DetachFromGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool] DetachFromGroup: no paths\n"); return; }

        int detachedCount = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (!hasSelected) continue;

            AIArtHandle parent = nullptr;
            result = sAIArt->GetArtParent(art, &parent);
            if (result != kNoErr || !parent) continue;

            short parentType = kUnknownArt;
            sAIArt->GetArtType(parent, &parentType);
            if (parentType != kGroupArt) continue;

            result = sAIArt->ReorderArt(art, kPlaceAbove, parent);
            if (result == kNoErr) detachedCount++;
            else fprintf(stderr, "[IllTool] DetachFromGroup: ReorderArt failed: %d\n", (int)result);
        }

        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[IllTool] DetachFromGroup: detached %d paths\n", detachedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] DetachFromGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] DetachFromGroup unknown error\n"); }
}

void IllToolPlugin::SplitToNewGroup()
{
    try {
        fprintf(stderr, "[IllTool] SplitToNewGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool] SplitToNewGroup: no paths\n"); return; }

        std::vector<AIArtHandle> selectedPaths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;
            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (hasSelected) selectedPaths.push_back(art);
        }
        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }
        if (selectedPaths.empty()) { fprintf(stderr, "[IllTool] SplitToNewGroup: no selected paths\n"); return; }

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) { fprintf(stderr, "[IllTool] SplitToNewGroup: NewArt failed: %d\n", (int)result); return; }

        ai::UnicodeString uName("Split Group");
        sAIArt->SetArtName(groupArt, uName);

        int movedCount = 0;
        for (AIArtHandle art : selectedPaths) {
            result = sAIArt->ReorderArt(art, kPlaceInsideOnTop, groupArt);
            if (result == kNoErr) movedCount++;
            else fprintf(stderr, "[IllTool] SplitToNewGroup: ReorderArt failed: %d\n", (int)result);
        }
        fprintf(stderr, "[IllTool] SplitToNewGroup: moved %d paths\n", movedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] SplitToNewGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] SplitToNewGroup unknown error\n"); }
}
