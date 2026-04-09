//========================================================================================
//
//  IllTool — Ill Trace Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for tracing raster images via multiple MCP backends.
//  Organized into collapsible accordion sections by category.
//  Scrollable — content can exceed panel height.
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

static NSButton* MakeTraceCheckbox(NSString *title, id target, SEL action, BOOL checked)
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
//  Accordion section: disclosure button + container view holding checkboxes
//========================================================================================

@interface TraceAccordionSection : NSObject
@property (nonatomic, strong) NSButton   *disclosureButton;
@property (nonatomic, strong) NSView     *container;
@property (nonatomic, assign) BOOL        expanded;
@property (nonatomic, assign) CGFloat     containerHeight;
@end

@implementation TraceAccordionSection
@end

//========================================================================================
//  TracePanelController
//========================================================================================

@interface TracePanelController ()

@property (nonatomic, strong) NSScrollView *scrollView;
@property (nonatomic, strong) TraceFlippedView *contentView;

// Accordion sections (4 groups)
@property (nonatomic, strong) NSMutableArray<TraceAccordionSection*> *sections;

// Backend checkboxes (12 backends — no image_trace)
@property (nonatomic, strong) NSButton *cbVtracer;
@property (nonatomic, strong) NSButton *cbOpenCV;
@property (nonatomic, strong) NSButton *cbStarVector;
@property (nonatomic, strong) NSButton *cbDiffVG;
@property (nonatomic, strong) NSButton *cbCartoonSeg;
@property (nonatomic, strong) NSButton *cbNormalRef;
@property (nonatomic, strong) NSButton *cbFormEdge;
@property (nonatomic, strong) NSButton *cbAnalyzeRef;
@property (nonatomic, strong) NSButton *cbContourScan;
@property (nonatomic, strong) NSButton *cbContourPath;
@property (nonatomic, strong) NSButton *cbContourLabel;
@property (nonatomic, strong) NSButton *cbContourNest;

// Parameter controls
@property (nonatomic, strong) NSSlider *speckleSlider;
@property (nonatomic, strong) NSTextField *speckleLabel;
@property (nonatomic, strong) NSSlider *colorPrecSlider;
@property (nonatomic, strong) NSTextField *colorPrecLabel;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSButton *traceButton;
@property (nonatomic, strong) NSTimer *statusTimer;

// Views that come after the accordion (need repositioning on toggle)
@property (nonatomic, strong) NSBox *paramSeparator;
@property (nonatomic, strong) NSTextField *paramTitle;
@property (nonatomic, strong) NSTextField *speckleTitleLabel;
@property (nonatomic, strong) NSTextField *colorPrecTitleLabel;
@property (nonatomic, strong) NSBox *buttonSeparator;

@end

