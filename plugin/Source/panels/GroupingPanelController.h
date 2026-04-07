//========================================================================================
//
//  IllTool — Grouping Panel Controller
//
//  Programmatic Cocoa panel for group management.
//  Controls: group name field, copy-to-group button, simplification slider,
//  points count, confirm/reset/cancel, detach/split buttons.
//
//========================================================================================

#ifndef __GROUPINGPANELCONTROLLER_H__
#define __GROUPINGPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface GroupingPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the points count label. */
- (void)updatePointsCount:(NSInteger)count;

/** Show or hide the in-group controls (detach/split). */
- (void)setInGroupMode:(BOOL)inGroup;

@end

#endif // __OBJC__
#endif // __GROUPINGPANELCONTROLLER_H__
