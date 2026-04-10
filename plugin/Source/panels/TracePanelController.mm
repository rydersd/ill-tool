//========================================================================================
//
//  IllTool — Ill Trace Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for tracing raster images via multiple MCP backends.
//  Each backend is its own accordion section with disclosure triangle, Run button,
//  and per-model parameter sliders.
//  Scrollable — content can exceed panel height.
//  No XIB — all NSViews built in code.
//  NO animation — instant show/hide + relayout.
//
//========================================================================================

#import "TracePanelController.h"
#include "IllToolPlugin.h"
#import "HttpBridge.h"
#import <cstdio>

// Theme constants and helpers inherited from TransformPanelController.mm
// (compiled in same translation unit via IllToolPanels.mm includes)
static const CGFloat kSliderH     = 18.0;
static const CGFloat kParamRowH   = 20.0;   // height for a param label row
static const CGFloat kParamGap    = 4.0;    // gap between param rows

//========================================================================================
//  FlippedView
//========================================================================================

@interface TraceFlippedView : NSView
@end

@implementation TraceFlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  TraceModelSection — one per backend model
//========================================================================================

@interface TraceModelSection : NSObject
@property (nonatomic, strong) NSButton   *disclosureButton;  // triangle + title (always visible)
@property (nonatomic, strong) NSButton   *runButton;         // [Run] button (always visible)
@property (nonatomic, strong) NSView     *paramContainer;    // holds sliders (visible when expanded)
@property (nonatomic, assign) BOOL        expanded;
@property (nonatomic, assign) CGFloat     paramHeight;       // computed height of param container
@property (nonatomic, copy)   NSString   *backendName;       // e.g. "vtracer", "opencv"
@end

@implementation TraceModelSection
@end

//========================================================================================
//  TracePanelController
//========================================================================================

@interface TracePanelController ()

@property (nonatomic, strong) NSScrollView *scrollView;
@property (nonatomic, strong) TraceFlippedView *contentView;

// 12 model sections
@property (nonatomic, strong) NSMutableArray<TraceModelSection*> *sections;

// Status label at the bottom
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTimer *statusTimer;

// --- Per-model parameter storage (member properties) ---
// vtracer (uses bridge vars for speckle + colorPrec; member for corner + mode)
@property (nonatomic, assign) int vtracerCornerThreshold;
@property (nonatomic, assign) int vtracerMode; // 0=spline, 1=polygon

// OpenCV Contours
@property (nonatomic, assign) int opencvThreshold;
@property (nonatomic, assign) int opencvMinArea;

// DiffVG Correction
@property (nonatomic, assign) int diffvgIterations;
@property (nonatomic, assign) double diffvgLearningRate;

// CartoonSeg
@property (nonatomic, assign) double cartoonsegConfidence;

// Normal Reference
@property (nonatomic, assign) int normalrefKPlanes;

// Form Edge Extract
@property (nonatomic, assign) int formedgeNumThresholds;
@property (nonatomic, assign) double formedgeBlurSigma;

// Contour Scanner
@property (nonatomic, assign) int contourscanStepSize;
@property (nonatomic, assign) int contourscanColorThreshold;

// Contour to Path
@property (nonatomic, assign) double contourpathTolerance;

// Contour Nesting
@property (nonatomic, assign) int contournestDepth;

// --- Slider + value label references for live updating ---
@property (nonatomic, strong) NSSlider *vtracerSpeckleSlider;
@property (nonatomic, strong) NSTextField *vtracerSpeckleValueLabel;
@property (nonatomic, strong) NSSlider *vtracerColorPrecSlider;
@property (nonatomic, strong) NSTextField *vtracerColorPrecValueLabel;
@property (nonatomic, strong) NSSlider *vtracerCornerSlider;
@property (nonatomic, strong) NSTextField *vtracerCornerValueLabel;
@property (nonatomic, strong) NSPopUpButton *vtracerModePopup;

@property (nonatomic, strong) NSSlider *opencvThresholdSlider;
@property (nonatomic, strong) NSTextField *opencvThresholdValueLabel;
@property (nonatomic, strong) NSSlider *opencvMinAreaSlider;
@property (nonatomic, strong) NSTextField *opencvMinAreaValueLabel;

