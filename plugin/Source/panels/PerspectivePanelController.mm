//========================================================================================
//
//  IllTool — Perspective Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for perspective grid controls.
//  Single "Set Perspective" button places all 3 VP lines at once.
//  Lock/Show toggles, per-line color legend, VP coordinate readouts.
//  Tabs: Grid | Mirror | Duplicate | Paste.
//  No XIB — all NSViews built in code.
//
//  NOTE: This file must be added to the Xcode project's pbxproj.
//
//========================================================================================

#import "PerspectivePanelController.h"
#import "IllToolTheme.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>
#import <string>


// Per-line VP colors (red, green, blue for VP1, VP2, VP3)
static NSColor* ITVP1Color()     { return [NSColor colorWithRed:0.90 green:0.30 blue:0.30 alpha:1.0]; }
static NSColor* ITVP2Color()     { return [NSColor colorWithRed:0.30 green:0.80 blue:0.30 alpha:1.0]; }
static NSColor* ITVP3Color()     { return [NSColor colorWithRed:0.35 green:0.55 blue:0.95 alpha:1.0]; }

static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;
static const CGFloat kSliderH     = 18.0;


static NSButton* MakeCheckbox(NSString *title, id target, SEL action)
{
    NSButton *chk = [NSButton checkboxWithTitle:title target:target action:action];
    chk.font = [IllToolTheme labelFont];
    // Dark theme text color for checkbox
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
        initWithString:title
        attributes:@{NSForegroundColorAttributeName: [IllToolTheme textColor], NSFontAttributeName: [IllToolTheme labelFont]}];
    chk.attributedTitle = attrTitle;
    [attrTitle release];
    return chk;
}

//========================================================================================
//  FlippedView — NSView subclass with y=0 at top (like UIKit)
//  Prevents top-of-panel clipping when panel window is shorter than content.
//========================================================================================

@interface PerspFlippedView : NSView
@end

@implementation PerspFlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  PerspectivePanelController
//========================================================================================

@interface PerspectivePanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Tab control
@property (nonatomic, strong) NSSegmentedControl *tabSegment;

// Tab content containers
@property (nonatomic, strong) NSView *gridTabView;
@property (nonatomic, strong) NSView *mirrorTabView;
@property (nonatomic, strong) NSView *duplicateTabView;
@property (nonatomic, strong) NSView *pasteTabView;

// Toolbar controls
@property (nonatomic, strong) NSButton *setPerspectiveButton;
@property (nonatomic, strong) NSButton *addVerticalButton;
@property (nonatomic, strong) NSButton *lockToggle;
@property (nonatomic, strong) NSButton *showToggle;
@property (nonatomic, strong) NSButton *deleteGridButton;
@property (nonatomic, strong) NSButton *autoMatchButton;
@property (nonatomic, strong) NSButton *snapToggle;

// Grid tab — status and VP readouts
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTextField *vp1CoordLabel;
@property (nonatomic, strong) NSTextField *vp2CoordLabel;
@property (nonatomic, strong) NSTextField *vp3CoordLabel;

// Grid tab — sliders
@property (nonatomic, strong) NSSlider *densitySlider;
@property (nonatomic, strong) NSTextField *densityValueLabel;
@property (nonatomic, strong) NSSlider *horizonSlider;
@property (nonatomic, strong) NSTextField *horizonValueLabel;

// Grid tab — preset controls
@property (nonatomic, strong) NSTextField *presetNameField;
@property (nonatomic, strong) NSButton *presetSaveButton;
@property (nonatomic, strong) NSButton *presetLoadButton;

// Mirror tab
@property (nonatomic, strong) NSSegmentedControl *mirrorAxisSegment;
@property (nonatomic, strong) NSButton *mirrorReplaceCheck;
@property (nonatomic, strong) NSButton *mirrorPreviewCheck;

// Duplicate tab
@property (nonatomic, strong) NSSlider *dupCountSlider;
@property (nonatomic, strong) NSTextField *dupCountLabel;
@property (nonatomic, strong) NSPopUpButton *dupSpacingPopup;
@property (nonatomic, strong) NSButton *dupPreviewCheck;

// Paste tab
@property (nonatomic, strong) NSSegmentedControl *pastePlaneSegment;
@property (nonatomic, strong) NSSlider *pasteScaleSlider;
@property (nonatomic, strong) NSTextField *pasteScaleLabel;

// Timer for polling grid status
@property (nonatomic, strong) NSTimer *statusTimer;

@end

