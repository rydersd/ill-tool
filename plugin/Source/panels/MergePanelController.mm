//========================================================================================
//
//  IllTool — Merge Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for endpoint merging.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "MergePanelController.h"
#import "HttpBridge.h"
#import <cstdio>
#import <string>

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

static NSButton* MakeCheckbox(NSString *title, id target, SEL action)
{
    NSButton *cb = [NSButton checkboxWithTitle:title target:target action:action];
    cb.font = ITLabelFont();
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc] initWithString:title];
    [attrTitle addAttribute:NSForegroundColorAttributeName value:ITTextColor()
                      range:NSMakeRange(0, title.length)];
    [attrTitle addAttribute:NSFontAttributeName value:ITLabelFont()
                      range:NSMakeRange(0, title.length)];
    cb.attributedTitle = attrTitle;
    return cb;
}

//========================================================================================
//  MergePanelController
//========================================================================================

@interface MergePanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSSlider *toleranceSlider;
@property (nonatomic, strong) NSTextField *toleranceValueLabel;
@property (nonatomic, strong) NSTextField *readoutLabel;
@property (nonatomic, strong) NSButton *chainMergeCheckbox;
@property (nonatomic, strong) NSButton *preserveHandlesCheckbox;

// Timer for polling merge readout updates
@property (nonatomic, strong) NSTimer *readoutTimer;

@end

@implementation MergePanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        [self buildUI];
        // Poll for merge readout updates at ~4Hz
        self.readoutTimer = [NSTimer scheduledTimerWithTimeInterval:0.25
            target:self selector:@selector(pollReadout:)
            userInfo:nil repeats:YES];
    }
    return self;
}

- (void)dealloc
{
    [self.readoutTimer invalidate];
    self.readoutTimer = nil;
    [super dealloc];
}

- (void)pollReadout:(NSTimer *)timer
{
    std::string text = BridgeGetMergeReadout();
    NSString *nsText = [NSString stringWithUTF8String:text.c_str()];
    if (![nsText isEqualToString:self.readoutLabel.stringValue]) {
        self.readoutLabel.stringValue = nsText;
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
    CGFloat totalHeight = 300.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Smart Merge", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    // --- Tolerance slider ---
    NSTextField *tolLbl = MakeLabel(@"Tolerance", ITLabelFont(), ITTextColor());
    tolLbl.frame = NSMakeRect(kPadding, y - 14, 80, 14);
    [root addSubview:tolLbl];

    NSTextField *tolVal = MakeLabel(@"5 pt", ITMonoFont(), ITAccentColor());
    tolVal.frame = NSMakeRect(kPanelWidth - kPadding - 40, y - 14, 40, 14);
    tolVal.alignment = NSTextAlignmentRight;
    [root addSubview:tolVal];
    self.toleranceValueLabel = tolVal;
    y -= (14 + 2);

    NSSlider *tolSlider = [NSSlider sliderWithValue:5 minValue:1 maxValue:30
                                             target:self action:@selector(onToleranceChanged:)];
    tolSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [root addSubview:tolSlider];
    self.toleranceSlider = tolSlider;
    y -= (kSliderH + kPadding);

    // --- Scan Endpoints button ---
    NSButton *scanBtn = MakeButton(@"Scan Endpoints", self, @selector(onScanEndpoints:));
    scanBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:scanBtn];
    y -= (kRowHeight + kPadding);

    // --- Readout label ---
    NSTextField *readout = MakeLabel(@"0 pairs found, 0 paths", ITMonoFont(), ITDimColor());
    readout.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [root addSubview:readout];
    self.readoutLabel = readout;
    y -= (14 + kPadding);

    // --- Separator ---
    NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep.boxType = NSBoxSeparator;
    [root addSubview:sep];
    y -= (1 + kPadding);

    // --- Chain Merge checkbox ---
    NSButton *chainCB = MakeCheckbox(@"Chain Merge", self, @selector(onChainMerge:));
    chainCB.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:chainCB];
    self.chainMergeCheckbox = chainCB;
    y -= (kRowHeight + 4);

    // --- Preserve Handles checkbox ---
    NSButton *handlesCB = MakeCheckbox(@"Preserve Handles", self, @selector(onPreserveHandles:));
    handlesCB.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:handlesCB];
    self.preserveHandlesCheckbox = handlesCB;
    y -= (kRowHeight + kPadding);

    // --- Merge / Undo row ---
    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;
    NSButton *mergeBtn = MakeButton(@"Merge", self, @selector(onMerge:));
    mergeBtn.frame = NSMakeRect(kPadding, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:mergeBtn];

    NSButton *undoBtn = MakeButton(@"Undo", self, @selector(onUndo:));
    undoBtn.frame = NSMakeRect(kPadding + halfW + 4, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:undoBtn];
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onToleranceChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.toleranceValueLabel.stringValue = [NSString stringWithFormat:@"%d pt", value];
    fprintf(stderr, "[IllTool Panel] Merge Tolerance: %d pt\n", value);
}

- (void)onScanEndpoints:(id)sender
{
    double tolerance = (double)self.toleranceSlider.integerValue;
    fprintf(stderr, "[IllTool Panel] Scan Endpoints (tolerance=%.1f) — queuing via bridge\n", tolerance);
    BridgeRequestScanEndpoints(tolerance);
}

- (void)onChainMerge:(NSButton *)sender
{
    BOOL checked = (sender.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Chain Merge: %s\n", checked ? "ON" : "OFF");
}

- (void)onPreserveHandles:(NSButton *)sender
{
    BOOL checked = (sender.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Preserve Handles: %s\n", checked ? "ON" : "OFF");
}

- (void)onMerge:(id)sender
{
    BOOL chainMerge = (self.chainMergeCheckbox.state == NSControlStateValueOn);
    BOOL preserveHandles = (self.preserveHandlesCheckbox.state == NSControlStateValueOn);
    fprintf(stderr, "[IllTool Panel] Merge (chain=%s, preserveHandles=%s) — queuing via bridge\n",
            chainMerge ? "ON" : "OFF", preserveHandles ? "ON" : "OFF");
    BridgeRequestMergeEndpoints((bool)chainMerge, (bool)preserveHandles);
}

- (void)onUndo:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Undo Merge — queuing via bridge\n");
    BridgeRequestUndoMerge();
}

//----------------------------------------------------------------------------------------
//  Public methods
//----------------------------------------------------------------------------------------

- (void)updateReadout:(NSString *)text
{
    self.readoutLabel.stringValue = text;
}

@end
