//========================================================================================
//
//  IllTool — Surface Shading Panel Controller
//
//  Dedicated panel for blend shading and mesh gradient shading.
//  Controls: mode toggle, color wells + eyedroppers, light direction circle,
//  intensity slider, mode-specific step/grid controls, apply button.
//
//  NOTE: This file must be added to the Xcode project's pbxproj
//
//========================================================================================

#ifndef __SHADINGPANELCONTROLLER_H__
#define __SHADINGPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface ShadingPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

@end

#endif // __OBJC__
#endif // __SHADINGPANELCONTROLLER_H__
