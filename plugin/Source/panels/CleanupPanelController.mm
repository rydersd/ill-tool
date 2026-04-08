//========================================================================================
//
//  IllTool — Cleanup Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for shape classification and cleanup.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "CleanupPanelController.h"
#include "IllToolPlugin.h"
#include "modules/CleanupModule.h"
#include "HttpBridge.h"
#import <cstdio>

// Access the global plugin instance for reading detected shape, etc.
extern IllToolPlugin *gPlugin;

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

static NSButton* MakeShapeButton(NSString *title, NSInteger tag, id target, SEL action)
{
    NSButton *btn = [NSButton buttonWithTitle:title target:target action:action];
    btn.font = [NSFont systemFontOfSize:9];
    btn.bezelStyle = NSBezelStyleSmallSquare;
    btn.tag = tag;
    return btn;
}

//========================================================================================
//  FlippedView — NSView subclass with y=0 at top (like UIKit)
//  Prevents top-of-panel clipping when panel window is shorter than content.
//========================================================================================

@interface FlippedView : NSView
@end

@implementation FlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  CleanupPanelController
//========================================================================================

@interface CleanupPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Tab control
@property (nonatomic, strong) NSSegmentedControl *tabControl;
@property (nonatomic, strong) NSView *shapeTabView;
@property (nonatomic, strong) NSView *decomposeTabView;

// Shape tab controls
@property (nonatomic, strong) NSMutableArray<NSButton *> *shapeButtons;
@property (nonatomic, assign) NSInteger activeShapeIndex;
@property (nonatomic, strong) NSTextField *detectedLabel;
@property (nonatomic, strong) NSSlider *tensionSlider;
@property (nonatomic, strong) NSTextField *tensionValueLabel;
@property (nonatomic, strong) NSSlider *simplificationSlider;
@property (nonatomic, strong) NSTextField *simplificationValueLabel;
@property (nonatomic, strong) NSTextField *pointsCountLabel;
@property (nonatomic, strong) NSTextField *layerNameField;
@property (nonatomic, strong) NSTextField *selectSmallField;

// Decompose tab controls
@property (nonatomic, strong) NSSlider *sensitivitySlider;
@property (nonatomic, strong) NSTextField *sensitivityValueLabel;
@property (nonatomic, strong) NSTextField *decomposeReadoutLabel;

// Selection polling timer
@property (nonatomic, strong) NSTimer *pollTimer;

// Last polled value — avoids redundant label updates
@property (nonatomic, assign) int lastPolledCount;

@end

@implementation CleanupPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        _lastPolledCount = -1;  // force first update
        [self buildUI];
        [self startPolling];
    }
    return self;
}

- (void)dealloc
{
    [self.pollTimer invalidate];
    self.pollTimer = nil;
    [super dealloc];
}

- (NSView *)rootView
{
    return self.rootViewInternal;
}

