//========================================================================================
//
//  IllTool — Transform All Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for batch-transforming selected shapes.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "TransformPanelController.h"
#import "IllToolTheme.h"
#include "IllToolPlugin.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>


static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;


/** Create an editable text field with dark theme styling. */
static NSTextField* MakeInputField(NSString *placeholder, CGFloat width)
{
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, width, 20)];
    field.font = [IllToolTheme monoFont];
    field.textColor = [IllToolTheme textColor];
    field.backgroundColor = [NSColor colorWithRed:0.15 green:0.15 blue:0.15 alpha:1.0];
    field.drawsBackground = YES;
    field.bordered = YES;
    field.bezelStyle = NSTextFieldSquareBezel;
    field.editable = YES;
    field.selectable = YES;
    field.placeholderString = placeholder;
    field.alignment = NSTextAlignmentRight;
    field.stringValue = @"0";
    return [field autorelease];
}

//========================================================================================
//  FlippedView — NSView subclass with y=0 at top (like UIKit)
//========================================================================================

@interface TransformFlippedView : NSView
@end

@implementation TransformFlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  TransformPanelController
//========================================================================================

@interface TransformPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSSegmentedControl *modeControl;
@property (nonatomic, strong) NSTextField *widthField;
@property (nonatomic, strong) NSTextField *heightField;
@property (nonatomic, strong) NSTextField *rotationField;
@property (nonatomic, strong) NSPopUpButton *widthUnitPicker;
@property (nonatomic, strong) NSPopUpButton *heightUnitPicker;
@property (nonatomic, strong) NSPopUpButton *rotationUnitPicker;
@property (nonatomic, strong) NSButton *randomCheckbox;
@property (nonatomic, strong) NSTextField *selectionCountLabel;
@property (nonatomic, strong) NSButton *applyButton;

// Timer for polling selection state
@property (nonatomic, strong) NSTimer *pollTimer;

@end

@implementation TransformPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        [self buildUI];
        // Poll for selection count at ~4Hz
        self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.25
            target:self selector:@selector(pollSelectionState:)
            userInfo:nil repeats:YES];
    }
    return self;
}

- (void)dealloc
{
    [self.pollTimer invalidate];
    self.pollTimer = nil;
    [super dealloc];
}

- (void)pollSelectionState:(NSTimer *)timer
{
    @autoreleasepool {
        // Read the cached selection count (updated by SDK notification context)
        int count = PluginGetSelectedAnchorCount();
        [self updateSelectionCount:count];
    }
}

