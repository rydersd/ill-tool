//========================================================================================
//
//  IllTool -- Shared Theme System (Objective-C++)
//
//  Centralized color/font/control-factory definitions for all IllTool panels.
//  Uses dynamic color providers so panels automatically adapt to Illustrator's
//  light and dark appearance modes.
//
//========================================================================================

#import "IllToolTheme.h"

@implementation IllToolTheme

//----------------------------------------------------------------------------------------
//  Background Colors
//----------------------------------------------------------------------------------------

+ (NSColor *)panelBackground
{
    return [NSColor colorWithName:nil dynamicProvider:^NSColor *(NSAppearance *appearance) {
        NSAppearanceName name = [appearance bestMatchFromAppearancesWithNames:@[
            NSAppearanceNameAqua, NSAppearanceNameDarkAqua
        ]];
        if ([name isEqualToString:NSAppearanceNameDarkAqua]) {
            return [NSColor colorWithWhite:0.20 alpha:1.0];
        } else {
            return [NSColor colorWithWhite:0.92 alpha:1.0];
        }
    }];
}

+ (NSColor *)groupBackground
{
    return [NSColor colorWithName:nil dynamicProvider:^NSColor *(NSAppearance *appearance) {
        NSAppearanceName name = [appearance bestMatchFromAppearancesWithNames:@[
            NSAppearanceNameAqua, NSAppearanceNameDarkAqua
        ]];
        if ([name isEqualToString:NSAppearanceNameDarkAqua]) {
            return [NSColor colorWithWhite:0.24 alpha:1.0];
        } else {
            return [NSColor colorWithWhite:0.88 alpha:1.0];
        }
    }];
}

//----------------------------------------------------------------------------------------
//  Text Colors
//----------------------------------------------------------------------------------------

+ (NSColor *)textColor
{
    return [NSColor controlTextColor];
}

+ (NSColor *)secondaryTextColor
{
    return [NSColor secondaryLabelColor];
}

+ (NSColor *)monoTextColor
{
    return [NSColor controlTextColor];
}

//----------------------------------------------------------------------------------------
//  Accent Colors
//----------------------------------------------------------------------------------------

+ (NSColor *)accentColor
{
    return [NSColor controlAccentColor];
}

+ (NSColor *)greenColor
{
    return [NSColor colorWithName:nil dynamicProvider:^NSColor *(NSAppearance *appearance) {
        NSAppearanceName name = [appearance bestMatchFromAppearancesWithNames:@[
            NSAppearanceNameAqua, NSAppearanceNameDarkAqua
        ]];
        if ([name isEqualToString:NSAppearanceNameDarkAqua]) {
            return [NSColor colorWithRed:0.3 green:0.85 blue:0.4 alpha:1.0];
        } else {
            return [NSColor colorWithRed:0.2 green:0.7 blue:0.3 alpha:1.0];
        }
    }];
}

//----------------------------------------------------------------------------------------
//  Control Colors
//----------------------------------------------------------------------------------------

+ (NSColor *)buttonBackground
{
    return [NSColor controlColor];
}

+ (NSColor *)buttonTextColor
{
    return [NSColor controlTextColor];
}

//----------------------------------------------------------------------------------------
//  Fonts
//----------------------------------------------------------------------------------------

+ (NSFont *)titleFont
{
    return [NSFont boldSystemFontOfSize:12];
}

+ (NSFont *)labelFont
{
    return [NSFont systemFontOfSize:11];
}

+ (NSFont *)monoFont
{
    return [NSFont monospacedSystemFontOfSize:10 weight:NSFontWeightRegular];
}

+ (NSFont *)smallFont
{
    return [NSFont systemFontOfSize:10];
}

//----------------------------------------------------------------------------------------
//  Helper: create a styled label
//----------------------------------------------------------------------------------------

+ (NSTextField *)makeLabelWithText:(NSString *)text font:(NSFont *)font color:(NSColor *)color
{
    NSTextField *label = [NSTextField labelWithString:text];
    label.font = font;
    label.textColor = color;
    label.backgroundColor = [NSColor clearColor];
    label.drawsBackground = NO;
    label.bordered = NO;
    label.editable = NO;
    label.selectable = NO;
    return label;
}

//----------------------------------------------------------------------------------------
//  Helper: create a styled button
//----------------------------------------------------------------------------------------

+ (NSButton *)makeButtonWithTitle:(NSString *)title target:(id)target action:(SEL)action
{
    NSButton *btn = [NSButton buttonWithTitle:title target:target action:action];
    btn.font = [IllToolTheme labelFont];
    btn.bezelStyle = NSBezelStyleSmallSquare;
    return btn;
}

@end
