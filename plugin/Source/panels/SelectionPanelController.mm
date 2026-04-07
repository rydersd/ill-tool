//========================================================================================
//
//  IllTool — Selection Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for lasso / smart selection panel.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "SelectionPanelController.h"
#include "IllToolPlugin.h"
#include "HttpBridge.h"
#import <cstdio>

//----------------------------------------------------------------------------------------
//  Dark theme constants matching Illustrator
//----------------------------------------------------------------------------------------

static NSColor* ITBGColor()       { return [NSColor colorWithRed:0.20 green:0.20 blue:0.20 alpha:1.0]; }
static NSColor* ITTextColor()     { return [NSColor colorWithRed:0.85 green:0.85 blue:0.85 alpha:1.0]; }
static NSColor* ITAccentColor()   { return [NSColor colorWithRed:0.48 green:0.72 blue:0.94 alpha:1.0]; }
static NSColor* ITDimColor()      { return [NSColor colorWithRed:0.55 green:0.55 blue:0.55 alpha:1.0]; }
static NSFont*  ITLabelFont()     { return [NSFont systemFontOfSize:11]; }
static NSFont*  ITMonoFont()      { return [NSFont monospacedSystemFontOfSize:10 weight:NSFontWeightRegular]; }

static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;
static const CGFloat kSliderH     = 18.0;

//----------------------------------------------------------------------------------------
//  Helper: create a styled label
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
    label.translatesAutoresizingMaskIntoConstraints = NO;
    return label;
}

//----------------------------------------------------------------------------------------
//  Helper: create a styled button
//----------------------------------------------------------------------------------------

static NSButton* MakeButton(NSString *title, id target, SEL action)
{
    NSButton *btn = [NSButton buttonWithTitle:title target:target action:action];
    btn.font = ITLabelFont();
    btn.bezelStyle = NSBezelStyleSmallSquare;
    btn.translatesAutoresizingMaskIntoConstraints = NO;
    return btn;
}

//----------------------------------------------------------------------------------------
//  Helper: create a styled checkbox
//----------------------------------------------------------------------------------------

static NSButton* MakeCheckbox(NSString *title, id target, SEL action)
{
    NSButton *cb = [NSButton checkboxWithTitle:title target:target action:action];
    cb.font = ITLabelFont();
    // Checkboxes inherit the cell's text color
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc] initWithString:title];
    [attrTitle addAttribute:NSForegroundColorAttributeName value:ITTextColor()
                      range:NSMakeRange(0, title.length)];
    [attrTitle addAttribute:NSFontAttributeName value:ITLabelFont()
                      range:NSMakeRange(0, title.length)];
    cb.attributedTitle = attrTitle;
    [attrTitle release];
    cb.translatesAutoresizingMaskIntoConstraints = NO;
    return cb;
}

//========================================================================================
//  SelectionPanelController
//========================================================================================

@interface SelectionPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls we need references to
@property (nonatomic, strong) NSSegmentedControl *modeSegment;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTextField *countLabel;
@property (nonatomic, strong) NSButton *addToSelectionCheckbox;
@property (nonatomic, strong) NSSlider *thresholdSlider;
@property (nonatomic, strong) NSTextField *thresholdLabel;
@property (nonatomic, strong) NSTextField *thresholdValueLabel;

// Key monitor for Enter/Escape
@property (nonatomic, strong) id keyMonitor;

// Selection polling timer
@property (nonatomic, strong) NSTimer *pollTimer;

// Last polled value — avoids redundant label updates
@property (nonatomic, assign) int lastPolledCount;

@end

@implementation SelectionPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        _lastPolledCount = -1;  // force first update
        [self buildUI];
        [self installKeyMonitor];
        [self startPolling];
    }
    return self;
}

- (void)dealloc
{
    [self.pollTimer invalidate];
    self.pollTimer = nil;
    if (self.keyMonitor) {
        [NSEvent removeMonitor:self.keyMonitor];
        self.keyMonitor = nil;
    }
    [super dealloc];
}

- (NSView *)rootView
{
    return self.rootViewInternal;
}

//----------------------------------------------------------------------------------------
//  Key monitor for Enter (close lasso) and Escape (clear lasso)
//----------------------------------------------------------------------------------------

