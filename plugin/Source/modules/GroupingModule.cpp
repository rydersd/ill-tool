//========================================================================================
//  GroupingModule — Copy to Group, Detach, Split
//  Ported from IllToolGrouping.cpp
//========================================================================================

#include "IllustratorSDK.h"
#include "GroupingModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <string>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Operation dispatch
//========================================================================================

bool GroupingModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::CopyToGroup:
            fprintf(stderr, "[GroupingModule] Copy to Group '%s'\n", op.strParam.c_str());
            CopyToGroup(op.strParam);
            InvalidateFullView();
            return true;

        case OpType::Detach:
            fprintf(stderr, "[GroupingModule] Detach from Group\n");
            DetachFromGroup();
            InvalidateFullView();
            return true;

        case OpType::Split:
            fprintf(stderr, "[GroupingModule] Split to New Group\n");
            SplitToNewGroup();
            InvalidateFullView();
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  CopyToGroup — duplicate selected paths into a named group
//========================================================================================

void GroupingModule::CopyToGroup(const std::string& groupName)
{
    try {
        fprintf(stderr, "[GroupingModule] CopyToGroup: begin (name='%s')\n", groupName.c_str());

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[GroupingModule] CopyToGroup: no path art found\n");
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
            fprintf(stderr, "[GroupingModule] CopyToGroup: no paths with selected segments\n");
            return;
        }

        fprintf(stderr, "[GroupingModule] CopyToGroup: %zu paths with selections\n", selectedPaths.size());

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) {
            fprintf(stderr, "[GroupingModule] CopyToGroup: NewArt(kGroupArt) failed: %d\n", (int)result);
            return;
        }

        ai::UnicodeString uName(groupName.c_str());
        sAIArt->SetArtName(groupArt, uName);

        int dupeCount = 0;
        for (AIArtHandle art : selectedPaths) {
            AIArtHandle dupArt = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, groupArt, &dupArt);
            if (result == kNoErr && dupArt) dupeCount++;
            else fprintf(stderr, "[GroupingModule] CopyToGroup: DuplicateArt failed: %d\n", (int)result);
        }

        fprintf(stderr, "[GroupingModule] CopyToGroup: duplicated %d paths into group '%s'\n", dupeCount, groupName.c_str());

        if (sAIIsolationMode && sAIIsolationMode->CanIsolateArt(groupArt)) {
            result = sAIIsolationMode->EnterIsolationMode(groupArt, false);
            if (result == kNoErr) fprintf(stderr, "[GroupingModule] CopyToGroup: entered isolation\n");
            else fprintf(stderr, "[GroupingModule] CopyToGroup: EnterIsolationMode failed: %d\n", (int)result);
        }

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[GroupingModule] CopyToGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[GroupingModule] CopyToGroup unknown error\n"); }
}

//========================================================================================
//  DetachFromGroup — move selected paths out of their parent group
//========================================================================================

void GroupingModule::DetachFromGroup()
{
    try {
        fprintf(stderr, "[GroupingModule] DetachFromGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[GroupingModule] DetachFromGroup: no paths\n"); return; }

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
            else fprintf(stderr, "[GroupingModule] DetachFromGroup: ReorderArt failed: %d\n", (int)result);
        }

        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[GroupingModule] DetachFromGroup: detached %d paths\n", detachedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[GroupingModule] DetachFromGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[GroupingModule] DetachFromGroup unknown error\n"); }
}

//========================================================================================
//  SplitToNewGroup — move selected paths into a new group
//========================================================================================

void GroupingModule::SplitToNewGroup()
{
    try {
        fprintf(stderr, "[GroupingModule] SplitToNewGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[GroupingModule] SplitToNewGroup: no paths\n"); return; }

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
        if (selectedPaths.empty()) { fprintf(stderr, "[GroupingModule] SplitToNewGroup: no selected paths\n"); return; }

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) { fprintf(stderr, "[GroupingModule] SplitToNewGroup: NewArt failed: %d\n", (int)result); return; }

        ai::UnicodeString uName("Split Group");
        sAIArt->SetArtName(groupArt, uName);

        int movedCount = 0;
        for (AIArtHandle art : selectedPaths) {
            result = sAIArt->ReorderArt(art, kPlaceInsideOnTop, groupArt);
            if (result == kNoErr) movedCount++;
            else fprintf(stderr, "[GroupingModule] SplitToNewGroup: ReorderArt failed: %d\n", (int)result);
        }
        fprintf(stderr, "[GroupingModule] SplitToNewGroup: moved %d paths\n", movedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[GroupingModule] SplitToNewGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[GroupingModule] SplitToNewGroup unknown error\n"); }
}
