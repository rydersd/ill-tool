//========================================================================================
//
//  IllTool — Selection Panel Controller
//
//  Programmatic Cocoa panel for lasso/smart selection tools.
//  Controls: segmented mode switch, status label, clear button,
//  add-to-selection checkbox, selection count, threshold slider.
//
//========================================================================================

#ifndef __SELECTIONPANELCONTROLLER_H__
#define __SELECTIONPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface SelectionPanelController : NSObject

/** The root view containing all controls (add as subview of panel host). */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Selection count displayed in the panel. */
@property (nonatomic, assign) NSInteger selectionCount;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the selection count label from C++ side. */
- (void)updateSelectionCount:(NSInteger)count;

/** Update the status label text. */
- (void)updateStatusText:(NSString *)text;

@end

#endif // __OBJC__
#endif // __SELECTIONPANELCONTROLLER_H__
