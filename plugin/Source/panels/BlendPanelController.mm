//========================================================================================
//
//  IllTool — Blend Harmonization Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for path blending with interactive curve editor.
//  No XIB — all NSViews built in code.
//
//  NOTE: This file must be added to the Xcode project's pbxproj
//
//========================================================================================

#import "BlendPanelController.h"
#import "IllToolTheme.h"
#import "IllToolStrings.h"
#import "HttpBridge.h"
#import <cstdio>
#import <string>
#import <vector>
#import <mutex>
#import <cmath>


static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;
static const CGFloat kSliderH     = 18.0;

//----------------------------------------------------------------------------------------
//  Bridge forwarding for blend easing points
//  Forwards to the real BridgeSetCustomEasingPoints in HttpBridge.cpp
//----------------------------------------------------------------------------------------

static void BridgeSetBlendEasingPoints(const std::vector<std::pair<double,double>>& points)
{
    // Forward to the real bridge function in HttpBridge.cpp
    std::vector<double> flat;
    for (auto& p : points) { flat.push_back(p.first); flat.push_back(p.second); }
    BridgeSetCustomEasingPoints((int)points.size(), flat.data());
}

//----------------------------------------------------------------------------------------
//  In-memory preset storage (mutex-protected)
//----------------------------------------------------------------------------------------

static std::mutex sPresetMutex;
static std::vector<std::vector<std::pair<double,double>>> sPresets;


//========================================================================================
//  EasingCurveView — Interactive cubic-bezier curve editor
//========================================================================================

@interface EasingCurveView : NSView

/** Control points in normalized 0..1 space. */
@property (nonatomic, strong) NSMutableArray<NSValue *> *controlPoints;

/** Index of point being dragged, -1 when idle. */
@property (nonatomic) int dragIndex;

/** Currently active preset index (0-3), or -1 for custom. */
@property (nonatomic) int activePreset;

/** Callback when points change (for syncing to bridge). */
@property (nonatomic, copy) void (^onPointsChanged)(NSArray<NSValue *> *points);

- (void)setPreset:(int)preset;
- (NSArray<NSNumber *> *)getControlPointsFlat;

@end

@implementation EasingCurveView

- (void)dealloc {
    [_controlPoints release];
    self.onPointsChanged = nil;
    [super dealloc];
}

- (instancetype)initWithFrame:(NSRect)frame
{
    self = [super initWithFrame:frame];
    if (self) {
        _dragIndex = -1;
        _activePreset = 0;
        // Default: linear (control points on the diagonal)
        self.controlPoints = [NSMutableArray arrayWithObjects:
            [NSValue valueWithPoint:NSMakePoint(0.25, 0.25)],
            [NSValue valueWithPoint:NSMakePoint(0.75, 0.75)],
            nil];
    }
    return self;
}

- (void)setPreset:(int)preset
{
    self.activePreset = preset;
    [self.controlPoints removeAllObjects];
    switch (preset) {
        case 0: // Linear
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.25, 0.25)]];
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.75, 0.75)]];
            break;
        case 1: // Ease In
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.42, 0.0)]];
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(1.0, 1.0)]];
            break;
        case 2: // Ease Out
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.0, 0.0)]];
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.58, 1.0)]];
            break;
        case 3: // Ease In Out
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.42, 0.0)]];
            [self.controlPoints addObject:[NSValue valueWithPoint:NSMakePoint(0.58, 1.0)]];
            break;
        default:
            break;
    }
    [self syncToBridge];
    [self setNeedsDisplay:YES];
}

- (NSArray<NSNumber *> *)getControlPointsFlat
{
    NSMutableArray<NSNumber *> *flat = [NSMutableArray array];
    for (NSValue *v in self.controlPoints) {
        NSPoint pt = v.pointValue;
        [flat addObject:@(pt.x)];
        [flat addObject:@(pt.y)];
    }
    return flat;
}

- (void)syncToBridge
{
    std::vector<std::pair<double,double>> pts;
    for (NSValue *v in self.controlPoints) {
        NSPoint pt = v.pointValue;
        pts.push_back({pt.x, pt.y});
    }
    BridgeSetBlendEasingPoints(pts);
    if (self.onPointsChanged) {
        self.onPointsChanged(self.controlPoints);
    }
}

