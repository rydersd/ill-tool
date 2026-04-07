//========================================================================================
//
//  IllTool — Surface Shading Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for surface shading with light direction widget.
//  No XIB — all NSViews built in code.
//
//  NOTE: This file must be added to the Xcode project's pbxproj
//
//========================================================================================

#import "ShadingPanelController.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>

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

//========================================================================================
//  LightDirectionView — Circular widget with draggable handle
//========================================================================================

@interface LightDirectionView : NSView

/** Light angle in degrees (0=right, 90=top, CCW). */
@property (nonatomic) double lightAngle;

/** Whether the user is currently dragging the handle. */
@property (nonatomic) BOOL dragging;

/** Callback when angle changes. */
@property (nonatomic, copy) void (^onAngleChanged)(double angleDeg);

@end

@implementation LightDirectionView

- (instancetype)initWithFrame:(NSRect)frame
{
    self = [super initWithFrame:frame];
    if (self) {
        _lightAngle = 135.0;  // default: upper-left light
        _dragging = NO;
    }
    return self;
}

- (BOOL)isFlipped { return NO; }

- (void)drawRect:(NSRect)dirtyRect
{
    [super drawRect:dirtyRect];

    NSRect bounds = self.bounds;
    CGFloat w = bounds.size.width;
    CGFloat h = bounds.size.height;
    CGFloat cx = w / 2.0;
    CGFloat cy = h / 2.0;
    CGFloat radius = MIN(w, h) / 2.0 - 12.0;

    // Background
    [[NSColor colorWithRed:0.12 green:0.12 blue:0.12 alpha:1.0] setFill];
    NSRectFill(bounds);

    // Dark circle background
    NSBezierPath *circleBg = [NSBezierPath bezierPathWithOvalInRect:
        NSMakeRect(cx - radius, cy - radius, radius * 2, radius * 2)];
    [[NSColor colorWithRed:0.18 green:0.18 blue:0.18 alpha:1.0] setFill];
    [circleBg fill];

    // Circle outline
    [[NSColor colorWithRed:0.35 green:0.35 blue:0.35 alpha:1.0] setStroke];
    circleBg.lineWidth = 1.0;
    [circleBg stroke];

    // Cross-hair guide lines (dim gray)
    NSBezierPath *crossHair = [NSBezierPath bezierPath];
    crossHair.lineWidth = 0.5;
    [[NSColor colorWithRed:0.30 green:0.30 blue:0.30 alpha:1.0] setStroke];
    // Horizontal
    [crossHair moveToPoint:NSMakePoint(cx - radius, cy)];
    [crossHair lineToPoint:NSMakePoint(cx + radius, cy)];
    // Vertical
    [crossHair moveToPoint:NSMakePoint(cx, cy - radius)];
    [crossHair lineToPoint:NSMakePoint(cx, cy + radius)];
    [crossHair stroke];

    // Handle position
    double rad = _lightAngle * M_PI / 180.0;
    CGFloat hx = cx + radius * cos(rad);
    CGFloat hy = cy + radius * sin(rad);

    // Line from center to handle
    NSBezierPath *dirLine = [NSBezierPath bezierPath];
    dirLine.lineWidth = 1.5;
    [ITAccentColor() setStroke];
    [dirLine moveToPoint:NSMakePoint(cx, cy)];
    [dirLine lineToPoint:NSMakePoint(hx, hy)];
    [dirLine stroke];

    // Line from center to opposite side (shadow indicator)
    CGFloat sx = cx - radius * cos(rad);
    CGFloat sy = cy - radius * sin(rad);
    NSBezierPath *shadowLine = [NSBezierPath bezierPath];
    shadowLine.lineWidth = 0.5;
    [[NSColor colorWithRed:0.40 green:0.40 blue:0.40 alpha:0.5] setStroke];
    CGFloat dashPattern[] = {3.0, 3.0};
    [shadowLine setLineDash:dashPattern count:2 phase:0];
    [shadowLine moveToPoint:NSMakePoint(cx, cy)];
    [shadowLine lineToPoint:NSMakePoint(sx, sy)];
    [shadowLine stroke];

    // Handle circle (accent, 10pt)
    NSRect handleRect = NSMakeRect(hx - 5, hy - 5, 10, 10);
    NSBezierPath *handleCircle = [NSBezierPath bezierPathWithOvalInRect:handleRect];
    [ITAccentColor() setFill];
    [handleCircle fill];
    [[NSColor whiteColor] setStroke];
    handleCircle.lineWidth = 1.0;
    [handleCircle stroke];

    // Shadow side indicator (small dim circle)
    NSRect shadowRect = NSMakeRect(sx - 3, sy - 3, 6, 6);
    NSBezierPath *shadowCircle = [NSBezierPath bezierPathWithOvalInRect:shadowRect];
    [ITDimColor() setFill];
    [shadowCircle fill];

    // Center dot
    NSRect centerRect = NSMakeRect(cx - 2, cy - 2, 4, 4);
    NSBezierPath *centerDot = [NSBezierPath bezierPathWithOvalInRect:centerRect];
    [ITDimColor() setFill];
    [centerDot fill];
}