//----------------------------------------------------------------------------------------
//  Selection polling — updates "Points: N" every 500ms
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
    int count = PluginGetSelectedAnchorCount();

    // Log every change AND periodically even when unchanged
    static int pollCycle = 0;
    pollCycle++;
    bool changed = (count != self.lastPolledCount);

    if (changed || (pollCycle % 20 == 1)) {
        fprintf(stderr, "[IllTool DEBUG] pollSelection: count=%d, lastPolledCount=%d, changed=%s, pollCycle=%d\n",
                count, (int)self.lastPolledCount, changed ? "YES" : "no", pollCycle);
    }

    // Poll decompose readout (every 5th cycle to avoid churn)
    if (pollCycle % 5 == 0) {
        std::string decompReadout = BridgeGetDecomposeReadout();
        NSString *decompStr = [NSString stringWithUTF8String:decompReadout.c_str()];
        dispatch_async(dispatch_get_main_queue(), ^{
            self.decomposeReadoutLabel.stringValue = decompStr;
        });
    }

    // Only update the shape tab labels when the count actually changes
    if (!changed) return;

    fprintf(stderr, "[IllTool DEBUG] pollSelection: UPDATING label from %d -> %d\n",
            (int)self.lastPolledCount, count);
    self.lastPolledCount = count;

    // Also read the detected shape from the plugin
    const char* detectedShape = "---";
    if (gPlugin) {
        auto* cleanup = gPlugin->GetModule<CleanupModule>();
        if (cleanup) detectedShape = cleanup->GetLastDetectedShape();
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        self.pointsCountLabel.stringValue = [NSString stringWithFormat:@"Points: %d", count];
        if (count > 0) {
            self.pointsCountLabel.textColor = ITAccentColor();
        } else {
            self.pointsCountLabel.textColor = ITDimColor();
        }
        // Update detected shape label
        self.detectedLabel.stringValue = [NSString stringWithUTF8String:detectedShape];
        fprintf(stderr, "[IllTool DEBUG] pollSelection: label updated to 'Points: %d', detected='%s'\n",
                count, detectedShape);
    });
}

//----------------------------------------------------------------------------------------
//  Build the programmatic UI
//----------------------------------------------------------------------------------------

- (void)buildUI
{
    CGFloat totalHeight = 480.0;
    FlippedView *root = [[FlippedView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];

    CGFloat y = kPadding;

    // --- Tab segmented control ---
    NSSegmentedControl *tabs = [NSSegmentedControl segmentedControlWithLabels:@[@"Shape", @"Decompose"]
                                                                 trackingMode:NSSegmentSwitchTrackingSelectOne
                                                                       target:self
                                                                       action:@selector(onTabChanged:)];
    tabs.selectedSegment = 0;
    tabs.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 22);
    [root addSubview:tabs];
    self.tabControl = tabs;
    y += 30;

    CGFloat tabTop = y;
    CGFloat tabContentHeight = totalHeight - tabTop;

    // --- Shape tab container ---
    FlippedView *shapeTab = [[FlippedView alloc] initWithFrame:NSMakeRect(0, tabTop, kPanelWidth, tabContentHeight)];
    [root addSubview:shapeTab];
    self.shapeTabView = shapeTab;
    [shapeTab release];

    // --- Decompose tab container (hidden initially) ---
    FlippedView *decompTab = [[FlippedView alloc] initWithFrame:NSMakeRect(0, tabTop, kPanelWidth, tabContentHeight)];
    decompTab.hidden = YES;
    [root addSubview:decompTab];
    self.decomposeTabView = decompTab;
    [decompTab release];

    // Build shape tab content
    [self buildShapeTab:shapeTab height:tabContentHeight];

    // Build decompose tab content
    [self buildDecomposeTab:decompTab height:tabContentHeight];
}

- (void)onTabChanged:(NSSegmentedControl *)sender
{
    NSInteger selectedTab = sender.selectedSegment;
    self.shapeTabView.hidden = (selectedTab != 0);
    self.decomposeTabView.hidden = (selectedTab != 1);
    fprintf(stderr, "[IllTool Panel] Tab changed to %s\n",
            selectedTab == 0 ? "Shape" : "Decompose");
}

