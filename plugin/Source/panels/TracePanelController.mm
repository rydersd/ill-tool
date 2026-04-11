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
#import "IllToolTheme.h"
#include "IllToolPlugin.h"
#import "HttpBridge.h"
#import <cstdio>

// Layout constants (kPanelWidth, kPadding, kRowHeight inherited from TransformPanelController.mm
// in the same translation unit via IllToolPanels.mm includes)
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
@property (nonatomic, strong) NSProgressIndicator *progressBar; // replaces Run button while tracing
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

// 16 model sections (0-11 existing + 12 Subject Cutout + 13 Apple Contours + 14 Pose Detection + 15 Depth Layers)
@property (nonatomic, strong) NSMutableArray<TraceModelSection*> *sections;

// Status label at the bottom
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTimer *statusTimer;
@property (nonatomic, assign) BOOL hardwareGatingApplied;

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
@property (nonatomic, assign) double normalrefBlur;
@property (nonatomic, assign) int normalrefKMeansStride;
@property (nonatomic, assign) int normalrefKMeansIter;

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
@property (nonatomic, strong) NSSlider *normalrefBlurSlider;
@property (nonatomic, strong) NSTextField *normalrefBlurValueLabel;
@property (nonatomic, strong) NSSlider *normalrefKMeansStrideSlider;
@property (nonatomic, strong) NSTextField *normalrefKMeansStrideValueLabel;
@property (nonatomic, strong) NSSlider *normalrefKMeansIterSlider;
@property (nonatomic, strong) NSTextField *normalrefKMeansIterValueLabel;

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

// New vtracer sliders (length threshold, splice angle, curve fit iterations, layer difference)
@property (nonatomic, strong) NSSlider *vtracerLengthThreshSlider;
@property (nonatomic, strong) NSTextField *vtracerLengthThreshValueLabel;
@property (nonatomic, strong) NSSlider *vtracerSpliceSlider;
@property (nonatomic, strong) NSTextField *vtracerSpliceValueLabel;
@property (nonatomic, strong) NSSlider *vtracerMaxIterSlider;
@property (nonatomic, strong) NSTextField *vtracerMaxIterValueLabel;
@property (nonatomic, strong) NSSlider *vtracerLayerDiffSlider;
@property (nonatomic, strong) NSTextField *vtracerLayerDiffValueLabel;

// Centerline preprocessing sliders (Canny, dilation, skeleton, normal strength)
@property (nonatomic, strong) NSSlider *cannyLowSlider;
@property (nonatomic, strong) NSTextField *cannyLowValueLabel;
@property (nonatomic, strong) NSSlider *cannyHighSlider;
@property (nonatomic, strong) NSTextField *cannyHighValueLabel;
@property (nonatomic, strong) NSSlider *normalStrengthSlider;
@property (nonatomic, strong) NSTextField *normalStrengthValueLabel;
@property (nonatomic, strong) NSSlider *skeletonThreshSlider;
@property (nonatomic, strong) NSTextField *skeletonThreshValueLabel;
@property (nonatomic, strong) NSSlider *dilationRadiusSlider;
@property (nonatomic, strong) NSTextField *dilationRadiusValueLabel;

// Output mode segmented control (Outline | Fill | Centerline)
@property (nonatomic, strong) NSSegmentedControl *outputModeControl;

// Subject Cutout (section 12) — Preview/Commit workflow
@property (nonatomic, strong) NSButton *cutoutPreviewButton;
@property (nonatomic, strong) NSButton *cutoutCommitButton;
@property (nonatomic, strong) NSSlider *cutoutSmoothnessSlider;
@property (nonatomic, strong) NSTextField *cutoutSmoothnessValueLabel;
@property (nonatomic, strong) NSProgressIndicator *cutoutProgressBar;
// Per-instance checkboxes (dynamically populated after detection)
@property (nonatomic, strong) NSMutableArray<NSButton *> *cutoutInstanceCheckboxes;
@property (nonatomic, strong) NSView *cutoutInstanceContainer;
@property (nonatomic, assign) int cutoutLastKnownInstanceCount;

// Apple Contours (section 13) — native Vision framework contour detection
@property (nonatomic, strong) NSSlider *appleContourContrastSlider;
@property (nonatomic, strong) NSTextField *appleContourContrastValueLabel;
@property (nonatomic, strong) NSSlider *appleContourPivotSlider;
@property (nonatomic, strong) NSTextField *appleContourPivotValueLabel;
@property (nonatomic, strong) NSButton *appleContourDarkOnLightCheckbox;

// Pose Detection (section 14) — body/face/hand pose overlay
@property (nonatomic, strong) NSButton *poseIncludeFaceCheckbox;
@property (nonatomic, strong) NSButton *poseIncludeHandsCheckbox;

