//========================================================================================
//  IllTool — Shape Classification + Simplification
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include "VisionEngine.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Static helpers for shape classification
//========================================================================================

// Helper: perpendicular distance from point P to line segment AB
static double PointToSegmentDist(AIRealPoint p, AIRealPoint a, AIRealPoint b)
{
    double abx = b.h - a.h, aby = b.v - a.v;
    double apx = p.h - a.h, apy = p.v - a.v;
    double abLenSq = abx * abx + aby * aby;
    if (abLenSq < 1e-12) return sqrt(apx * apx + apy * apy);
    double t = (apx * abx + apy * aby) / abLenSq;
    if (t < 0) t = 0; if (t > 1) t = 1;
    double dx = p.h - (a.h + abx * t);
    double dy = p.v - (a.v + aby * t);
    return sqrt(dx * dx + dy * dy);
}

static double Dist2D(AIRealPoint a, AIRealPoint b) {
    double dx = b.h - a.h, dy = b.v - a.v;
    return sqrt(dx * dx + dy * dy);
}

static bool Circumcircle(AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                          double& cx, double& cy, double& radius) {
    double ax = p1.h, ay = p1.v, bx = p2.h, by = p2.v, ccx = p3.h, ccy = p3.v;
    double D = 2.0 * (ax*(by-ccy) + bx*(ccy-ay) + ccx*(ay-by));
    if (fabs(D) < 1e-10) return false;
    cx = ((ax*ax+ay*ay)*(by-ccy) + (bx*bx+by*by)*(ccy-ay) + (ccx*ccx+ccy*ccy)*(ay-by)) / D;
    cy = ((ax*ax+ay*ay)*(ccx-bx) + (bx*bx+by*by)*(ax-ccx) + (ccx*ccx+ccy*ccy)*(bx-ax)) / D;
    double ddx = cx - p1.h, ddy = cy - p1.v;
    radius = sqrt(ddx*ddx + ddy*ddy);
    return true;
}

static const char* kShapeNames[] = {
    "LINE", "ARC", "L-SHAPE", "RECT", "S-CURVE", "ELLIPSE", "FREEFORM"
};

// Helper: find first path with segment-level or art-level selection
static AIArtHandle FindSelectedPath(AIArtHandle** matches, ai::int32 numMatches)
{
    AIArtHandle targetPath = nullptr;
    for (ai::int32 i = 0; i < numMatches && !targetPath; i++) {
        AIArtHandle art = (*matches)[i];
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(art, &segCount);
        if (segCount < 2) continue;
        for (ai::int16 s = 0; s < segCount; s++) {
            ai::int16 sel = kSegmentNotSelected;
            sAIPath->GetPathSegmentSelected(art, s, &sel);
            if (sel & kSegmentPointSelected) { targetPath = art; break; }
        }
        if (!targetPath) {
            ai::int32 selAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &selAttrs);
            if (selAttrs & kArtSelected) targetPath = art;
        }
    }
    return targetPath;
}

// Helper: find ALL paths with segment-level or art-level selection
static std::vector<AIArtHandle> FindAllSelectedPaths(AIArtHandle** matches, ai::int32 numMatches)
{
    std::vector<AIArtHandle> result;
    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(art, &segCount);
        if (segCount < 2) continue;
        bool hasSel = false;
        for (ai::int16 s = 0; s < segCount; s++) {
            ai::int16 sel = kSegmentNotSelected;
            sAIPath->GetPathSegmentSelected(art, s, &sel);
            if (sel & kSegmentPointSelected) { hasSel = true; break; }
        }
        if (!hasSel) {
            ai::int32 selAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &selAttrs);
            if (!(selAttrs & kArtSelected)) continue;
        }
        result.push_back(art);
    }
    return result;
}