- (void)buildShapeTab:(NSView *)container height:(CGFloat)totalHeight
{
    // Flipped container: y=0 is top, increments downward
    CGFloat y = kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Shape Cleanup", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 16);
    [container addSubview:title];
    y += 24;

    // --- Shape type buttons row (7 buttons with Unicode icons) ---
    NSArray *icons  = @[@"\u2014", @"\u2312", @"\u221F", @"\u25AD", @"\u223F", @"\u25CB", @"\u224B"];
    NSArray *labels = @[@"LINE",   @"ARC",    @"L",      @"RECT",   @"S",      @"ELLIPSE",@"FREE"];
    CGFloat btnW = (kPanelWidth - 2*kPadding - 6*2) / 7.0;
    CGFloat btnH = 36.0;
    CGFloat btnX = kPadding;
    self.shapeButtons = [NSMutableArray arrayWithCapacity:7];
    self.activeShapeIndex = -1;
    for (NSInteger i = 0; i < (NSInteger)icons.count; i++) {
        NSString *btnTitle = [NSString stringWithFormat:@"%@\n%@", icons[i], labels[i]];
        NSButton *btn = MakeShapeButton(btnTitle, i, self, @selector(onShapeType:));
        btn.frame = NSMakeRect(btnX, y, btnW, btnH);
        btn.wantsLayer = YES;

        NSMutableParagraphStyle *para = [[NSMutableParagraphStyle alloc] init];
        para.alignment = NSTextAlignmentCenter;
        para.lineSpacing = 0;
        NSMutableAttributedString *attrStr = [[NSMutableAttributedString alloc] init];
        NSDictionary *iconAttrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:14],
            NSForegroundColorAttributeName: ITTextColor(),
            NSParagraphStyleAttributeName: para
        };
        NSDictionary *labelAttrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:7 weight:NSFontWeightMedium],
            NSForegroundColorAttributeName: ITDimColor(),
            NSParagraphStyleAttributeName: para
        };
        NSAttributedString *iconPart = [[NSAttributedString alloc] initWithString:icons[i] attributes:iconAttrs];
        [attrStr appendAttributedString:iconPart];
        [iconPart release];
        NSAttributedString *nlPart = [[NSAttributedString alloc] initWithString:@"\n" attributes:iconAttrs];
        [attrStr appendAttributedString:nlPart];
        [nlPart release];
        NSAttributedString *labelPart = [[NSAttributedString alloc] initWithString:labels[i] attributes:labelAttrs];
        [attrStr appendAttributedString:labelPart];
        [labelPart release];
        btn.attributedTitle = attrStr;
        [attrStr release];
        [para release];

        [container addSubview:btn];
        [self.shapeButtons addObject:btn];
        btnX += btnW + 2;
    }
    y += (btnH + kPadding);

    // --- Detected shape label ---
    NSTextField *detLbl = MakeLabel(@"Detected:", ITLabelFont(), ITDimColor());
    detLbl.frame = NSMakeRect(kPadding, y, 60, 14);
    [container addSubview:detLbl];

    NSTextField *detVal = MakeLabel(@"---", ITMonoFont(), ITAccentColor());
    detVal.frame = NSMakeRect(70, y, kPanelWidth - 70 - kPadding, 14);
    [container addSubview:detVal];
    self.detectedLabel = detVal;
    y += (14 + kPadding + 2);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [container addSubview:sep1];
    [sep1 release];
    y += (1 + kPadding);

    // --- Curve Tension slider ---
    NSTextField *tensLbl = MakeLabel(@"Curve Tension", ITLabelFont(), ITTextColor());
    tensLbl.frame = NSMakeRect(kPadding, y, 110, 14);
    [container addSubview:tensLbl];

    NSTextField *tensVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    tensVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, 14);
    tensVal.alignment = NSTextAlignmentRight;
    [container addSubview:tensVal];
    self.tensionValueLabel = tensVal;
    y += (14 + 2);

    NSSlider *tensSlider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                              target:self action:@selector(onTensionChanged:)];
    tensSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:tensSlider];
    self.tensionSlider = tensSlider;
    y += (kSliderH + kPadding);

    // --- Simplification slider ---
    NSTextField *simpLbl = MakeLabel(@"Simplification", ITLabelFont(), ITTextColor());
    simpLbl.frame = NSMakeRect(kPadding, y, 110, 14);
    [container addSubview:simpLbl];

    NSTextField *simpVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    simpVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, 14);
    simpVal.alignment = NSTextAlignmentRight;
    [container addSubview:simpVal];
    self.simplificationValueLabel = simpVal;
    y += (14 + 2);

    NSSlider *simpSlider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                              target:self action:@selector(onSimplificationChanged:)];
    simpSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:simpSlider];
    self.simplificationSlider = simpSlider;
    y += (kSliderH + kPadding);

    // --- Points count ---
    NSTextField *ptsLbl = MakeLabel(@"Points: 0", ITMonoFont(), ITAccentColor());
    ptsLbl.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 14);
    [container addSubview:ptsLbl];
    self.pointsCountLabel = ptsLbl;
    y += (14 + kPadding);

    // --- Layer name field ---
    NSTextField *layerLbl = MakeLabel(@"Layer Name", ITLabelFont(), ITTextColor());
    layerLbl.frame = NSMakeRect(kPadding, y, 80, 14);
    [container addSubview:layerLbl];
    y += (14 + 2);

    NSTextField *layerField = [[NSTextField alloc] initWithFrame:
        NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight)];
    layerField.font = ITLabelFont();
    layerField.placeholderString = @"Layer name...";
    layerField.bezelStyle = NSTextFieldSquareBezel;
    layerField.bordered = YES;
    layerField.editable = YES;
    [container addSubview:layerField];
    self.layerNameField = layerField;
    [layerField release];
    y += (kRowHeight + kPadding);

    // --- Average Selection button ---
    NSButton *avgBtn = MakeButton(@"Average Selection", self, @selector(onAverageSelection:));
    avgBtn.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:avgBtn];
    y += (kRowHeight + kPadding/2);

    // --- Delete Originals checkbox ---
    NSButton *delOrigCB = [NSButton checkboxWithTitle:@"Delete Originals"
                                               target:self
                                               action:@selector(onDeleteOriginalsChanged:)];
    delOrigCB.font = ITLabelFont();
    delOrigCB.state = NSControlStateValueOn;
    NSMutableAttributedString *cbTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Delete Originals"
        attributes:@{
            NSForegroundColorAttributeName: ITTextColor(),
            NSFontAttributeName: ITLabelFont()
        }];
    delOrigCB.attributedTitle = cbTitle;
    [cbTitle release];
    delOrigCB.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [container addSubview:delOrigCB];
    self.deleteOriginalsCheckbox = delOrigCB;
    y += (kRowHeight + kPadding/2);

    // --- Apply / Cancel row ---
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;
    NSButton *applyBtn = MakeButton(@"Apply", self, @selector(onApply:));
    applyBtn.frame = NSMakeRect(kPadding, y, halfW, kRowHeight);
    [container addSubview:applyBtn];

    NSButton *cancelBtn = MakeButton(@"Cancel", self, @selector(onCancel:));
    cancelBtn.frame = NSMakeRect(kPadding + halfW + 4, y, halfW, kRowHeight);
    [container addSubview:cancelBtn];
    y += (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [container addSubview:sep2];
    [sep2 release];
    y += (1 + kPadding);

    // --- Select Small row ---
    NSButton *selSmallBtn = MakeButton(@"Select Small", self, @selector(onSelectSmall:));
    selSmallBtn.frame = NSMakeRect(kPadding, y, 100, kRowHeight);
    [container addSubview:selSmallBtn];

    NSTextField *threshField = [[NSTextField alloc] initWithFrame:
        NSMakeRect(kPadding + 104, y, 50, kRowHeight)];
    threshField.font = ITMonoFont();
    threshField.placeholderString = @"pt";
    threshField.bezelStyle = NSTextFieldSquareBezel;
    threshField.bordered = YES;
    threshField.editable = YES;
    threshField.stringValue = @"2";
    [container addSubview:threshField];
    self.selectSmallField = threshField;
    [threshField release];

    NSTextField *ptLabel = MakeLabel(@"pt", ITLabelFont(), ITDimColor());
    ptLabel.frame = NSMakeRect(kPadding + 158, y + 3, 20, 14);
    [container addSubview:ptLabel];
}

