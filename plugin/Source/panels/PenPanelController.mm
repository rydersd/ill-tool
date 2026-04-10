//========================================================================================
//
//  IllTool — Ill Pen Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for the Ill Pen drawing tool.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "PenPanelController.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>

//----------------------------------------------------------------------------------------
//  Dark theme constants matching Illustrator
//----------------------------------------------------------------------------------------

static NSColor* PenBGColor()       { return [NSColor colorWithRed:0.20 green:0.20 blue:0.20 alpha:1.0]; }
static NSColor* PenTextColor()     { return [NSColor colorWithRed:0.85 green:0.85 blue:0.85 alpha:1.0]; }
static NSColor* PenAccentColor()   { return [NSColor colorWithRed:0.48 green:0.72 blue:0.94 alpha:1.0]; }
static NSColor* PenDimColor()      { return [NSColor colorWithRed:0.55 green:0.55 blue:0.55 alpha:1.0]; }
static NSFont*  PenLabelFont()     { return [NSFont systemFontOfSize:11]; }
static NSFont*  PenHeaderFont()    { return [NSFont boldSystemFontOfSize:12]; }

static const CGFloat kPenPanelWidth  = 240.0;
static const CGFloat kPenPadding     = 8.0;
static const CGFloat kPenRowHeight   = 22.0;
static const CGFloat kPenSliderH     = 18.0;

//----------------------------------------------------------------------------------------
//  Helpers
//----------------------------------------------------------------------------------------

static NSTextField* PenMakeLabel(NSString *text, NSFont *font, NSColor *color)
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

static NSButton* PenMakeButton(NSString *title, id target, SEL action)
{
    NSButton *btn = [NSButton buttonWithTitle:title target:target action:action];
    btn.font = PenLabelFont();
    btn.bezelStyle = NSBezelStyleSmallSquare;
    return btn;
}

//========================================================================================
//  PenPanelController
//========================================================================================

@interface PenPanelController ()

@property (nonatomic, strong) NSView *rootViewBacking;

// Controls
@property (nonatomic, strong) NSButton *penModeCheckbox;
@property (nonatomic, strong) NSTextField *pathNameField;
@property (nonatomic, strong) NSPopUpButton *targetGroupPopup;
@property (nonatomic, strong) NSSlider *chamferSlider;
@property (nonatomic, strong) NSTextField *chamferValueLabel;
@property (nonatomic, strong) NSButton *uniformEdgesCheckbox;
@property (nonatomic, strong) NSPopUpButton *presetPopup;
@property (nonatomic, strong) NSTextField *statusLabel;

// Timer for status updates
@property (nonatomic, strong) NSTimer *updateTimer;

@end

@implementation PenPanelController

- (void)dealloc
{
    [_updateTimer invalidate];
    _updateTimer = nil;
    [super dealloc];
}

