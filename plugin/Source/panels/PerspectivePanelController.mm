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
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>
#import <string>

//----------------------------------------------------------------------------------------
//  Dark theme constants matching Illustrator (same as other panels)
//----------------------------------------------------------------------------------------

static NSColor* ITBGColor()       { return [NSColor colorWithRed:0.20 green:0.20 blue:0.20 alpha:1.0]; }
static NSColor* ITTextColor()     { return [NSColor colorWithRed:0.85 green:0.85 blue:0.85 alpha:1.0]; }
static NSColor* ITAccentColor()   { return [NSColor colorWithRed:0.48 green:0.72 blue:0.94 alpha:1.0]; }
static NSColor* ITDimColor()      { return [NSColor colorWithRed:0.55 green:0.55 blue:0.55 alpha:1.0]; }
static NSColor* ITGreenColor()    { return [NSColor colorWithRed:0.40 green:0.80 blue:0.40 alpha:1.0]; }
static NSFont*  ITLabelFont()     { return [NSFont systemFontOfSize:11]; }
static NSFont*  ITMonoFont()      { return [NSFont monospacedSystemFontOfSize:10 weight:NSFontWeightRegular]; }

// Per-line VP colors (red, green, blue for VP1, VP2, VP3)
static NSColor* ITVP1Color()     { return [NSColor colorWithRed:0.90 green:0.30 blue:0.30 alpha:1.0]; }
static NSColor* ITVP2Color()     { return [NSColor colorWithRed:0.30 green:0.80 blue:0.30 alpha:1.0]; }
static NSColor* ITVP3Color()     { return [NSColor colorWithRed:0.35 green:0.55 blue:0.95 alpha:1.0]; }

static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;
static const CGFloat kSliderH     = 18.0;

//----------------------------------------------------------------------------------------
//  Helpers
//----------------------------------------------------------------------------------------

static NSTextField* MakeLabel(NSString *text, NSFont *font, NSColor *color)
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

static NSButton* MakeButton(NSString *title, id target, SEL action)
{
    NSButton *btn = [NSButton buttonWithTitle:title target:target action:action];
    btn.font = ITLabelFont();
    btn.bezelStyle = NSBezelStyleSmallSquare;
    return btn;
}

static NSButton* MakeCheckbox(NSString *title, id target, SEL action)
{
    NSButton *chk = [NSButton checkboxWithTitle:title target:target action:action];
    chk.font = ITLabelFont();
    // Dark theme text color for checkbox
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
        initWithString:title
        attributes:@{NSForegroundColorAttributeName: ITTextColor(), NSFontAttributeName: ITLabelFont()}];
    chk.attributedTitle = attrTitle;
    [attrTitle release];
    return chk;
}

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
@property (nonatomic, strong) NSButton *lockToggle;
@property (nonatomic, strong) NSButton *showToggle;

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
        self.statusLabel.textColor = ITGreenColor();
    } else if (valid) {
        if (activeCount >= 3) {
            self.statusLabel.stringValue = @"3-point perspective";
        } else {
            self.statusLabel.stringValue = @"2-point perspective";
        }
        self.statusLabel.textColor = ITAccentColor();
    } else if (activeCount > 0) {
        self.statusLabel.stringValue = [NSString stringWithFormat:@"%d line(s) placed", activeCount];
        self.statusLabel.textColor = ITDimColor();
    } else {
        self.statusLabel.stringValue = @"No grid";
        self.statusLabel.textColor = ITDimColor();
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
    if (activeCount >= 3) {
        self.setPerspectiveButton.title = @"Reset Perspective";
    } else if (activeCount > 0) {
        self.setPerspectiveButton.title = @"Set Perspective";
    } else {
        self.setPerspectiveButton.title = @"Set Perspective";
    }
}