//----------------------------------------------------------------------------------------
//  Decompose tab layout
//----------------------------------------------------------------------------------------

- (void)buildDecomposeTab:(NSView *)container height:(CGFloat)totalHeight
{
    // Flipped container: y=0 is top, increments downward
    CGFloat y = kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Auto-Decompose", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 16);
    [container addSubview:title];
    y += 24;

    // --- Analyze button ---
    NSButton *analyzeBtn = MakeButton(@"Analyze", self, @selector(onDecomposeAnalyze:));
    analyzeBtn.frame = NSMakeRect(kPadding, y, 80, kRowHeight);
    [container addSubview:analyzeBtn];

    // --- Sensitivity label + value (same row as Analyze) ---
    NSTextField *sensLbl = MakeLabel(@"Sensitivity:", ITLabelFont(), ITDimColor());
    sensLbl.frame = NSMakeRect(kPadding + 88, y + 3, 70, 14);
    [container addSubview:sensLbl];

    NSTextField *sensVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    sensVal.frame = NSMakeRect(kPanelWidth - kPadding - 25, y + 3, 25, 14);
    sensVal.alignment = NSTextAlignmentRight;
    [container addSubview:sensVal];
    self.sensitivityValueLabel = sensVal;
    y += (kRowHeight + 4);

    // --- Sensitivity slider ---
    NSSlider *sensSlider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                              target:self action:@selector(onSensitivityChanged:)];
    sensSlider.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH);
    [container addSubview:sensSlider];
    self.sensitivitySlider = sensSlider;
    y += (kSliderH + kPadding);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [container addSubview:sep1];
    [sep1 release];
    y += (1 + kPadding);

    // --- Clusters readout ---
    NSTextField *clustersLbl = MakeLabel(@"Clusters:", ITLabelFont(), ITDimColor());
    clustersLbl.frame = NSMakeRect(kPadding, y, 55, 14);
    [container addSubview:clustersLbl];

    NSTextField *readout = MakeLabel(@"---", ITMonoFont(), ITAccentColor());
    readout.frame = NSMakeRect(kPadding + 60, y, kPanelWidth - kPadding - 68, 14);
    [container addSubview:readout];
    self.decomposeReadoutLabel = readout;
    y += (14 + kPadding);

    // --- Accept All / Cancel row ---
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;
    NSButton *acceptBtn = MakeButton(@"Accept All", self, @selector(onDecomposeAcceptAll:));
    acceptBtn.frame = NSMakeRect(kPadding, y, halfW, kRowHeight);
    [container addSubview:acceptBtn];

    NSButton *cancelBtn = MakeButton(@"Cancel", self, @selector(onDecomposeCancel:));
    cancelBtn.frame = NSMakeRect(kPadding + halfW + 4, y, halfW, kRowHeight);
    [container addSubview:cancelBtn];
    y += (kRowHeight + kPadding / 2);

    // --- Split / Merge row ---
    NSButton *splitBtn = MakeButton(@"Split", self, @selector(onDecomposeSplit:));
    splitBtn.frame = NSMakeRect(kPadding, y, halfW, kRowHeight);
    [container addSubview:splitBtn];

    NSButton *mergeBtn = MakeButton(@"Merge Groups", self, @selector(onDecomposeMerge:));
    mergeBtn.frame = NSMakeRect(kPadding + halfW + 4, y, halfW, kRowHeight);
    [container addSubview:mergeBtn];
}