- (NSView *)rootView
{
    return _rootViewBacking;
}

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    // We'll build a stack of subviews and compute final height
    NSMutableArray<NSView*> *rows = [NSMutableArray array];

    //------------------------------------------------------------------
    //  Title
    //------------------------------------------------------------------
    {
        NSTextField *title = PenMakeLabel(@"Ill Pen", PenHeaderFont(), PenAccentColor());
        title.frame = NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, kPenRowHeight);
        [rows addObject:title];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Pen Mode toggle
    //------------------------------------------------------------------
    {
        NSButton *cb = [NSButton checkboxWithTitle:@"Pen Mode Active" target:self action:@selector(penModeToggled:)];
        cb.font = PenLabelFont();
        [cb setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
        cb.frame = NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, kPenRowHeight);
        cb.state = NSControlStateValueOff;
        _penModeCheckbox = cb;
        [rows addObject:cb];
    }

    //------------------------------------------------------------------
    //  Path Name
    //------------------------------------------------------------------
    {
        NSTextField *label = PenMakeLabel(@"Path Name:", PenLabelFont(), PenDimColor());
        label.frame = NSMakeRect(kPenPadding, 0, 80, kPenRowHeight);
        [rows addObject:label];

        NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(kPenPadding + 82, 0, kPenPanelWidth - 2 * kPenPadding - 82, kPenRowHeight)];
        field.font = PenLabelFont();
        field.textColor = PenTextColor();
        field.backgroundColor = [NSColor colorWithRed:0.15 green:0.15 blue:0.15 alpha:1.0];
        field.bordered = YES;
        field.editable = YES;
        field.placeholderString = @"(auto)";
        field.target = self;
        field.action = @selector(pathNameChanged:);
        _pathNameField = field;
        [rows addObject:field];
    }

    //------------------------------------------------------------------
    //  Target Group
    //------------------------------------------------------------------
    {
        NSTextField *label = PenMakeLabel(@"Target Group:", PenLabelFont(), PenDimColor());
        label.frame = NSMakeRect(kPenPadding, 0, 90, kPenRowHeight);
        [rows addObject:label];

        NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPenPadding + 92, 0, kPenPanelWidth - 2 * kPenPadding - 92, kPenRowHeight) pullsDown:NO];
        popup.font = PenLabelFont();
        [popup addItemWithTitle:@"None"];
        popup.target = self;
        popup.action = @selector(targetGroupChanged:);
        _targetGroupPopup = popup;
        [rows addObject:popup];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Chamfer section header
    //------------------------------------------------------------------
    {
        NSTextField *header = PenMakeLabel(@"Chamfer", PenHeaderFont(), PenTextColor());
        header.frame = NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, kPenRowHeight);
        [rows addObject:header];
    }

    //------------------------------------------------------------------
    //  Chamfer Radius slider
    //------------------------------------------------------------------
    {
        NSTextField *label = PenMakeLabel(@"Radius:", PenLabelFont(), PenDimColor());
        label.frame = NSMakeRect(kPenPadding, 0, 50, kPenSliderH);
        [rows addObject:label];

        NSSlider *slider = [[NSSlider alloc] initWithFrame:NSMakeRect(kPenPadding + 52, 0, kPenPanelWidth - 2 * kPenPadding - 92, kPenSliderH)];
        slider.minValue = 0;
        slider.maxValue = 20;
        slider.doubleValue = 0;
        slider.continuous = YES;
        slider.target = self;
        slider.action = @selector(chamferSliderChanged:);
        _chamferSlider = slider;
        [rows addObject:slider];

        NSTextField *valLabel = PenMakeLabel(@"0pt", PenLabelFont(), PenTextColor());
        valLabel.frame = NSMakeRect(kPenPanelWidth - kPenPadding - 36, 0, 36, kPenSliderH);
        valLabel.alignment = NSTextAlignmentRight;
        _chamferValueLabel = valLabel;
        [rows addObject:valLabel];
    }

    //------------------------------------------------------------------
    //  Uniform Edges checkbox
    //------------------------------------------------------------------
    {
        NSButton *cb = [NSButton checkboxWithTitle:@"Uniform Edges" target:self action:@selector(uniformEdgesToggled:)];
        cb.font = PenLabelFont();
        cb.frame = NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, kPenRowHeight);
        cb.state = NSControlStateValueOn;
        _uniformEdgesCheckbox = cb;
        [rows addObject:cb];
    }

    //------------------------------------------------------------------
    //  Preset popup
    //------------------------------------------------------------------
    {
        NSTextField *label = PenMakeLabel(@"Preset:", PenLabelFont(), PenDimColor());
        label.frame = NSMakeRect(kPenPadding, 0, 50, kPenRowHeight);
        [rows addObject:label];

        NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPenPadding + 52, 0, kPenPanelWidth - 2 * kPenPadding - 52, kPenRowHeight) pullsDown:NO];
        popup.font = PenLabelFont();
        [popup addItemWithTitle:@"Sharp"];
        [popup addItemWithTitle:@"Soft"];
        [popup addItemWithTitle:@"Round"];
        [popup addItemWithTitle:@"Custom"];
        popup.target = self;
        popup.action = @selector(presetChanged:);
        _presetPopup = popup;
        [rows addObject:popup];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Finalize / Cancel buttons
    //------------------------------------------------------------------
    {
        NSButton *finalizeBtn = PenMakeButton(@"Finalize", self, @selector(finalizeClicked:));
        finalizeBtn.frame = NSMakeRect(kPenPadding, 0, (kPenPanelWidth - 3 * kPenPadding) / 2, 28);
        [rows addObject:finalizeBtn];

        NSButton *cancelBtn = PenMakeButton(@"Cancel", self, @selector(cancelClicked:));
        cancelBtn.frame = NSMakeRect(kPenPadding + (kPenPanelWidth - 3 * kPenPadding) / 2 + kPenPadding, 0, (kPenPanelWidth - 3 * kPenPadding) / 2, 28);
        [rows addObject:cancelBtn];
    }

    //------------------------------------------------------------------
    //  Status label
    //------------------------------------------------------------------
    {
        NSTextField *status = PenMakeLabel(@"Click to draw, double-click to finish", PenLabelFont(), PenDimColor());
        status.frame = NSMakeRect(kPenPadding, 0, kPenPanelWidth - 2 * kPenPadding, kPenRowHeight);
        _statusLabel = status;
        [rows addObject:status];
    }

    //------------------------------------------------------------------
    //  Layout all rows top-down
    //------------------------------------------------------------------

    // We do manual layout since we're not using Auto Layout
    CGFloat totalHeight = kPenPadding;
    // First pass: compute sizes and positions
    NSMutableArray<NSValue*> *yPositions = [NSMutableArray array];
    for (NSView *row in rows) {
        [yPositions addObject:[NSValue valueWithPoint:NSMakePoint(0, totalHeight)]];
        totalHeight += row.frame.size.height + 4;  // 4pt spacing between rows
    }
    totalHeight += kPenPadding;

    // Create flipped root view (so y=0 is at top)
    _rootViewBacking = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPenPanelWidth, totalHeight)];
    _rootViewBacking.wantsLayer = YES;
    _rootViewBacking.layer.backgroundColor = PenBGColor().CGColor;

    // Add all rows (flip y coordinates since NSView is not flipped by default)
    for (NSUInteger i = 0; i < rows.count; i++) {
        NSView *row = rows[i];
        CGFloat rowY = [yPositions[i] pointValue].y;
        NSRect frame = row.frame;
        // Position from top in a flipped coordinate sense:
        // In non-flipped coords, y=0 is bottom, so we flip
        frame.origin.y = totalHeight - rowY - frame.size.height;
        frame.origin.x = row.frame.origin.x;
        if (frame.origin.x < 0.001) frame.origin.x = kPenPadding;
        row.frame = frame;
        [_rootViewBacking addSubview:row];
    }

    // Initialize bridge state
    BridgeSetPenMode(false);
    BridgeSetPenChamferRadius(0);
    BridgeSetPenUniformEdges(true);

    // Start update timer for status
    _updateTimer = [NSTimer scheduledTimerWithTimeInterval:0.5
                                                   target:self
                                                 selector:@selector(updateStatus:)
                                                 userInfo:nil
                                                  repeats:YES];

    fprintf(stderr, "[PenPanel] Panel created (height=%.0f)\n", totalHeight);

    return self;
}