@implementation PerspectivePanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        [self buildUI];
        // Poll for grid status updates at ~4Hz
        self.statusTimer = [NSTimer scheduledTimerWithTimeInterval:0.25
            target:self selector:@selector(pollStatus:)
            userInfo:nil repeats:YES];
    }
    return self;
}

- (void)dealloc
{
    [self.statusTimer invalidate];
    self.statusTimer = nil;
    [super dealloc];
}

- (NSView *)rootView
{
    return self.rootViewInternal;
}

//----------------------------------------------------------------------------------------
//  Status polling — reads bridge state to update labels
//----------------------------------------------------------------------------------------

- (void)pollStatus:(NSTimer *)timer
{
    BridgePerspectiveLine left  = BridgeGetPerspectiveLine(0);
    BridgePerspectiveLine right = BridgeGetPerspectiveLine(1);
    BridgePerspectiveLine vert  = BridgeGetPerspectiveLine(2);
    bool locked  = BridgeGetPerspectiveLocked();
    bool visible = BridgeGetPerspectiveVisible();

    int activeCount = (left.active ? 1 : 0) + (right.active ? 1 : 0) + (vert.active ? 1 : 0);
    bool valid = left.active && right.active;

    // Update status label
    if (locked && valid) {
        if (activeCount >= 3) {
            self.statusLabel.stringValue = @"Locked \u2014 3-point";
        } else {
            self.statusLabel.stringValue = @"Locked \u2014 2-point";
        }
        self.statusLabel.textColor = [IllToolTheme greenColor];
    } else if (valid) {
        if (activeCount >= 3) {
            self.statusLabel.stringValue = @"3-point perspective";
        } else {
            self.statusLabel.stringValue = @"2-point perspective";
        }
        self.statusLabel.textColor = [IllToolTheme accentColor];
    } else if (activeCount > 0) {
        self.statusLabel.stringValue = [NSString stringWithFormat:@"%d line(s) placed", activeCount];
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    } else {
        self.statusLabel.stringValue = @"No grid";
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    }

    // Update VP coordinate readouts
    [self updateVPCoord:self.vp1CoordLabel line:left label:@"VP1"];
    [self updateVPCoord:self.vp2CoordLabel line:right label:@"VP2"];
    [self updateVPCoord:self.vp3CoordLabel line:vert label:@"VP3"];

    // Update lock toggle state
    self.lockToggle.state = locked ? NSControlStateValueOn : NSControlStateValueOff;

    // Update show toggle state
    self.showToggle.state = visible ? NSControlStateValueOn : NSControlStateValueOff;

    // Update Set Perspective button title based on state
    if (activeCount >= 2) {
        self.setPerspectiveButton.title = @"Reset Perspective";
    } else {
        self.setPerspectiveButton.title = @"Set Perspective";
    }

    // Disable "Add Vertical" if VP3 is already placed or VP1/VP2 not yet placed
    self.addVerticalButton.enabled = (activeCount >= 2 && !vert.active);

    // Disable "Delete Grid" if no grid is placed
    self.deleteGridButton.enabled = (activeCount > 0);
}