// Classify a single path — returns best shape type and confidence
static BridgeShapeType ClassifySinglePath(AIArtHandle targetPath, double& outConf)
{
    outConf = 0;
    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(targetPath, &segCount);
    if (segCount < 2) return BridgeShapeType::Freeform;

    std::vector<AIRealPoint> pts(segCount);
    { std::vector<AIPathSegment> segs(segCount);
      sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
      for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p; }

    AIBoolean isClosed = false;
    sAIPath->GetPathClosed(targetPath, &isClosed);

    int n = (int)pts.size();
    AIRealPoint first = pts[0], last = pts[n-1];
    double span = Dist2D(first, last);

    // --- Test Line ---
    double lineDev = 0;
    for (int i = 1; i < n-1; i++) lineDev += PointToSegmentDist(pts[i], first, last);
    double avgLineDev = (n > 2) ? lineDev / (n-2) : 0;
    double lineConf = fmax(0, 1.0 - ((span > 1e-6) ? avgLineDev/span : 1.0) * 20.0);

    // --- Test Arc ---
    double arcConf = 0;
    if (n >= 3) {
        double ccxv, ccyv, r;
        if (Circumcircle(first, pts[n/2], last, ccxv, ccyv, r) && r > 1e-6) {
            double td = 0;
            for (int i = 0; i < n; i++)
                td += fabs(sqrt((pts[i].h-ccxv)*(pts[i].h-ccxv)+(pts[i].v-ccyv)*(pts[i].v-ccyv)) - r);
            double sw = fabs(atan2(first.v-ccyv,first.h-ccxv) - atan2(last.v-ccyv,last.h-ccxv));
            if (sw > M_PI) sw = 2*M_PI - sw;
            arcConf = fmax(0, (1.0 - (td/n)/r*10.0) * (sw < 5.5 ? 1.0 : 0.3));
        }
    }

    // --- Test L-Shape ---
    double lConf = 0;
    if (n >= 3 && span > 1e-6) {
        double maxD = 0; int ci = 0;
        for (int i = 1; i < n-1; i++) { double d = PointToSegmentDist(pts[i],first,last); if (d>maxD){maxD=d;ci=i;} }
        AIRealPoint corner = pts[ci];
        double d1 = 0, d2 = 0;
        for (int a = 1; a < ci; a++) d1 += PointToSegmentDist(pts[a], first, corner);
        for (int b = ci+1; b < n-1; b++) d2 += PointToSegmentDist(pts[b], corner, last);
        double rd = ((d1+d2)/fmax(1,n-3)) / span;
        double v1x=first.h-corner.h, v1y=first.v-corner.v, v2x=last.h-corner.h, v2y=last.v-corner.v;
        double ll1=sqrt(v1x*v1x+v1y*v1y), ll2=sqrt(v2x*v2x+v2y*v2y);
        double dot = (ll1>1e-6&&ll2>1e-6) ? (v1x*v2x+v1y*v2y)/(ll1*ll2) : 0;
        lConf = fmax(0, (1.0-rd*15.0) * fmax(0,1.0-fabs(dot)));
    }

    // --- Test Rectangle ---
    double rectConf = 0;
    if (n >= 4 && isClosed && (n == 4 || n == 5)) {
        int ra = 0;
        for (int i = 0; i < n; i++) {
            int prv = (i==0)?n-1:i-1, nxt = (i+1)%n;
            double aax=pts[prv].h-pts[i].h, aay=pts[prv].v-pts[i].v;
            double bbx=pts[nxt].h-pts[i].h, bby=pts[nxt].v-pts[i].v;
            double la=sqrt(aax*aax+aay*aay), lb=sqrt(bbx*bbx+bby*bby);
            if (la>1e-6 && lb>1e-6 && fabs((aax*bbx+aay*bby)/(la*lb)) < 0.3) ra++;
        }
        rectConf = (double)ra / fmax(1,n) * 0.9;
    }

    // --- Test S-Curve ---
    double sConf = 0;
    if (n >= 4) {
        int sc = 0, ps = 0;
        for (int i = 1; i < n-1; i++) {
            double cp = (pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v) - (pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
            int sg = (cp>0)?1:((cp<0)?-1:0);
            if (sg && ps && sg!=ps) sc++;
            if (sg) ps = sg;
        }
        sConf = 0.6 * ((sc>=1&&sc<=3)?1.0:0.3) * ((lineConf<0.7)?1.0:0.3);
    }

    // --- Test Ellipse ---
    double ellConf = 0;
    if (n >= 5 && isClosed) {
        double ecx=0,ecy=0;
        for (int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
        double ar=0;
        for (int i=0;i<n;i++) ar += sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy));
        ar /= n; if (ar<1) ar=1;
        double td=0;
        for (int i=0;i<n;i++) td += fabs(sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy))-ar);
        ellConf = fmax(0, (1.0-(td/n)/ar*5.0) * (isClosed ? 1.0 : 0.3));
    }

    struct { double conf; BridgeShapeType type; } cands[] = {
        {lineConf, BridgeShapeType::Line}, {arcConf, BridgeShapeType::Arc},
        {lConf, BridgeShapeType::LShape}, {rectConf, BridgeShapeType::Rect},
        {sConf, BridgeShapeType::SCurve}, {ellConf, BridgeShapeType::Ellipse},
    };

    BridgeShapeType bestType = BridgeShapeType::Freeform;
    double bestConf = 0.1;
    for (auto& c : cands) { if (c.conf > bestConf) { bestConf = c.conf; bestType = c.type; } }
    outConf = bestConf;
    return bestType;
}

