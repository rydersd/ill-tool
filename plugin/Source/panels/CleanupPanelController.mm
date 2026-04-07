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
//  CleanupPanelController
//========================================================================================

@interface CleanupPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls we need references to
@property (nonatomic, strong) NSTextField *detectedLabel;
@property (nonatomic, strong) NSSlider *tensionSlider;
@property (nonatomic, strong) NSTextField *tensionValueLabel;
@property (nonatomic, strong) NSSlider *simplificationSlider;
@property (nonatomic, strong) NSTextField *simplificationValueLabel;
@property (nonatomic, strong) NSTextField *pointsCountLabel;
@property (nonatomic, strong) NSTextField *layerNameField;
@property (nonatomic, strong) NSTextField *selectSmallField;

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

    // Only update the label when the count actually changes
    if (!changed) return;

    fprintf(stderr, "[IllTool DEBUG] pollSelection: UPDATING label from %d -> %d\n",
            (int)self.lastPolledCount, count);
    self.lastPolledCount = count;

    // Also read the detected shape from the plugin
    const char* detectedShape = gPlugin ? gPlugin->fLastDetectedShape : "---";

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
    CGFloat totalHeight = 448.0;  // 420 + 28 for Delete Originals checkbox row
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Shape Cleanup", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    // --- Shape type buttons row (7 buttons with Unicode icons) ---
    // Icons match the original CEP panel: —  ⌀  ∟  ▭  ∿  ○  ≋
    NSArray *icons  = @[@"\u2014", @"\u2312", @"\u221F", @"\u25AD", @"\u223F", @"\u25CB", @"\u224B"];
    NSArray *labels = @[@"LINE",   @"ARC",    @"L",      @"RECT",   @"S",      @"ELLIPSE",@"FREE"];
    CGFloat btnW = (kPanelWidth - 2*kPadding - 6*2) / 7.0;
    CGFloat btnH = 36.0;  // taller to fit icon + label
    CGFloat btnX = kPadding;
    for (NSInteger i = 0; i < (NSInteger)icons.count; i++) {
        // Icon + label stacked vertically
        NSString *btnTitle = [NSString stringWithFormat:@"%@\n%@", icons[i], labels[i]];
        NSButton *btn = MakeShapeButton(btnTitle, i, self, @selector(onShapeType:));
        btn.frame = NSMakeRect(btnX, y - btnH, btnW, btnH);

        // Multi-line attributed string: icon large, label small
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
        [attrStr appendAttributedString:[[NSAttributedString alloc] initWithString:icons[i] attributes:iconAttrs]];
        [attrStr appendAttributedString:[[NSAttributedString alloc] initWithString:@"\n" attributes:iconAttrs]];
        [attrStr appendAttributedString:[[NSAttributedString alloc] initWithString:labels[i] attributes:labelAttrs]];
        btn.attributedTitle = attrStr;

        [root addSubview:btn];
        btnX += btnW + 2;
    }
    y -= (btnH + kPadding);

    // --- Detected shape label ---
    NSTextField *detLbl = MakeLabel(@"Detected:", ITLabelFont(), ITDimColor());
    detLbl.frame = NSMakeRect(kPadding, y - 14, 60, 14);
    [root addSubview:detLbl];

    NSTextField *detVal = MakeLabel(@"---", ITMonoFont(), ITAccentColor());
    detVal.frame = NSMakeRect(70, y - 14, kPanelWidth - 70 - kPadding, 14);
    [root addSubview:detVal];
    self.detectedLabel = detVal;
    y -= (14 + kPadding + 2);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [root addSubview:sep1];
    y -= (1 + kPadding);

    // --- Curve Tension slider ---
    NSTextField *tensLbl = MakeLabel(@"Curve Tension", ITLabelFont(), ITTextColor());
    tensLbl.frame = NSMakeRect(kPadding, y - 14, 110, 14);
    [root addSubview:tensLbl];

    NSTextField *tensVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    tensVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    tensVal.alignment = NSTextAlignmentRight;
    [root addSubview:tensVal];
    self.tensionValueLabel = tensVal;
    y -= (14 + 2);

    NSSlider *tensSlider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                              target:self action:@selector(onTensionChanged:)];
    tensSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [root addSubview:tensSlider];
    self.tensionSlider = tensSlider;
    y -= (kSliderH + kPadding);

    // --- Simplification slider ---
    NSTextField *simpLbl = MakeLabel(@"Simplification", ITLabelFont(), ITTextColor());
    simpLbl.frame = NSMakeRect(kPadding, y - 14, 110, 14);
    [root addSubview:simpLbl];

    NSTextField *simpVal = MakeLabel(@"50", ITMonoFont(), ITAccentColor());
    simpVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    simpVal.alignment = NSTextAlignmentRight;
    [root addSubview:simpVal];
    self.simplificationValueLabel = simpVal;
    y -= (14 + 2);

    NSSlider *simpSlider = [NSSlider sliderWithValue:50 minValue:0 maxValue:100
                                              target:self action:@selector(onSimplificationChanged:)];
    simpSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [root addSubview:simpSlider];
    self.simplificationSlider = simpSlider;
    y -= (kSliderH + kPadding);

    // --- Points count ---
    NSTextField *ptsLbl = MakeLabel(@"Points: 0", ITMonoFont(), ITAccentColor());
    ptsLbl.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [root addSubview:ptsLbl];
    self.pointsCountLabel = ptsLbl;
    y -= (14 + kPadding);

    // --- Layer name field ---
    NSTextField *layerLbl = MakeLabel(@"Layer Name", ITLabelFont(), ITTextColor());
    layerLbl.frame = NSMakeRect(kPadding, y - 14, 80, 14);
    [root addSubview:layerLbl];
    y -= (14 + 2);

    NSTextField *layerField = [[NSTextField alloc] initWithFrame:
        NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight)];
    layerField.font = ITLabelFont();
    layerField.placeholderString = @"Layer name...";
    layerField.bezelStyle = NSTextFieldSquareBezel;
    layerField.bordered = YES;
    layerField.editable = YES;
    [root addSubview:layerField];
    self.layerNameField = layerField;
    y -= (kRowHeight + kPadding);

    // --- Average Selection button ---
    NSButton *avgBtn = MakeButton(@"Average Selection", self, @selector(onAverageSelection:));
    avgBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:avgBtn];
    y -= (kRowHeight + kPadding/2);

    // --- Delete Originals checkbox ---
    NSButton *delOrigCB = [NSButton checkboxWithTitle:@"Delete Originals"
                                               target:self
                                               action:@selector(onDeleteOriginalsChanged:)];
    delOrigCB.font = ITLabelFont();
    delOrigCB.state = NSControlStateValueOn;  // checked by default
    // Style the checkbox text for dark theme
    NSMutableAttributedString *cbTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Delete Originals"
        attributes:@{
            NSForegroundColorAttributeName: ITTextColor(),
            NSFontAttributeName: ITLabelFont()
        }];
    delOrigCB.attributedTitle = cbTitle;
    delOrigCB.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:delOrigCB];
    self.deleteOriginalsCheckbox = delOrigCB;
    y -= (kRowHeight + kPadding/2);

    // --- Apply / Cancel row ---
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;
    NSButton *applyBtn = MakeButton(@"Apply", self, @selector(onApply:));
    applyBtn.frame = NSMakeRect(kPadding, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:applyBtn];

    NSButton *cancelBtn = MakeButton(@"Cancel", self, @selector(onCancel:));
    cancelBtn.frame = NSMakeRect(kPadding + halfW + 4, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:cancelBtn];
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [root addSubview:sep2];
    y -= (1 + kPadding);

    // --- Select Small row ---
    NSButton *selSmallBtn = MakeButton(@"Select Small", self, @selector(onSelectSmall:));
    selSmallBtn.frame = NSMakeRect(kPadding, y - kRowHeight, 100, kRowHeight);
    [root addSubview:selSmallBtn];

    NSTextField *threshField = [[NSTextField alloc] initWithFrame:
        NSMakeRect(kPadding + 104, y - kRowHeight, 50, kRowHeight)];
    threshField.font = ITMonoFont();
    threshField.placeholderString = @"pt";
    threshField.bezelStyle = NSTextFieldSquareBezel;
    threshField.bordered = YES;
    threshField.editable = YES;
    threshField.stringValue = @"2";
    [root addSubview:threshField];
    self.selectSmallField = threshField;

    NSTextField *ptLabel = MakeLabel(@"pt", ITLabelFont(), ITDimColor());
    ptLabel.frame = NSMakeRect(kPadding + 158, y - kRowHeight + 3, 20, 14);
    [root addSubview:ptLabel];
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
    BridgeRequestReclassify(static_cast<BridgeShapeType>((int)sender.tag));
}

- (void)onTensionChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.tensionValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Tension: %d\n", value);
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
    fprintf(stderr, "[IllTool Panel] Select Small (threshold: %.1f pt)\n", threshold);
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

@end