//----------------------------------------------------------------------------------------
//  Drawing
//----------------------------------------------------------------------------------------

- (BOOL)isFlipped { return NO; }

- (void)drawRect:(NSRect)dirtyRect
{
    [super drawRect:dirtyRect];

    NSRect bounds = self.bounds;
    CGFloat w = bounds.size.width;
    CGFloat h = bounds.size.height;

    // Background
    [[NSColor colorWithRed:0.12 green:0.12 blue:0.12 alpha:1.0] setFill];
    NSRectFill(bounds);

    // 4x4 grid lines
    [[NSColor colorWithRed:0.25 green:0.25 blue:0.25 alpha:1.0] setStroke];
    NSBezierPath *gridPath = [NSBezierPath bezierPath];
    gridPath.lineWidth = 0.5;
    for (int i = 1; i < 4; i++) {
        CGFloat pos = (CGFloat)i / 4.0;
        [gridPath moveToPoint:NSMakePoint(pos * w, 0)];
        [gridPath lineToPoint:NSMakePoint(pos * w, h)];
        [gridPath moveToPoint:NSMakePoint(0, pos * h)];
        [gridPath lineToPoint:NSMakePoint(w, pos * h)];
    }
    [gridPath stroke];

    // Diagonal guide line (0,0) -> (1,1)
    NSBezierPath *diagPath = [NSBezierPath bezierPath];
    diagPath.lineWidth = 0.5;
    [[IllToolTheme secondaryTextColor] setStroke];
    [diagPath moveToPoint:NSMakePoint(0, 0)];
    [diagPath lineToPoint:NSMakePoint(w, h)];
    [diagPath stroke];

    // Evaluate and draw the curve
    NSBezierPath *curvePath = [NSBezierPath bezierPath];
    curvePath.lineWidth = 2.0;
    [[NSColor whiteColor] setStroke];

    NSUInteger count = self.controlPoints.count;
    for (int i = 0; i <= 50; i++) {
        CGFloat t = (CGFloat)i / 50.0;
        CGFloat yVal = 0;

        if (count == 2) {
            // Cubic bezier: P0=(0,0), P1=cp[0], P2=cp[1], P3=(1,1)
            NSPoint cp1 = [self.controlPoints[0] pointValue];
            NSPoint cp2 = [self.controlPoints[1] pointValue];
            CGFloat mt = 1.0 - t;
            yVal = mt*mt*mt * 0.0
                 + 3.0 * mt*mt * t * cp1.y
                 + 3.0 * mt * t*t * cp2.y
                 + t*t*t * 1.0;
            // x for parametric curve (used only for proper cubic bezier display)
            CGFloat xVal = mt*mt*mt * 0.0
                         + 3.0 * mt*mt * t * cp1.x
                         + 3.0 * mt * t*t * cp2.x
                         + t*t*t * 1.0;
            NSPoint screenPt = NSMakePoint(xVal * w, yVal * h);
            if (i == 0) [curvePath moveToPoint:screenPt];
            else        [curvePath lineToPoint:screenPt];
        } else if (count > 2) {
            // Piecewise linear through sorted points including (0,0) and (1,1)
            NSMutableArray<NSValue *> *allPts = [NSMutableArray array];
            [allPts addObject:[NSValue valueWithPoint:NSMakePoint(0, 0)]];
            // Sort control points by x
            NSArray<NSValue *> *sorted = [self.controlPoints sortedArrayUsingComparator:
                ^NSComparisonResult(NSValue *a, NSValue *b) {
                    CGFloat ax = a.pointValue.x;
                    CGFloat bx = b.pointValue.x;
                    if (ax < bx) return NSOrderedAscending;
                    if (ax > bx) return NSOrderedDescending;
                    return NSOrderedSame;
                }];
            [allPts addObjectsFromArray:sorted];
            [allPts addObject:[NSValue valueWithPoint:NSMakePoint(1, 1)]];

            // Evaluate at x = t
            CGFloat x = t;
            yVal = 0;
            for (NSUInteger j = 0; j < allPts.count - 1; j++) {
                NSPoint p0 = [allPts[j] pointValue];
                NSPoint p1 = [allPts[j+1] pointValue];
                if (x >= p0.x && x <= p1.x) {
                    CGFloat segLen = p1.x - p0.x;
                    if (segLen < 0.0001) { yVal = p0.y; }
                    else { yVal = p0.y + (p1.y - p0.y) * ((x - p0.x) / segLen); }
                    break;
                }
            }
            NSPoint screenPt = NSMakePoint(x * w, yVal * h);
            if (i == 0) [curvePath moveToPoint:screenPt];
            else        [curvePath lineToPoint:screenPt];
        } else {
            // 0 or 1 control points — linear fallback
            NSPoint screenPt = NSMakePoint(t * w, t * h);
            if (i == 0) [curvePath moveToPoint:screenPt];
            else        [curvePath lineToPoint:screenPt];
        }
    }
    [curvePath stroke];

    // Draw control point handles (lines from P0/P3 to control points)
    if (count == 2) {
        NSBezierPath *handlePath = [NSBezierPath bezierPath];
        handlePath.lineWidth = 1.0;
        [[NSColor colorWithRed:0.48 green:0.72 blue:0.94 alpha:0.5] setStroke];
        NSPoint cp1 = [self.controlPoints[0] pointValue];
        NSPoint cp2 = [self.controlPoints[1] pointValue];
        [handlePath moveToPoint:NSMakePoint(0, 0)];
        [handlePath lineToPoint:NSMakePoint(cp1.x * w, cp1.y * h)];
        [handlePath moveToPoint:NSMakePoint(w, h)];
        [handlePath lineToPoint:NSMakePoint(cp2.x * w, cp2.y * h)];
        [handlePath stroke];
    }

    // Draw control points as filled colored circles (8pt diameter)
    for (NSUInteger i = 0; i < self.controlPoints.count; i++) {
        NSPoint pt = [self.controlPoints[i] pointValue];
        CGFloat cx = pt.x * w;
        CGFloat cy = pt.y * h;
        NSRect circleRect = NSMakeRect(cx - 4, cy - 4, 8, 8);
        NSBezierPath *circle = [NSBezierPath bezierPathWithOvalInRect:circleRect];
        [[IllToolTheme accentColor] setFill];
        [circle fill];
        [[NSColor whiteColor] setStroke];
        circle.lineWidth = 1.0;
        [circle stroke];
    }
}

