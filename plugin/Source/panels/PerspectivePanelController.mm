//========================================================================================
//
//  IllTool — Perspective Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for perspective grid controls.
//  Users place two-handle lines on the canvas; VPs are computed from extensions.
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

// Grid tab controls
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTextField *leftVPLabel;
@property (nonatomic, strong) NSTextField *rightVPLabel;
@property (nonatomic, strong) NSTextField *vertVPLabel;
@property (nonatomic, strong) NSButton *lockButton;
@property (nonatomic, strong) NSSlider *densitySlider;
@property (nonatomic, strong) NSTextField *densityValueLabel;
@property (nonatomic, strong) NSSlider *horizonSlider;
@property (nonatomic, strong) NSTextField *horizonValueLabel;

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
    bool locked = BridgeGetPerspectiveLocked();

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

    // Update per-line status
    self.leftVPLabel.textColor  = left.active ? ITAccentColor() : ITDimColor();
    self.leftVPLabel.stringValue = left.active ? @"Left VP \u2713" : @"Left VP";
    self.rightVPLabel.textColor = right.active ? ITAccentColor() : ITDimColor();
    self.rightVPLabel.stringValue = right.active ? @"Right VP \u2713" : @"Right VP";
    self.vertVPLabel.textColor  = vert.active ? ITAccentColor() : ITDimColor();
    self.vertVPLabel.stringValue = vert.active ? @"Vertical VP \u2713" : @"Vertical VP";

    // Lock button title
    self.lockButton.title = locked ? @"Unlock Grid" : @"Lock Grid";
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 380.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];  // P2: balance alloc — strong property retains

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Perspective", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

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
    [self.gridTabView release];  // P2: balance alloc in buildGridTab — strong property retains

    // --- Placeholder tabs ---
    self.mirrorTabView = [self buildPlaceholderTab:contentFrame label:@"Mirror in Perspective\n\nRequires locked perspective grid.\nComing in Stage 10b."];
    self.mirrorTabView.hidden = YES;
    [root addSubview:self.mirrorTabView];
    [self.mirrorTabView release];

    self.duplicateTabView = [self buildPlaceholderTab:contentFrame label:@"Duplicate in Perspective\n\nRequires locked perspective grid.\nComing in Stage 10c."];
    self.duplicateTabView.hidden = YES;
    [root addSubview:self.duplicateTabView];
    [self.duplicateTabView release];

    self.pasteTabView = [self buildPlaceholderTab:contentFrame label:@"Paste in Perspective\n\nRequires locked perspective grid.\nComing in Stage 10d."];
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

    // --- Left VP button + status ---
    NSButton *leftBtn = MakeButton(@"Left VP", self, @selector(onPlaceLeftVP:));
    leftBtn.frame = NSMakeRect(kPadding, y - kRowHeight, 100, kRowHeight);
    [container addSubview:leftBtn];

    NSTextField *leftLbl = MakeLabel(@"Left VP", ITMonoFont(), ITDimColor());
    leftLbl.frame = NSMakeRect(110, y - kRowHeight + 3, kPanelWidth - 118, 14);
    [container addSubview:leftLbl];
    self.leftVPLabel = leftLbl;
    y -= (kRowHeight + 4);

    // --- Right VP button + status ---
    NSButton *rightBtn = MakeButton(@"Right VP", self, @selector(onPlaceRightVP:));
    rightBtn.frame = NSMakeRect(kPadding, y - kRowHeight, 100, kRowHeight);
    [container addSubview:rightBtn];

    NSTextField *rightLbl = MakeLabel(@"Right VP", ITMonoFont(), ITDimColor());
    rightLbl.frame = NSMakeRect(110, y - kRowHeight + 3, kPanelWidth - 118, 14);
    [container addSubview:rightLbl];
    self.rightVPLabel = rightLbl;
    y -= (kRowHeight + 4);

    // --- Vertical VP button + status ---
    NSButton *vertBtn = MakeButton(@"Vertical VP", self, @selector(onPlaceVerticalVP:));
    vertBtn.frame = NSMakeRect(kPadding, y - kRowHeight, 100, kRowHeight);
    [container addSubview:vertBtn];

    NSTextField *vertLbl = MakeLabel(@"Vertical VP", ITMonoFont(), ITDimColor());
    vertLbl.frame = NSMakeRect(110, y - kRowHeight + 3, kPanelWidth - 118, 14);
    [container addSubview:vertLbl];
    self.vertVPLabel = vertLbl;
    y -= (kRowHeight + kPadding);

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

    // --- Lock / Clear row ---
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;
    NSButton *lockBtn = MakeButton(@"Lock Grid", self, @selector(onLockGrid:));
    lockBtn.frame = NSMakeRect(kPadding, y - kRowHeight, halfW, kRowHeight);
    [container addSubview:lockBtn];
    self.lockButton = lockBtn;

    NSButton *clearBtn = MakeButton(@"Clear Grid", self, @selector(onClearGrid:));
    clearBtn.frame = NSMakeRect(kPadding + halfW + 4, y - kRowHeight, halfW, kRowHeight);
    [container addSubview:clearBtn];

    return container;
}

