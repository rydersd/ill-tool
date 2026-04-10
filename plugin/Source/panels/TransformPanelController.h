//========================================================================================
//
//  IllTool — Transform All Panel Controller
//
//  Programmatic Cocoa panel for batch-transforming selected shapes.
//  Controls: mode toggle (absolute/relative), width/height/rotation fields
//  with px/% unit pickers, random variance checkbox, selection count, apply button.
//
//========================================================================================

#ifndef __TRANSFORMPANELCONTROLLER_H__
#define __TRANSFORMPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface TransformPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the selected anchor count display. */
- (void)updateSelectionCount:(NSInteger)count;

@end

#endif // __OBJC__
#endif // __TRANSFORMPANELCONTROLLER_H__