- (void)installKeyMonitor
{
    self.keyMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
                                                           handler:^NSEvent*(NSEvent* event) {
        if (event.keyCode == 36 || event.keyCode == 76) {
            // Return (36) or numpad Enter (76) — close the polygon lasso
            fprintf(stderr, "[IllTool Panel] Enter key — requesting lasso close\n");
            BridgeRequestLassoClose();
            return nil;  // consume the event
        }
        if (event.keyCode == 53) {
            // Escape — clear the polygon lasso
            fprintf(stderr, "[IllTool Panel] Escape key — requesting lasso clear\n");
            BridgeRequestLassoClear();
            return nil;  // consume the event
        }
        return event;
    }];
    fprintf(stderr, "[IllTool Panel] Key monitor installed (Enter=close, Escape=clear)\n");
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 260.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];  // P2: balance alloc — strong property retains

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Selection Tools", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    title.autoresizingMask = NSViewWidthSizable;
    [root addSubview:title];
    y -= 24;

    // --- Segmented control: Lasso | Smart ---
    NSSegmentedControl *seg = [NSSegmentedControl segmentedControlWithLabels:@[@"Lasso", @"Smart"]
                                trackingMode:NSSegmentSwitchTrackingSelectOne
                                      target:self
                                      action:@selector(onModeChanged:)];
    seg.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    seg.selectedSegment = 0;
    seg.autoresizingMask = NSViewWidthSizable;
    seg.font = ITLabelFont();
    [root addSubview:seg];
    self.modeSegment = seg;
    y -= (kRowHeight + kPadding);

    // --- Status label ---
    NSTextField *status = MakeLabel(@"Click to place points, Enter or double-click to select", ITLabelFont(), ITDimColor());
    status.frame = NSMakeRect(kPadding, y - 28, kPanelWidth - 2*kPadding, 28);
    status.maximumNumberOfLines = 2;
    status.lineBreakMode = NSLineBreakByWordWrapping;
    status.autoresizingMask = NSViewWidthSizable;
    [root addSubview:status];
    self.statusLabel = status;
    y -= (28 + kPadding);

    // --- Clear button ---
    NSButton *clearBtn = MakeButton(@"Clear", self, @selector(onClear:));
    clearBtn.frame = NSMakeRect(kPadding, y - kRowHeight, 80, kRowHeight);
    [root addSubview:clearBtn];
    y -= (kRowHeight + kPadding);

    // --- Add to Selection checkbox ---
    NSButton *addCB = MakeCheckbox(@"Add to Selection", self, @selector(onAddToSelection:));
    addCB.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:addCB];
    self.addToSelectionCheckbox = addCB;
    y -= (kRowHeight + kPadding);

    // --- Selection count ---
    NSTextField *countLbl = MakeLabel(@"0 anchors selected", ITMonoFont(), ITAccentColor());
    countLbl.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    countLbl.autoresizingMask = NSViewWidthSizable;
    [root addSubview:countLbl];
    self.countLabel = countLbl;
    y -= (16 + kPadding + 4);

    // --- Separator ---
    NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep.boxType = NSBoxSeparator;
    [root addSubview:sep];
    [sep release];
    y -= (1 + kPadding);

    // --- Threshold slider (Smart mode only) ---
    NSTextField *threshLbl = MakeLabel(@"Similarity Threshold", ITLabelFont(), ITTextColor());
    threshLbl.frame = NSMakeRect(kPadding, y - 14, 140, 14);
    [root addSubview:threshLbl];
    self.thresholdLabel = threshLbl;

    NSTextField *threshVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    threshVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    threshVal.alignment = NSTextAlignmentRight;
    [root addSubview:threshVal];
    self.thresholdValueLabel = threshVal;
    y -= (14 + 4);

    NSSlider *slider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                          target:self action:@selector(onThresholdChanged:)];
    slider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    slider.autoresizingMask = NSViewWidthSizable;
    [root addSubview:slider];
    self.thresholdSlider = slider;

    // Start in Lasso mode: hide threshold controls
    [self updateSmartModeVisible:NO];
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onModeChanged:(NSSegmentedControl *)sender
{
    NSInteger selected = sender.selectedSegment;
    if (selected == 0) {
        // Lasso mode
        fprintf(stderr, "[IllTool Panel] Selection mode -> Lasso\n");
        BridgeSetToolMode((BridgeToolMode)0);  // BridgeToolMode::Lasso == 0
        [self updateStatusText:@"Click to place points, Enter or double-click to select"];
        [self updateSmartModeVisible:NO];
    } else {
        // Smart mode
        fprintf(stderr, "[IllTool Panel] Selection mode -> Smart\n");
        BridgeSetToolMode((BridgeToolMode)1);  // BridgeToolMode::Smart == 1
        [self updateStatusText:@"Click a path to select related"];
        [self updateSmartModeVisible:YES];
    }
}

- (void)onClear:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Clear polygon — queuing for SDK context\n");
    BridgeRequestLassoClear();
}

- (void)onAddToSelection:(NSButton *)sender
{
    BOOL checked = (sender.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Add to Selection: %s\n", checked ? "ON" : "OFF");
    BridgeSetAddToSelection((bool)checked);
}

- (void)onThresholdChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.thresholdValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    // Communicate the threshold to the Smart Select matching logic
    BridgeSetSmartThreshold((double)value);
    fprintf(stderr, "[IllTool Panel] Threshold: %d\n", value);
}

//----------------------------------------------------------------------------------------
//  Selection polling — updates "N anchors selected" every 500ms
//----------------------------------------------------------------------------------------

- (void)startPolling
{
    self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.5
                                                     target:self
                                                   selector:@selector(pollSelection)
                                                   userInfo:nil
                                                    repeats:YES];
    // Ensure timer fires during UI tracking (e.g. slider drag)
    [[NSRunLoop currentRunLoop] addTimer:self.pollTimer forMode:NSRunLoopCommonModes];
}

- (void)pollSelection
{
    // Skip if the panel view is not in a visible window
    if (!self.rootViewInternal.window || !self.rootViewInternal.window.isVisible) return;

    int count = PluginGetSelectedAnchorCount();

    // Only update the label when the count actually changes
    if (count == self.lastPolledCount) return;
    self.lastPolledCount = count;

    self.selectionCount = count;
    self.countLabel.stringValue = [NSString stringWithFormat:@"%d anchors selected", count];
    if (count > 0) {
        self.countLabel.textColor = ITAccentColor();
    } else {
        self.countLabel.textColor = ITDimColor();
    }
}

//----------------------------------------------------------------------------------------
//  Public update methods
//----------------------------------------------------------------------------------------

- (void)updateSelectionCount:(NSInteger)count
{
    self.selectionCount = count;
    self.lastPolledCount = (int)count;  // sync polling cache with manual updates
    self.countLabel.stringValue = [NSString stringWithFormat:@"%ld anchors selected", (long)count];
}

- (void)updateStatusText:(NSString *)text
{
    self.statusLabel.stringValue = text;
}

- (void)updateSmartModeVisible:(BOOL)visible
{
    self.thresholdSlider.hidden = !visible;
    self.thresholdLabel.hidden = !visible;
    self.thresholdValueLabel.hidden = !visible;
}

@end