//----------------------------------------------------------------------------------------
//  Decompose actions
//----------------------------------------------------------------------------------------

- (void)onDecomposeAnalyze:(id)sender
{
    float sensitivity = (float)(self.sensitivitySlider.doubleValue / 100.0);
    fprintf(stderr, "[IllTool Panel] Decompose Analyze (sensitivity=%.2f)\n", sensitivity);
    BridgeRequestDecompose(sensitivity);
}

- (void)onSensitivityChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.sensitivityValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Decompose Sensitivity: %d\n", value);
    BridgeSetDecomposeSensitivity((float)value / 100.0f);
}

- (void)onDecomposeAcceptAll:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Decompose Accept All\n");
    BridgeRequestDecomposeAccept();
}

- (void)onDecomposeCancel:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Decompose Cancel\n");
    BridgeRequestDecomposeCancel();
}

- (void)onDecomposeSplit:(id)sender
{
    // Split cluster 0 (first cluster) — a future UI could allow picking
    fprintf(stderr, "[IllTool Panel] Decompose Split (cluster 0)\n");
    BridgeRequestDecomposeSplit(0);
}

- (void)onDecomposeMerge:(id)sender
{
    // Merge clusters 0 and 1 — a future UI could allow picking
    fprintf(stderr, "[IllTool Panel] Decompose Merge (clusters 0+1)\n");
    BridgeRequestDecomposeMergeGroups(0, 1);
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onShapeType:(NSButton *)sender
{
    NSArray *names = @[@"Line", @"Arc", @"L", @"Rect", @"S", @"Ellipse", @"Free"];
    NSString *name = (sender.tag < (NSInteger)names.count) ? names[sender.tag] : @"?";
    fprintf(stderr, "[IllTool Panel] Shape type selected: %s (tag=%ld) — queuing reclassify\n",
            name.UTF8String, (long)sender.tag);
    [self setActiveShapeButton:sender.tag];
    BridgeRequestReclassify(static_cast<BridgeShapeType>((int)sender.tag));
}

- (void)setActiveShapeButton:(NSInteger)index
{
    // Clear previous active state
    for (NSInteger i = 0; i < (NSInteger)self.shapeButtons.count; i++) {
        NSButton *btn = self.shapeButtons[i];
        if (i == index) {
            btn.layer.backgroundColor = ITAccentColor().CGColor;
            btn.layer.cornerRadius = 3.0;
        } else {
            btn.layer.backgroundColor = [NSColor clearColor].CGColor;
        }
    }
    self.activeShapeIndex = index;
}

- (void)onTensionChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.tensionValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Tension: %d\n", value);
    BridgeSetTension((double)value);
}