@property (nonatomic, strong) NSSlider *diffvgIterationsSlider;
@property (nonatomic, strong) NSTextField *diffvgIterationsValueLabel;
@property (nonatomic, strong) NSSlider *diffvgLRSlider;
@property (nonatomic, strong) NSTextField *diffvgLRValueLabel;

@property (nonatomic, strong) NSSlider *cartoonsegConfSlider;
@property (nonatomic, strong) NSTextField *cartoonsegConfValueLabel;

@property (nonatomic, strong) NSSlider *normalrefKPlanesSlider;
@property (nonatomic, strong) NSTextField *normalrefKPlanesValueLabel;

@property (nonatomic, strong) NSSlider *formedgeNumThreshSlider;
@property (nonatomic, strong) NSTextField *formedgeNumThreshValueLabel;
@property (nonatomic, strong) NSSlider *formedgeBlurSlider;
@property (nonatomic, strong) NSTextField *formedgeBlurValueLabel;

@property (nonatomic, strong) NSSlider *contourscanStepSlider;
@property (nonatomic, strong) NSTextField *contourscanStepValueLabel;
@property (nonatomic, strong) NSSlider *contourscanColorSlider;
@property (nonatomic, strong) NSTextField *contourscanColorValueLabel;

@property (nonatomic, strong) NSSlider *contourpathToleranceSlider;
@property (nonatomic, strong) NSTextField *contourpathToleranceValueLabel;

@property (nonatomic, strong) NSSlider *contournestDepthSlider;
@property (nonatomic, strong) NSTextField *contournestDepthValueLabel;

// Output mode segmented control (Outline | Fill)
@property (nonatomic, strong) NSSegmentedControl *outputModeControl;

@end

@implementation TracePanelController

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    self.sections = [NSMutableArray array];

    // Set defaults for member properties
    self.vtracerCornerThreshold = 60;
    self.vtracerMode = 0;
    self.opencvThreshold = 128;
    self.opencvMinArea = 50;
    self.diffvgIterations = 100;
    self.diffvgLearningRate = 0.01;
    self.cartoonsegConfidence = 0.5;
    self.normalrefKPlanes = 6;
    self.formedgeNumThresholds = 10;
    self.formedgeBlurSigma = 1.0;
    self.contourscanStepSize = 5;
    self.contourscanColorThreshold = 30;
    self.contourpathTolerance = 1.0;
    self.contournestDepth = 3;

    // Create the scroll view wrapper
    self.scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, 660)];
    self.scrollView.hasVerticalScroller = YES;
    self.scrollView.hasHorizontalScroller = NO;
    self.scrollView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.scrollView.drawsBackground = YES;
    self.scrollView.backgroundColor = ITBGColor();
    self.scrollView.borderType = NSNoBorder;

    // Content view inside the scroll view
    self.contentView = [[TraceFlippedView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, 1200)];
    self.contentView.wantsLayer = YES;
    self.contentView.layer.backgroundColor = ITBGColor().CGColor;
    self.scrollView.documentView = self.contentView;

    CGFloat contentW = kPanelWidth - 2*kPadding;

    // --- Panel title ---
    NSTextField *title = MakeLabel(@"Ill Trace", ITLabelFont(), ITAccentColor());
    title.frame = NSMakeRect(kPadding, kPadding, contentW, kRowHeight);
    title.font = [NSFont boldSystemFontOfSize:12];
    [self.contentView addSubview:title];

    // --- Output mode segmented control (Outline | Fill) ---
    self.outputModeControl = [NSSegmentedControl segmentedControlWithLabels:@[@"Outline", @"Fill"]
                                                              trackingMode:NSSegmentSwitchTrackingSelectOne
                                                                    target:self
                                                                    action:@selector(outputModeChanged:)];
    self.outputModeControl.selectedSegment = 1;  // default: Fill
    self.outputModeControl.frame = NSMakeRect(kPadding, kPadding + kRowHeight + 4, contentW, 22);
    self.outputModeControl.font = [NSFont systemFontOfSize:10];
    [self.contentView addSubview:self.outputModeControl];

    // ==========================================
    //  Build 12 model sections
    // ==========================================

    // 0: vtracer
    [self addModelSection:@"vtracer (clean SVG)" backend:@"vtracer" tag:0
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildVtracerParams:container width:cw];
    }];

    // 1: OpenCV Contours
    [self addModelSection:@"OpenCV Contours" backend:@"opencv" tag:1
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildOpenCVParams:container width:cw];
    }];

    // 2: StarVector (ML) — no params
    [self addModelSection:@"StarVector (ML)" backend:@"starvector" tag:2
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return (CGFloat)0.0;
    }];

    // 3: DiffVG Correction
    [self addModelSection:@"DiffVG Correction" backend:@"diffvg" tag:3
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildDiffVGParams:container width:cw];
    }];

    // 4: CartoonSeg
    [self addModelSection:@"CartoonSeg" backend:@"cartoonseg" tag:4
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildCartoonSegParams:container width:cw];
    }];

    // 5: Normal Reference
    [self addModelSection:@"Normal Reference" backend:@"normal_ref" tag:5
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildNormalRefParams:container width:cw];
    }];

    // 6: Form Edge Extract
    [self addModelSection:@"Form Edge Extract" backend:@"form_edge" tag:6
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildFormEdgeParams:container width:cw];
    }];

    // 7: Analyze Reference — no params
    [self addModelSection:@"Analyze Reference" backend:@"analyze_ref" tag:7
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return (CGFloat)0.0;
    }];

    // 8: Contour Scanner
    [self addModelSection:@"Contour Scanner" backend:@"contour_scan" tag:8
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildContourScanParams:container width:cw];
    }];

    // 9: Contour to Path
    [self addModelSection:@"Contour to Path" backend:@"contour_path" tag:9
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildContourPathParams:container width:cw];
    }];

    // 10: Contour Labeler — no params
    [self addModelSection:@"Contour Labeler" backend:@"contour_label" tag:10
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return (CGFloat)0.0;
    }];

    // 11: Contour Nesting
    [self addModelSection:@"Contour Nesting" backend:@"contour_nest" tag:11
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildContourNestParams:container width:cw];
    }];

    // --- Status label at the bottom ---
    self.statusLabel = MakeLabel(@"Expand a model, adjust params, click Run", ITLabelFont(), ITDimColor());
    self.statusLabel.maximumNumberOfLines = 3;
    [self.contentView addSubview:self.statusLabel];

    // Perform initial layout
    [self relayoutContent];

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
    return self.scrollView;
}