//----------------------------------------------------------------------------------------
//  Mouse handling — constrain drag to circle perimeter
//----------------------------------------------------------------------------------------

- (void)mouseDown:(NSEvent *)event
{
    NSPoint localPt = [self convertPoint:event.locationInWindow fromView:nil];
    CGFloat cx = self.bounds.size.width / 2.0;
    CGFloat cy = self.bounds.size.height / 2.0;
    CGFloat radius = MIN(self.bounds.size.width, self.bounds.size.height) / 2.0 - 12.0;

    // Check if near the handle
    double rad = _lightAngle * M_PI / 180.0;
    CGFloat hx = cx + radius * cos(rad);
    CGFloat hy = cy + radius * sin(rad);
    CGFloat dx = localPt.x - hx;
    CGFloat dy = localPt.y - hy;
    if (sqrt(dx*dx + dy*dy) < 15.0) {
        _dragging = YES;
        [self updateAngleFromPoint:localPt];
    }
}

- (void)mouseDragged:(NSEvent *)event
{
    if (!_dragging) return;
    NSPoint localPt = [self convertPoint:event.locationInWindow fromView:nil];
    [self updateAngleFromPoint:localPt];
}

- (void)mouseUp:(NSEvent *)event
{
    _dragging = NO;
}

- (void)updateAngleFromPoint:(NSPoint)pt
{
    CGFloat cx = self.bounds.size.width / 2.0;
    CGFloat cy = self.bounds.size.height / 2.0;

    double angle = atan2(pt.y - cy, pt.x - cx) * 180.0 / M_PI;
    if (angle < 0) angle += 360.0;

    _lightAngle = angle;
    [self setNeedsDisplay:YES];

    // Notify bridge
    BridgeSetShadingLightAngle(angle);
    if (self.onAngleChanged) {
        self.onAngleChanged(angle);
    }
}

@end

//========================================================================================
//  ShadingPanelController
//========================================================================================

@interface ShadingPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSSegmentedControl *modeToggle;
@property (nonatomic, strong) NSColorWell *highlightColorWell;
@property (nonatomic, strong) NSColorWell *shadowColorWell;
@property (nonatomic, strong) LightDirectionView *lightDirView;
@property (nonatomic, strong) NSTextField *angleLabel;
@property (nonatomic, strong) NSSlider *intensitySlider;
@property (nonatomic, strong) NSTextField *intensityValueLabel;

// Mode-specific controls
@property (nonatomic, strong) NSView *blendControlsView;
@property (nonatomic, strong) NSSlider *stepSlider;
@property (nonatomic, strong) NSTextField *stepValueLabel;

@property (nonatomic, strong) NSView *meshControlsView;
@property (nonatomic, strong) NSSlider *gridSlider;
@property (nonatomic, strong) NSTextField *gridValueLabel;

@property (nonatomic, strong) NSButton *applyButton;

// Timer for polling color well changes
@property (nonatomic, strong) NSTimer *pollTimer;

