//========================================================================================
//
//  IllTool — Trace Panel Controller
//
//  Programmatic Cocoa panel for tracing raster images via MCP backends.
//  Controls: backend popup (vtracer/OpenCV/StarVector), speckle slider,
//  color precision slider, trace button, status label.
//
//========================================================================================

#ifndef __TRACEPANELCONTROLLER_H__
#define __TRACEPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface TracePanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update status text from bridge. */
- (void)updateStatus;

@end

#endif // __OBJC__
#endif // __TRACEPANELCONTROLLER_H__