//----------------------------------------------------------------------------------------
//  addModelSection — creates disclosure + run button + param container for one backend
//----------------------------------------------------------------------------------------

- (void)addModelSection:(NSString *)displayTitle
                backend:(NSString *)backendName
                    tag:(NSInteger)tag
           paramBuilder:(CGFloat(^)(NSView *container, CGFloat contentW, TracePanelController *ctrl))builder
{
    CGFloat contentW = kPanelWidth - 2*kPadding;

    TraceModelSection *sec = [[TraceModelSection alloc] init];
    sec.backendName = backendName;
    sec.expanded = (tag == 0); // first section expanded by default

    // Disclosure button (triangle + title)
    sec.disclosureButton = [self makeDisclosureButton:displayTitle tag:tag expanded:sec.expanded];
    [self.contentView addSubview:sec.disclosureButton];

    // Run button
    sec.runButton = [NSButton buttonWithTitle:@"Run" target:self action:@selector(runModelClicked:)];
    sec.runButton.font = [NSFont systemFontOfSize:10];
    sec.runButton.bezelStyle = NSBezelStyleSmallSquare;
    sec.runButton.tag = tag;
    [self.contentView addSubview:sec.runButton];

    // Parameter container
    sec.paramContainer = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
    [self.contentView addSubview:sec.paramContainer];

    // Build parameters inside the container
    CGFloat paramH = builder(sec.paramContainer, contentW - 16, self); // 16 = indent
    sec.paramHeight = paramH;

    if (!sec.expanded) {
        sec.paramContainer.hidden = YES;
    }

    [self.sections addObject:sec];
}

//----------------------------------------------------------------------------------------
//  Disclosure button factory
//----------------------------------------------------------------------------------------