//----------------------------------------------------------------------------------------
//  Mouse handling
//----------------------------------------------------------------------------------------

- (int)hitTestPoint:(NSPoint)localPt
{
    CGFloat w = self.bounds.size.width;
    CGFloat h = self.bounds.size.height;
    for (NSUInteger i = 0; i < self.controlPoints.count; i++) {
        NSPoint cp = [self.controlPoints[i] pointValue];
        CGFloat dx = cp.x * w - localPt.x;
        CGFloat dy = cp.y * h - localPt.y;
        if (sqrt(dx*dx + dy*dy) < 10.0) {
            return (int)i;
        }
    }
    return -1;
}

- (NSPoint)normalizedPointFromEvent:(NSEvent *)event
{
    NSPoint localPt = [self convertPoint:event.locationInWindow fromView:nil];
    CGFloat w = self.bounds.size.width;
    CGFloat h = self.bounds.size.height;
    CGFloat nx = localPt.x / w;
    CGFloat ny = localPt.y / h;
    // Clamp to 0..1
    nx = fmax(0.0, fmin(1.0, nx));
    ny = fmax(0.0, fmin(1.0, ny));
    return NSMakePoint(nx, ny);
}

- (void)mouseDown:(NSEvent *)event
{
    NSPoint localPt = [self convertPoint:event.locationInWindow fromView:nil];
    int hit = [self hitTestPoint:localPt];
    if (hit >= 0) {
        self.dragIndex = hit;
    } else {
        // Add a new control point
        NSPoint norm = [self normalizedPointFromEvent:event];
        [self.controlPoints addObject:[NSValue valueWithPoint:norm]];
        self.dragIndex = (int)(self.controlPoints.count - 1);
        self.activePreset = -1;
        [self syncToBridge];
        [self setNeedsDisplay:YES];
    }
}