//----------------------------------------------------------------------------------------
//  Placeholder tab for future features
//----------------------------------------------------------------------------------------

- (NSView *)buildPlaceholderTab:(NSRect)frame label:(NSString *)text
{
    NSView *container = [[NSView alloc] initWithFrame:frame];
    CGFloat y = frame.size.height - kPadding * 3;

    NSTextField *lbl = MakeLabel(text, ITLabelFont(), ITDimColor());
    lbl.frame = NSMakeRect(kPadding, y - 80, kPanelWidth - 2*kPadding, 80);
    lbl.maximumNumberOfLines = 0;
    lbl.lineBreakMode = NSLineBreakByWordWrapping;
    [container addSubview:lbl];

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
//  VP line placement buttons
//  Each places a default two-handle line that the user can then adjust.
//  Default positions: centered around a typical artboard, angled for perspective.
//----------------------------------------------------------------------------------------

- (void)onPlaceLeftVP:(id)sender
{
    // Default left perspective line: angled upper-left to lower-right
    double horizon = BridgeGetHorizonY();
    BridgeSetPerspectiveLine(0, 200, horizon + 100, 400, horizon + 200);
    fprintf(stderr, "[IllTool Panel] Place Left VP line\n");
}

- (void)onPlaceRightVP:(id)sender
{
    // Default right perspective line: angled upper-right to lower-left
    double horizon = BridgeGetHorizonY();
    BridgeSetPerspectiveLine(1, 600, horizon + 200, 400, horizon + 100);
    fprintf(stderr, "[IllTool Panel] Place Right VP line\n");
}

- (void)onPlaceVerticalVP:(id)sender
{
    // Default vertical perspective line: tilted slightly from vertical
    double horizon = BridgeGetHorizonY();
    BridgeSetPerspectiveLine(2, 400, horizon + 50, 410, horizon + 250);
    fprintf(stderr, "[IllTool Panel] Place Vertical VP line\n");
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
//  Lock / Clear
//----------------------------------------------------------------------------------------

- (void)onLockGrid:(id)sender
{
    bool currentlyLocked = BridgeGetPerspectiveLocked();
    PluginOp op;
    op.type = OpType::LockPerspective;
    op.boolParam1 = !currentlyLocked;
    BridgeEnqueueOp(op);
    BridgeSetPerspectiveLocked(!currentlyLocked);
    fprintf(stderr, "[IllTool Panel] %s grid\n", currentlyLocked ? "Unlock" : "Lock");
}

- (void)onClearGrid:(id)sender
{
    PluginOp op;
    op.type = OpType::ClearPerspective;
    BridgeEnqueueOp(op);
    // Also clear bridge state directly for immediate feedback
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    fprintf(stderr, "[IllTool Panel] Clear Grid\n");
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