- (NSButton *)makeDisclosureButton:(NSString *)title tag:(NSInteger)tag expanded:(BOOL)expanded
{
    NSButton *header = [[NSButton alloc] initWithFrame:NSZeroRect];
    header.bordered = NO;
    header.buttonType = NSButtonTypeMomentaryLight;
    header.target = self;
    header.action = @selector(sectionToggled:);
    header.tag = tag;

    NSString *prefix = expanded ? @"\u25BC " : @"\u25B6 ";
    NSString *fullTitle = [NSString stringWithFormat:@"%@%@", prefix, title];
    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
        initWithString:fullTitle];
    [attrTitle addAttribute:NSForegroundColorAttributeName
                      value:ITAccentColor()
                      range:NSMakeRange(0, attrTitle.length)];
    [attrTitle addAttribute:NSFontAttributeName
                      value:[NSFont boldSystemFontOfSize:11]
                      range:NSMakeRange(0, attrTitle.length)];
    header.attributedTitle = attrTitle;
    header.alignment = NSTextAlignmentLeft;
    [attrTitle release];

    return [header autorelease];
}

//----------------------------------------------------------------------------------------
//  Relayout — recalculates y-positions for all sections and the status label
//  NO animation. Pure position recalculation.
//----------------------------------------------------------------------------------------

- (void)relayoutContent
{
    CGFloat contentW = kPanelWidth - 2*kPadding;
    CGFloat y = kPadding + kRowHeight + 6;  // skip past title

    // Position segmented control below title
    self.outputModeControl.frame = NSMakeRect(kPadding, y, contentW, 22);
    y += 26;  // segmented control height + spacing

    CGFloat runBtnW = 40.0;
    CGFloat disclosureW = contentW - runBtnW - 4;

    for (TraceModelSection *sec in self.sections) {
        // Disclosure button (left side)
        sec.disclosureButton.frame = NSMakeRect(kPadding, y, disclosureW, 20);
        // Run button (right side, same row)
        sec.runButton.frame = NSMakeRect(kPadding + disclosureW + 4, y, runBtnW, 20);
        y += 22;

        // Parameter container (indented)
        if (sec.expanded && sec.paramHeight > 0) {
            sec.paramContainer.frame = NSMakeRect(kPadding + 8, y, contentW - 8, sec.paramHeight);
            sec.paramContainer.hidden = NO;
            y += sec.paramHeight + 2;
        } else {
            sec.paramContainer.hidden = YES;
        }

        y += 4;  // spacing between sections
    }

    y += 4;

    // Status label
    self.statusLabel.frame = NSMakeRect(kPadding, y, contentW, kRowHeight * 3);
    y += kRowHeight * 3 + kPadding;

    // Resize contentView to fit
    self.contentView.frame = NSMakeRect(0, 0, kPanelWidth, y);
}

//========================================================================================
//  Parameter builders — each returns the total height used
//========================================================================================

//--- Helper: add a slider row (label + slider + value display) ---

- (CGFloat)addSliderRow:(NSView *)container
                  atY:(CGFloat)y
                width:(CGFloat)w
                label:(NSString *)labelText
             minValue:(double)minVal
             maxValue:(double)maxVal
         defaultValue:(double)defVal
          isFloatDisp:(BOOL)isFloat
           outSlider:(NSSlider **)outSlider
        outValueLabel:(NSTextField **)outValueLabel
               action:(SEL)action
{
    CGFloat valueW = 40.0;
    CGFloat labelW = w - valueW - 4;

    NSTextField *lbl = MakeLabel(labelText, ITLabelFont(), ITTextColor());
    lbl.frame = NSMakeRect(0, y, labelW, kParamRowH);
    [container addSubview:lbl];

    NSTextField *valLabel = MakeLabel(
        isFloat ? [NSString stringWithFormat:@"%.2f", defVal]
                : [NSString stringWithFormat:@"%d", (int)defVal],
        ITLabelFont(), ITDimColor());
    valLabel.alignment = NSTextAlignmentRight;
    valLabel.frame = NSMakeRect(w - valueW, y, valueW, kParamRowH);
    [container addSubview:valLabel];

    y += kParamRowH;

    NSSlider *slider = [[NSSlider alloc] initWithFrame:NSMakeRect(0, y, w, kSliderH)];
    slider.minValue = minVal;
    slider.maxValue = maxVal;
    slider.doubleValue = defVal;
    slider.target = self;
    slider.action = action;
    [container addSubview:slider];

    if (outSlider) *outSlider = slider;
    if (outValueLabel) *outValueLabel = valLabel;

    y += kSliderH + kParamGap;
    return y;
}

//--- Helper: add a popup row (label + popup button) ---