- (void)mouseDragged:(NSEvent *)event
{
    if (self.dragIndex < 0 || self.dragIndex >= (int)self.controlPoints.count) return;
    NSPoint norm = [self normalizedPointFromEvent:event];
    self.controlPoints[self.dragIndex] = [NSValue valueWithPoint:norm];
    self.activePreset = -1;
    [self syncToBridge];
    [self setNeedsDisplay:YES];
}

- (void)mouseUp:(NSEvent *)event
{
    self.dragIndex = -1;
}

- (void)rightMouseDown:(NSEvent *)event
{
    NSPoint localPt = [self convertPoint:event.locationInWindow fromView:nil];
    int hit = [self hitTestPoint:localPt];
    if (hit >= 0 && self.controlPoints.count > 1) {
        [self.controlPoints removeObjectAtIndex:hit];
        self.activePreset = -1;
        [self syncToBridge];
        [self setNeedsDisplay:YES];
    }
}

@end

//========================================================================================
//  BlendPanelController
//========================================================================================

@interface BlendPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSButton *pickAButton;
@property (nonatomic, strong) NSButton *pickBButton;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSSlider *stepSlider;
@property (nonatomic, strong) NSTextField *stepValueLabel;
@property (nonatomic, strong) NSArray<NSButton *> *easingButtons;
@property (nonatomic, strong) EasingCurveView *curveEditor;
@property (nonatomic, strong) NSButton *blendButton;

// State
@property (nonatomic) BOOL hasPathA;
@property (nonatomic) BOOL hasPathB;
@property (nonatomic) int activeEasingPreset;

// Timer for polling blend state
@property (nonatomic, strong) NSTimer *blendTimer;

@end

@implementation BlendPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        _hasPathA = NO;
        _hasPathB = NO;
        _activeEasingPreset = 0;
        [self buildUI];
        // Poll for blend state updates at ~4Hz
        self.blendTimer = [NSTimer scheduledTimerWithTimeInterval:0.25
            target:self selector:@selector(pollBlendState:)
            userInfo:nil repeats:YES];
    }
    return self;
}

- (void)dealloc
{
    [self.blendTimer invalidate];
    self.blendTimer = nil;
    [super dealloc];
}