// Depth Layers (section 15) — ONNX Depth Anything V2 depth decomposition
@property (nonatomic, strong) NSSlider *depthLayerCountSlider;
@property (nonatomic, strong) NSTextField *depthLayerCountValueLabel;

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
    // Halve the default tooltip delay (macOS default is ~1.5s)
    [[NSUserDefaults standardUserDefaults] setInteger:500 forKey:@"NSInitialToolTipDelay"];

    self.diffvgIterations = 100;
    self.diffvgLearningRate = 0.01;
    self.cartoonsegConfidence = 0.5;
    self.normalrefKPlanes = 6;
    self.normalrefBlur = 1.5;
    self.normalrefKMeansStride = 4;
    self.normalrefKMeansIter = 20;
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
    self.scrollView.backgroundColor = [IllToolTheme panelBackground];
    self.scrollView.borderType = NSNoBorder;

    // Content view inside the scroll view
    self.contentView = [[TraceFlippedView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, 1200)];
    self.contentView.wantsLayer = YES;
    self.contentView.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    self.scrollView.documentView = self.contentView;

    CGFloat contentW = kPanelWidth - 2*kPadding;

    // --- Panel title ---
    NSTextField *title = [IllToolTheme makeLabelWithText:@"Ill Trace" font:[IllToolTheme labelFont] color:[IllToolTheme accentColor]];
    title.frame = NSMakeRect(kPadding, kPadding, contentW, kRowHeight);
    title.font = [NSFont boldSystemFontOfSize:12];
    [self.contentView addSubview:title];

    // --- Output mode segmented control (Outline | Fill | Centerline) ---
    self.outputModeControl = [NSSegmentedControl segmentedControlWithLabels:@[@"Outline", @"Fill", @"Centerline"]
                                                              trackingMode:NSSegmentSwitchTrackingSelectOne
                                                                    target:self
                                                                    action:@selector(outputModeChanged:)];
    self.outputModeControl.selectedSegment = 1;  // default: Fill
    self.outputModeControl.frame = NSMakeRect(kPadding, kPadding + kRowHeight + 4, contentW, 22);
    self.outputModeControl.font = [NSFont systemFontOfSize:10];
    self.outputModeControl.toolTip = @"Outline: black strokes only. Fill: colored regions. Centerline: single-pixel center of drawn strokes.";
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

    // 12: Subject Cutout (macOS Vision framework)
    [self addCutoutSection];

    // 13: Apple Contours (Native Vision framework contour detection)
    [self addModelSection:@"Apple Contours (Native)" backend:@"apple_contours" tag:13
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildAppleContoursParams:container width:cw];
    }];

    // 14: Pose Detection (body/face/hand keypoints via Vision framework)
    [self addModelSection:@"Pose Detection" backend:@"detect_pose" tag:14
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildPoseParams:container width:cw];
    }];

    // 15: Depth Layers (ONNX Depth Anything V2)
    [self addModelSection:@"Depth Layers (AI)" backend:@"depth_decompose" tag:15
           paramBuilder:^(NSView *container, CGFloat cw, TracePanelController *ctrl) {
        return [ctrl buildDepthParams:container width:cw];
    }];

    // --- Status label at the bottom ---
    self.statusLabel = [IllToolTheme makeLabelWithText:@"Expand a model, adjust params, click Run" font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
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

    // Progress bar (hidden by default, shown during trace)
    sec.progressBar = [[NSProgressIndicator alloc] initWithFrame:NSZeroRect];
    sec.progressBar.style = NSProgressIndicatorStyleBar;
    sec.progressBar.indeterminate = YES;
    sec.progressBar.hidden = YES;
    [self.contentView addSubview:sec.progressBar];

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
                      value:[IllToolTheme textColor]
                      range:NSMakeRange(0, attrTitle.length)];
    [attrTitle addAttribute:NSFontAttributeName
                      value:[IllToolTheme labelFont]
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
        // Run button / progress bar (right side, same row)
        NSRect runFrame = NSMakeRect(kPadding + disclosureW + 4, y, runBtnW, 20);
        sec.runButton.frame = runFrame;
        sec.progressBar.frame = runFrame;
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
              tooltip:(NSString *)tooltip
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

    NSTextField *lbl = [IllToolTheme makeLabelWithText:labelText font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    lbl.frame = NSMakeRect(0, y, labelW, kParamRowH);
    lbl.toolTip = tooltip;
    [container addSubview:lbl];

    NSTextField *valLabel = [IllToolTheme makeLabelWithText:isFloat ? [NSString stringWithFormat:@"%.2f", defVal]
                : [NSString stringWithFormat:@"%d", (int)defVal] font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
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
    slider.toolTip = tooltip;
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
             tooltip:(NSString *)tooltip
               items:(NSArray<NSString*> *)items
        defaultIndex:(NSInteger)defIdx
           outPopup:(NSPopUpButton **)outPopup
              action:(SEL)action
{
    CGFloat popupW = 100.0;
    CGFloat labelW = w - popupW - 4;

    NSTextField *lbl = [IllToolTheme makeLabelWithText:labelText font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    lbl.frame = NSMakeRect(0, y, labelW, kParamRowH);
    lbl.toolTip = tooltip;
    [container addSubview:lbl];

    NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(w - popupW, y, popupW, kParamRowH) pullsDown:NO];
    popup.font = [NSFont systemFontOfSize:10];
    popup.toolTip = tooltip;
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
                   tooltip:@"Remove noise clusters smaller than N pixels. Higher = cleaner, fewer details."
                  minValue:1 maxValue:100 defaultValue:4 isFloatDisp:NO
                 outSlider:&_vtracerSpeckleSlider outValueLabel:&_vtracerSpeckleValueLabel
                    action:@selector(vtracerSpeckleChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Color Precision:"
                   tooltip:@"Color quantization bits. Lower = fewer colors, simpler shapes. Higher = more color fidelity."
                  minValue:1 maxValue:10 defaultValue:6 isFloatDisp:NO
                 outSlider:&_vtracerColorPrecSlider outValueLabel:&_vtracerColorPrecValueLabel
                    action:@selector(vtracerColorPrecChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Corner Threshold:"
                   tooltip:@"Angle (degrees) to detect sharp turns. Lower = more corners detected. Higher = smoother curves."
                  minValue:0 maxValue:180 defaultValue:60 isFloatDisp:NO
                 outSlider:&_vtracerCornerSlider outValueLabel:&_vtracerCornerValueLabel
                    action:@selector(vtracerCornerChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Length Threshold:"
                   tooltip:@"Minimum path length to keep. Higher = removes short fragments. Lower = keeps fine details."
                  minValue:0.5 maxValue:50.0 defaultValue:4.0 isFloatDisp:YES
                 outSlider:&_vtracerLengthThreshSlider outValueLabel:&_vtracerLengthThreshValueLabel
                    action:@selector(vtracerLengthThreshChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Splice Angle:"
                   tooltip:@"Angle (degrees) for joining adjacent paths. Higher = more aggressive joining. Lower = more separate paths."
                  minValue:0 maxValue:180 defaultValue:45 isFloatDisp:NO
                 outSlider:&_vtracerSpliceSlider outValueLabel:&_vtracerSpliceValueLabel
                    action:@selector(vtracerSpliceChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Curve Fit Iterations:"
                   tooltip:@"Curve fitting passes. Higher = smoother curves, slower. Lower = faster, more angular."
                  minValue:1 maxValue:50 defaultValue:10 isFloatDisp:NO
                 outSlider:&_vtracerMaxIterSlider outValueLabel:&_vtracerMaxIterValueLabel
                    action:@selector(vtracerMaxIterChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Layer Difference:"
                   tooltip:@"Color difference threshold for layer separation. Lower = more layers, finer detail. Higher = fewer layers, simpler."
                  minValue:1 maxValue:128 defaultValue:25 isFloatDisp:NO
                 outSlider:&_vtracerLayerDiffSlider outValueLabel:&_vtracerLayerDiffValueLabel
                    action:@selector(vtracerLayerDiffChanged:)];

    y = [self addPopupRow:container atY:y width:w label:@"Mode:"
                  tooltip:@"Spline = smooth bezier curves. Polygon = straight-line segments only."
                    items:@[@"spline", @"polygon"] defaultIndex:0
                 outPopup:&_vtracerModePopup action:@selector(vtracerModeChanged:)];

    // --- Centerline Settings separator ---
    y += 4;
    NSTextField *clLabel = [IllToolTheme makeLabelWithText:@"Centerline Settings" font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
    clLabel.frame = NSMakeRect(0, y, w, kParamRowH);
    [container addSubview:clLabel];
    y += kParamRowH + 2;

    y = [self addSliderRow:container atY:y width:w label:@"Canny Low:"
                   tooltip:@"Weak edge threshold. Lower = more edges detected, noisier. Higher = only strong edges."
                  minValue:10 maxValue:200 defaultValue:80 isFloatDisp:NO
                 outSlider:&_cannyLowSlider outValueLabel:&_cannyLowValueLabel
                    action:@selector(cannyLowChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Canny High:"
                   tooltip:@"Strong edge threshold. Sets minimum gradient for definite edges."
                  minValue:50 maxValue:400 defaultValue:200 isFloatDisp:NO
                 outSlider:&_cannyHighSlider outValueLabel:&_cannyHighValueLabel
                    action:@selector(cannyHighChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Edge Dilation:"
                   tooltip:@"Edge thickening radius before skeletonization. Higher = connects fragmented lines. Lower = preserves detail. (kernel = 2*val+1)"
                  minValue:0 maxValue:5 defaultValue:2 isFloatDisp:NO
                 outSlider:&_dilationRadiusSlider outValueLabel:&_dilationRadiusValueLabel
                    action:@selector(dilationRadiusChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Skeleton Threshold:"
                   tooltip:@"Brightness cutoff for thinning. Lower = more aggressive skeleton. Higher = preserves thicker strokes."
                  minValue:50 maxValue:200 defaultValue:128 isFloatDisp:NO
                 outSlider:&_skeletonThreshSlider outValueLabel:&_skeletonThreshValueLabel
                    action:@selector(skeletonThreshChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Normal Strength:"
                   tooltip:@"Height-to-normal conversion intensity. Higher = more pronounced surface detail. Lower = subtler normals."
                  minValue:0.5 maxValue:10.0 defaultValue:2.0 isFloatDisp:YES
                 outSlider:&_normalStrengthSlider outValueLabel:&_normalStrengthValueLabel
                    action:@selector(normalStrengthChanged:)];

    return y;
}

//--- OpenCV Contours: Threshold, Min Area ---

- (CGFloat)buildOpenCVParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Threshold:"
                   tooltip:@"Binarization cutoff (0-255). Pixels above = white, below = black. Affects edge detection."
                  minValue:0 maxValue:255 defaultValue:128 isFloatDisp:NO
                 outSlider:&_opencvThresholdSlider outValueLabel:&_opencvThresholdValueLabel
                    action:@selector(opencvThresholdChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Min Area:"
                   tooltip:@"Minimum contour area in pixels. Filters out small noise regions. Higher = fewer, larger shapes."
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
                   tooltip:@"Optimization passes. More iterations = closer match to raster, slower. Fewer = faster, rougher."
                  minValue:10 maxValue:500 defaultValue:100 isFloatDisp:NO
                 outSlider:&_diffvgIterationsSlider outValueLabel:&_diffvgIterationsValueLabel
                    action:@selector(diffvgIterationsChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Learning Rate:"
                   tooltip:@"Step size per optimization pass. Higher = faster convergence but may overshoot. Lower = stable but slower."
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
                   tooltip:@"Segmentation confidence threshold. Higher = fewer but more certain regions. Lower = more regions, may include noise."
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
                   tooltip:@"Number of normal-map planes to extract. More planes = finer surface detail. Fewer = broader forms."
                  minValue:2 maxValue:16 defaultValue:6 isFloatDisp:NO
                 outSlider:&_normalrefKPlanesSlider outValueLabel:&_normalrefKPlanesValueLabel
                    action:@selector(normalrefKPlanesChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Pre-Blur Sigma:"
                   tooltip:@"Smooth noise before computing normals. Higher = softer normals, less noise. 0 = no blur."
                  minValue:0.0 maxValue:5.0 defaultValue:1.5 isFloatDisp:YES
                 outSlider:&_normalrefBlurSlider outValueLabel:&_normalrefBlurValueLabel
                    action:@selector(normalrefBlurChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Clustering Stride:"
                   tooltip:@"Sample every Nth pixel for clustering. Lower = more accurate, slower. Higher = faster, rougher."
                  minValue:1 maxValue:10 defaultValue:4 isFloatDisp:NO
                 outSlider:&_normalrefKMeansStrideSlider outValueLabel:&_normalrefKMeansStrideValueLabel
                    action:@selector(normalrefKMeansStrideChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Clustering Iterations:"
                   tooltip:@"Convergence passes for surface clustering. Higher = better grouping, slower."
                  minValue:5 maxValue:50 defaultValue:20 isFloatDisp:NO
                 outSlider:&_normalrefKMeansIterSlider outValueLabel:&_normalrefKMeansIterValueLabel
                    action:@selector(normalrefKMeansIterChanged:)];

    return y;
}

//--- Form Edge Extract: Num Thresholds, Blur Sigma ---

- (CGFloat)buildFormEdgeParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 2;

    y = [self addSliderRow:container atY:y width:w label:@"Num Thresholds:"
                   tooltip:@"Number of luminance thresholds for edge detection. More = finer form contours. Fewer = bolder edges."
                  minValue:3 maxValue:20 defaultValue:10 isFloatDisp:NO
                 outSlider:&_formedgeNumThreshSlider outValueLabel:&_formedgeNumThreshValueLabel
                    action:@selector(formedgeNumThreshChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Blur Sigma:"
                   tooltip:@"Gaussian blur radius before edge detection. Higher = smoother, fewer noisy edges. Lower = sharper, more detail."
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
                   tooltip:@"Pixel step between scan lines. Smaller = more contours found, slower. Larger = fewer contours, faster."
                  minValue:1 maxValue:20 defaultValue:5 isFloatDisp:NO
                 outSlider:&_contourscanStepSlider outValueLabel:&_contourscanStepValueLabel
                    action:@selector(contourscanStepChanged:)];

    y = [self addSliderRow:container atY:y width:w label:@"Color Threshold:"
                   tooltip:@"Color difference to separate contour regions. Lower = more sensitive, more regions. Higher = fewer, broader regions."
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
                   tooltip:@"Path simplification tolerance. Higher = fewer anchor points, smoother. Lower = more points, closer to original."
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
                   tooltip:@"Maximum nesting depth to analyze. Higher = deeper parent-child hierarchy. Lower = flatter structure."
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
                      value:[IllToolTheme textColor]
                      range:NSMakeRange(0, attrTitle.length)];
    [attrTitle addAttribute:NSFontAttributeName
                      value:[IllToolTheme labelFont]
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

    // Swap Run button → progress bar
    sec.runButton.hidden = YES;
    sec.progressBar.hidden = NO;
    [sec.progressBar startAnimation:nil];

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

- (void)vtracerLengthThreshChanged:(id)sender
{
    double val = self.vtracerLengthThreshSlider.doubleValue;
    BridgeSetTraceLengthThresh(val);
    self.vtracerLengthThreshValueLabel.stringValue = [NSString stringWithFormat:@"%.1f", val];
}

- (void)vtracerSpliceChanged:(id)sender
{
    int val = (int)self.vtracerSpliceSlider.intValue;
    BridgeSetTraceSpliceThresh(val);
    self.vtracerSpliceValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerMaxIterChanged:(id)sender
{
    int val = (int)self.vtracerMaxIterSlider.intValue;
    BridgeSetTraceMaxIter(val);
    self.vtracerMaxIterValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerLayerDiffChanged:(id)sender
{
    int val = (int)self.vtracerLayerDiffSlider.intValue;
    BridgeSetTraceLayerDiff(val);
    self.vtracerLayerDiffValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)vtracerModeChanged:(id)sender
{
    self.vtracerMode = (int)self.vtracerModePopup.indexOfSelectedItem;
}

//========================================================================================
//  Slider actions — Centerline preprocessing
//========================================================================================

- (void)cannyLowChanged:(id)sender
{
    int val = (int)self.cannyLowSlider.intValue;
    BridgeSetTraceCannyLow((double)val);
    self.cannyLowValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)cannyHighChanged:(id)sender
{
    int val = (int)self.cannyHighSlider.intValue;
    BridgeSetTraceCannyHigh((double)val);
    self.cannyHighValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)dilationRadiusChanged:(id)sender
{
    int val = (int)self.dilationRadiusSlider.intValue;
    BridgeSetTraceDilationRadius(val);
    self.dilationRadiusValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)skeletonThreshChanged:(id)sender
{
    int val = (int)self.skeletonThreshSlider.intValue;
    BridgeSetTraceSkeletonThresh(val);
    self.skeletonThreshValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)normalStrengthChanged:(id)sender
{
    double val = self.normalStrengthSlider.doubleValue;
    BridgeSetTraceNormalStrength(val);
    self.normalStrengthValueLabel.stringValue = [NSString stringWithFormat:@"%.1f", val];
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
    BridgeSetTraceKPlanes(val);
    self.normalrefKPlanesValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)normalrefBlurChanged:(id)sender
{
    double val = self.normalrefBlurSlider.doubleValue;
    self.normalrefBlur = val;
    BridgeSetTraceNormalBlur(val);
    self.normalrefBlurValueLabel.stringValue = [NSString stringWithFormat:@"%.2f", val];
}

- (void)normalrefKMeansStrideChanged:(id)sender
{
    int val = (int)self.normalrefKMeansStrideSlider.intValue;
    self.normalrefKMeansStride = val;
    BridgeSetTraceKMeansStride(val);
    self.normalrefKMeansStrideValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)normalrefKMeansIterChanged:(id)sender
{
    int val = (int)self.normalrefKMeansIterSlider.intValue;
    self.normalrefKMeansIter = val;
    BridgeSetTraceKMeansIter(val);
    self.normalrefKMeansIterValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
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
    BridgeSetTraceOutputMode((int)selected);  // 0=outline, 1=fill, 2=centerline
    const char* names[] = {"outline", "fill", "centerline"};
    fprintf(stderr, "[TracePanel] Output mode: %s\n", (selected >= 0 && selected <= 2) ? names[selected] : "unknown");
}

//----------------------------------------------------------------------------------------
//  Status polling
//----------------------------------------------------------------------------------------

- (void)updateStatus
{
    // Deferred hardware gating — VIInitialize runs after panel creation
    if (!self.hardwareGatingApplied) {
        // Check if capabilities have been set yet (nonzero backend = initialized)
        if (BridgeGetHasContourDetection() || BridgeGetHasNeuralEngine()) {
            self.hardwareGatingApplied = YES;

            if (!BridgeGetHasInstanceSegmentation()) {
                self.cutoutPreviewButton.enabled = NO;
                self.cutoutPreviewButton.toolTip =
                    @"Requires Apple Silicon Mac (M1 or later) for subject segmentation";
                self.cutoutCommitButton.enabled = NO;
                self.cutoutCommitButton.toolTip =
                    @"Requires Apple Silicon Mac (M1 or later) for subject segmentation";
                self.cutoutSmoothnessSlider.enabled = NO;
                fprintf(stderr, "[TracePanel] Hardware gating: instance segmentation DISABLED\n");
            } else {
                fprintf(stderr, "[TracePanel] Hardware gating: all features ENABLED\n");
            }
        }
    }

    std::string status = BridgeGetTraceStatus();
    if (!status.empty()) {
        self.statusLabel.stringValue = [NSString stringWithUTF8String:status.c_str()];

        // Check if trace completed — status contains "Traced:" or "failed" or "error"
        // Restore Run buttons from progress bars
        bool done = (status.find("Traced:") != std::string::npos ||
                     status.find("failed") != std::string::npos ||
                     status.find("error") != std::string::npos ||
                     status.find("references") != std::string::npos ||
                     status.find("No image") != std::string::npos ||
                     status.find("preview:") != std::string::npos ||
                     status.find("committed:") != std::string::npos ||
                     status.find("Cutout complete") != std::string::npos ||
                     status.find("Cutout committed") != std::string::npos ||
                     status.find("Apple Contours:") != std::string::npos ||
                     status.find("No contours") != std::string::npos ||
                     status.find("Depth decomposition") != std::string::npos ||
                     status.find("Depth estimation failed") != std::string::npos);
        if (done) {
            for (TraceModelSection *sec in self.sections) {
                if (sec.runButton.hidden) {
                    [sec.progressBar stopAnimation:nil];
                    sec.progressBar.hidden = YES;
                    sec.runButton.hidden = NO;
                }
            }

            // Update cutout-specific UI
            [self.cutoutProgressBar stopAnimation:nil];
            self.cutoutProgressBar.hidden = YES;

            if (BridgeGetCutoutPreviewActive()) {
                self.cutoutPreviewButton.title = @"Clear";
                self.cutoutCommitButton.enabled = YES;
            } else {
                self.cutoutPreviewButton.title = @"Preview";
                self.cutoutCommitButton.enabled = NO;
            }

            // Rebuild instance checkboxes if count changed
            int instanceCount = BridgeGetCutoutInstanceCount();
            if (instanceCount != self.cutoutLastKnownInstanceCount) {
                [self rebuildCutoutInstanceCheckboxes:instanceCount];
                self.cutoutLastKnownInstanceCount = instanceCount;
            }
        }
    }
}

//========================================================================================
//  Subject Cutout — custom section with Preview toggle + Commit + Smoothness slider
//========================================================================================

- (void)addCutoutSection
{
    CGFloat contentW = kPanelWidth - 2*kPadding;

    TraceModelSection *sec = [[TraceModelSection alloc] init];
    sec.backendName = @"cutout";
    sec.expanded = NO;

    // Disclosure button
    sec.disclosureButton = [self makeDisclosureButton:@"Subject Cutout" tag:12 expanded:NO];
    [self.contentView addSubview:sec.disclosureButton];

    // Run button — hidden for cutout (Preview/Commit used instead)
    sec.runButton = [NSButton buttonWithTitle:@"Run" target:self action:@selector(runModelClicked:)];
    sec.runButton.font = [NSFont systemFontOfSize:10];
    sec.runButton.bezelStyle = NSBezelStyleSmallSquare;
    sec.runButton.tag = 12;
    sec.runButton.hidden = YES;
    [self.contentView addSubview:sec.runButton];

    // Progress bar (section-level, also hidden for cutout)
    sec.progressBar = [[NSProgressIndicator alloc] initWithFrame:NSZeroRect];
    sec.progressBar.style = NSProgressIndicatorStyleBar;
    sec.progressBar.indeterminate = YES;
    sec.progressBar.hidden = YES;
    [self.contentView addSubview:sec.progressBar];

    // Parameter container
    sec.paramContainer = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
    [self.contentView addSubview:sec.paramContainer];

    // Build cutout-specific controls
    CGFloat cw = contentW - 16;  // indent to match other sections
    CGFloat y = 0;

    // Row 1: Preview + Commit buttons side by side
    CGFloat btnW = (cw - 6) / 2.0;

    self.cutoutPreviewButton = [NSButton buttonWithTitle:@"Preview"
                                                 target:self
                                                 action:@selector(cutoutPreviewClicked:)];
    self.cutoutPreviewButton.font = [NSFont systemFontOfSize:10];
    self.cutoutPreviewButton.bezelStyle = NSBezelStyleSmallSquare;
    self.cutoutPreviewButton.frame = NSMakeRect(0, y, btnW, 22);
    self.cutoutPreviewButton.toolTip =
        @"Run Vision framework subject segmentation and show silhouette preview overlay";
    [sec.paramContainer addSubview:self.cutoutPreviewButton];

    self.cutoutCommitButton = [NSButton buttonWithTitle:@"Commit"
                                                target:self
                                                action:@selector(cutoutCommitClicked:)];
    self.cutoutCommitButton.font = [NSFont systemFontOfSize:10];
    self.cutoutCommitButton.bezelStyle = NSBezelStyleSmallSquare;
    self.cutoutCommitButton.frame = NSMakeRect(btnW + 6, y, btnW, 22);
    self.cutoutCommitButton.enabled = NO;
    self.cutoutCommitButton.toolTip = @"Create actual paths from preview on the Cut Lines layer";
    [sec.paramContainer addSubview:self.cutoutCommitButton];

    y += 26;

    // Progress bar for cutout (inline, below buttons)
    self.cutoutProgressBar = [[NSProgressIndicator alloc]
        initWithFrame:NSMakeRect(0, y, cw, 12)];
    self.cutoutProgressBar.style = NSProgressIndicatorStyleBar;
    self.cutoutProgressBar.indeterminate = YES;
    self.cutoutProgressBar.hidden = YES;
    [sec.paramContainer addSubview:self.cutoutProgressBar];
    y += 16;

    // Row 2: Smoothness label + value
    NSTextField *smoothLabel = [IllToolTheme makeLabelWithText:@"Smoothness"
                                                         font:[IllToolTheme labelFont]
                                                        color:[IllToolTheme secondaryTextColor]];
    smoothLabel.frame = NSMakeRect(0, y, cw * 0.5, kParamRowH);
    [sec.paramContainer addSubview:smoothLabel];

    self.cutoutSmoothnessValueLabel = [IllToolTheme makeLabelWithText:@"50"
                                                                font:[IllToolTheme labelFont]
                                                               color:[IllToolTheme textColor]];
    self.cutoutSmoothnessValueLabel.frame = NSMakeRect(cw - 30, y, 30, kParamRowH);
    self.cutoutSmoothnessValueLabel.alignment = NSTextAlignmentRight;
    [sec.paramContainer addSubview:self.cutoutSmoothnessValueLabel];
    y += kParamRowH;

    // Row 3: Smoothness slider (1-100, controls vtracer filter_speckle)
    self.cutoutSmoothnessSlider = [[NSSlider alloc]
        initWithFrame:NSMakeRect(0, y, cw, kSliderH)];
    self.cutoutSmoothnessSlider.minValue = 1;
    self.cutoutSmoothnessSlider.maxValue = 100;
    self.cutoutSmoothnessSlider.intValue = 50;
    self.cutoutSmoothnessSlider.target = self;
    self.cutoutSmoothnessSlider.action = @selector(cutoutSmoothnessChanged:);
    self.cutoutSmoothnessSlider.continuous = YES;
    self.cutoutSmoothnessSlider.toolTip =
        @"Higher = smoother silhouette (filters small speckles). "
        @"Lower = preserves fine detail in the outline.";
    [sec.paramContainer addSubview:self.cutoutSmoothnessSlider];
    y += kSliderH + kParamGap;

    // Row 4: Click Threshold label + value
    NSTextField *threshLabel = [IllToolTheme makeLabelWithText:@"Click Threshold"
                                                         font:[IllToolTheme labelFont]
                                                        color:[IllToolTheme secondaryTextColor]];
    threshLabel.frame = NSMakeRect(0, y, cw * 0.6, kParamRowH);
    threshLabel.toolTip = @"Shift+click=add, Option+click=subtract.\n"
                          @"Controls how much the flood fill expands.\n"
                          @"Lower = tight selection. Higher = more area.";
    [sec.paramContainer addSubview:threshLabel];

    NSTextField *threshVal = [IllToolTheme makeLabelWithText:@"30"
                                                       font:[IllToolTheme labelFont]
                                                      color:[IllToolTheme textColor]];
    threshVal.frame = NSMakeRect(cw - 30, y, 30, kParamRowH);
    threshVal.alignment = NSTextAlignmentRight;
    threshVal.tag = 9020;  // for updating
    [sec.paramContainer addSubview:threshVal];
    y += kParamRowH;

    // Row 5: Click Threshold slider
    NSSlider *threshSlider = [[NSSlider alloc] initWithFrame:NSMakeRect(0, y, cw, kSliderH)];
    threshSlider.minValue = 5;
    threshSlider.maxValue = 100;
    threshSlider.intValue = 30;
    threshSlider.target = self;
    threshSlider.action = @selector(cutoutThresholdChanged:);
    threshSlider.continuous = YES;
    threshSlider.toolTip = @"Shift+click=add area, Option+click=subtract.\n"
                           @"Low = tight around clicked color.\n"
                           @"High = expands to include more similar colors.";
    threshSlider.tag = 9021;
    [sec.paramContainer addSubview:threshSlider];
    y += kSliderH + kParamGap;

    // Instance checkboxes container (dynamically populated after detection)
    self.cutoutInstanceContainer = [[TraceFlippedView alloc] initWithFrame:NSMakeRect(0, y, cw, 0)];
    [sec.paramContainer addSubview:self.cutoutInstanceContainer];
    self.cutoutInstanceCheckboxes = [[NSMutableArray alloc] init];
    self.cutoutLastKnownInstanceCount = 0;
    // No y advance yet — container starts at height 0

    // Usage instructions
    NSTextField *descLabel = [IllToolTheme makeLabelWithText:
        @"⇧+click = add area  ⌥+click = subtract\n"
        @"Adjust threshold to control fill spread"
                                                       font:[NSFont systemFontOfSize:9]
                                                      color:[IllToolTheme secondaryTextColor]];
    descLabel.maximumNumberOfLines = 2;
    descLabel.frame = NSMakeRect(0, y, cw, kParamRowH);
    descLabel.tag = 9012;  // tag for relayout when instances change
    [sec.paramContainer addSubview:descLabel];
    y += kParamRowH;

    sec.paramHeight = y;
    sec.paramContainer.hidden = YES;  // collapsed by default

    // NOTE: Hardware gating is deferred to the poll timer (first tick)
    // because VIInitialize runs in PostStartupPlugin AFTER panels are created.
    // See updateHardwareGating below.

    [self.sections addObject:sec];
}

//----------------------------------------------------------------------------------------
//  Cutout button actions
//----------------------------------------------------------------------------------------

- (void)cutoutPreviewClicked:(NSButton *)sender
{
    bool isActive = BridgeGetCutoutPreviewActive();

    if (isActive) {
        // Toggle OFF — clear the preview overlay and instance state
        BridgeSetCutoutPreviewActive(false);
        BridgeSetCutoutPreviewPaths("");
        BridgeSetCutoutInstanceCount(0);
        self.cutoutPreviewButton.title = @"Preview";
        self.cutoutCommitButton.enabled = NO;
        BridgeSetTraceStatus("Cutout preview cleared");
        fprintf(stderr, "[TracePanel] Cutout preview toggled OFF\n");
        return;
    }

    // Toggle ON — run Vision subject segmentation + vtracer
    self.cutoutPreviewButton.title = @"Clear";
    self.cutoutProgressBar.hidden = NO;
    [self.cutoutProgressBar startAnimation:nil];

    BridgeRequestTrace("cutout");

    self.statusLabel.stringValue = @"Extracting subject...";
    fprintf(stderr, "[TracePanel] Cutout preview requested\n");
}

- (void)cutoutCommitClicked:(NSButton *)sender
{
    if (!BridgeGetCutoutPreviewActive()) {
        self.statusLabel.stringValue = @"No preview to commit — click Preview first";
        return;
    }

    BridgeRequestTrace("cutout_commit");

    self.cutoutPreviewButton.title = @"Preview";
    self.cutoutCommitButton.enabled = NO;
    self.statusLabel.stringValue = @"Creating cut paths...";
    fprintf(stderr, "[TracePanel] Cutout commit requested\n");
}

- (void)cutoutSmoothnessChanged:(id)sender
{
    int val = (int)self.cutoutSmoothnessSlider.intValue;
    BridgeSetCutoutSmoothness(val);
    self.cutoutSmoothnessValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
}

- (void)cutoutThresholdChanged:(id)sender
{
    NSSlider *slider = (NSSlider *)sender;
    int val = (int)slider.intValue;
    BridgeSetCutoutClickThreshold(val);
    // Update value label (tag 9020)
    NSView *paramContainer = slider.superview;
    for (NSView *sub in paramContainer.subviews) {
        if (sub.tag == 9020 && [sub isKindOfClass:[NSTextField class]]) {
            ((NSTextField *)sub).stringValue = [NSString stringWithFormat:@"%d", val];
            break;
        }
    }
}

//----------------------------------------------------------------------------------------
//  Instance checkbox management — dynamically created after detection
//----------------------------------------------------------------------------------------

- (void)rebuildCutoutInstanceCheckboxes:(int)count
{
    // Remove all existing subviews from the instance container
    for (NSView *v in [self.cutoutInstanceContainer.subviews copy]) {
        [v removeFromSuperview];
    }
    [self.cutoutInstanceCheckboxes removeAllObjects];

    if (count <= 0) {
        // Collapse the instance container
        self.cutoutInstanceContainer.frame = NSMakeRect(
            self.cutoutInstanceContainer.frame.origin.x,
            self.cutoutInstanceContainer.frame.origin.y,
            self.cutoutInstanceContainer.frame.size.width, 0);
        [self relayoutCutoutSection];
        return;
    }

    CGFloat cw = self.cutoutInstanceContainer.frame.size.width;
    CGFloat y = 0;

    // Section label
    NSTextField *instanceLabel = [IllToolTheme makeLabelWithText:
        [NSString stringWithFormat:@"Instances (%d)", count]
                                                           font:[IllToolTheme labelFont]
                                                          color:[IllToolTheme secondaryTextColor]];
    instanceLabel.frame = NSMakeRect(0, y, cw, 14);
    instanceLabel.tag = 9013;  // tag for identification
    [self.cutoutInstanceContainer addSubview:instanceLabel];
    y += 16;

    // Create a checkbox for each instance
    for (int i = 0; i < count && i < 16; i++) {
        NSButton *cb = [NSButton checkboxWithTitle:
            [NSString stringWithFormat:@"Instance %d", i + 1]
                                            target:self
                                            action:@selector(cutoutInstanceToggled:)];
        cb.font = [NSFont systemFontOfSize:10];
        cb.tag = i;
        cb.state = BridgeGetCutoutInstanceSelected(i) ? NSControlStateValueOn : NSControlStateValueOff;
        cb.frame = NSMakeRect(0, y, cw, 18);
        [self.cutoutInstanceContainer addSubview:cb];
        [self.cutoutInstanceCheckboxes addObject:cb];
        y += 20;
    }

    // Resize the container
    self.cutoutInstanceContainer.frame = NSMakeRect(
        self.cutoutInstanceContainer.frame.origin.x,
        self.cutoutInstanceContainer.frame.origin.y,
        cw, y);

    [self relayoutCutoutSection];
    fprintf(stderr, "[TracePanel] Rebuilt %d instance checkboxes\n", count);
}

- (void)cutoutInstanceToggled:(NSButton *)sender
{
    int index = (int)sender.tag;
    bool selected = (sender.state == NSControlStateValueOn);
    BridgeSetCutoutInstanceSelected(index, selected);

    fprintf(stderr, "[TracePanel] Instance %d toggled %s\n", index, selected ? "ON" : "OFF");

    // Trigger recomposite + re-trace
    if (BridgeGetCutoutPreviewActive()) {
        self.cutoutProgressBar.hidden = NO;
        [self.cutoutProgressBar startAnimation:nil];
        self.statusLabel.stringValue = @"Recompositing instances...";
        BridgeRequestTrace("cutout_recomposite");
    }
}

- (void)relayoutCutoutSection
{
    // Find the cutout section (index 12 in sections array)
    // Recalculate paramHeight based on current instance container size
    if (self.sections.count <= 12) return;

    TraceModelSection *sec = self.sections[12];
    if (![sec.backendName isEqualToString:@"cutout"]) return;

    CGFloat cw = kPanelWidth - 2*kPadding - 16;

    // Walk through param container subviews to find the desc label (tag 9012)
    // and reposition it below the instance container
    CGFloat containerBottom = self.cutoutInstanceContainer.frame.origin.y +
                              self.cutoutInstanceContainer.frame.size.height;

    for (NSView *subview in sec.paramContainer.subviews) {
        if (subview.tag == 9012) {
            NSRect f = subview.frame;
            f.origin.y = containerBottom;
            subview.frame = f;
            break;
        }
    }

    // Update section height
    sec.paramHeight = containerBottom + kParamRowH;

    // Trigger full panel relayout
    [self relayoutContent];
}

//========================================================================================
//  Apple Contours (Section 13) — native Vision framework contour detection
//========================================================================================

- (CGFloat)buildAppleContoursParams:(NSView *)container width:(CGFloat)w
{
    CGFloat y = 0;

    // Contrast slider (0.0-3.0, default 1.5)
    y = [self addSliderRow:container atY:y width:w
                     label:@"Contrast"
                   tooltip:@"Edge contrast amplification. Higher = stronger edges detected."
                  minValue:0.0 maxValue:3.0 defaultValue:1.5
               isFloatDisp:YES
                outSlider:&_appleContourContrastSlider
             outValueLabel:&_appleContourContrastValueLabel
                    action:@selector(appleContourContrastChanged:)];

    // Pivot slider (0.0-1.0, default 0.5)
    y = [self addSliderRow:container atY:y width:w
                     label:@"Pivot"
                   tooltip:@"Contrast pivot point. Adjusts which brightness level is the edge boundary."
                  minValue:0.0 maxValue:1.0 defaultValue:0.5
               isFloatDisp:YES
                outSlider:&_appleContourPivotSlider
             outValueLabel:&_appleContourPivotValueLabel
                    action:@selector(appleContourPivotChanged:)];

    // Dark on Light checkbox (default YES)
    self.appleContourDarkOnLightCheckbox = [NSButton checkboxWithTitle:@"Dark on Light"
                                                               target:self
                                                               action:@selector(appleContourDarkOnLightChanged:)];
    self.appleContourDarkOnLightCheckbox.frame = NSMakeRect(0, y, w, kParamRowH);
    self.appleContourDarkOnLightCheckbox.state = NSControlStateValueOn;
    self.appleContourDarkOnLightCheckbox.font = [IllToolTheme labelFont];
    self.appleContourDarkOnLightCheckbox.toolTip =
        @"Check for dark lines on light background. Uncheck for light lines on dark.";

    // Style the checkbox text to match the panel theme
    NSMutableAttributedString *cbTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Dark on Light"];
    [cbTitle addAttribute:NSForegroundColorAttributeName
                    value:[IllToolTheme textColor]
                    range:NSMakeRange(0, cbTitle.length)];
    [cbTitle addAttribute:NSFontAttributeName
                    value:[IllToolTheme labelFont]
                    range:NSMakeRange(0, cbTitle.length)];
    self.appleContourDarkOnLightCheckbox.attributedTitle = cbTitle;
    [cbTitle release];

    [container addSubview:self.appleContourDarkOnLightCheckbox];
    y += kParamRowH + kParamGap;

    // Description
    NSTextField *descLabel = [IllToolTheme makeLabelWithText:
        @"macOS 11+: Vision framework edge contour detection"
                                                       font:[NSFont systemFontOfSize:9]
                                                      color:[IllToolTheme secondaryTextColor]];
    descLabel.frame = NSMakeRect(0, y, w, kParamRowH);
    [container addSubview:descLabel];
    y += kParamRowH;

    return y;
}

- (void)appleContourContrastChanged:(id)sender
{
    double val = self.appleContourContrastSlider.doubleValue;
    BridgeSetTraceContourContrast(val);
    self.appleContourContrastValueLabel.stringValue = [NSString stringWithFormat:@"%.2f", val];
}

- (void)appleContourPivotChanged:(id)sender
{
    double val = self.appleContourPivotSlider.doubleValue;
    BridgeSetTraceContourPivot(val);
    self.appleContourPivotValueLabel.stringValue = [NSString stringWithFormat:@"%.2f", val];
}

- (void)appleContourDarkOnLightChanged:(id)sender
{
    bool val = (self.appleContourDarkOnLightCheckbox.state == NSControlStateValueOn);
    BridgeSetTraceContourDarkOnLight(val);
    fprintf(stderr, "[TracePanel] Apple Contours: darkOnLight=%s\n", val ? "true" : "false");
}

//========================================================================================
//  Pose Detection section parameters
//========================================================================================

- (CGFloat)buildPoseParams:(NSView *)container width:(CGFloat)cw
{
    CGFloat y = 0;

    // Checkbox: Include Face Landmarks
    self.poseIncludeFaceCheckbox = [NSButton checkboxWithTitle:@"Include Face Landmarks"
                                                        target:self
                                                        action:@selector(poseIncludeFaceChanged:)];
    self.poseIncludeFaceCheckbox.font = [NSFont systemFontOfSize:10];
    self.poseIncludeFaceCheckbox.frame = NSMakeRect(0, y, cw, 18);
    self.poseIncludeFaceCheckbox.state = NSControlStateValueOn;  // default: included
    self.poseIncludeFaceCheckbox.toolTip =
        @"Detect face landmark points (76 points: eyes, nose, mouth, jawline, eyebrows)";
    [container addSubview:self.poseIncludeFaceCheckbox];
    y += 22;

    // Checkbox: Include Hand Pose
    self.poseIncludeHandsCheckbox = [NSButton checkboxWithTitle:@"Include Hand Pose"
                                                         target:self
                                                         action:@selector(poseIncludeHandsChanged:)];
    self.poseIncludeHandsCheckbox.font = [NSFont systemFontOfSize:10];
    self.poseIncludeHandsCheckbox.frame = NSMakeRect(0, y, cw, 18);
    self.poseIncludeHandsCheckbox.state = NSControlStateValueOff;  // default: not included
    self.poseIncludeHandsCheckbox.toolTip =
        @"Detect hand joint positions (21 points per hand, up to 2 hands). Requires macOS 12+.";
    // Gate: Hand pose detection requires macOS 12+
    if (@available(macOS 12.0, *)) {
        // Hand pose available on this macOS version
    } else {
        self.poseIncludeHandsCheckbox.enabled = NO;
        self.poseIncludeHandsCheckbox.toolTip = @"Requires macOS 12 or later";
    }
    [container addSubview:self.poseIncludeHandsCheckbox];
    y += 22;

    // Description label
    NSTextField *descLabel = [IllToolTheme makeLabelWithText:
        @"macOS 11+: body skeleton, face, hand keypoints"
                                                       font:[NSFont systemFontOfSize:9]
                                                      color:[IllToolTheme secondaryTextColor]];
    descLabel.frame = NSMakeRect(0, y, cw, kParamRowH);
    [container addSubview:descLabel];
    y += kParamRowH;

    return y;
}

- (void)poseIncludeFaceChanged:(id)sender
{
    bool val = (self.poseIncludeFaceCheckbox.state == NSControlStateValueOn);
    BridgeSetPoseIncludeFace(val);
    fprintf(stderr, "[TracePanel] Pose: includeFace=%s\n", val ? "true" : "false");
}

- (void)poseIncludeHandsChanged:(id)sender
{
    bool val = (self.poseIncludeHandsCheckbox.state == NSControlStateValueOn);
    BridgeSetPoseIncludeHands(val);
    fprintf(stderr, "[TracePanel] Pose: includeHands=%s\n", val ? "true" : "false");
}

//========================================================================================
//  Section 15: Depth Layers (ONNX Depth Anything V2) — buildDepthParams
//========================================================================================

- (CGFloat)buildDepthParams:(NSView *)container width:(CGFloat)cw
{
    CGFloat y = 0;

    // Layer Count label
    NSTextField *layerCountLabel = [IllToolTheme makeLabelWithText:@"Layer Count"
                                                             font:[NSFont systemFontOfSize:10]
                                                            color:[IllToolTheme textColor]];
    layerCountLabel.frame = NSMakeRect(0, y, cw * 0.45, kParamRowH);
    [container addSubview:layerCountLabel];

    // Layer Count value label
    self.depthLayerCountValueLabel = [IllToolTheme makeLabelWithText:@"4"
                                                               font:[NSFont monospacedDigitSystemFontOfSize:10 weight:NSFontWeightRegular]
                                                              color:[IllToolTheme textColor]];
    self.depthLayerCountValueLabel.frame = NSMakeRect(cw - 30, y, 30, kParamRowH);
    self.depthLayerCountValueLabel.alignment = NSTextAlignmentRight;
    [container addSubview:self.depthLayerCountValueLabel];
    y += kParamRowH;

    // Layer Count slider (2-8, default 4)
    self.depthLayerCountSlider = [[NSSlider alloc] initWithFrame:NSMakeRect(0, y, cw, kSliderH)];
    self.depthLayerCountSlider.minValue = 2;
    self.depthLayerCountSlider.maxValue = 8;
    self.depthLayerCountSlider.doubleValue = 4;
    self.depthLayerCountSlider.numberOfTickMarks = 7;  // 2,3,4,5,6,7,8
    self.depthLayerCountSlider.allowsTickMarkValuesOnly = YES;
    self.depthLayerCountSlider.target = self;
    self.depthLayerCountSlider.action = @selector(depthLayerCountChanged:);
    self.depthLayerCountSlider.toolTip = @"Number of depth bands. More = finer separation.";
    [container addSubview:self.depthLayerCountSlider];
    y += kSliderH + kParamGap;

    // Description label
    NSTextField *descLabel = [IllToolTheme makeLabelWithText:
        @"Separates image into depth layers using Depth Anything V2 AI"
                                                       font:[NSFont systemFontOfSize:9]
                                                      color:[IllToolTheme secondaryTextColor]];
    descLabel.frame = NSMakeRect(0, y, cw, kParamRowH * 2);
    descLabel.maximumNumberOfLines = 2;
    [container addSubview:descLabel];
    y += kParamRowH * 2;

    // Gate: disable if ONNX depth model not loaded
    if (!BridgeGetHasDepthEstimation()) {
        self.depthLayerCountSlider.enabled = NO;
        descLabel.stringValue = @"ONNX depth model not found. Place depth_anything_v2_small_int8.onnx in plugin/models/";
    }

    return y;
}

- (void)depthLayerCountChanged:(id)sender
{
    int val = (int)self.depthLayerCountSlider.integerValue;
    BridgeSetDepthLayerCount(val);
    self.depthLayerCountValueLabel.stringValue = [NSString stringWithFormat:@"%d", val];
    fprintf(stderr, "[TracePanel] Depth layer count: %d\n", val);
}

@end