- (CGFloat)addPopupRow:(NSView *)container
                 atY:(CGFloat)y
               width:(CGFloat)w
               label:(NSString *)labelText
               items:(NSArray<NSString*> *)items
        defaultIndex:(NSInteger)defIdx
           outPopup:(NSPopUpButton **)outPopup
              action:(SEL)action
{
    CGFloat popupW = 100.0;
    CGFloat labelW = w - popupW - 4;

    NSTextField *lbl = MakeLabel(labelText, ITLabelFont(), ITTextColor());
    lbl.frame = NSMakeRect(0, y, labelW, kParamRowH);
    [container addSubview:lbl];

    NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(w - popupW, y, popupW, kParamRowH) pullsDown:NO];
    popup.font = [NSFont systemFontOfSize:10];
    [popup addItemsWithTitles:items];
    [popup selectItemAtIndex:defIdx];
    popup.target = self;
    popup.action = action;
    [container addSubview:popup];

    if (outPopup) *outPopup = popup;

    y += kParamRowH + kParamGap;
    return y;
}

//--- vtracer: Speckle, Color Precision, Corner Threshold, Mode ---

- (CGFloat)buildVtracerParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Speckle Filter:"
                  minValue:1 maxValue:100 defaultValue:4 isFloatDisp:NO
                 outSlider:&_vtracerSpeckleSlider outValueLabel:&_vtracerSpeckleValueLabel
                    action:@selector(vtracerSpeckleChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Color Precision:"
                  minValue:1 maxValue:10 defaultValue:6 isFloatDisp:NO
                 outSlider:&_vtracerColorPrecSlider outValueLabel:&_vtracerColorPrecValueLabel
                    action:@selector(vtracerColorPrecChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Corner Threshold:"
                  minValue:0 maxValue:180 defaultValue:60 isFloatDisp:NO
                 outSlider:&_vtracerCornerSlider outValueLabel:&_vtracerCornerValueLabel
                    action:@selector(vtracerCornerChanged:)];

    y = [self addPopupRow:container atY:y width:w label:@"Mode:"
                    items:@[@"spline", @"polygon"] defaultIndex:0
                 outPopup:&_vtracerModePopup action:@selector(vtracerModeChanged:)];

    return y;
}

//--- OpenCV Contours: Threshold, Min Area ---

- (CGFloat)buildOpenCVParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Threshold:"
                  minValue:0 maxValue:255 defaultValue:128 isFloatDisp:NO
                 outSlider:&_opencvThresholdSlider outValueLabel:&_opencvThresholdValueLabel
                    action:@selector(opencvThresholdChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Min Area:"
                  minValue:1 maxValue:1000 defaultValue:50 isFloatDisp:NO
                 outSlider:&_opencvMinAreaSlider outValueLabel:&_opencvMinAreaValueLabel
                    action:@selector(opencvMinAreaChanged:)];

    return y;
}

//--- DiffVG Correction: Iterations, Learning Rate ---

- (CGFloat)buildDiffVGParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Iterations:"
                  minValue:10 maxValue:500 defaultValue:100 isFloatDisp:NO
                 outSlider:&_diffvgIterationsSlider outValueLabel:&_diffvgIterationsValueLabel
                    action:@selector(diffvgIterationsChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Learning Rate:"
                  minValue:0.01 maxValue:1.0 defaultValue:0.01 isFloatDisp:YES
                 outSlider:&_diffvgLRSlider outValueLabel:&_diffvgLRValueLabel
                    action:@selector(diffvgLRChanged:)];

    return y;
}

//--- CartoonSeg: Confidence ---

- (CGFloat)buildCartoonSegParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Confidence:"
                  minValue:0.1 maxValue:1.0 defaultValue:0.5 isFloatDisp:YES
                 outSlider:&_cartoonsegConfSlider outValueLabel:&_cartoonsegConfValueLabel
                    action:@selector(cartoonsegConfChanged:)];

    return y;
}

//--- Normal Reference: K Planes ---

- (CGFloat)buildNormalRefParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"K Planes:"
                  minValue:2 maxValue:16 defaultValue:6 isFloatDisp:NO
                 outSlider:&_normalrefKPlanesSlider outValueLabel:&_normalrefKPlanesValueLabel
                    action:@selector(normalrefKPlanesChanged:)];

    return y;
}

//--- Form Edge Extract: Num Thresholds, Blur Sigma ---