- (void)pollBlendState:(NSTimer *)timer
{
    @autoreleasepool {
        BOOL hasA = BridgeHasBlendPathA();
        BOOL hasB = BridgeHasBlendPathB();
        [self updatePathStatus:hasA pathB:hasB];
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
    CGFloat totalHeight = 520.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];  // P2: balance alloc — strong property retains

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = [IllToolTheme makeLabelWithText:kITS_Blend font:[NSFont boldSystemFontOfSize:12] color:[IllToolTheme textColor]];
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    //==================================================================================
    //  Section 1: Path Selection (60pt)
    //==================================================================================

    CGFloat halfW = (kPanelWidth - 2*kPadding - 4) / 2.0;

    NSButton *pickABtn = [IllToolTheme makeButtonWithTitle:kITS_PickA target:self action:@selector(onPickA:)];
    pickABtn.frame = NSMakeRect(kPadding, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:pickABtn];
    self.pickAButton = pickABtn;

    NSButton *pickBBtn = [IllToolTheme makeButtonWithTitle:kITS_PickB target:self action:@selector(onPickB:)];
    pickBBtn.frame = NSMakeRect(kPadding + halfW + 4, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:pickBBtn];
    self.pickBButton = pickBBtn;
    y -= (kRowHeight + 4);

    NSTextField *status = [IllToolTheme makeLabelWithText:kITS_NoPathsSelected font:[IllToolTheme monoFont] color:[IllToolTheme secondaryTextColor]];
    status.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [root addSubview:status];
    self.statusLabel = status;
    y -= (14 + kPadding);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [root addSubview:sep1];
    [sep1 release];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 2: Step Count (50pt)
    //==================================================================================

    NSTextField *stepsLbl = [IllToolTheme makeLabelWithText:kITS_Steps font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    stepsLbl.frame = NSMakeRect(kPadding, y - 14, 60, 14);
    [root addSubview:stepsLbl];

    NSTextField *stepsVal = [IllToolTheme makeLabelWithText:@"5" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    stepsVal.frame = NSMakeRect(kPanelWidth - kPadding - 30, y - 14, 30, 14);
    stepsVal.alignment = NSTextAlignmentRight;
    [root addSubview:stepsVal];
    self.stepValueLabel = stepsVal;
    y -= (14 + 2);

    NSSlider *stepsSlider = [NSSlider sliderWithValue:5 minValue:1 maxValue:20
                                               target:self action:@selector(onStepsChanged:)];
    stepsSlider.frame = NSMakeRect(kPadding, y - kSliderH, kPanelWidth - 2*kPadding, kSliderH);
    stepsSlider.numberOfTickMarks = 20;
    stepsSlider.allowsTickMarkValuesOnly = YES;
    [root addSubview:stepsSlider];
    self.stepSlider = stepsSlider;
    y -= (kSliderH + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [root addSubview:sep2];
    [sep2 release];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 3: Easing Presets (60pt)
    //==================================================================================

    NSTextField *easingLbl = [IllToolTheme makeLabelWithText:kITS_Easing font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    easingLbl.frame = NSMakeRect(kPadding, y - 14, 60, 14);
    [root addSubview:easingLbl];
    y -= (14 + 4);

    NSArray<NSString *> *presetNames = @[kITS_EasingLin, kITS_EasingIn, kITS_EasingOut, kITS_EasingInOut];
    CGFloat btnW = (kPanelWidth - 2*kPadding - 3*4) / 4.0;
    NSMutableArray<NSButton *> *easingBtns = [NSMutableArray array];
    for (int i = 0; i < 4; i++) {
        NSButton *btn = [IllToolTheme makeButtonWithTitle:presetNames[i] target:self action:@selector(onEasingPreset:)];
        btn.frame = NSMakeRect(kPadding + i * (btnW + 4), y - kRowHeight, btnW, kRowHeight);
        btn.tag = i;
        [root addSubview:btn];
        [easingBtns addObject:btn];
    }
    self.easingButtons = easingBtns;
    [self highlightEasingButton:0];
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep3 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep3.boxType = NSBoxSeparator;
    [root addSubview:sep3];
    [sep3 release];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 4: Curve Editor (200pt)
    //==================================================================================

    CGFloat curveSize = kPanelWidth - 2*kPadding;
    EasingCurveView *curveView = [[EasingCurveView alloc]
        initWithFrame:NSMakeRect(kPadding, y - curveSize, curveSize, curveSize)];
    [root addSubview:curveView];
    self.curveEditor = curveView;
    [curveView release];

    // P2: __block avoids MRC retain cycle in block capture
    __block BlendPanelController *blockSelf = self;
    curveView.onPointsChanged = ^(NSArray<NSValue *> *points) {
        // Mark as custom preset when user edits the curve
        if (blockSelf.curveEditor.activePreset < 0) {
            [blockSelf highlightEasingButton:-1];
        }
    };

    y -= (curveSize + kPadding);

    //==================================================================================
    //  Section 5: Presets Save/Load (40pt)
    //==================================================================================

    NSButton *saveBtn = [IllToolTheme makeButtonWithTitle:kITS_Save target:self action:@selector(onSavePreset:)];
    saveBtn.frame = NSMakeRect(kPadding, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:saveBtn];

    NSButton *loadBtn = [IllToolTheme makeButtonWithTitle:kITS_Load target:self action:@selector(onLoadPreset:)];
    loadBtn.frame = NSMakeRect(kPadding + halfW + 4, y - kRowHeight, halfW, kRowHeight);
    [root addSubview:loadBtn];
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep4 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep4.boxType = NSBoxSeparator;
    [root addSubview:sep4];
    [sep4 release];
    y -= (1 + kPadding);

    //==================================================================================
    //  Section 6: Execute (50pt)
    //==================================================================================

    NSButton *blendBtn = [NSButton buttonWithTitle:kITS_Blend target:self action:@selector(onBlend:)];
    blendBtn.font = [NSFont boldSystemFontOfSize:12];
    blendBtn.bezelStyle = NSBezelStyleSmallSquare;
    blendBtn.frame = NSMakeRect(kPadding, y - 30, kPanelWidth - 2*kPadding, 30);
    blendBtn.enabled = NO;
    // Style the blend button with accent color
    blendBtn.wantsLayer = YES;
    blendBtn.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
    blendBtn.layer.cornerRadius = 3.0;
    NSMutableAttributedString *blendTitle = [[NSMutableAttributedString alloc]
        initWithString:kITS_Blend];
    [blendTitle addAttribute:NSForegroundColorAttributeName
                       value:[NSColor whiteColor]
                       range:NSMakeRange(0, [kITS_Blend length])];
    [blendTitle addAttribute:NSFontAttributeName
                       value:[NSFont boldSystemFontOfSize:12]
                       range:NSMakeRange(0, [kITS_Blend length])];
    blendBtn.attributedTitle = blendTitle;
    [blendTitle release];
    [root addSubview:blendBtn];
    self.blendButton = blendBtn;
}

//----------------------------------------------------------------------------------------
//  Easing button highlighting
//----------------------------------------------------------------------------------------

- (void)highlightEasingButton:(int)activeIndex
{
    self.activeEasingPreset = activeIndex;
    for (int i = 0; i < (int)self.easingButtons.count; i++) {
        NSButton *btn = self.easingButtons[i];
        btn.wantsLayer = YES;
        if (i == activeIndex) {
            btn.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
            NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
                initWithString:btn.title];
            [attrTitle addAttribute:NSForegroundColorAttributeName
                              value:[NSColor whiteColor]
                              range:NSMakeRange(0, btn.title.length)];
            [attrTitle addAttribute:NSFontAttributeName
                              value:[IllToolTheme labelFont]
                              range:NSMakeRange(0, btn.title.length)];
            btn.attributedTitle = attrTitle;
            [attrTitle release];
        } else {
            btn.layer.backgroundColor = [NSColor clearColor].CGColor;
            NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
                initWithString:btn.title];
            [attrTitle addAttribute:NSForegroundColorAttributeName
                              value:[IllToolTheme textColor]
                              range:NSMakeRange(0, btn.title.length)];
            [attrTitle addAttribute:NSFontAttributeName
                              value:[IllToolTheme labelFont]
                              range:NSMakeRange(0, btn.title.length)];
            btn.attributedTitle = attrTitle;
            [attrTitle release];
        }
    }
}

//----------------------------------------------------------------------------------------
//  Path status update
//----------------------------------------------------------------------------------------

- (void)updatePathStatus:(BOOL)hasA pathB:(BOOL)hasB
{
    self.hasPathA = hasA;
    self.hasPathB = hasB;

    // Update Pick A button appearance
    self.pickAButton.wantsLayer = YES;
    if (hasA) {
        self.pickAButton.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
        NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
            initWithString:kITS_PickA];
        [attrTitle addAttribute:NSForegroundColorAttributeName
                          value:[NSColor whiteColor]
                          range:NSMakeRange(0, [kITS_PickA length])];
        [attrTitle addAttribute:NSFontAttributeName
                          value:[IllToolTheme labelFont]
                          range:NSMakeRange(0, [kITS_PickA length])];
        self.pickAButton.attributedTitle = attrTitle;
        [attrTitle release];
    } else {
        self.pickAButton.layer.backgroundColor = [NSColor clearColor].CGColor;
    }

    // Update Pick B button appearance
    self.pickBButton.wantsLayer = YES;
    if (hasB) {
        self.pickBButton.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
        NSMutableAttributedString *attrTitle = [[NSMutableAttributedString alloc]
            initWithString:kITS_PickB];
        [attrTitle addAttribute:NSForegroundColorAttributeName
                          value:[NSColor whiteColor]
                          range:NSMakeRange(0, [kITS_PickA length])];
        [attrTitle addAttribute:NSFontAttributeName
                          value:[IllToolTheme labelFont]
                          range:NSMakeRange(0, [kITS_PickA length])];
        self.pickBButton.attributedTitle = attrTitle;
        [attrTitle release];
    } else {
        self.pickBButton.layer.backgroundColor = [NSColor clearColor].CGColor;
    }

    // Update status label
    if (hasA && hasB) {
        self.statusLabel.stringValue = kITS_ReadyToBlend;
        self.statusLabel.textColor = [IllToolTheme accentColor];
    } else if (hasA) {
        self.statusLabel.stringValue = kITS_PathASet;
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    } else if (hasB) {
        self.statusLabel.stringValue = kITS_PathBSet;
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    } else {
        self.statusLabel.stringValue = kITS_NoPathsSelected;
        self.statusLabel.textColor = [IllToolTheme secondaryTextColor];
    }

    // Enable/disable blend button
    self.blendButton.enabled = (hasA && hasB);
    self.blendButton.wantsLayer = YES;
    if (hasA && hasB) {
        self.blendButton.layer.backgroundColor = [IllToolTheme accentColor].CGColor;
    } else {
        self.blendButton.layer.backgroundColor =
            [NSColor colorWithRed:0.30 green:0.30 blue:0.30 alpha:1.0].CGColor;
    }
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onPickA:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Blend Pick A — queuing via bridge\n");
    PluginOp op;
    op.type = OpType::BlendPickA;
    BridgeEnqueueOp(op);
}

- (void)onPickB:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Blend Pick B — queuing via bridge\n");
    PluginOp op;
    op.type = OpType::BlendPickB;
    BridgeEnqueueOp(op);
}

