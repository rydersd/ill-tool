//========================================================================================
//
//  IllTool — Ill Layers Panel Controller
//
//  Programmatic Cocoa panel with NSOutlineView for the Illustrator layer tree.
//  Controls: preset popup, add layer, auto-organize, layer tree with
//  visibility/lock toggles, inline rename, drag-and-drop reorder.
//
//========================================================================================

#ifndef __LAYERPANELCONTROLLER_H__
#define __LAYERPANELCONTROLLER_H__

#ifdef __OBJC__
#import <Cocoa/Cocoa.h>

@class LayerNode;

@interface LayerPanelController : NSObject <NSOutlineViewDataSource, NSOutlineViewDelegate, NSTextFieldDelegate>

/** The root view containing all controls. */
@property (nonatomic, strong, readonly) NSView *rootView;

/** Create the controller and build the view hierarchy. */
- (instancetype)init;

@end

#endif // __OBJC__
#endif // __LAYERPANELCONTROLLER_H__