@implementation TracePanelController

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    self.sections = [NSMutableArray array];

    // Create the scroll view wrapper
    self.scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, 660)];
    self.scrollView.hasVerticalScroller = YES;
    self.scrollView.hasHorizontalScroller = NO;
    self.scrollView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.scrollView.drawsBackground = YES;
    self.scrollView.backgroundColor = ITBGColor();
    self.scrollView.borderType = NSNoBorder;

    // Content view inside the scroll view
    self.contentView = [[TraceFlippedView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, 800)];
    self.contentView.wantsLayer = YES;
    self.contentView.layer.backgroundColor = ITBGColor().CGColor;
    self.scrollView.documentView = self.contentView;

    CGFloat contentW = kPanelWidth - 2*kPadding;

    // Build controls into contentView — initial positions will be set by relayout
    CGFloat y = kPadding;

    // --- Panel title ---
    NSTextField *title = MakeLabel(@"Ill Trace", ITLabelFont(), ITAccentColor());
    title.frame = NSMakeRect(kPadding, y, contentW, kRowHeight);
    title.font = [NSFont boldSystemFontOfSize:12];
    [self.contentView addSubview:title];
    y += kRowHeight + 6;

    // ==========================================
    //  Section 1: Vector Tracing
    // ==========================================
    {
        TraceAccordionSection *sec = [[TraceAccordionSection alloc] init];
        sec.expanded = YES;

        sec.disclosureButton = [self makeDisclosureButton:@"Vector Tracing" tag:0];
        [self.contentView addSubview:sec.disclosureButton];

        sec.container = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
        [self.contentView addSubview:sec.container];

        CGFloat cy = 0;
        self.cbVtracer = MakeTraceCheckbox(@"vtracer (clean SVG)", self, @selector(backendToggled:), YES);
        self.cbVtracer.tag = 0;
        self.cbVtracer.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbVtracer];
        cy += 20;

        self.cbOpenCV = MakeTraceCheckbox(@"OpenCV Contours", self, @selector(backendToggled:), NO);
        self.cbOpenCV.tag = 1;
        self.cbOpenCV.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbOpenCV];
        cy += 20;

        self.cbStarVector = MakeTraceCheckbox(@"StarVector (ML)", self, @selector(backendToggled:), NO);
        self.cbStarVector.tag = 2;
        self.cbStarVector.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbStarVector];
        cy += 20;

        self.cbDiffVG = MakeTraceCheckbox(@"DiffVG Correction", self, @selector(backendToggled:), NO);
        self.cbDiffVG.tag = 3;
        self.cbDiffVG.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbDiffVG];
        cy += 20;

        sec.containerHeight = cy;
        [self.sections addObject:sec];
    }

    // ==========================================
    //  Section 2: Segmentation
    // ==========================================
    {
        TraceAccordionSection *sec = [[TraceAccordionSection alloc] init];
        sec.expanded = NO;

        sec.disclosureButton = [self makeDisclosureButton:@"Segmentation" tag:1];
        [self.contentView addSubview:sec.disclosureButton];

        sec.container = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
        [self.contentView addSubview:sec.container];

        CGFloat cy = 0;
        self.cbCartoonSeg = MakeTraceCheckbox(@"CartoonSeg (parts)", self, @selector(backendToggled:), NO);
        self.cbCartoonSeg.tag = 4;
        self.cbCartoonSeg.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbCartoonSeg];
        cy += 20;

        sec.containerHeight = cy;
        [self.sections addObject:sec];
    }

    // ==========================================
    //  Section 3: Normal Analysis
    // ==========================================
    {
        TraceAccordionSection *sec = [[TraceAccordionSection alloc] init];
        sec.expanded = NO;

        sec.disclosureButton = [self makeDisclosureButton:@"Normal Analysis" tag:2];
        [self.contentView addSubview:sec.disclosureButton];

        sec.container = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
        [self.contentView addSubview:sec.container];

        CGFloat cy = 0;
        self.cbNormalRef = MakeTraceCheckbox(@"Normal Reference", self, @selector(backendToggled:), NO);
        self.cbNormalRef.tag = 5;
        self.cbNormalRef.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbNormalRef];
        cy += 20;

        self.cbFormEdge = MakeTraceCheckbox(@"Form Edge Extract", self, @selector(backendToggled:), NO);
        self.cbFormEdge.tag = 6;
        self.cbFormEdge.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbFormEdge];
        cy += 20;

        self.cbAnalyzeRef = MakeTraceCheckbox(@"Analyze Reference", self, @selector(backendToggled:), NO);
        self.cbAnalyzeRef.tag = 7;
        self.cbAnalyzeRef.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbAnalyzeRef];
        cy += 20;

        sec.containerHeight = cy;
        [self.sections addObject:sec];
    }

    // ==========================================
    //  Section 4: Contour Tools
    // ==========================================
    {
        TraceAccordionSection *sec = [[TraceAccordionSection alloc] init];
        sec.expanded = NO;

        sec.disclosureButton = [self makeDisclosureButton:@"Contour Tools" tag:3];
        [self.contentView addSubview:sec.disclosureButton];

        sec.container = [[TraceFlippedView alloc] initWithFrame:NSZeroRect];
        [self.contentView addSubview:sec.container];

        CGFloat cy = 0;
        self.cbContourScan = MakeTraceCheckbox(@"Contour Scanner", self, @selector(backendToggled:), NO);
        self.cbContourScan.tag = 8;
        self.cbContourScan.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbContourScan];
        cy += 20;

        self.cbContourPath = MakeTraceCheckbox(@"Contour to Path", self, @selector(backendToggled:), NO);
        self.cbContourPath.tag = 9;
        self.cbContourPath.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbContourPath];
        cy += 20;

        self.cbContourLabel = MakeTraceCheckbox(@"Contour Labeler", self, @selector(backendToggled:), NO);
        self.cbContourLabel.tag = 10;
        self.cbContourLabel.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbContourLabel];
        cy += 20;

        self.cbContourNest = MakeTraceCheckbox(@"Contour Nesting", self, @selector(backendToggled:), NO);
        self.cbContourNest.tag = 11;
        self.cbContourNest.frame = NSMakeRect(8, cy, contentW - 16, 18);
        [sec.container addSubview:self.cbContourNest];
        cy += 20;

        sec.containerHeight = cy;
        [self.sections addObject:sec];
    }

    // ==========================================
    //  Parameters section (below accordion)
    // ==========================================

    self.paramSeparator = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, 0, contentW, 1)];
    self.paramSeparator.boxType = NSBoxSeparator;
    [self.contentView addSubview:self.paramSeparator];

    self.paramTitle = MakeLabel(@"Parameters:", ITLabelFont(), ITDimColor());
    [self.contentView addSubview:self.paramTitle];

    // Speckle filter
    self.speckleTitleLabel = MakeLabel(@"Speckle Filter:", ITLabelFont(), ITTextColor());
    [self.contentView addSubview:self.speckleTitleLabel];

    self.speckleLabel = MakeLabel(@"4", ITLabelFont(), ITDimColor());
    self.speckleLabel.alignment = NSTextAlignmentRight;
    [self.contentView addSubview:self.speckleLabel];

    self.speckleSlider = [[NSSlider alloc] initWithFrame:NSZeroRect];
    self.speckleSlider.minValue = 1;
    self.speckleSlider.maxValue = 100;
    self.speckleSlider.intValue = 4;
    self.speckleSlider.target = self;
    self.speckleSlider.action = @selector(speckleChanged:);
    [self.contentView addSubview:self.speckleSlider];

    // Color precision
    self.colorPrecTitleLabel = MakeLabel(@"Color Precision:", ITLabelFont(), ITTextColor());
    [self.contentView addSubview:self.colorPrecTitleLabel];

    self.colorPrecLabel = MakeLabel(@"6", ITLabelFont(), ITDimColor());
    self.colorPrecLabel.alignment = NSTextAlignmentRight;
    [self.contentView addSubview:self.colorPrecLabel];

    self.colorPrecSlider = [[NSSlider alloc] initWithFrame:NSZeroRect];
    self.colorPrecSlider.minValue = 1;
    self.colorPrecSlider.maxValue = 10;
    self.colorPrecSlider.intValue = 6;
    self.colorPrecSlider.target = self;
    self.colorPrecSlider.action = @selector(colorPrecChanged:);
    [self.contentView addSubview:self.colorPrecSlider];

    // ==========================================
    //  Run button + status
    // ==========================================

    self.buttonSeparator = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, 0, contentW, 1)];
    self.buttonSeparator.boxType = NSBoxSeparator;
    [self.contentView addSubview:self.buttonSeparator];

    self.traceButton = MakeButton(@"Run Selected", self, @selector(traceClicked:));
    [self.contentView addSubview:self.traceButton];

    self.statusLabel = MakeLabel(@"Select backends, place an image, click Run", ITLabelFont(), ITDimColor());
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
//  Disclosure button factory
//----------------------------------------------------------------------------------------