- (void)updateVPCoord:(NSTextField *)label line:(BridgePerspectiveLine)line label:(NSString *)prefix
{
    if (line.active) {
        // Compute approximate VP by extending the line (midpoint as display coordinate)
        double mx = (line.h1x + line.h2x) * 0.5;
        double my = (line.h1y + line.h2y) * 0.5;
        label.stringValue = [NSString stringWithFormat:@"%@: (%.0f, %.0f)", prefix, mx, my];
        label.textColor = ITTextColor();
    } else {
        label.stringValue = [NSString stringWithFormat:@"%@ \u2014 Not set", prefix];
        label.textColor = ITDimColor();
    }
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 440.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];  // strong property retains

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Perspective", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    // --- Toolbar row: [Set Perspective] [Lock] [Show] ---
    CGFloat btnW = (kPanelWidth - 2*kPadding - 8) / 3.0;  // 3 buttons with 4px gaps

    NSButton *setBtn = MakeButton(@"Set Perspective", self, @selector(onSetPerspective:));
    setBtn.frame = NSMakeRect(kPadding, y - kRowHeight, btnW + 20, kRowHeight);
    [root addSubview:setBtn];
    self.setPerspectiveButton = setBtn;

    NSButton *lockChk = MakeCheckbox(@"Lock", self, @selector(onLockToggle:));
    lockChk.frame = NSMakeRect(kPadding + btnW + 24, y - kRowHeight, 52, kRowHeight);
    [root addSubview:lockChk];
    self.lockToggle = lockChk;

    NSButton *showChk = MakeCheckbox(@"Show", self, @selector(onShowToggle:));
    showChk.frame = NSMakeRect(kPadding + btnW + 80, y - kRowHeight, 52, kRowHeight);
    showChk.state = NSControlStateValueOn;  // default visible
    [root addSubview:showChk];
    self.showToggle = showChk;

    y -= (kRowHeight + kPadding);

    // --- Per-line color legend ---
    NSTextField *colorTitle = MakeLabel(@"Line Colors:", ITLabelFont(), ITDimColor());
    colorTitle.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [root addSubview:colorTitle];
    y -= (14 + 4);

    CGFloat colW = (kPanelWidth - 2*kPadding) / 3.0;

    // VP1 swatch + label
    NSView *sw1 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding, y - 12, 10, 10)];
    sw1.wantsLayer = YES;
    sw1.layer.backgroundColor = ITVP1Color().CGColor;
    sw1.layer.cornerRadius = 5.0;
    [root addSubview:sw1];
    [sw1 release];

    NSTextField *vp1Lbl = MakeLabel(@"VP1", ITMonoFont(), ITVP1Color());
    vp1Lbl.frame = NSMakeRect(kPadding + 14, y - 12, colW - 14, 12);
    [root addSubview:vp1Lbl];

    // VP2 swatch + label
    NSView *sw2 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding + colW, y - 12, 10, 10)];
    sw2.wantsLayer = YES;
    sw2.layer.backgroundColor = ITVP2Color().CGColor;
    sw2.layer.cornerRadius = 5.0;
    [root addSubview:sw2];
    [sw2 release];

    NSTextField *vp2Lbl = MakeLabel(@"VP2", ITMonoFont(), ITVP2Color());
    vp2Lbl.frame = NSMakeRect(kPadding + colW + 14, y - 12, colW - 14, 12);
    [root addSubview:vp2Lbl];

    // VP3 swatch + label
    NSView *sw3 = [[NSView alloc] initWithFrame:NSMakeRect(kPadding + 2*colW, y - 12, 10, 10)];
    sw3.wantsLayer = YES;
    sw3.layer.backgroundColor = ITVP3Color().CGColor;
    sw3.layer.cornerRadius = 5.0;
    [root addSubview:sw3];
    [sw3 release];

    NSTextField *vp3Lbl = MakeLabel(@"VP3", ITMonoFont(), ITVP3Color());
    vp3Lbl.frame = NSMakeRect(kPadding + 2*colW + 14, y - 12, colW - 14, 12);
    [root addSubview:vp3Lbl];

    y -= (12 + kPadding);

    // --- Tab Segment Control ---
    NSArray *tabs = @[@"Grid", @"Mirror", @"Duplicate", @"Paste"];
    NSSegmentedControl *seg = [NSSegmentedControl segmentedControlWithLabels:tabs
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onTabChanged:)];
    seg.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    seg.font = [NSFont systemFontOfSize:10];
    seg.selectedSegment = 0;
    [root addSubview:seg];
    self.tabSegment = seg;
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep.boxType = NSBoxSeparator;
    [root addSubview:sep];
    [sep release];
    y -= (1 + kPadding);

    CGFloat contentH = y;
    NSRect contentFrame = NSMakeRect(0, 0, kPanelWidth, contentH);

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
    NSView *container = [[NSView alloc] initWithFrame:frame];
    CGFloat y = frame.size.height - kPadding;

    // --- Status label ---
    NSTextField *status = MakeLabel(@"No grid", ITMonoFont(), ITDimColor());
    status.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [container addSubview:status];
    self.statusLabel = status;
    y -= (14 + kPadding);

    // --- VP coordinate readouts (read-only) ---
    NSTextField *vp1 = MakeLabel(@"VP1 \u2014 Not set", ITMonoFont(), ITDimColor());
    vp1.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp1];
    self.vp1CoordLabel = vp1;
    y -= (14 + 2);

    NSTextField *vp2 = MakeLabel(@"VP2 \u2014 Not set", ITMonoFont(), ITDimColor());
    vp2.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp2];
    self.vp2CoordLabel = vp2;
    y -= (14 + 2);

    NSTextField *vp3 = MakeLabel(@"VP3 \u2014 Not set", ITMonoFont(), ITDimColor());
    vp3.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [container addSubview:vp3];
    self.vp3CoordLabel = vp3;
    y -= (14 + kPadding);

    // --- Horizon slider ---
    NSTextField *horizLbl = MakeLabel(@"Horizon Y", ITLabelFont(), ITTextColor());
    horizLbl.frame = NSMakeRect(kPadding, y - 14, 80, 14);
    [container addSubview:horizLbl];

    NSTextField *horizVal = MakeLabel(@"400", ITMonoFont(), ITAccentColor());
    horizVal.frame = NSMakeRect(kPanelWidth - kPadding - 40, y - 14, 40, 14);
    horizVal.alignment = NSTextAlignmentRight;
    [container addSubview:horizVal];
    self.horizonValueLabel = horizVal;
    y -= (14 + 2);

    NSSlider *horizSlider = [NSSlider sliderWithValue:400 minValue:-500 maxValue:1500
                                               target:self action:@selector(onHorizonChanged:)];
    horizSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:horizSlider];
    self.horizonSlider = horizSlider;
    y -= (kSliderH + kPadding);

    // --- Grid density slider ---
    NSTextField *densLbl = MakeLabel(@"Grid Density", ITLabelFont(), ITTextColor());
    densLbl.frame = NSMakeRect(kPadding, y - 14, 100, 14);
    [container addSubview:densLbl];

    NSTextField *densVal = MakeLabel(@"5", ITMonoFont(), ITAccentColor());
    densVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    densVal.alignment = NSTextAlignmentRight;
    [container addSubview:densVal];
    self.densityValueLabel = densVal;
    y -= (14 + 2);

    NSSlider *densSlider = [NSSlider sliderWithValue:5 minValue:2 maxValue:20
                                              target:self action:@selector(onDensityChanged:)];
    densSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:densSlider];
    self.densitySlider = densSlider;
    y -= (kSliderH + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [container addSubview:sep2];
    [sep2 release];
    y -= (1 + kPadding);

    // --- Clear Grid button ---
    NSButton *clearBtn = MakeButton(@"Clear Grid", self, @selector(onClearGrid:));
    clearBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:clearBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Mirror tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildMirrorTab:(NSRect)frame
{
    NSView *container = [[NSView alloc] initWithFrame:frame];
    CGFloat y = frame.size.height - kPadding;

    // --- Axis selector ---
    NSTextField *axisLbl = MakeLabel(@"Axis:", ITLabelFont(), ITTextColor());
    axisLbl.frame = NSMakeRect(kPadding, y - 14, 40, 14);
    [container addSubview:axisLbl];
    y -= (14 + 4);

    NSArray *axisLabels = @[@"Vertical", @"Horizontal", @"Custom"];
    NSSegmentedControl *axisSeg = [NSSegmentedControl segmentedControlWithLabels:axisLabels
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onMirrorAxisChanged:)];
    axisSeg.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    axisSeg.font = [NSFont systemFontOfSize:10];
    axisSeg.selectedSegment = 0;
    [container addSubview:axisSeg];
    self.mirrorAxisSegment = axisSeg;
    y -= (kRowHeight + kPadding);

    // --- Options ---
    NSButton *replaceChk = MakeCheckbox(@"Replace original (copy by default)", self, @selector(onMirrorOptionChanged:));
    replaceChk.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:replaceChk];
    self.mirrorReplaceCheck = replaceChk;
    y -= (kRowHeight + 2);

    NSButton *previewChk = MakeCheckbox(@"Preview", self, @selector(onMirrorOptionChanged:));
    previewChk.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:previewChk];
    self.mirrorPreviewCheck = previewChk;
    y -= (kRowHeight + kPadding);

    // --- Mirror button ---
    NSButton *mirrorBtn = MakeButton(@"Mirror", self, @selector(onMirrorExecute:));
    mirrorBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:mirrorBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Duplicate tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildDuplicateTab:(NSRect)frame
{
    NSView *container = [[NSView alloc] initWithFrame:frame];
    CGFloat y = frame.size.height - kPadding;

    // --- Count slider ---
    NSTextField *countLbl = MakeLabel(@"Count:", ITLabelFont(), ITTextColor());
    countLbl.frame = NSMakeRect(kPadding, y - 14, 50, 14);
    [container addSubview:countLbl];

    NSTextField *countVal = MakeLabel(@"3", ITMonoFont(), ITAccentColor());
    countVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    countVal.alignment = NSTextAlignmentRight;
    [container addSubview:countVal];
    self.dupCountLabel = countVal;
    y -= (14 + 2);

    NSSlider *countSlider = [NSSlider sliderWithValue:3 minValue:1 maxValue:20
                                               target:self action:@selector(onDupCountChanged:)];
    countSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:countSlider];
    self.dupCountSlider = countSlider;
    y -= (kSliderH + kPadding);

    // --- Spacing popup ---
    NSTextField *spaceLbl = MakeLabel(@"Spacing:", ITLabelFont(), ITTextColor());
    spaceLbl.frame = NSMakeRect(kPadding, y - 14, 60, 14);
    [container addSubview:spaceLbl];
    y -= (14 + 4);

    NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight) pullsDown:NO];
    [popup addItemsWithTitles:@[@"Equal in Perspective", @"Equal in Screen", @"Custom"]];
    popup.font = ITLabelFont();
    popup.target = self;
    popup.action = @selector(onDupSpacingChanged:);
    [container addSubview:popup];
    self.dupSpacingPopup = popup;
    [popup release];  // strong property retains
    y -= (kRowHeight + kPadding);

    // --- Options ---
    NSButton *previewChk = MakeCheckbox(@"Preview", self, @selector(onDupOptionChanged:));
    previewChk.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:previewChk];
    self.dupPreviewCheck = previewChk;
    y -= (kRowHeight + kPadding);

    // --- Duplicate button ---
    NSButton *dupBtn = MakeButton(@"Duplicate", self, @selector(onDuplicateExecute:));
    dupBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:dupBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Paste tab content
