//========================================================================================
//
//  IllTool — Ill Pen Panel Controller
//
//  Programmatic Cocoa panel for the Ill Pen drawing tool.
//  Controls: pen mode toggle, path name, target group, chamfer radius
//  with uniform edges checkbox and presets, finalize/cancel buttons.
//
//========================================================================================

#ifndef __PENPANELCONTROLLER_H__
#define __PENPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface PenPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

@end

#endif // __OBJC__
#endif // __PENPANELCONTROLLER_H__
