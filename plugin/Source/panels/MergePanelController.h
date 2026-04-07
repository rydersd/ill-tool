//========================================================================================
//
//  IllTool — Merge Panel Controller
//
//  Programmatic Cocoa panel for endpoint merging.
//  Controls: tolerance slider, scan button, readout label,
//  chain-merge checkbox, preserve-handles checkbox, merge/undo buttons.
//
//========================================================================================

#ifndef __MERGEPANELCONTROLLER_H__
#define __MERGEPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface MergePanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the merge readout label. */
- (void)updateReadout:(NSString *)text;

@end

#endif // __OBJC__
#endif // __MERGEPANELCONTROLLER_H__