//----------------------------------------------------------------------------------------

- (NSView *)buildPasteTab:(NSRect)frame
{
    NSView *container = [[NSView alloc] initWithFrame:frame];
    CGFloat y = frame.size.height - kPadding;

    // --- Plane selector ---
    NSTextField *planeLbl = MakeLabel(@"Plane:", ITLabelFont(), ITTextColor());
    planeLbl.frame = NSMakeRect(kPadding, y - 14, 50, 14);
    [container addSubview:planeLbl];
    y -= (14 + 4);

    NSArray *planeLabels = @[@"Floor", @"Left Wall", @"Right Wall", @"Custom"];
    NSSegmentedControl *planeSeg = [NSSegmentedControl segmentedControlWithLabels:planeLabels
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onPastePlaneChanged:)];
    planeSeg.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    planeSeg.font = [NSFont systemFontOfSize:9];
    planeSeg.selectedSegment = 0;
    [container addSubview:planeSeg];
    self.pastePlaneSegment = planeSeg;
    y -= (kRowHeight + kPadding);

    // --- Scale slider ---
    NSTextField *scaleLbl = MakeLabel(@"Scale:", ITLabelFont(), ITTextColor());
    scaleLbl.frame = NSMakeRect(kPadding, y - 14, 50, 14);
    [container addSubview:scaleLbl];

    NSTextField *scaleVal = MakeLabel(@"100%", ITMonoFont(), ITAccentColor());
    scaleVal.frame = NSMakeRect(kPanelWidth - kPadding - 45, y - 14, 45, 14);
    scaleVal.alignment = NSTextAlignmentRight;
    [container addSubview:scaleVal];
    self.pasteScaleLabel = scaleVal;
    y -= (14 + 2);

    NSSlider *scaleSlider = [NSSlider sliderWithValue:100 minValue:10 maxValue:200
                                               target:self action:@selector(onPasteScaleChanged:)];
    scaleSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:scaleSlider];
    self.pasteScaleSlider = scaleSlider;
    y -= (kSliderH + kPadding * 2);

    // --- Paste in Perspective button ---
    NSButton *pasteBtn = MakeButton(@"Paste in Perspective", self, @selector(onPasteExecute:));
    pasteBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
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
//  Set Perspective — places all 3 VP lines at once
//----------------------------------------------------------------------------------------