//========================================================================================
//  Actions
//========================================================================================

- (void)penModeToggled:(NSButton *)sender
{
    bool active = (sender.state == NSControlStateValueOn);
    BridgeSetPenMode(active);
    fprintf(stderr, "[PenPanel] Pen mode %s\n", active ? "ON" : "OFF");
}

- (void)pathNameChanged:(NSTextField *)sender
{
    std::string name = [[sender stringValue] UTF8String];
    BridgeSetPenPathName(name);
}

- (void)targetGroupChanged:(NSPopUpButton *)sender
{
    std::string groupName = [[sender titleOfSelectedItem] UTF8String];
    BridgeSetPenTargetGroup(groupName);
    fprintf(stderr, "[PenPanel] Target group: '%s'\n", groupName.c_str());
}

- (void)chamferSliderChanged:(NSSlider *)sender
{
    double radius = sender.doubleValue;
    BridgeSetPenChamferRadius(radius);
    _chamferValueLabel.stringValue = [NSString stringWithFormat:@"%.0fpt", radius];

    // Update preset selection
    if (radius == 0) [_presetPopup selectItemAtIndex:0];       // Sharp
    else if (radius == 2) [_presetPopup selectItemAtIndex:1];  // Soft
    else if (radius == 6) [_presetPopup selectItemAtIndex:2];  // Round
    else [_presetPopup selectItemAtIndex:3];                   // Custom

    // Send live update to module
    PluginOp op{OpType::PenSetChamfer};
    op.param1 = radius;
    BridgeEnqueueOp(op);
}

- (void)uniformEdgesToggled:(NSButton *)sender
{
    bool uniform = (sender.state == NSControlStateValueOn);
    BridgeSetPenUniformEdges(uniform);
    fprintf(stderr, "[PenPanel] Uniform edges %s\n", uniform ? "ON" : "OFF");
}

- (void)presetChanged:(NSPopUpButton *)sender
{
    NSInteger idx = [sender indexOfSelectedItem];
    double radius = 0;
    switch (idx) {
        case 0: radius = 0; break;   // Sharp
        case 1: radius = 2; break;   // Soft
        case 2: radius = 6; break;   // Round
        case 3: return;              // Custom — don't change slider
    }
    [_chamferSlider setDoubleValue:radius];
    BridgeSetPenChamferRadius(radius);
    _chamferValueLabel.stringValue = [NSString stringWithFormat:@"%.0fpt", radius];

    PluginOp op{OpType::PenSetChamfer};
    op.param1 = radius;
    BridgeEnqueueOp(op);
}

- (void)finalizeClicked:(NSButton *)sender
{
    BridgeEnqueueOp({OpType::PenFinalize});
    fprintf(stderr, "[PenPanel] Finalize clicked\n");
}

- (void)cancelClicked:(NSButton *)sender
{
    BridgeEnqueueOp({OpType::PenCancel});
    fprintf(stderr, "[PenPanel] Cancel clicked\n");
}

//========================================================================================
//  Status update timer
//========================================================================================

- (void)updateStatus:(NSTimer *)timer
{
    bool penMode = BridgeGetPenMode();
    _penModeCheckbox.state = penMode ? NSControlStateValueOn : NSControlStateValueOff;

    if (!penMode) {
        _statusLabel.stringValue = @"Enable Pen Mode to draw";
        _statusLabel.textColor = PenDimColor();
    } else {
        _statusLabel.stringValue = @"Click to draw, double-click to finish";
        _statusLabel.textColor = PenAccentColor();
    }
}

@end