- (void)updateVPCoord:(NSTextField *)label line:(BridgePerspectiveLine)line label:(NSString *)prefix
{
    if (line.active) {
        // Compute approximate VP by extending the line (midpoint as display coordinate)
        double mx = (line.h1x + line.h2x) * 0.5;
        double my = (line.h1y + line.h2y) * 0.5;
        label.stringValue = [NSString stringWithFormat:@"%@: (%.0f, %.0f)", prefix, mx, my];
        label.textColor = [IllToolTheme textColor];
    } else {
        label.stringValue = [NSString stringWithFormat:@"%@ \u2014 Not set", prefix];
        label.textColor = [IllToolTheme secondaryTextColor];
    }
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 530.0;  // must match panel height in IllToolPanels.mm
    // Flipped view: y=0 at top, content builds top-down. If panel is shorter,
    // bottom gets clipped (less important) rather than top (buttons).
    PerspFlippedView *root = [[PerspFlippedView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];

    CGFloat y = kPadding;

    // --- Bottom: [Snap to Perspective] ---
    NSButton *snapChk = MakeCheckbox(@"Snap to Perspective", self, @selector(onSnapToggle:));
    snapChk.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    snapChk.state = NSControlStateValueOn;
    [root addSubview:snapChk];
    self.snapToggle = snapChk;
    y += (kRowHeight + 4);

    // --- Row: [Lock] [Show] [Delete Grid] ---
    NSButton *lockChk = MakeCheckbox(@"Lock", self, @selector(onLockToggle:));
    lockChk.frame = NSMakeRect(kPadding, y, 52, kRowHeight);
    [root addSubview:lockChk];
    self.lockToggle = lockChk;

    NSButton *showChk = MakeCheckbox(@"Show", self, @selector(onShowToggle:));
    showChk.frame = NSMakeRect(kPadding + 56, y, 52, kRowHeight);
    showChk.state = NSControlStateValueOn;
    [root addSubview:showChk];
    self.showToggle = showChk;

    NSButton *delBtn = [IllToolTheme makeButtonWithTitle:@"Delete Grid" target:self action:@selector(onDeleteGrid:)];
    delBtn.frame = NSMakeRect(kPadding + 112, y, kPanelWidth - 2*kPadding - 112, kRowHeight);
    [root addSubview:delBtn];
    self.deleteGridButton = delBtn;
    y += (kRowHeight + 4);

    // --- Row: [Set Perspective] [Add Vertical] ---
    CGFloat halfBtnW = (kPanelWidth - 2*kPadding - 4) / 2.0;

    NSButton *setBtn = [IllToolTheme makeButtonWithTitle:@"Set Perspective" target:self action:@selector(onSetPerspective:)];
    setBtn.frame = NSMakeRect(kPadding, y, halfBtnW, kRowHeight);
    [root addSubview:setBtn];
    self.setPerspectiveButton = setBtn;

    NSButton *addVertBtn = [IllToolTheme makeButtonWithTitle:@"Add Vertical" target:self action:@selector(onAddVertical:)];
    addVertBtn.frame = NSMakeRect(kPadding + halfBtnW + 4, y, halfBtnW, kRowHeight);
    [root addSubview:addVertBtn];
    self.addVerticalButton = addVertBtn;
    y += (kRowHeight + 4);

    // --- Row: [Auto Match] — detect VPs from placed reference image ---
    NSButton *autoMatchBtn = [IllToolTheme makeButtonWithTitle:@"Auto Match" target:self action:@selector(onAutoMatch:)];
    autoMatchBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:autoMatchBtn];
    self.autoMatchButton = autoMatchBtn;
    y += (kRowHeight + kPadding);

    // --- Per-line color legend ---
    NSTextField *colorTitle = [IllToolTheme makeLabelWithText:@"Line Colors:" font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
    colorTitle.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [root addSubview:colorTitle];
    y += (14 + 4);

    CGFloat colW = (kPanelWidth - 2*kPadding) / 3.0;

    // VP1 swatch + label
    NSView *sw1 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding, y, 10, 10)];
    sw1.wantsLayer = YES;
    sw1.layer.backgroundColor = ITVP1Color().CGColor;
    sw1.layer.cornerRadius = 5.0;
    [root addSubview:sw1];
    [sw1 release];

    NSTextField *vp1Lbl = [IllToolTheme makeLabelWithText:@"VP1" font:[IllToolTheme monoFont] color:ITVP1Color()];
    vp1Lbl.frame = NSMakeRect(kPadding + 14, y, colW - 14, 12);
    [root addSubview:vp1Lbl];

    // VP2 swatch + label
    NSView *sw2 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding + colW, y, 10, 10)];
    sw2.wantsLayer = YES;
    sw2.layer.backgroundColor = ITVP2Color().CGColor;
    sw2.layer.cornerRadius = 5.0;
    [root addSubview:sw2];
    [sw2 release];

    NSTextField *vp2Lbl = [IllToolTheme makeLabelWithText:@"VP2" font:[IllToolTheme monoFont] color:ITVP2Color()];
    vp2Lbl.frame = NSMakeRect(kPadding + colW + 14, y, colW - 14, 12);
    [root addSubview:vp2Lbl];

    // VP3 swatch + label
    NSView *sw3 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding + 2*colW, y, 10, 10)];
    sw3.wantsLayer = YES;
    sw3.layer.backgroundColor = ITVP3Color().CGColor;
    sw3.layer.cornerRadius = 5.0;
    [root addSubview:sw3];
    [sw3 release];

    NSTextField *vp3Lbl = [IllToolTheme makeLabelWithText:@"VP3" font:[IllToolTheme monoFont] color:ITVP3Color()];
    vp3Lbl.frame = NSMakeRect(kPadding + 2*colW + 14, y, colW - 14, 12);
    [root addSubview:vp3Lbl];

    y += (12 + kPadding);

    // --- Tab Segment Control ---
    NSArray *tabs = @[@"Grid", @"Mirror", @"Duplicate", @"Paste"];
    NSSegmentedControl *seg = [NSSegmentedControl segmentedControlWithLabels:tabs
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onTabChanged:)];
    seg.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    seg.font = [NSFont systemFontOfSize:10];
    seg.selectedSegment = 0;
    [root addSubview:seg];
    self.tabSegment = seg;
    y += (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep.boxType = NSBoxSeparator;
    [root addSubview:sep];
    [sep release];
    y += (1 + kPadding);

    // Tab content starts here and fills remaining space upward
    CGFloat contentH = totalHeight - y;
    NSRect contentFrame = NSMakeRect(0, y, kPanelWidth, contentH);

    // --- Grid Tab ---
    self.gridTabView = [self buildGridTab:contentFrame];
    [root addSubview:self.gridTabView];
    [self.gridTabView release];  // strong property retains

    // --- Mirror Tab ---
    self.mirrorTabView = [self buildMirrorTab:contentFrame];
    self.mirrorTabView.hidden = YES;
    [root addSubview:self.mirrorTabView];
    [self.mirrorTabView release];

    // --- Duplicate Tab ---
    self.duplicateTabView = [self buildDuplicateTab:contentFrame];
    self.duplicateTabView.hidden = YES;
    [root addSubview:self.duplicateTabView];
    [self.duplicateTabView release];

    // --- Paste Tab ---
    self.pasteTabView = [self buildPasteTab:contentFrame];
    self.pasteTabView.hidden = YES;
    [root addSubview:self.pasteTabView];
    [self.pasteTabView release];
}