- (void)onStepsChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.stepValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Blend Steps: %d\n", value);
    PluginOp op;
    op.type = OpType::BlendSetSteps;
    op.intParam = value;
    BridgeEnqueueOp(op);
}

- (void)onEasingPreset:(NSButton *)sender
{
    int preset = (int)sender.tag;
    fprintf(stderr, "[IllTool Panel] Blend Easing Preset: %d\n", preset);
    [self highlightEasingButton:preset];
    [self.curveEditor setPreset:preset];
    PluginOp op;
    op.type = OpType::BlendSetEasing;
    op.intParam = preset;
    BridgeEnqueueOp(op);
}

- (void)onSavePreset:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Blend Save Preset\n");
    // Read current easing points from the real bridge
    double xyBuf[40]; // max 20 control points
    int count = BridgeGetCustomEasingPoints(xyBuf, 20);
    std::vector<std::pair<double,double>> pts;
    for (int i = 0; i < count; i++) {
        pts.push_back({xyBuf[i*2], xyBuf[i*2+1]});
    }
    std::lock_guard<std::mutex> lock(sPresetMutex);
    sPresets.push_back(pts);
    fprintf(stderr, "[IllTool Panel] Saved preset #%lu\n", (unsigned long)sPresets.size());
}

- (void)onLoadPreset:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Blend Load Preset\n");
    std::lock_guard<std::mutex> lock(sPresetMutex);
    if (sPresets.empty()) {
        fprintf(stderr, "[IllTool Panel] No saved presets\n");
        return;
    }
    // Load the most recently saved preset
    const auto& pts = sPresets.back();
    BridgeSetBlendEasingPoints(pts);

    // Update the curve editor UI
    [self.curveEditor.controlPoints removeAllObjects];
    for (const auto& p : pts) {
        [self.curveEditor.controlPoints addObject:
            [NSValue valueWithPoint:NSMakePoint(p.first, p.second)]];
    }
    self.curveEditor.activePreset = -1;
    [self highlightEasingButton:-1];
    [self.curveEditor setNeedsDisplay:YES];

    PluginOp op;
    op.type = OpType::BlendSetEasing;
    op.intParam = 4; // 4 = custom
    BridgeEnqueueOp(op);
}

- (void)onBlend:(id)sender
{
    if (!self.hasPathA || !self.hasPathB) return;
    int steps = (int)self.stepSlider.integerValue;
    fprintf(stderr, "[IllTool Panel] Blend Execute (steps=%d, easing=%d) — queuing via bridge\n",
            steps, self.activeEasingPreset);
    PluginOp op;
    op.type = OpType::BlendExecute;
    op.intParam = steps;
    op.param1 = (double)self.activeEasingPreset;
    BridgeEnqueueOp(op);
}

@end
