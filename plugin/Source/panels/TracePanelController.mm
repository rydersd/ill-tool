//========================================================================================
//
//  IllTool — Ill Trace Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for tracing raster images via multiple MCP backends.
//  Checkboxes for each backend — run selected simultaneously.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "TracePanelController.h"
#include "IllToolPlugin.h"
#import "HttpBridge.h"
#import <cstdio>

// Theme constants and helpers inherited from TransformPanelController.mm
// (compiled in same translation unit via IllToolPanels.mm includes)
static const CGFloat kSliderH     = 18.0;

//========================================================================================
//  FlippedView
//========================================================================================

@interface TraceFlippedView : NSView
@end

@implementation TraceFlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  Backend checkbox helper
//========================================================================================

static NSButton* MakeCheckbox(NSString *title, id target, SEL action, BOOL checked)
{
    NSButton *cb = [NSButton checkboxWithTitle:title target:target action:action];
    cb.font = ITLabelFont();
    // Dark theme text
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
        initWithString:title];
    [attrTitle addAttribute:NSForegroundColorAttributeName
                      value:ITTextColor()
                      range:NSMakeRange(0, attrTitle.length)];
    [attrTitle addAttribute:NSFontAttributeName
                      value:ITLabelFont()
                      range:NSMakeRange(0, attrTitle.length)];
    cb.attributedTitle = attrTitle;
    [attrTitle release];
    cb.state = checked ? NSControlStateValueOn : NSControlStateValueOff;
    return cb;
}

//========================================================================================
//  TracePanelController
//========================================================================================

@interface TracePanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Backend checkboxes (13 backends)
@property (nonatomic, strong) NSButton *cbVtracer;
@property (nonatomic, strong) NSButton *cbOpenCV;
@property (nonatomic, strong) NSButton *cbStarVector;
@property (nonatomic, strong) NSButton *cbCartoonSeg;
@property (nonatomic, strong) NSButton *cbImageTrace;
@property (nonatomic, strong) NSButton *cbDiffVG;
@property (nonatomic, strong) NSButton *cbContourScan;
@property (nonatomic, strong) NSButton *cbContourPath;
@property (nonatomic, strong) NSButton *cbContourLabel;
@property (nonatomic, strong) NSButton *cbContourNest;
@property (nonatomic, strong) NSButton *cbFormEdge;
@property (nonatomic, strong) NSButton *cbNormalRef;
@property (nonatomic, strong) NSButton *cbAnalyzeRef;

// Parameter controls
@property (nonatomic, strong) NSSlider *speckleSlider;
@property (nonatomic, strong) NSTextField *speckleLabel;
@property (nonatomic, strong) NSSlider *colorPrecSlider;
@property (nonatomic, strong) NSTextField *colorPrecLabel;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSButton *traceButton;
@property (nonatomic, strong) NSTimer *statusTimer;

@end