- (CGFloat)buildFormEdgeParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Num Thresholds:"
                  minValue:3 maxValue:20 defaultValue:10 isFloatDisp:NO
                 outSlider:&_formedgeNumThreshSlider outValueLabel:&_formedgeNumThreshValueLabel
                    action:@selector(formedgeNumThreshChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Blur Sigma:"
                  minValue:0.5 maxValue:5.0 defaultValue:1.0 isFloatDisp:YES
                 outSlider:&_formedgeBlurSlider outValueLabel:&_formedgeBlurValueLabel
                    action:@selector(formedgeBlurChanged:)];

    return y;
}

//--- Contour Scanner: Step Size, Color Threshold ---

- (CGFloat)buildContourScanParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Step Size:"
                  minValue:1 maxValue:20 defaultValue:5 isFloatDisp:NO
                 outSlider:&_contourscanStepSlider outValueLabel:&_contourscanStepValueLabel
                    action:@selector(contourscanStepChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Color Threshold:"
                  minValue:0 maxValue:100 defaultValue:30 isFloatDisp:NO
                 outSlider:&_contourscanColorSlider outValueLabel:&_contourscanColorValueLabel
                    action:@selector(contourscanColorChanged:)];

    return y;
}

//--- Contour to Path: Tolerance ---

- (CGFloat)buildContourPathParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Tolerance:"
                  minValue:0.1 maxValue:10.0 defaultValue:1.0 isFloatDisp:YES
                 outSlider:&_contourpathToleranceSlider outValueLabel:&_contourpathToleranceValueLabel
                    action:@selector(contourpathToleranceChanged:)];

    return y;
}

//--- Contour Nesting: Depth ---

- (CGFloat)buildContourNestParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Depth:"
                  minValue:1 maxValue:10 defaultValue:3 isFloatDisp:NO
                 outSlider:&_contournestDepthSlider outValueLabel:&_contournestDepthValueLabel
                    action:@selector(contournestDepthChanged:)];

    return y;
}

//========================================================================================
//  Actions — section toggle
//========================================================================================

- (void)sectionToggled:(NSButton *)sender
{
    NSInteger idx = sender.tag;
    if (idx < 0 || idx >= (NSInteger)self.sections.count) return;

    TraceModelSection *sec = self.sections[idx];
    sec.expanded = !sec.expanded;

    // Update the disclosure triangle in the button title
    NSString *currentTitle = sender.title;
    // Strip the first 2 characters (triangle + space) to get the section name
    NSString *sectionName = (currentTitle.length > 2) ? [currentTitle substringFromIndex:2] : currentTitle;
    NSString *prefix = sec.expanded ? @"\u25BC " : @"\u25B6 ";
    NSString *newTitle = [NSString stringWithFormat:@"%@%@", prefix, sectionName];

    NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
        initWithString:newTitle];
    [attrTitle addAttribute:NSForegroundColorAttributeName
                      value:ITAccentColor()
                      range:NSMakeRange(0, attrTitle.length)];
    [attrTitle addAttribute:NSFontAttributeName
                      value:[NSFont boldSystemFontOfSize:11]
                      range:NSMakeRange(0, attrTitle.length)];
    sender.attributedTitle = attrTitle;
    [attrTitle release];

    // Instant show/hide + reposition. NO animation.
    sec.paramContainer.hidden = !sec.expanded;
    [self relayoutContent];

    fprintf(stderr, "[TracePanel] Section %d (%s) %s\n",
            (int)idx, [sec.backendName UTF8String],
            sec.expanded ? "expanded" : "collapsed");
}

//========================================================================================
//  Actions — Run button per model
//========================================================================================

- (void)runModelClicked:(NSButton *)sender
{
    NSInteger idx = sender.tag;
    if (idx < 0 || idx >= (NSInteger)self.sections.count) return;

    TraceModelSection *sec = self.sections[idx];
    std::string backendStr = [sec.backendName UTF8String];

    BridgeRequestTrace(backendStr);

    self.statusLabel.stringValue = [NSString stringWithFormat:@"Running %@...", sec.backendName];
    fprintf(stderr, "[TracePanel] Run clicked: backend=%s\n", backendStr.c_str());
}

//========================================================================================
//  Slider actions — vtracer
//========================================================================================

