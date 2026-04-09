//========================================================================================
//
//  IllTool — Surface Extraction Panel Controller
//
//  Click-to-extract surface boundaries from reference images.
//  Controls: extract mode toggle, sensitivity slider, status display.
//
//========================================================================================

#ifndef __SURFACEPANELCONTROLLER_H__
#define __SURFACEPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface SurfacePanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update status text from bridge. */
- (void)updateStatus;

@end

#endif // __OBJC__
#endif // __SURFACEPANELCONTROLLER_H__
