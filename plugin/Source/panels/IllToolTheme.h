#ifndef __ILLTOOLTHEME_H__
#define __ILLTOOLTHEME_H__

#import <Cocoa/Cocoa.h>

/// Shared theme helpers for all IllTool panels.
/// Uses system appearance (NSAppearance) which Illustrator sets to match its theme.
/// All colors automatically adapt to light/dark mode.
@interface IllToolTheme : NSObject

// Background
+ (NSColor *)panelBackground;       // panel content area background
+ (NSColor *)groupBackground;       // slightly lighter/darker for grouped sections

// Text
+ (NSColor *)textColor;             // primary text (labels, titles)
+ (NSColor *)secondaryTextColor;    // dimmed text (status, hints)
+ (NSColor *)monoTextColor;         // monospace value displays

// Accent
+ (NSColor *)accentColor;           // highlight color for values, counts
+ (NSColor *)greenColor;            // success/active indicators

// Controls
+ (NSColor *)buttonBackground;      // button fill
+ (NSColor *)buttonTextColor;       // button label

// Fonts
+ (NSFont *)titleFont;              // bold 12pt for panel titles
+ (NSFont *)labelFont;              // regular 11pt for labels
+ (NSFont *)monoFont;               // monospace 10pt for values
+ (NSFont *)smallFont;              // regular 10pt for status text

// Helpers -- create standard controls with theme colors
+ (NSTextField *)makeLabelWithText:(NSString *)text font:(NSFont *)font color:(NSColor *)color;
+ (NSButton *)makeButtonWithTitle:(NSString *)title target:(id)target action:(SEL)action;

@end

#endif
