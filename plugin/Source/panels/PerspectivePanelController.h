//========================================================================================
//
//  IllTool — Perspective Panel Controller
//
//  Programmatic Cocoa panel for perspective grid management.
//  Controls: VP buttons, grid density slider, tab segments for
//  Grid / Mirror / Duplicate / Paste modes.
//
//  NOTE: This file must be added to the Xcode project's pbxproj.
//
//========================================================================================

#ifndef __PERSPECTIVEPANELCONTROLLER_H__
#define __PERSPECTIVEPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface PerspectivePanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update grid status display. */
- (void)updateGridStatus:(BOOL)valid vpCount:(int)count density:(int)density;

@end

#endif // __OBJC__
#endif // __PERSPECTIVEPANELCONTROLLER_H__
