//========================================================================================
//
//  IllTool — Perspective Panel Controller
//
//  Programmatic Cocoa panel for perspective grid management.
//  Controls: unified Set Perspective button, lock/show toggles,
//  per-line color legend, grid density slider, tab segments for
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

/** Save/load preset actions. */
- (void)onPresetSave:(id)sender;
- (void)onPresetLoad:(id)sender;

/** C-callable: place VP3 at center of viewport (called from "Add Vertical" button). */
void PluginPlaceVerticalVP(void);

/** C-callable: delete perspective grid entirely. */
void PluginDeletePerspective(void);

/** C-callable: auto-match perspective from placed reference image. */
void PluginAutoMatchPerspective(void);

@end

#endif // __OBJC__
#endif // __PERSPECTIVEPANELCONTROLLER_H__
