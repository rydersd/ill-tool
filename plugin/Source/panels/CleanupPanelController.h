//========================================================================================
//
//  IllTool — Cleanup Panel Controller
//
//  Programmatic Cocoa panel for shape classification and cleanup.
//  Controls: shape type buttons, detected shape label, tension/simplification
//  sliders, points count, layer name, average/confirm/cancel/select-small buttons.
//
//========================================================================================

#ifndef __CLEANUPPANELCONTROLLER_H__
#define __CLEANUPPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@interface CleanupPanelController : NSObject

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Checkbox: whether to delete originals on Apply. */
@property (nonatomic, strong) NSButton *deleteOriginalsCheckbox;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

/** Update the detected shape label. */
- (void)updateDetectedShape:(NSString *)shapeName;

/** Update the points count label. */
- (void)updatePointsCount:(NSInteger)count;

/** Update the decompose readout label. */
- (void)updateDecomposeReadout:(NSString *)text;

@end

#endif // __OBJC__
#endif // __CLEANUPPANELCONTROLLER_H__