//========================================================================================
//  Shape Classification — multi-path aware
//========================================================================================

void IllToolPlugin::ClassifySelection()
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            fLastDetectedShape = "---"; return;
        }
        std::vector<AIArtHandle> selected = FindAllSelectedPaths(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (selected.empty()) { fLastDetectedShape = "---"; return; }

        // Classify each selected path, tally votes
        int votes[7] = {0}; // indexed by BridgeShapeType
        int pathCount = (int)selected.size();

        for (AIArtHandle path : selected) {
            double conf = 0;
            BridgeShapeType type = ClassifySinglePath(path, conf);
            int idx = (int)type;
            if (idx >= 0 && idx < 7) votes[idx]++;
            fprintf(stderr, "[IllTool Timer] ClassifySelection: path=%p → %s (conf=%.2f)\n",
                    (void*)path, kShapeNames[idx], conf);
        }

        // Find dominant type by vote count
        BridgeShapeType dominant = BridgeShapeType::Freeform;
        int maxVotes = 0;
        for (int i = 0; i < 7; i++) {
            if (votes[i] > maxVotes) { maxVotes = votes[i]; dominant = (BridgeShapeType)i; }
        }

        // Check if mixed (dominant has less than all votes)
        bool isMixed = (maxVotes < pathCount && pathCount > 1);

        // Format label: "ARC" for single, "ARC (3)" for multi-same, "MIXED (7)" for multi-mixed
        static char labelBuf[32];
        if (pathCount == 1) {
            snprintf(labelBuf, sizeof(labelBuf), "%s", kShapeNames[(int)dominant]);
        } else if (isMixed) {
            snprintf(labelBuf, sizeof(labelBuf), "MIXED (%d)", pathCount);
        } else {
            snprintf(labelBuf, sizeof(labelBuf), "%s (%d)", kShapeNames[(int)dominant], pathCount);
        }
        fLastDetectedShape = labelBuf;

        fprintf(stderr, "[IllTool Timer] ClassifySelection: %d paths → %s [votes: L=%d A=%d Ls=%d R=%d S=%d E=%d F=%d]\n",
                pathCount, fLastDetectedShape,
                votes[0], votes[1], votes[2], votes[3], votes[4], votes[5], votes[6]);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] ClassifySelection error: %d\n", (int)ex); fLastDetectedShape = "ERROR"; }
    catch (...) { fprintf(stderr, "[IllTool Timer] ClassifySelection unknown error\n"); fLastDetectedShape = "ERROR"; }
}

//========================================================================================
//  Shape Reclassification — force-fit selection to a specific shape
//========================================================================================