- (void)onSetPerspective:(id)sender
{
    double horizon = BridgeGetHorizonY();

    // Place all 3 lines in one action — user drags them into position
    // Left VP line: angled upper-left to lower-right
    BridgeSetPerspectiveLine(0, 200, horizon + 100, 400, horizon + 200);
    // Right VP line: angled upper-right to lower-left
    BridgeSetPerspectiveLine(1, 600, horizon + 200, 400, horizon + 100);
    // Vertical VP line: tilted slightly from vertical
    BridgeSetPerspectiveLine(2, 400, horizon + 50, 410, horizon + 250);

    // Ensure visibility
    BridgeSetPerspectiveVisible(true);

    fprintf(stderr, "[IllTool Panel] Set Perspective — all 3 lines placed\n");
}

//----------------------------------------------------------------------------------------
//  Lock / Show toggles
//----------------------------------------------------------------------------------------

- (void)onLockToggle:(NSButton *)sender
{
    bool newLocked = (sender.state == NSControlStateValueOn);
    PluginOp op;
    op.type = OpType::LockPerspective;
    op.boolParam1 = newLocked;
    BridgeEnqueueOp(op);
    BridgeSetPerspectiveLocked(newLocked);
    fprintf(stderr, "[IllTool Panel] %s grid\n", newLocked ? "Lock" : "Unlock");
}

- (void)onShowToggle:(NSButton *)sender
{
    bool newVisible = (sender.state == NSControlStateValueOn);
    BridgeSetPerspectiveVisible(newVisible);
    fprintf(stderr, "[IllTool Panel] %s grid\n", newVisible ? "Show" : "Hide");
}

//----------------------------------------------------------------------------------------
//  Slider actions
//----------------------------------------------------------------------------------------

- (void)onHorizonChanged:(NSSlider *)sender
{
    double value = sender.doubleValue;
    self.horizonValueLabel.stringValue = [NSString stringWithFormat:@"%.0f", value];
    BridgeSetHorizonY(value);
    fprintf(stderr, "[IllTool Panel] Horizon Y: %.0f\n", value);
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
        self.statusLabel.textColor = ITDimColor();
    } else if (count >= 3) {
        self.statusLabel.stringValue = @"3-point perspective";
        self.statusLabel.textColor = ITAccentColor();
    } else {
        self.statusLabel.stringValue = @"2-point perspective";
        self.statusLabel.textColor = ITAccentColor();
    }
    self.densitySlider.integerValue = density;
    self.densityValueLabel.stringValue = [NSString stringWithFormat:@"%d", density];
}

@end