- (NSButton *)makeDisclosureButton:(NSString *)title tag:(NSInteger)tag
{
    // Borderless push-on/push-off button with triangle prefix as section header
    NSButton *header = [[NSButton alloc] initWithFrame:NSZeroRect];
    header.bordered = NO;
    header.buttonType = NSButtonTypeOnOff;
    header.state = (tag == 0) ? NSControlStateValueOn : NSControlStateValueOff;
    header.target = self;
    header.action = @selector(sectionToggled:);
    header.tag = tag;

    // Build attributed title with triangle prefix (down=expanded, right=collapsed)
    NSString *prefix = (tag == 0) ? @"\u25BC " : @"\u25B6 ";
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
//  Relayout — recalculates y-positions for all sections and trailing controls
//----------------------------------------------------------------------------------------

- (void)relayoutContent
{
    CGFloat contentW = kPanelWidth - 2*kPadding;
    CGFloat y = kPadding + kRowHeight + 6;  // skip past title

    for (TraceAccordionSection *sec in self.sections) {
        // Disclosure button
        sec.disclosureButton.frame = NSMakeRect(kPadding, y, contentW, 20);
        y += 22;

        // Container
        if (sec.expanded) {
            sec.container.frame = NSMakeRect(kPadding, y, contentW, sec.containerHeight);
            sec.container.hidden = NO;
            y += sec.containerHeight + 2;
        } else {
            sec.container.hidden = YES;
        }

        y += 2;  // spacing between sections
    }

    y += 4;

    // --- Parameter separator ---
    self.paramSeparator.frame = NSMakeRect(kPadding, y, contentW, 1);
    y += 8;

    self.paramTitle.frame = NSMakeRect(kPadding, y, contentW, kRowHeight);
    y += kRowHeight + 2;

    // Speckle filter
    self.speckleTitleLabel.frame = NSMakeRect(kPadding, y, 100, kRowHeight);
    self.speckleLabel.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, kRowHeight);
    y += kRowHeight;

    self.speckleSlider.frame = NSMakeRect(kPadding, y, contentW, kSliderH);
    y += kSliderH + 6;

    // Color precision
    self.colorPrecTitleLabel.frame = NSMakeRect(kPadding, y, 110, kRowHeight);
    self.colorPrecLabel.frame = NSMakeRect(kPanelWidth - kPadding - 30, y, 30, kRowHeight);
    y += kRowHeight;

    self.colorPrecSlider.frame = NSMakeRect(kPadding, y, contentW, kSliderH);
    y += kSliderH + 12;

    // --- Button separator ---
    self.buttonSeparator.frame = NSMakeRect(kPadding, y, contentW, 1);
    y += 8;

    // Run button
    self.traceButton.frame = NSMakeRect(kPadding, y, contentW, 28);
    y += 28 + 8;

    // Status label
    self.statusLabel.frame = NSMakeRect(kPadding, y, contentW, kRowHeight * 3);
    y += kRowHeight * 3 + kPadding;

    // Resize contentView to fit
    self.contentView.frame = NSMakeRect(0, 0, kPanelWidth, y);
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)sectionToggled:(NSButton *)sender
{
    NSInteger idx = sender.tag;
    if (idx < 0 || idx >= (NSInteger)self.sections.count) return;

    TraceAccordionSection *sec = self.sections[idx];
    sec.expanded = !sec.expanded;

    // Update the disclosure triangle character in the button title
    NSString *currentTitle = sender.title;
    // Strip the first 2 characters (triangle + space) to get the section name
    NSString *sectionName = [currentTitle substringFromIndex:2];
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

    // Animate the relayout
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *ctx) {
        ctx.duration = 0.15;
        ctx.allowsImplicitAnimation = YES;
        [self relayoutContent];
    }];

    fprintf(stderr, "[TracePanel] Section %d %s\n",
            (int)idx, sec.expanded ? "expanded" : "collapsed");
}