@end

@implementation ShadingPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        [self buildUI];
        // Poll for color well changes at ~4Hz
        self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.25
            target:self selector:@selector(pollColors:)
            userInfo:nil repeats:YES];
    }
    return self;
}

- (void)dealloc
{
    [self.pollTimer invalidate];
    self.pollTimer = nil;
}

- (void)pollColors:(NSTimer *)timer
{
    @autoreleasepool {
        // Sync color wells to bridge state
        NSColor *hl = [self.highlightColorWell.color colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
        if (hl) {
            BridgeSetShadingHighlight(hl.redComponent, hl.greenComponent, hl.blueComponent);
        }
        NSColor *sh = [self.shadowColorWell.color colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
        if (sh) {
            BridgeSetShadingShadow(sh.redComponent, sh.greenComponent, sh.blueComponent);
        }
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
    CGFloat totalHeight = 540.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = MakeLabel(@"Shading", [NSFont boldSystemFontOfSize:12], ITTextColor());
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    //==================================================================================
    //  Section 1: Mode Toggle (30pt)
    //==================================================================================

    NSSegmentedControl *modeCtrl = [NSSegmentedControl segmentedControlWithLabels:@[@"Blend", @"Mesh"]
        trackingMode:NSSegmentSwitchTrackingSelectOne
        target:self action:@selector(onModeChanged:)];
    modeCtrl.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    modeCtrl.selectedSegment = 0;
    [root addSubview:modeCtrl];
    self.modeToggle = modeCtrl;
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [root addSubview:sep1];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 2: Color Section (80pt)
    //==================================================================================

    // Highlight row
    NSTextField *hlLabel = MakeLabel(@"Highlight:", ITLabelFont(), ITTextColor());
    hlLabel.frame = NSMakeRect(kPadding, y - 30, 70, 14);
    [root addSubview:hlLabel];

    NSColorWell *hlWell = [[NSColorWell alloc] initWithFrame:NSMakeRect(kPadding + 75, y - 34, 30, 30)];
    hlWell.color = [NSColor colorWithRed:1.0 green:0.95 blue:0.8 alpha:1.0];  // warm highlight
    [root addSubview:hlWell];
    self.highlightColorWell = hlWell;

    y -= (34 + 4);

    // Shadow row
    NSTextField *shLabel = MakeLabel(@"Shadow:", ITLabelFont(), ITTextColor());
    shLabel.frame = NSMakeRect(kPadding, y - 30, 70, 14);
    [root addSubview:shLabel];

    NSColorWell *shWell = [[NSColorWell alloc] initWithFrame:NSMakeRect(kPadding + 75, y - 34, 30, 30)];
    shWell.color = [NSColor colorWithRed:0.15 green:0.1 blue:0.25 alpha:1.0];  // cool shadow
    [root addSubview:shWell];
    self.shadowColorWell = shWell;

    y -= (34 + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [root addSubview:sep2];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 3: Light Direction (160pt)
    //==================================================================================

    NSTextField *lightLabel = MakeLabel(@"Light Direction", ITLabelFont(), ITTextColor());
    lightLabel.frame = NSMakeRect(kPadding, y - 14, 120, 14);
    [root addSubview:lightLabel];
    y -= (14 + 4);

    CGFloat circleSize = 140.0;
    CGFloat circleX = (kPanelWidth - circleSize) / 2.0;
    LightDirectionView *lightView = [[LightDirectionView alloc]
        initWithFrame:NSMakeRect(circleX, y - circleSize, circleSize, circleSize)];
    [root addSubview:lightView];
    self.lightDirView = lightView;

    // Angle readout below the circle
    NSTextField *angleLbl = MakeLabel(@"135\u00B0", ITMonoFont(), ITAccentColor());
    angleLbl.frame = NSMakeRect(kPadding, y - circleSize - 16, kPanelWidth - 2*kPadding, 14);
    angleLbl.alignment = NSTextAlignmentCenter;
    [root addSubview:angleLbl];
    self.angleLabel = angleLbl;

    // Wire angle callback
    lightView.onAngleChanged = ^(double angleDeg) {
        self.angleLabel.stringValue = [NSString stringWithFormat:@"%.0f\u00B0", angleDeg];
    };

    y -= (circleSize + 16 + kPadding);

    // --- Separator ---
    NSBox *sep3 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep3.boxType = NSBoxSeparator;
    [root addSubview:sep3];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 4: Intensity (40pt)
    //==================================================================================

    NSTextField *intLabel = MakeLabel(@"Intensity", ITLabelFont(), ITTextColor());
    intLabel.frame = NSMakeRect(kPadding, y - 14, 60, 14);
    [root addSubview:intLabel];

    NSTextField *intVal = MakeLabel(@"70", ITMonoFont(), ITAccentColor());
    intVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    intVal.alignment = NSTextAlignmentRight;
    [root addSubview:intVal];
    self.intensityValueLabel = intVal;
    y -= (14 + 2);

    NSSlider *intSlider = [NSSlider sliderWithValue:70 minValue:0 maxValue:100
                                             target:self action:@selector(onIntensityChanged:)];
    intSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    [root addSubview:intSlider];
    self.intensitySlider = intSlider;
    y -= (kSliderH + kPadding);

    // Set initial bridge values
    BridgeSetShadingIntensity(70.0);
    BridgeSetShadingLightAngle(135.0);
    BridgeSetShadingBlendSteps(7);
    BridgeSetShadingMeshGrid(3);

    // --- Separator ---
    NSBox *sep4 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep4.boxType = NSBoxSeparator;
    [root addSubview:sep4];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 5: Mode-specific controls (80pt)
    //==================================================================================

    CGFloat modeY = y;

    // -- Blend mode controls --
    {
        NSView *blendView = [[NSView alloc] initWithFrame:NSMakeRect(0, modeY - 60, kPanelWidth, 60)];
        blendView.wantsLayer = YES;
        [root addSubview:blendView];
        self.blendControlsView = blendView;

        NSTextField *stepLbl = MakeLabel(@"Steps", ITLabelFont(), ITTextColor());
        stepLbl.frame = NSMakeRect(kPadding, 60 - 14, 60, 14);
        [blendView addSubview:stepLbl];

        NSTextField *stepVal = MakeLabel(@"7", ITMonoFont(), ITAccentColor());
        stepVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, 60 - 14, 30, 14);
        stepVal.alignment = NSTextAlignmentRight;
        [blendView addSubview:stepVal];
        self.stepValueLabel = stepVal;

        NSSlider *stepSl = [NSSlider sliderWithValue:7 minValue:3 maxValue:15
                                              target:self action:@selector(onStepsChanged:)];
        stepSl.frame = NSMakeRect(kPadding, 60 - 14 - 2 - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
        stepSl.numberOfTickMarks = 13;
        stepSl.allowsTickMarkValuesOnly = YES;
        [blendView addSubview:stepSl];
        self.stepSlider = stepSl;
    }

    // -- Mesh mode controls --
    {
        NSView *meshView = [[NSView alloc] initWithFrame:NSMakeRect(0, modeY - 60, kPanelWidth, 60)];
        meshView.wantsLayer = YES;
        meshView.hidden = YES;  // hidden by default (blend mode active)
        [root addSubview:meshView];
        self.meshControlsView = meshView;

        NSTextField *gridLbl = MakeLabel(@"Grid", ITLabelFont(), ITTextColor());
        gridLbl.frame = NSMakeRect(kPadding, 60 - 14, 60, 14);
        [meshView addSubview:gridLbl];

        NSTextField *gridVal = MakeLabel(@"3x3", ITMonoFont(), ITAccentColor());
        gridVal.frame = NSMakeRect(kPanelWidth - kPadding - 40, 60 - 14, 40, 14);
        gridVal.alignment = NSTextAlignmentRight;
        [meshView addSubview:gridVal];
        self.gridValueLabel = gridVal;

        NSSlider *gridSl = [NSSlider sliderWithValue:3 minValue:2 maxValue:6
                                              target:self action:@selector(onGridChanged:)];
        gridSl.frame = NSMakeRect(kPadding, 60 - 14 - 2 - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
        gridSl.numberOfTickMarks = 5;
        gridSl.allowsTickMarkValuesOnly = YES;
        [meshView addSubview:gridSl];
        self.gridSlider = gridSl;
    }

    y -= (60 + kPadding);

    // --- Separator ---
    NSBox *sep5 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep5.boxType = NSBoxSeparator;
    [root addSubview:sep5];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 6: Execute (50pt)
    //==================================================================================

    NSButton *applyBtn = [NSButton buttonWithTitle:@"Apply Shading" target:self action:@selector(onApply:)];
    applyBtn.font = [NSFont boldSystemFontOfSize:12];
    applyBtn.bezelStyle = NSBezelStyleSmallSquare;
    applyBtn.frame = NSMakeRect(kPadding, y - 30, kPanelWidth - 2*kPadding, 30);
    applyBtn.wantsLayer = YES;
    applyBtn.layer.backgroundColor = ITAccentColor().CGColor;
    applyBtn.layer.cornerRadius = 3.0;

    NSMutableAttributedString *applyTitle = [[NSMutableAttributedString alloc]
        initWithString:@"Apply Shading"];
    [applyTitle addAttribute:NSForegroundColorAttributeName
                       value:[NSColor whiteColor]
                       range:NSMakeRange(0, 13)];
    [applyTitle addAttribute:NSFontAttributeName
                       value:[NSFont boldSystemFontOfSize:12]
                       range:NSMakeRange(0, 13)];
    applyBtn.attributedTitle = applyTitle;

    [root addSubview:applyBtn];
    self.applyButton = applyBtn;
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onModeChanged:(NSSegmentedControl *)sender
{
    int mode = (int)sender.selectedSegment;
    fprintf(stderr, "[IllTool Panel] Shading mode: %s\n", mode == 0 ? "Blend" : "Mesh");

    self.blendControlsView.hidden = (mode != 0);
    self.meshControlsView.hidden  = (mode != 1);

    PluginOp op;
    op.type = OpType::ShadingSetMode;
    op.intParam = mode;
    BridgeEnqueueOp(op);
}

- (void)onIntensityChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.intensityValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    BridgeSetShadingIntensity((double)value);
}

- (void)onStepsChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.stepValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    BridgeSetShadingBlendSteps(value);
    fprintf(stderr, "[IllTool Panel] Shading steps: %d\n", value);
}

- (void)onGridChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.gridValueLabel.stringValue = [NSString stringWithFormat:@"%dx%d", value, value];
    BridgeSetShadingMeshGrid(value);
    fprintf(stderr, "[IllTool Panel] Shading grid: %dx%d\n", value, value);
}

- (void)onApply:(id)sender
{
    int mode = (int)self.modeToggle.selectedSegment;
    double angle = BridgeGetShadingLightAngle();
    double intensity = BridgeGetShadingIntensity();

    if (mode == 0) {
        // Blend shading
        int steps = (int)self.stepSlider.integerValue;
        fprintf(stderr, "[IllTool Panel] Apply Blend Shading (steps=%d, angle=%.0f, intensity=%.0f)\n",
                steps, angle, intensity);
        PluginOp op;
        op.type = OpType::ShadingApplyBlend;
        op.intParam = steps;
        op.param1 = angle;
        op.param2 = intensity;
        BridgeEnqueueOp(op);
    } else {
        // Mesh shading
        int gridSize = (int)self.gridSlider.integerValue;
        fprintf(stderr, "[IllTool Panel] Apply Mesh Shading (grid=%dx%d, angle=%.0f, intensity=%.0f)\n",
                gridSize, gridSize, angle, intensity);
        PluginOp op;
        op.type = OpType::ShadingApplyMesh;
        op.intParam = gridSize;
        op.param1 = angle;
        op.param2 = intensity;
        BridgeEnqueueOp(op);
    }
}

@end