- (void)onSimplificationChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.simplificationValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Simplification: %d — queuing simplify\n", value);
    BridgeRequestSimplify((double)value);
}

- (void)onAverageSelection:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Average Selection — queuing request\n");
    BridgeRequestAverageSelection();
}

- (void)onDeleteOriginalsChanged:(NSButton *)sender
{
    bool checked = (sender.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Delete Originals: %s\n", checked ? "ON" : "OFF");
}

- (void)onApply:(id)sender
{
    bool deleteOrig = (self.deleteOriginalsCheckbox.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Apply (deleteOriginals=%s) — queuing for SDK context\n",
            deleteOrig ? "true" : "false");
    BridgeRequestWorkingApply(deleteOrig);
}

- (void)onCancel:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Cancel — queuing for SDK context\n");
    BridgeRequestWorkingCancel();
}

- (void)onSelectSmall:(id)sender
{
    double threshold = self.selectSmallField.doubleValue;
    fprintf(stderr, "[IllTool Panel] Select Small (threshold: %.1f pt) — queuing request\n", threshold);
    BridgeRequestSelectSmall(threshold);
}

//----------------------------------------------------------------------------------------
//  Public update methods
//----------------------------------------------------------------------------------------

- (void)updateDetectedShape:(NSString *)shapeName
{
    self.detectedLabel.stringValue = shapeName;
}

- (void)updatePointsCount:(NSInteger)count
{
    self.pointsCountLabel.stringValue = [NSString stringWithFormat:@"Points: %ld", (long)count];
}

- (void)updateDecomposeReadout:(NSString *)text
{
    self.decomposeReadoutLabel.stringValue = text;
}

@end
