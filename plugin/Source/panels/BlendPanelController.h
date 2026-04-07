//========================================================================================
//
//  IllTool — Blend Harmonization Panel Controller
//
//  Programmatic Cocoa panel for path blending.
//  Controls: path pick A/B, step count slider, easing presets,
//  interactive cubic-bezier curve editor, preset save/load, blend button.
//
//  NOTE: This file must be added to the Xcode project's pbxproj
//
//========================================================================================

#ifndef __BLENDPANELCONTROLLER_H__
#define __BLENDPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface BlendPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the path status display from external state. */
- (void)updatePathStatus:(BOOL)hasA pathB:(BOOL)hasB;

@end

#endif // __OBJC__
#endif // __BLENDPANELCONTROLLER_H__