@implementation TracePanelController

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    CGFloat y = kPadding;
    CGFloat contentW = kPanelWidth - 2*kPadding;

    TraceFlippedView *root = [[TraceFlippedView alloc] initWithFrame:
                              NSMakeRect(0, 0, kPanelWidth, 660)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;

    // Section title
    NSTextField *title = MakeLabel(@"Ill Trace", ITLabelFont(), ITAccentColor());
    title.frame = NSMakeRect(kPadding, y, contentW, kRowHeight);
    title.font = [NSFont boldSystemFontOfSize:12];
    [root addSubview:title];
    y += kRowHeight + 6;

    // --- Backend checkboxes ---
    NSTextField *backendTitle = MakeLabel(@"Backends:", ITLabelFont(), ITDimColor());
    backendTitle.frame = NSMakeRect(kPadding, y, contentW, kRowHeight);
    [root addSubview:backendTitle];
    y += kRowHeight + 2;

    self.cbVtracer = MakeCheckbox(@"vtracer (Rust — clean SVG)", self, @selector(backendToggled:), YES);
    self.cbVtracer.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbVtracer.tag = 0;
    [root addSubview:self.cbVtracer];
    y += 20;

    self.cbOpenCV = MakeCheckbox(@"OpenCV Contours", self, @selector(backendToggled:), NO);
    self.cbOpenCV.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbOpenCV.tag = 1;
    [root addSubview:self.cbOpenCV];
    y += 20;

    self.cbStarVector = MakeCheckbox(@"StarVector (ML)", self, @selector(backendToggled:), NO);
    self.cbStarVector.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbStarVector.tag = 2;
    [root addSubview:self.cbStarVector];
    y += 20;

    self.cbCartoonSeg = MakeCheckbox(@"CartoonSeg (Instance Seg)", self, @selector(backendToggled:), NO);
    self.cbCartoonSeg.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbCartoonSeg.tag = 3;
    [root addSubview:self.cbCartoonSeg];
    y += 20;

    self.cbImageTrace = MakeCheckbox(@"Illustrator Image Trace", self, @selector(backendToggled:), NO);
    self.cbImageTrace.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbImageTrace.tag = 4;
    [root addSubview:self.cbImageTrace];
    y += 20;

    self.cbContourScan = MakeCheckbox(@"Axis Contour Scanner", self, @selector(backendToggled:), NO);
    self.cbContourScan.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbContourScan.tag = 5;
    [root addSubview:self.cbContourScan];
    y += 20;

    self.cbDiffVG = MakeCheckbox(@"DiffVG Correction", self, @selector(backendToggled:), NO);
    self.cbDiffVG.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbDiffVG.tag = 5;
    [root addSubview:self.cbDiffVG];
    y += 20;

    self.cbContourScan = MakeCheckbox(@"Axis Contour Scanner", self, @selector(backendToggled:), NO);
    self.cbContourScan.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbContourScan.tag = 6;
    [root addSubview:self.cbContourScan];
    y += 20;

    self.cbContourPath = MakeCheckbox(@"Contour to Path", self, @selector(backendToggled:), NO);
    self.cbContourPath.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbContourPath.tag = 7;
    [root addSubview:self.cbContourPath];
    y += 20;

    self.cbContourLabel = MakeCheckbox(@"Contour Labeler", self, @selector(backendToggled:), NO);
    self.cbContourLabel.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbContourLabel.tag = 8;
    [root addSubview:self.cbContourLabel];
    y += 20;

    self.cbContourNest = MakeCheckbox(@"Contour Nesting", self, @selector(backendToggled:), NO);
    self.cbContourNest.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbContourNest.tag = 9;
    [root addSubview:self.cbContourNest];
    y += 20;

    self.cbFormEdge = MakeCheckbox(@"Form Edge Extract", self, @selector(backendToggled:), NO);
    self.cbFormEdge.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbFormEdge.tag = 10;
    [root addSubview:self.cbFormEdge];
    y += 20;

    self.cbNormalRef = MakeCheckbox(@"Normal Reference", self, @selector(backendToggled:), NO);
    self.cbNormalRef.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbNormalRef.tag = 11;
    [root addSubview:self.cbNormalRef];
    y += 20;

    self.cbAnalyzeRef = MakeCheckbox(@"Analyze Reference", self, @selector(backendToggled:), NO);
    self.cbAnalyzeRef.frame = NSMakeRect(kPadding + 8, y, contentW - 8, 18);
    self.cbAnalyzeRef.tag = 12;
    [root addSubview:self.cbAnalyzeRef];
    y += 24;

    // --- Separator ---
    NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, contentW, 1)];
    sep.boxType = NSBoxSeparator;
    [root addSubview:sep];
    [sep release];
    y += 8;

    // --- Parameters ---
    NSTextField *paramTitle = MakeLabel(@"Parameters:", ITLabelFont(), ITDimColor());
    paramTitle.frame = NSMakeRect(kPadding, y, contentW, kRowHeight);
    [root addSubview:paramTitle];
    y += kRowHeight + 2;

    // Speckle filter slider
    NSTextField *speckleTitleLabel = MakeLabel(@"Speckle Filter:", ITLabelFont(), ITTextColor());
    speckleTitleLabel.frame = NSMakeRect(kPadding, y, 100, kRowHeight);
    [root addSubview:speckleTitleLabel];

    self.speckleLabel = MakeLabel(@"4", ITLabelFont(), ITDimColor());
    self.speckleLabel.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, kRowHeight);
    self.speckleLabel.alignment = NSTextAlignmentRight;
    [root addSubview:self.speckleLabel];
    y += kRowHeight;

    self.speckleSlider = [[NSSlider alloc] initWithFrame:
                          NSMakeRect(kPadding, y, contentW, kSliderH)];
    self.speckleSlider.minValue = 1;
    self.speckleSlider.maxValue = 100;
    self.speckleSlider.intValue = 4;
    self.speckleSlider.target = self;
    self.speckleSlider.action = @selector(speckleChanged:);
    [root addSubview:self.speckleSlider];
    y += kSliderH + 6;

    // Color precision slider
    NSTextField *colorPrecTitleLabel = MakeLabel(@"Color Precision:", ITLabelFont(), ITTextColor());
    colorPrecTitleLabel.frame = NSMakeRect(kPadding, y, 110, kRowHeight);
    [root addSubview:colorPrecTitleLabel];

    self.colorPrecLabel = MakeLabel(@"6", ITLabelFont(), ITDimColor());
    self.colorPrecLabel.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, kRowHeight);
    self.colorPrecLabel.alignment = NSTextAlignmentRight;
    [root addSubview:self.colorPrecLabel];
    y += kRowHeight;

    self.colorPrecSlider = [[NSSlider alloc] initWithFrame:
                            NSMakeRect(kPadding, y, contentW, kSliderH)];
    self.colorPrecSlider.minValue = 1;
    self.colorPrecSlider.maxValue = 10;
    self.colorPrecSlider.intValue = 6;
    self.colorPrecSlider.target = self;
    self.colorPrecSlider.action = @selector(colorPrecChanged:);
    [root addSubview:self.colorPrecSlider];
    y += kSliderH + 12;

    // --- Run button ---
    self.traceButton = MakeButton(@"Run Selected", self, @selector(traceClicked:));
    self.traceButton.frame = NSMakeRect(kPadding, y, contentW, 28);
    [root addSubview:self.traceButton];
    y += 28 + 8;

    // Status label
    self.statusLabel = MakeLabel(@"Select backends, place an image, click Run", ITLabelFont(), ITDimColor());
    self.statusLabel.frame = NSMakeRect(kPadding, y, contentW, kRowHeight * 3);
    self.statusLabel.maximumNumberOfLines = 3;
    [root addSubview:self.statusLabel];
    y += kRowHeight * 3 + kPadding;

    root.frame = NSMakeRect(0, 0, kPanelWidth, y);
    self.rootViewInternal = root;

    // Status polling timer
    self.statusTimer = [NSTimer scheduledTimerWithTimeInterval:0.5
                                                       target:self
                                                     selector:@selector(updateStatus)
                                                     userInfo:nil
                                                      repeats:YES];

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
//  Actions
//----------------------------------------------------------------------------------------