- (void)backendToggled:(NSButton *)sender
{
    fprintf(stderr, "[TracePanel] Backend %d toggled to %s\n",
            (int)sender.tag, sender.state == NSControlStateValueOn ? "ON" : "OFF");
}

- (void)traceClicked:(id)sender
{
    // Collect all checked backends — ordered by tag
    // Tags: 0=vtracer, 1=opencv, 2=starvector, 3=diffvg,
    //        4=cartoonseg, 5=normal_ref, 6=form_edge, 7=analyze_ref,
    //        8=contour_scan, 9=contour_path, 10=contour_label, 11=contour_nest
    NSArray<NSButton*> *checkboxes = @[
        self.cbVtracer, self.cbOpenCV, self.cbStarVector, self.cbDiffVG,
        self.cbCartoonSeg,
        self.cbNormalRef, self.cbFormEdge, self.cbAnalyzeRef,
        self.cbContourScan, self.cbContourPath, self.cbContourLabel, self.cbContourNest
    ];
    NSArray<NSString*> *backendNames = @[
        @"vtracer", @"opencv", @"starvector", @"diffvg",
        @"cartoonseg",
        @"normal_ref", @"form_edge", @"analyze_ref",
        @"contour_scan", @"contour_path", @"contour_label", @"contour_nest"
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