- (void)vtracerSpeckleChanged:(id)sender
{
    int val = (int)self.vtracerSpeckleSlider.intValue;
    BridgeSetTraceSpeckle(val);
    self.vtracerSpeckleValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerColorPrecChanged:(id)sender
{
    int val = (int)self.vtracerColorPrecSlider.intValue;
    BridgeSetTraceColorPrecision(val);
    self.vtracerColorPrecValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerCornerChanged:(id)sender
{
    int val = (int)self.vtracerCornerSlider.intValue;
    self.vtracerCornerThreshold = val;
    self.vtracerCornerValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerModeChanged:(id)sender
{
    self.vtracerMode = (int)self.vtracerModePopup.indexOfSelectedItem;
}

//========================================================================================
//  Slider actions — OpenCV
//========================================================================================

- (void)opencvThresholdChanged:(id)sender
{
    int val = (int)self.opencvThresholdSlider.intValue;
    self.opencvThreshold = val;
    self.opencvThresholdValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)opencvMinAreaChanged:(id)sender
{
    int val = (int)self.opencvMinAreaSlider.intValue;
    self.opencvMinArea = val;
    self.opencvMinAreaValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

//========================================================================================
//  Slider actions — DiffVG
//========================================================================================

- (void)diffvgIterationsChanged:(id)sender
{
    int val = (int)self.diffvgIterationsSlider.intValue;
    self.diffvgIterations = val;
    self.diffvgIterationsValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)diffvgLRChanged:(id)sender
{
    double val = self.diffvgLRSlider.doubleValue;
    self.diffvgLearningRate = val;
    self.diffvgLRValueLabel.stringValue = [NSString stringWithFormat:@"%.2f", val];
}

//========================================================================================
//  Slider actions — CartoonSeg
//========================================================================================

- (void)cartoonsegConfChanged:(id)sender
{
    double val = self.cartoonsegConfSlider.doubleValue;
    self.cartoonsegConfidence = val;
    self.cartoonsegConfValueLabel.stringValue = [NSString stringWithFormat:@"%.2f", val];
}

//========================================================================================
//  Slider actions — Normal Reference
//========================================================================================

- (void)normalrefKPlanesChanged:(id)sender
{
    int val = (int)self.normalrefKPlanesSlider.intValue;
    self.normalrefKPlanes = val;
    self.normalrefKPlanesValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

//========================================================================================
//  Slider actions — Form Edge Extract
//========================================================================================

- (void)formedgeNumThreshChanged:(id)sender
{
    int val = (int)self.formedgeNumThreshSlider.intValue;
    self.formedgeNumThresholds = val;
    self.formedgeNumThreshValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)formedgeBlurChanged:(id)sender
{
    double val = self.formedgeBlurSlider.doubleValue;
    self.formedgeBlurSigma = val;
    self.formedgeBlurValueLabel.stringValue = [NSString stringWithFormat:@"%.1f", val];
}

//========================================================================================
//  Slider actions — Contour Scanner
//========================================================================================

- (void)contourscanStepChanged:(id)sender
{
    int val = (int)self.contourscanStepSlider.intValue;
    self.contourscanStepSize = val;
    self.contourscanStepValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)contourscanColorChanged:(id)sender
{
    int val = (int)self.contourscanColorSlider.intValue;
    self.contourscanColorThreshold = val;
    self.contourscanColorValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

//========================================================================================
//  Slider actions — Contour to Path
//========================================================================================

- (void)contourpathToleranceChanged:(id)sender
{
    double val = self.contourpathToleranceSlider.doubleValue;
    self.contourpathTolerance = val;
    self.contourpathToleranceValueLabel.stringValue = [NSString stringWithFormat:@"%.1f", val];
}

//========================================================================================
//  Slider actions — Contour Nesting
//========================================================================================

- (void)contournestDepthChanged:(id)sender
{
    int val = (int)self.contournestDepthSlider.intValue;
    self.contournestDepth = val;
    self.contournestDepthValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

//========================================================================================
//  Output mode segmented control action
//========================================================================================

- (void)outputModeChanged:(id)sender
{
    NSInteger selected = self.outputModeControl.selectedSegment;
    BridgeSetTraceOutputMode((int)selected);  // 0=outline, 1=fill
    fprintf(stderr, "[TracePanel] Output mode: %s\n", selected == 0 ? "outline" : "fill");
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
