#ifndef __TRANSFORMMODULE_H__
#define __TRANSFORMMODULE_H__

//========================================================================================
//  TransformModule — Batch transform multiple selected shapes
//
//  Handles: TransformApply
//  Applies scale and rotation to all selected paths at once, with optional
//  random variance (+-20%) for organic variety.
//  Supports absolute and relative modes, px and % units.
//========================================================================================

#include "IllToolModule.h"

class TransformModule : public IllToolModule {
public:
    TransformModule() = default;
    ~TransformModule() override = default;

    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;

private:
    //------------------------------------------------------------------------------------
    //  Transform operation
    //------------------------------------------------------------------------------------

    /** Apply transform to all selected paths using bridge state. */
    void ApplyTransform();

    /** Transform a single point (p, in-handle, out-handle) through a matrix.
        Matrix is: translate to origin -> scale -> rotate -> translate back.
        @param pt       The point to transform (modified in place).
        @param cx, cy   Center of the art (pivot point).
        @param scaleX   Horizontal scale factor.
        @param scaleY   Vertical scale factor.
        @param cosA     Cosine of rotation angle.
        @param sinA     Sine of rotation angle. */
    static void TransformPoint(AIRealPoint& pt,
                               double cx, double cy,
                               double scaleX, double scaleY,
                               double cosA, double sinA);
};

#endif // __TRANSFORMMODULE_H__