void IllToolPlugin::ReclassifyAs(BridgeShapeType shapeType)
{
    // Freeform = no-op, don't destroy existing undo snapshot (Issue #7)
    if (shapeType == BridgeShapeType::Freeform) {
        fLastDetectedShape = "FREEFORM";
        fprintf(stderr, "[IllTool Timer] ReclassifyAs: freeform — no modification\n");
        return;
    }

    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            fprintf(stderr, "[IllTool Timer] ReclassifyAs: no path art\n"); return;
        }
        std::vector<AIArtHandle> selected = FindAllSelectedPaths(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (selected.empty()) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: no selected paths\n"); return; }

        // Snapshot all paths before destructive modification (H3 UndoStack)
        fUndoStack.PushFrame();

        // Tension scaling: slider 0-100, default 50 = no change (scale 1.0)
        double tensionScale = fmax(0.1, BridgeGetTension() / 50.0);
        fprintf(stderr, "[IllTool Timer] ReclassifyAs: %d paths, tension=%.0f, scale=%.2f\n",
                (int)selected.size(), BridgeGetTension(), tensionScale);

        int modifiedCount = 0;
        for (AIArtHandle targetPath : selected) {
        fUndoStack.SnapshotPath(targetPath);

        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(targetPath, &segCount);
        if (segCount < 2) continue;

        std::vector<AIPathSegment> segs(segCount);
        sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
        std::vector<AIRealPoint> pts(segCount);
        for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p;
        AIRealPoint first = pts[0], last = pts[segCount-1];

        std::vector<AIPathSegment> newSegs;

        switch (shapeType) {
            case BridgeShapeType::Line: {
                AIPathSegment s1={}, s2={};
                s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                s2.p=last;  s2.in=last;  s2.out=last;  s2.corner=true;
                newSegs.push_back(s1); newSegs.push_back(s2);
                break;
            }
            case BridgeShapeType::Arc: {
                int n=(int)pts.size();
                double ccxv,ccyv,r;
                if (!Circumcircle(first, pts[n/2], last, ccxv, ccyv, r) || r<1e-6) {
                    AIPathSegment s1={}, s2={};
                    s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                    s2.p=last;  s2.in=last;  s2.out=last;  s2.corner=true;
                    newSegs.push_back(s1); newSegs.push_back(s2);
                } else {
                    double a1=atan2(first.v-ccyv,first.h-ccxv), a3=atan2(last.v-ccyv,last.h-ccxv);
                    double sweep=a3-a1;
                    while(sweep>M_PI)sweep-=2*M_PI; while(sweep<-M_PI)sweep+=2*M_PI;
                    double am=a1+sweep*0.5;
                    AIRealPoint ap[3]={
                        {(AIReal)(ccxv+r*cos(a1)),(AIReal)(ccyv+r*sin(a1))},
                        {(AIReal)(ccxv+r*cos(am)),(AIReal)(ccyv+r*sin(am))},
                        {(AIReal)(ccxv+r*cos(a1+sweep)),(AIReal)(ccyv+r*sin(a1+sweep))}};
                    double sa=fabs(sweep/2), hLen=(4.0/3.0)*tan(sa/4.0)*r*tensionScale;
                    double ss=(sweep>=0)?1.0:-1.0;
                    double angs[3]={a1,am,a1+sweep};
                    for(int i=0;i<3;i++){
                        double th=angs[i], tx=-sin(th)*ss, ty=cos(th)*ss;
                        AIPathSegment seg={}; seg.p=ap[i]; seg.corner=false;
                        if(i==0){seg.in=ap[i]; seg.out.h=(AIReal)(ap[i].h+tx*hLen); seg.out.v=(AIReal)(ap[i].v+ty*hLen);}
                        else if(i==2){seg.in.h=(AIReal)(ap[i].h-tx*hLen); seg.in.v=(AIReal)(ap[i].v-ty*hLen); seg.out=ap[i];}
                        else{seg.in.h=(AIReal)(ap[i].h-tx*hLen); seg.in.v=(AIReal)(ap[i].v-ty*hLen);
                             seg.out.h=(AIReal)(ap[i].h+tx*hLen); seg.out.v=(AIReal)(ap[i].v+ty*hLen);}
                        newSegs.push_back(seg);
                    }
                }
                break;
            }
            case BridgeShapeType::LShape: {
                int ci=0; double md=0; int n=(int)pts.size();
                for(int i=1;i<n-1;i++){double d=PointToSegmentDist(pts[i],first,last);if(d>md){md=d;ci=i;}}
                AIRealPoint corner=pts[ci];
                AIPathSegment s1={},s2={},s3={};
                s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                s2.p=corner; s2.in=corner; s2.out=corner; s2.corner=true;
                s3.p=last; s3.in=last; s3.out=last; s3.corner=true;
                newSegs.push_back(s1); newSegs.push_back(s2); newSegs.push_back(s3);
                break;
            }
            case BridgeShapeType::Rect: {
                double mnH=pts[0].h, mxH=pts[0].h, mnV=pts[0].v, mxV=pts[0].v;
                for(int i=1;i<(int)pts.size();i++){
                    if(pts[i].h<mnH)mnH=pts[i].h; if(pts[i].h>mxH)mxH=pts[i].h;
                    if(pts[i].v<mnV)mnV=pts[i].v; if(pts[i].v>mxV)mxV=pts[i].v;
                }
                AIRealPoint co[4]={{(AIReal)mnH,(AIReal)mnV},{(AIReal)mxH,(AIReal)mnV},
                                   {(AIReal)mxH,(AIReal)mxV},{(AIReal)mnH,(AIReal)mxV}};
                for(int i=0;i<4;i++){AIPathSegment sg={}; sg.p=co[i]; sg.in=co[i]; sg.out=co[i]; sg.corner=true; newSegs.push_back(sg);}
                break;
            }
            case BridgeShapeType::SCurve: {
                int n=(int)pts.size(), ii=n/2, ps=0;
                for(int i=1;i<n-1;i++){
                    double cp=(pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v)-(pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
                    int sg=(cp>0)?1:((cp<0)?-1:0);
                    if(sg&&ps&&sg!=ps){ii=i;break;} if(sg)ps=sg;
                }
                AIRealPoint ip=pts[ii]; double tn=(1.0/6.0)*tensionScale;
                auto ms=[](AIRealPoint p,AIRealPoint ih,AIRealPoint oh){AIPathSegment sg={}; sg.p=p; sg.in=ih; sg.out=oh; sg.corner=false; return sg;};
                double t0x=(ip.h-first.h)*tn, t0y=(ip.v-first.v)*tn;
                newSegs.push_back(ms(first, first, {(AIReal)(first.h+t0x),(AIReal)(first.v+t0y)}));
                double t1x=(last.h-first.h)*tn, t1y=(last.v-first.v)*tn;
                newSegs.push_back(ms(ip, {(AIReal)(ip.h-t1x),(AIReal)(ip.v-t1y)}, {(AIReal)(ip.h+t1x),(AIReal)(ip.v+t1y)}));
                double t2x=(last.h-ip.h)*tn, t2y=(last.v-ip.v)*tn;
                newSegs.push_back(ms(last, {(AIReal)(last.h-t2x),(AIReal)(last.v-t2y)}, last));
                break;
            }
            case BridgeShapeType::Ellipse: {
                int n=(int)pts.size(); double ecx=0,ecy=0;
                for(int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
                double cxx=0,cxy=0,cyy=0;
                for(int i=0;i<n;i++){double dx=pts[i].h-ecx,dy=pts[i].v-ecy; cxx+=dx*dx; cxy+=dx*dy; cyy+=dy*dy;}
                cxx/=n; cxy/=n; cyy/=n;
                double tr=cxx+cyy, dt=cxx*cyy-cxy*cxy, disc=fmax(0,tr*tr/4-dt);
                double ev1=tr/2+sqrt(disc), ev2=tr/2-sqrt(disc);
                double ssa=sqrt(fmax(0,2*ev1)), ssb=sqrt(fmax(0,2*ev2));
                if(ssa<1)ssa=1; if(ssb<1)ssb=1;
                double ang = fabs(cxy)>1e-10 ? atan2(ev1-cxx,cxy) : (cxx>=cyy?0:M_PI/2);
                double ca=cos(ang), sna=sin(ang), kp=(4.0/3.0)*(sqrt(2.0)-1.0);
                double cAng[4]={0,M_PI/2,M_PI,3*M_PI/2};
                for(int j=0;j<4;j++){
                    double t=cAng[j], exx=ssa*cos(t), eyy=ssb*sin(t);
                    double px=exx*ca-eyy*sna+ecx, py=exx*sna+eyy*ca+ecy;
                    double ltx=-ssa*sin(t), lty=ssb*cos(t);
                    double wtx=ltx*ca-lty*sna, wty=ltx*sna+lty*ca;
                    double tl=sqrt(wtx*wtx+wty*wty); if(tl>1e-10){wtx/=tl;wty/=tl;}
                    double hl=((j%2==0)?kp*ssb:kp*ssa)*tensionScale;
                    AIPathSegment sg={}; sg.p.h=(AIReal)px; sg.p.v=(AIReal)py;
                    sg.in.h=(AIReal)(px-wtx*hl); sg.in.v=(AIReal)(py-wty*hl);
                    sg.out.h=(AIReal)(px+wtx*hl); sg.out.v=(AIReal)(py+wty*hl);
                    sg.corner=false; newSegs.push_back(sg);
                }
                break;
            }
            default:
                // Freeform handled by early return above; this covers unknown enum values
                return;
        }

        if (!newSegs.empty()) {
            ai::int16 nc = (ai::int16)newSegs.size();
            result = sAIPath->SetPathSegmentCount(targetPath, nc);
            if (result != kNoErr) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: SetPathSegmentCount failed: %d\n", (int)result); continue; }
            result = sAIPath->SetPathSegments(targetPath, 0, nc, newSegs.data());
            if (result != kNoErr) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: SetPathSegments failed: %d\n", (int)result); continue; }
            if (shapeType == BridgeShapeType::Rect || shapeType == BridgeShapeType::Ellipse)
                sAIPath->SetPathClosed(targetPath, true);
            else if (shapeType != BridgeShapeType::Freeform)
                sAIPath->SetPathClosed(targetPath, false);
            modifiedCount++;
            fprintf(stderr, "[IllTool Timer] ReclassifyAs: path %p → %d segments as %s\n",
                    (void*)targetPath, (int)nc, kShapeNames[(int)shapeType]);
        }
        } // end for-each selected path

        fLastDetectedShape = kShapeNames[(int)shapeType];
        fprintf(stderr, "[IllTool Timer] ReclassifyAs: modified %d/%d paths as %s\n",
                modifiedCount, (int)selected.size(), fLastDetectedShape);
        if (modifiedCount > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] ReclassifyAs error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool Timer] ReclassifyAs unknown error\n"); }
}

//========================================================================================
//  Simplification — Douglas-Peucker on selected paths
//========================================================================================

void IllToolPlugin::SimplifySelection(double tolerance)
{
    if (tolerance < 0.01) {
        fprintf(stderr, "[IllTool Timer] SimplifySelection: tolerance too small (%.2f), skipping\n", tolerance);
        return;
    }

    // Push undo frame before destructive modification (H3 UndoStack)
    fUndoStack.PushFrame();
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            fprintf(stderr, "[IllTool Timer] SimplifySelection: no path art\n"); return;
        }

        int totalSimplified = 0, totalBefore = 0, totalAfter = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden | kArtSelected, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            bool hasSel = false;
            if (attrs & kArtSelected) { hasSel = true; }
            else {
                ai::int16 sc = 0; sAIPath->GetPathSegmentCount(art, &sc);
                for (ai::int16 s = 0; s < sc; s++) {
                    ai::int16 sel = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &sel);
                    if (sel & kSegmentPointSelected) { hasSel = true; break; }
                }
            }
            if (!hasSel) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 3) continue;

            std::vector<AIPathSegment> segs(segCount);
            result = sAIPath->GetPathSegments(art, 0, segCount, segs.data());
            if (result != kNoErr) continue;
            totalBefore += segCount;

            // Douglas-Peucker iterative
            std::vector<bool> keep(segCount, false);
            keep[0] = true; keep[segCount-1] = true;
            std::vector<std::pair<int,int>> stk;
            stk.push_back({0, segCount-1});
            while (!stk.empty()) {
                auto rng = stk.back(); stk.pop_back();
                if (rng.second - rng.first < 2) continue;
                double md = 0; int mi = rng.first;
                for (int j = rng.first+1; j < rng.second; j++) {
                    double d = PointToSegmentDist(segs[j].p, segs[rng.first].p, segs[rng.second].p);
                    if (d > md) { md = d; mi = j; }
                }
                if (md > tolerance) { keep[mi]=true; stk.push_back({rng.first,mi}); stk.push_back({mi,rng.second}); }
            }

            std::vector<AIPathSegment> ns;
            for (int j=0; j<segCount; j++) if (keep[j]) ns.push_back(segs[j]);
            ai::int16 nc = (ai::int16)ns.size();
            if (nc >= 2 && nc < segCount) {
                fUndoStack.SnapshotPath(art);  // H3: snapshot before modifying
                sAIPath->SetPathSegmentCount(art, nc);
                sAIPath->SetPathSegments(art, 0, nc, ns.data());
                totalSimplified++; totalAfter += nc;
                fprintf(stderr, "[IllTool Timer] SimplifySelection: path %d: %d -> %d points\n", (int)i, (int)segCount, (int)nc);
            } else { totalAfter += segCount; }
        }
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[IllTool Timer] SimplifySelection: %d paths, %d -> %d pts (tol=%.1f)\n",
                totalSimplified, totalBefore, totalAfter, tolerance);
        if (totalSimplified > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] SimplifySelection error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool Timer] SimplifySelection unknown error\n"); }
}