- (NSView *)rootView
{
    return self.rootViewInternal;
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 320.0;
    TransformFlippedView *root = [[TransformFlippedView alloc]
        initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];

    CGFloat y = kPadding;
    CGFloat contentW = kPanelWidth - 2 * kPadding;

    //==================================================================================
    //  Title
    //==================================================================================

    NSTextField *title = [IllToolTheme makeLabelWithText:@"Transform All" font:[NSFont boldSystemFontOfSize:12] color:[IllToolTheme textColor]];
    title.frame = NSMakeRect(kPadding, y, contentW, 16);
    [root addSubview:title];
    y += 22;

    //==================================================================================
    //  Separator
    //==================================================================================

    NSBox *sep0 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, contentW, 1)];
    sep0.boxType = NSBoxSeparator;
    [root addSubview:sep0];
    [sep0 release];
    y += 1 + kPadding;

    //==================================================================================
    //  Mode toggle: Absolute / Relative
    //==================================================================================

    NSTextField *modeLbl = [IllToolTheme makeLabelWithText:@"Mode" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    modeLbl.frame = NSMakeRect(kPadding, y, 40, 16);
    [root addSubview:modeLbl];

    NSSegmentedControl *modeSeg = [NSSegmentedControl segmentedControlWithLabels:@[@"Absolute", @"Relative"]
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onModeChanged:)];
    modeSeg.frame = NSMakeRect(kPadding + 44, y - 2, contentW - 44, kRowHeight);
    modeSeg.selectedSegment = 1;  // Default to relative
    modeSeg.font = [NSFont systemFontOfSize:10];
    [root addSubview:modeSeg];
    self.modeControl = modeSeg;
    y += kRowHeight + kPadding;

    //==================================================================================
    //  Width row: label + input + unit picker
    //==================================================================================

    CGFloat labelW = 55;
    CGFloat unitW = 50;
    CGFloat fieldW = contentW - labelW - unitW - 8;

    // Width
    NSTextField *widthLbl = [IllToolTheme makeLabelWithText:@"Width:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    widthLbl.frame = NSMakeRect(kPadding, y + 2, labelW, 16);
    [root addSubview:widthLbl];

    NSTextField *wField = MakeInputField(@"0", fieldW);
    wField.frame = NSMakeRect(kPadding + labelW + 4, y, fieldW, 20);
    [root addSubview:wField];
    self.widthField = wField;

    NSPopUpButton *wUnit = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding + labelW + fieldW + 8, y, unitW, 20) pullsDown:NO];
    [wUnit addItemsWithTitles:@[@"px", @"%"]];
    wUnit.font = [NSFont systemFontOfSize:10];
    [root addSubview:wUnit];
    self.widthUnitPicker = wUnit;
    [wUnit release];
    y += kRowHeight + 4;

    // Height
    NSTextField *heightLbl = [IllToolTheme makeLabelWithText:@"Height:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    heightLbl.frame = NSMakeRect(kPadding, y + 2, labelW, 16);
    [root addSubview:heightLbl];

    NSTextField *hField = MakeInputField(@"0", fieldW);
    hField.frame = NSMakeRect(kPadding + labelW + 4, y, fieldW, 20);
    [root addSubview:hField];
    self.heightField = hField;

    NSPopUpButton *hUnit = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding + labelW + fieldW + 8, y, unitW, 20) pullsDown:NO];
    [hUnit addItemsWithTitles:@[@"px", @"%"]];
    hUnit.font = [NSFont systemFontOfSize:10];
    [root addSubview:hUnit];
    self.heightUnitPicker = hUnit;
    [hUnit release];
    y += kRowHeight + 4;

    // Rotation
    NSTextField *rotLbl = [IllToolTheme makeLabelWithText:@"Rotation:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    rotLbl.frame = NSMakeRect(kPadding, y + 2, labelW, 16);
    [root addSubview:rotLbl];

    NSTextField *rField = MakeInputField(@"0", fieldW);
    rField.frame = NSMakeRect(kPadding + labelW + 4, y, fieldW, 20);
    [root addSubview:rField];
    self.rotationField = rField;

    NSPopUpButton *rUnit = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding + labelW + fieldW + 8, y, unitW, 20) pullsDown:NO];
    [rUnit addItemsWithTitles:@[@"\u00B0", @"%"]];  // degree symbol
    rUnit.font = [NSFont systemFontOfSize:10];
    [root addSubview:rUnit];
    self.rotationUnitPicker = rUnit;
    [rUnit release];
    y += kRowHeight + kPadding;

    //==================================================================================
    //  Separator
    //==================================================================================

    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, contentW, 1)];
    sep1.boxType = NSBoxSeparator;
    [root addSubview:sep1];
    [sep1 release];
    y += 1 + kPadding;

    //==================================================================================
    //  Random checkbox
    //==================================================================================

    NSButton *randomCB = [NSButton checkboxWithTitle:@"Random (\u00B120% variance)"
                                              target:self action:@selector(onRandomToggled:)];
    randomCB.font = [IllToolTheme labelFont];
    // Checkbox text color (MRC-compatible attributed title)
    NSMutableAttributedString *cbTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Random (\u00B120% variance)"];
    [cbTitle addAttribute:NSForegroundColorAttributeName
                    value:[IllToolTheme textColor]
                    range:NSMakeRange(0, cbTitle.length)];
    [cbTitle addAttribute:NSFontAttributeName
                    value:[IllToolTheme labelFont]
                    range:NSMakeRange(0, cbTitle.length)];
    randomCB.attributedTitle = cbTitle;
    [cbTitle release];
    randomCB.frame = NSMakeRect(kPadding, y, contentW, 18);
    randomCB.state = NSControlStateValueOff;
    [root addSubview:randomCB];
    self.randomCheckbox = randomCB;
    y += 18 + 4;

    // Aspect ratio lock checkbox
    NSButton *aspectCB = [NSButton checkboxWithTitle:@"Lock Aspect Ratio"
                                              target:self action:@selector(onAspectLockToggled:)];
    aspectCB.font = [IllToolTheme labelFont];
    NSMutableAttributedString *aspectTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Lock Aspect Ratio"];
    [aspectTitle addAttribute:NSForegroundColorAttributeName
                        value:[IllToolTheme textColor]
                        range:NSMakeRange(0, aspectTitle.length)];
    [aspectTitle addAttribute:NSFontAttributeName
                        value:[IllToolTheme labelFont]
                        range:NSMakeRange(0, aspectTitle.length)];
    aspectCB.attributedTitle = aspectTitle;
    [aspectTitle release];
    aspectCB.frame = NSMakeRect(kPadding, y, contentW, 18);
    aspectCB.state = NSControlStateValueOff;
    [root addSubview:aspectCB];
    y += 18 + kPadding;

    //==================================================================================
    //  Separator
    //==================================================================================

    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, contentW, 1)];
    sep2.boxType = NSBoxSeparator;
    [root addSubview:sep2];
    [sep2 release];
    y += 1 + kPadding;

    //==================================================================================
    //  Selection count
    //==================================================================================

    NSTextField *selLbl = [IllToolTheme makeLabelWithText:@"Selected: 0 anchors" font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    selLbl.frame = NSMakeRect(kPadding, y, contentW, 14);
    [root addSubview:selLbl];
    self.selectionCountLabel = selLbl;
    y += 14 + kPadding;

    //==================================================================================
    //  Apply button
    //==================================================================================

    NSButton *applyBtn = [NSButton buttonWithTitle:@"Apply" target:self action:@selector(onApply:)];
    applyBtn.font = [NSFont boldSystemFontOfSize:12];
    applyBtn.bezelStyle = NSBezelStyleSmallSquare;
    applyBtn.frame = NSMakeRect(kPadding, y, contentW, 30);
    applyBtn.wantsLayer = YES;
    applyBtn.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
    applyBtn.layer.cornerRadius = 3.0;
    // White text on accent background
    NSMutableAttributedString *applyTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Apply"];
    [applyTitle addAttribute:NSForegroundColorAttributeName
                       value:[NSColor whiteColor]
                       range:NSMakeRange(0, 5)];
    [applyTitle addAttribute:NSFontAttributeName
                       value:[NSFont boldSystemFontOfSize:12]
                       range:NSMakeRange(0, 5)];
    applyBtn.attributedTitle = applyTitle;
    [applyTitle release];
    [root addSubview:applyBtn];
    self.applyButton = applyBtn;

    // Set initial bridge state to relative mode
    BridgeSetTransformMode(1);
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onModeChanged:(NSSegmentedControl *)sender
{
    int mode = (int)sender.selectedSegment;
    BridgeSetTransformMode(mode);
    fprintf(stderr, "[TransformPanel] Mode changed to %s\n",
            mode == 0 ? "absolute" : "relative");
}

- (void)onAspectLockToggled:(NSButton *)sender
{
    bool lock = (sender.state == NSControlStateValueOn);
    BridgeSetTransformLockAspectRatio(lock);
    fprintf(stderr, "[TransformPanel] Aspect lock %s\n", lock ? "ON" : "OFF");
}

- (void)onRandomToggled:(NSButton *)sender
{
    bool random = (sender.state == NSControlStateValueOn);
    BridgeSetTransformRandom(random);
    fprintf(stderr, "[TransformPanel] Random %s\n", random ? "ON" : "OFF");
}

- (void)onApply:(NSButton *)sender
{
    // Read field values and push to bridge
    double w = self.widthField.doubleValue;
    double h = self.heightField.doubleValue;
    double r = self.rotationField.doubleValue;

    BridgeSetTransformWidth(w);
    BridgeSetTransformHeight(h);
    BridgeSetTransformRotation(r);
    BridgeSetTransformUnitSize((int)self.widthUnitPicker.indexOfSelectedItem);
    BridgeSetTransformUnitRotation((int)self.rotationUnitPicker.indexOfSelectedItem);

    // Enqueue the operation
    PluginOp op{OpType::TransformApply};
    BridgeEnqueueOp(op);

    fprintf(stderr, "[TransformPanel] Apply: w=%.1f h=%.1f rot=%.1f mode=%d random=%d\n",
            w, h, r, BridgeGetTransformMode(), (int)BridgeGetTransformRandom());
}

//----------------------------------------------------------------------------------------
//  Selection count update
//----------------------------------------------------------------------------------------

- (void)updateSelectionCount:(NSInteger)count
{
    NSString *text = [NSString stringWithFormat:@"Selected: %ld anchor%s",
                      (long)count, count == 1 ? "" : "s"];
    self.selectionCountLabel.stringValue = text;
}

@end