- (void)backendToggled:(NSButton *)sender
{
    // Just log — the actual selection is read at trace time
    fprintf(stderr, "[TracePanel] Backend %d toggled to %s\n",
            (int)sender.tag, sender.state == NSControlStateValueOn ? "ON" : "OFF");
}

- (void)traceClicked:(id)sender
{
    // Collect all checked backends
    NSArray<NSButton*> *checkboxes = @[
        self.cbVtracer, self.cbOpenCV, self.cbStarVector,
        self.cbCartoonSeg, self.cbImageTrace, self.cbDiffVG,
        self.cbContourScan, self.cbContourPath, self.cbContourLabel,
        self.cbContourNest, self.cbFormEdge, self.cbNormalRef, self.cbAnalyzeRef
    ];
    NSArray<NSString*> *backendNames = @[
        @"vtracer", @"opencv", @"starvector",
        @"cartoonseg", @"image_trace", @"diffvg",
        @"contour_scan", @"contour_path", @"contour_label",
        @"contour_nest", @"form_edge", @"normal_ref", @"analyze_ref"
    ];

    NSMutableArray<NSString*> *selected = [NSMutableArray array];
    for (NSUInteger i = 0; i < checkboxes.count; i++) {
        if (checkboxes[i].state == NSControlStateValueOn) {
            [selected addObject:backendNames[i]];
        }
    }

    if (selected.count == 0) {
        self.statusLabel.stringValue = @"No backends selected";
        return;
    }

    // Enqueue a trace request for each selected backend
    for (NSString *backend in selected) {
        std::string backendStr = [backend UTF8String];
        BridgeRequestTrace(backendStr);
        fprintf(stderr, "[TracePanel] Trace requested: backend=%s\n", backendStr.c_str());
    }

    self.statusLabel.stringValue = [NSString stringWithFormat:@"Running %lu backend%s...",
                                    (unsigned long)selected.count,
                                    selected.count > 1 ? "s" : ""];
}

- (void)speckleChanged:(id)sender
{
    int val = (int)self.speckleSlider.intValue;
    BridgeSetTraceSpeckle(val);
    self.speckleLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)colorPrecChanged:(id)sender
{
    int val = (int)self.colorPrecSlider.intValue;
    BridgeSetTraceColorPrecision(val);
    self.colorPrecLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

//----------------------------------------------------------------------------------------
//  Status polling
//----------------------------------------------------------------------------------------

- (void)updateStatus
{
    std::string status = BridgeGetTraceStatus();
    if (!status.empty()) {
        self.statusLabel.stringValue = [NSString stringWithUTF8String:status.c_str()];
    }
}

@end