//========================================================================================
//  SelectSmall — select all paths with arc length below threshold
//========================================================================================

void IllToolPlugin::SelectSmall(double threshold)
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            fprintf(stderr, "[IllTool Timer] SelectSmall: no path art\n");
            return;
        }

        // Deselect all paths first so SelectSmall replaces the selection
        for (ai::int32 d = 0; d < numMatches; d++) {
            AIArtHandle dArt = (*matches)[d];
            sAIArt->SetArtUserAttr(dArt, kArtSelected, 0);
        }

        int selectedCount = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 2) continue;

            AIBoolean closed = false;
            sAIPath->GetPathClosed(art, &closed);

            // Codex P2 fix: Use MeasureSegments for accurate bezier arc length
            // (same pattern as IllToolSmartSelect.cpp ComputeSignature)
            ai::int16 numPieces = closed ? segCount : (ai::int16)(segCount - 1);
            double totalLen = 0;
            if (numPieces > 0) {
                std::vector<AIReal> pieceLengths(numPieces);
                std::vector<AIReal> accumLengths(numPieces);
                ASErr measErr = sAIPath->MeasureSegments(art, 0, numPieces,
                                                         pieceLengths.data(), accumLengths.data());
                if (measErr == kNoErr) {
                    totalLen = (double)accumLengths[numPieces - 1]
                             + (double)pieceLengths[numPieces - 1];
                }
            }

            // Fallback: sum chord distances if MeasureSegments yielded zero
            if (totalLen <= 0.0) {
                std::vector<AIPathSegment> segs(segCount);
                sAIPath->GetPathSegments(art, 0, segCount, segs.data());
                for (ai::int16 s = 1; s < segCount; s++) {
                    totalLen += Dist2D(segs[s-1].p, segs[s].p);
                }
                if (closed && segCount >= 2) {
                    totalLen += Dist2D(segs[segCount-1].p, segs[0].p);
                }
            }

            if (totalLen < threshold) {
                sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
                selectedCount++;
            }
        }

        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[IllTool Timer] SelectSmall: selected %d paths below %.1f pt\n",
                selectedCount, threshold);
        if (selectedCount > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] SelectSmall error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool Timer] SelectSmall unknown error\n"); }
}