//----------------------------------------------------------------------------------------
//  Grid tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildGridTab:(NSRect)frame
{
    PerspFlippedView *container = [[PerspFlippedView alloc] initWithFrame:frame];
    CGFloat y = kPadding;

    // --- Status label ---
    NSTextField *status = [IllToolTheme makeLabelWithText:@"No grid" font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    status.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [container addSubview:status];
    self.statusLabel = status;
    y += (14 + kPadding);

    // --- VP coordinate readouts (read-only) ---
    NSTextField *vp1 = [IllToolTheme makeLabelWithText:@"VP1 \u2014 Not set" font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    vp1.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp1];
    self.vp1CoordLabel = vp1;
    y += (14 + 2);

    NSTextField *vp2 = [IllToolTheme makeLabelWithText:@"VP2 \u2014 Not set" font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    vp2.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp2];
    self.vp2CoordLabel = vp2;
    y += (14 + 2);

    NSTextField *vp3 = [IllToolTheme makeLabelWithText:@"VP3 \u2014 Not set" font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    vp3.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp3];
    self.vp3CoordLabel = vp3;
    y += (14 + kPadding);

    // --- Horizon slider (0-100% of artboard height, 100=top) ---
    NSTextField *horizLbl = [IllToolTheme makeLabelWithText:@"Horizon" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    horizLbl.frame = NSMakeRect(kPadding, y, 80, 14);
    [container addSubview:horizLbl];

    NSTextField *horizVal = [IllToolTheme makeLabelWithText:@"33%" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    horizVal.frame = NSMakeRect(kPanelWidth - kPadding - 40, y, 40, 14);
    horizVal.alignment = NSTextAlignmentRight;
    [container addSubview:horizVal];
    self.horizonValueLabel = horizVal;
    y += (14 + 2);

    NSSlider *horizSlider = [NSSlider sliderWithValue:33 minValue:0 maxValue:100
                                               target:self action:@selector(onHorizonChanged:)];
    horizSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:horizSlider];
    self.horizonSlider = horizSlider;
    y += (kSliderH + kPadding);

    // --- Grid density slider ---
    NSTextField *densLbl = [IllToolTheme makeLabelWithText:@"Grid Density" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    densLbl.frame = NSMakeRect(kPadding, y, 100, 14);
    [container addSubview:densLbl];

    NSTextField *densVal = [IllToolTheme makeLabelWithText:@"5" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    densVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, 14);
    densVal.alignment = NSTextAlignmentRight;
    [container addSubview:densVal];
    self.densityValueLabel = densVal;
    y += (14 + 2);

    NSSlider *densSlider = [NSSlider sliderWithValue:5 minValue:2 maxValue:20
                                              target:self action:@selector(onDensityChanged:)];
    densSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:densSlider];
    self.densitySlider = densSlider;
    y += (kSliderH + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [container addSubview:sep2];
    [sep2 release];
    y += (1 + kPadding);

    // --- Preset section ---
    NSTextField *presetLbl = [IllToolTheme makeLabelWithText:@"Preset" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    presetLbl.frame = NSMakeRect(kPadding, y, 50, 14);
    [container addSubview:presetLbl];
    y += (14 + 4);

    // Preset name text field (editable)
    NSTextField *presetField = [[NSTextField alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight)];
    presetField.font = [IllToolTheme monoFont];
    presetField.textColor = [IllToolTheme textColor];
    presetField.backgroundColor = [NSColor colorWithRed:0.15 green:0.15 blue:0.15 alpha:1.0];
    presetField.drawsBackground = YES;
    presetField.bordered = YES;
    presetField.editable = YES;
    presetField.placeholderString = @"preset1";
    [container addSubview:presetField];
    self.presetNameField = presetField;
    [presetField release];
    y += (kRowHeight + 4);

    // Save / Load buttons side by side
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;

    NSButton *saveBtn = [IllToolTheme makeButtonWithTitle:@"Save Preset" target:self action:@selector(onPresetSave:)];
    saveBtn.frame = NSMakeRect(kPadding, y, halfW, kRowHeight);
    [container addSubview:saveBtn];
    self.presetSaveButton = saveBtn;

    NSButton *loadBtn = [IllToolTheme makeButtonWithTitle:@"Load Preset" target:self action:@selector(onPresetLoad:)];
    loadBtn.frame = NSMakeRect(kPadding + halfW + 4, y, halfW, kRowHeight);
    [container addSubview:loadBtn];
    self.presetLoadButton = loadBtn;
    y += (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep3 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep3.boxType = NSBoxSeparator;
    [container addSubview:sep3];
    [sep3 release];
    y += (1 + kPadding);

    // --- Clear Grid button ---
    NSButton *clearBtn = [IllToolTheme makeButtonWithTitle:@"Clear Grid" target:self action:@selector(onClearGrid:)];
    clearBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:clearBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Mirror tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildMirrorTab:(NSRect)frame
{
    PerspFlippedView *container = [[PerspFlippedView alloc] initWithFrame:frame];
    CGFloat y = kPadding;

    // --- Axis selector ---
    NSTextField *axisLbl = [IllToolTheme makeLabelWithText:@"Axis:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    axisLbl.frame = NSMakeRect(kPadding, y, 40, 14);
    [container addSubview:axisLbl];
    y += (14 + 4);

    NSArray *axisLabels = @[@"Vertical", @"Horizontal", @"Custom"];
    NSSegmentedControl *axisSeg = [NSSegmentedControl segmentedControlWithLabels:axisLabels
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onMirrorAxisChanged:)];
    axisSeg.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    axisSeg.font = [NSFont systemFontOfSize:10];
    axisSeg.selectedSegment = 0;
    [container addSubview:axisSeg];
    self.mirrorAxisSegment = axisSeg;
    y += (kRowHeight + kPadding);

    // --- Options ---
    NSButton *replaceChk = MakeCheckbox(@"Replace original (copy by default)", self, @selector(onMirrorOptionChanged:));
    replaceChk.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:replaceChk];
    self.mirrorReplaceCheck = replaceChk;
    y += (kRowHeight + 2);

    NSButton *previewChk = MakeCheckbox(@"Preview", self, @selector(onMirrorOptionChanged:));
    previewChk.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:previewChk];
    self.mirrorPreviewCheck = previewChk;
    y += (kRowHeight + kPadding);

    // --- Mirror button ---
    NSButton *mirrorBtn = [IllToolTheme makeButtonWithTitle:@"Mirror" target:self action:@selector(onMirrorExecute:)];
    mirrorBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:mirrorBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Duplicate tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildDuplicateTab:(NSRect)frame
{
    PerspFlippedView *container = [[PerspFlippedView alloc] initWithFrame:frame];
    CGFloat y = kPadding;

    // --- Count slider ---
    NSTextField *countLbl = [IllToolTheme makeLabelWithText:@"Count:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    countLbl.frame = NSMakeRect(kPadding, y, 50, 14);
    [container addSubview:countLbl];

    NSTextField *countVal = [IllToolTheme makeLabelWithText:@"3" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    countVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, 14);
    countVal.alignment = NSTextAlignmentRight;
    [container addSubview:countVal];
    self.dupCountLabel = countVal;
    y += (14 + 2);

    NSSlider *countSlider = [NSSlider sliderWithValue:3 minValue:1 maxValue:20
                                               target:self action:@selector(onDupCountChanged:)];
    countSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:countSlider];
    self.dupCountSlider = countSlider;
    y += (kSliderH + kPadding);

    // --- Spacing popup ---
    NSTextField *spaceLbl = [IllToolTheme makeLabelWithText:@"Spacing:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    spaceLbl.frame = NSMakeRect(kPadding, y, 60, 14);
    [container addSubview:spaceLbl];
    y += (14 + 4);

    NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight) pullsDown:NO];
    [popup addItemsWithTitles:@[@"Equal in Perspective", @"Equal in Screen", @"Custom"]];
    popup.font = [IllToolTheme labelFont];
    popup.target = self;
    popup.action = @selector(onDupSpacingChanged:);
    [container addSubview:popup];
    self.dupSpacingPopup = popup;
    [popup release];
    y += (kRowHeight + kPadding);

    // --- Options ---
    NSButton *previewChk = MakeCheckbox(@"Preview", self, @selector(onDupOptionChanged:));
    previewChk.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:previewChk];
    self.dupPreviewCheck = previewChk;
    y += (kRowHeight + kPadding);

    // --- Duplicate button ---
    NSButton *dupBtn = [IllToolTheme makeButtonWithTitle:@"Duplicate" target:self action:@selector(onDuplicateExecute:)];
    dupBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:dupBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Paste tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildPasteTab:(NSRect)frame
{
    PerspFlippedView *container = [[PerspFlippedView alloc] initWithFrame:frame];
    CGFloat y = kPadding;

    // --- Plane selector ---
    NSTextField *planeLbl = [IllToolTheme makeLabelWithText:@"Plane:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    planeLbl.frame = NSMakeRect(kPadding, y, 50, 14);
    [container addSubview:planeLbl];
    y += (14 + 4);

    NSArray *planeLabels = @[@"Floor", @"Left Wall", @"Right Wall", @"Custom"];
    NSSegmentedControl *planeSeg = [NSSegmentedControl segmentedControlWithLabels:planeLabels
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onPastePlaneChanged:)];
    planeSeg.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    planeSeg.font = [NSFont systemFontOfSize:9];
    planeSeg.selectedSegment = 0;
    [container addSubview:planeSeg];
    self.pastePlaneSegment = planeSeg;
    y += (kRowHeight + kPadding);

    // --- Scale slider ---
    NSTextField *scaleLbl = [IllToolTheme makeLabelWithText:@"Scale:" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    scaleLbl.frame = NSMakeRect(kPadding, y, 50, 14);
    [container addSubview:scaleLbl];

    NSTextField *scaleVal = [IllToolTheme makeLabelWithText:@"100%" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    scaleVal.frame = NSMakeRect(kPanelWidth - kPadding - 45, y, 45, 14);
    scaleVal.alignment = NSTextAlignmentRight;
    [container addSubview:scaleVal];
    self.pasteScaleLabel = scaleVal;
    y += (14 + 2);

    NSSlider *scaleSlider = [NSSlider sliderWithValue:100 minValue:10 maxValue:200
                                               target:self action:@selector(onPasteScaleChanged:)];
    scaleSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:scaleSlider];
    self.pasteScaleSlider = scaleSlider;
    y += (kSliderH + kPadding * 2);

    // --- Paste in Perspective button ---
    NSButton *pasteBtn = [IllToolTheme makeButtonWithTitle:@"Paste in Perspective" target:self action:@selector(onPasteExecute:)];
    pasteBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:pasteBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Tab switching
//----------------------------------------------------------------------------------------

- (void)onTabChanged:(NSSegmentedControl *)sender
{
    NSInteger tab = sender.selectedSegment;
    self.gridTabView.hidden      = (tab != 0);
    self.mirrorTabView.hidden    = (tab != 1);
    self.duplicateTabView.hidden = (tab != 2);
    self.pasteTabView.hidden     = (tab != 3);
    fprintf(stderr, "[IllTool Panel] Perspective tab: %ld\n", (long)tab);
}

//----------------------------------------------------------------------------------------
//  Set Perspective — activates the perspective tool for VP1 placement on canvas
//  VP2 is auto-mirrored across viewport center when VP1 is placed.
//----------------------------------------------------------------------------------------

- (void)onSetPerspective:(id)sender
{
    PluginOp op;
    op.type = OpType::ActivatePerspectiveTool;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Set Perspective — activating tool for VP placement\n");
}

//----------------------------------------------------------------------------------------
//  Add Vertical — places VP3 at center of viewport
//----------------------------------------------------------------------------------------

- (void)onAddVertical:(id)sender
{
    PluginOp op;
    op.type = OpType::PlaceVerticalVP;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Add Vertical VP\n");
}

//----------------------------------------------------------------------------------------
//  Auto Match — detect VPs from placed reference image
//----------------------------------------------------------------------------------------

- (void)onAutoMatch:(id)sender
{
    PluginOp op;
    op.type = OpType::AutoMatchPerspective;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Auto Match Perspective from reference image\n");
}

//----------------------------------------------------------------------------------------
//  Delete Grid — clear grid and hide everything
//----------------------------------------------------------------------------------------

- (void)onDeleteGrid:(id)sender
{
    PluginOp op;
    op.type = OpType::DeletePerspective;
    BridgeEnqueueOp(op);
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    BridgeSetPerspectiveVisible(false);
    fprintf(stderr, "[IllTool Panel] Delete Grid\n");
}

//----------------------------------------------------------------------------------------
//  Lock / Show toggles
//----------------------------------------------------------------------------------------

- (void)onLockToggle:(NSButton *)sender
{
    bool newLocked = (sender.state == NSControlStateValueOn);
    // Lock = exit edit mode. Unlock = enter edit mode.
    PluginOp op;
    op.type = OpType::LockPerspective;
    op.boolParam1 = newLocked;
    BridgeEnqueueOp(op);
    BridgeSetPerspectiveLocked(newLocked);
    // Also toggle edit mode via bridge op
    PluginOp editOp;
    editOp.type = OpType::SetPerspEditMode;
    editOp.boolParam1 = !newLocked;  // edit when unlocked
    BridgeEnqueueOp(editOp);
    fprintf(stderr, "[IllTool Panel] %s grid (%s)\n",
            newLocked ? "Lock" : "Unlock",
            newLocked ? "exit edit" : "enter edit");
}

- (void)onShowToggle:(NSButton *)sender
{
    bool newVisible = (sender.state == NSControlStateValueOn);
    BridgeSetPerspectiveVisible(newVisible);
    fprintf(stderr, "[IllTool Panel] %s grid\n", newVisible ? "Show" : "Hide");
}

- (void)onSnapToggle:(NSButton *)sender
{
    bool snap = (sender.state == NSControlStateValueOn);
    BridgeSetSnapToPerspective(snap);
    fprintf(stderr, "[IllTool Panel] Snap to perspective: %s\n", snap ? "ON" : "OFF");
}

//----------------------------------------------------------------------------------------
//  Slider actions
//----------------------------------------------------------------------------------------

- (void)onHorizonChanged:(NSSlider *)sender
{
    double pct = sender.doubleValue;
    self.horizonValueLabel.stringValue = [NSString stringWithFormat:@"%.0f%%", pct];
    // Send as percentage — module converts to artboard Y
    BridgeSetHorizonY(pct);
    // Enqueue an invalidation op so the annotator redraws immediately
    // (without this, the grid only updates on the next timer-driven draw cycle)
    PluginOp op;
    op.type = OpType::InvalidateOverlay;
    BridgeEnqueueOp(op);
}

- (void)onDensityChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.densityValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    PluginOp op;
    op.type = OpType::SetGridDensity;
    op.intParam = value;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Grid Density: %d\n", value);
}

//----------------------------------------------------------------------------------------
//  Clear Grid
//----------------------------------------------------------------------------------------

- (void)onClearGrid:(id)sender
{
    PluginOp op;
    op.type = OpType::ClearPerspective;
    BridgeEnqueueOp(op);
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    fprintf(stderr, "[IllTool Panel] Clear Grid\n");
}

//----------------------------------------------------------------------------------------
//  Mirror tab actions
//----------------------------------------------------------------------------------------

- (void)onMirrorAxisChanged:(NSSegmentedControl *)sender
{
    int axis = (int)sender.selectedSegment;
    fprintf(stderr, "[IllTool Panel] Mirror axis: %d\n", axis);
}

- (void)onMirrorOptionChanged:(id)sender
{
    // Options update — state read at execute time
}

- (void)onMirrorExecute:(id)sender
{
    int axis = (int)self.mirrorAxisSegment.selectedSegment;
    bool replace = (self.mirrorReplaceCheck.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Mirror execute: axis=%d replace=%d\n", axis, replace);

    PluginOp op;
    op.type = OpType::MirrorPerspective;
    op.intParam = axis;
    op.boolParam1 = replace;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Mirror op queued\n");
}

//----------------------------------------------------------------------------------------
//  Duplicate tab actions
//----------------------------------------------------------------------------------------

- (void)onDupCountChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.dupCountLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Duplicate count: %d\n", value);
}

- (void)onDupSpacingChanged:(NSPopUpButton *)sender
{
    int spacing = (int)sender.indexOfSelectedItem;
    fprintf(stderr, "[IllTool Panel] Duplicate spacing: %d\n", spacing);
}

- (void)onDupOptionChanged:(id)sender
{
    // Options update — state read at execute time
}

- (void)onDuplicateExecute:(id)sender
{
    int count = (int)self.dupCountSlider.integerValue;
    int spacing = (int)self.dupSpacingPopup.indexOfSelectedItem;
    fprintf(stderr, "[IllTool Panel] Duplicate execute: count=%d spacing=%d\n", count, spacing);

    PluginOp op;
    op.type = OpType::DuplicatePerspective;
    op.intParam = count;
    op.param1 = (double)spacing;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Duplicate op queued\n");
}

//----------------------------------------------------------------------------------------
//  Paste tab actions
//----------------------------------------------------------------------------------------

- (void)onPastePlaneChanged:(NSSegmentedControl *)sender
{
    int plane = (int)sender.selectedSegment;
    fprintf(stderr, "[IllTool Panel] Paste plane: %d\n", plane);
}

- (void)onPasteScaleChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.pasteScaleLabel.stringValue = [NSString stringWithFormat:@"%d%%", value];
    fprintf(stderr, "[IllTool Panel] Paste scale: %d%%\n", value);
}

- (void)onPasteExecute:(id)sender
{
    int plane = (int)self.pastePlaneSegment.selectedSegment;
    double scale = self.pasteScaleSlider.doubleValue;
    fprintf(stderr, "[IllTool Panel] Paste execute: plane=%d scale=%.0f%%\n", plane, scale);

    PluginOp op;
    op.type = OpType::PastePerspective;
    op.intParam = plane;
    op.param1 = scale;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Paste op queued\n");
}

//----------------------------------------------------------------------------------------
//  Public API
//----------------------------------------------------------------------------------------

- (void)updateGridStatus:(BOOL)valid vpCount:(int)count density:(int)density
{
    if (!valid) {
        self.statusLabel.stringValue = @"No grid";
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    } else if (count >= 3) {
        self.statusLabel.stringValue = @"3-point perspective";
        self.statusLabel.textColor = [IllToolTheme accentColor];
    } else {
        self.statusLabel.stringValue = @"2-point perspective";
        self.statusLabel.textColor = [IllToolTheme accentColor];
    }
    self.densitySlider.integerValue = density;
    self.densityValueLabel.stringValue = [NSString stringWithFormat:@"%d", density];
}

//----------------------------------------------------------------------------------------
//  Preset Save / Load
//----------------------------------------------------------------------------------------

- (void)onPresetSave:(id)sender
{
    NSString *name = self.presetNameField.stringValue;
    if (name.length == 0) name = @"preset1";

    PluginOp op;
    op.type = OpType::PerspectivePresetSave;
    op.strParam = std::string([name UTF8String]);
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Save preset: %s\n", [name UTF8String]);
}

- (void)onPresetLoad:(id)sender
{
    NSString *name = self.presetNameField.stringValue;
    if (name.length == 0) name = @"preset1";

    PluginOp op;
    op.type = OpType::PerspectivePresetLoad;
    op.strParam = std::string([name UTF8String]);
    BridgeEnqueueOp(op);
    fprintf(stderr, "[IllTool Panel] Load preset: %s\n", [name UTF8String]);
}

@end

//========================================================================================
//  C-callable wrappers
//========================================================================================

void PluginPlaceVerticalVP(void)
{
    PluginOp op;
    op.type = OpType::PlaceVerticalVP;
    BridgeEnqueueOp(op);
}

void PluginDeletePerspective(void)
{
    PluginOp op;
    op.type = OpType::DeletePerspective;
    BridgeEnqueueOp(op);
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    BridgeSetPerspectiveVisible(false);
}

void PluginAutoMatchPerspective(void)
{
    PluginOp op;
    op.type = OpType::AutoMatchPerspective;
    BridgeEnqueueOp(op);
}