//========================================================================================
//  UndoStack implementation (H3) — generic multi-level undo for path operations
//========================================================================================

void IllToolPlugin::UndoStack::PushFrame()
{
    stack.push_back({});
    // Trim old frames if over limit
    while ((int)stack.size() > kMaxFrames) {
        stack.erase(stack.begin());
    }
    fprintf(stderr, "[IllTool] UndoStack: pushed frame (%zu frames total)\n", stack.size());
}

void IllToolPlugin::UndoStack::SnapshotPath(AIArtHandle art)
{
    if (stack.empty()) return;
    PathSnapshot snap;
    snap.art = art;
    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(art, &segCount);
    snap.segments.resize(segCount);
    sAIPath->GetPathSegments(art, 0, segCount, snap.segments.data());
    sAIPath->GetPathClosed(art, &snap.closed);
    stack.back().push_back(std::move(snap));
    fprintf(stderr, "[IllTool] UndoStack: snapshot path (%d segs) in frame %zu\n",
            (int)segCount, stack.size());
}

int IllToolPlugin::UndoStack::Undo()
{
    if (stack.empty()) {
        fprintf(stderr, "[IllTool] UndoStack: nothing to undo\n");
        return 0;
    }

    auto& frame = stack.back();
    int restored = 0;
    for (auto& snap : frame) {
        // Validate handle before restoring
        short artType = 0;
        ASErr err = sAIArt->GetArtType(snap.art, &artType);
        if (err != kNoErr || artType != kPathArt) {
            fprintf(stderr, "[IllTool] UndoStack: stale handle, skipping\n");
            continue;
        }
        ai::int16 nc = (ai::int16)snap.segments.size();
        sAIPath->SetPathSegmentCount(snap.art, nc);
        sAIPath->SetPathSegments(snap.art, 0, nc, snap.segments.data());
        sAIPath->SetPathClosed(snap.art, snap.closed);
        restored++;
    }
    stack.pop_back();
    fprintf(stderr, "[IllTool] UndoStack: restored %d paths (%zu frames remain)\n",
            restored, stack.size());
    if (restored > 0) sAIDocument->RedrawDocument();
    return restored;
}
