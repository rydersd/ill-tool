//========================================================================================
//
//  IllTool — Ill Pen Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for the Ill Pen drawing tool.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "PenPanelController.h"
#import "IllToolTheme.h"
#import "IllToolStrings.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>


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
        NSTextField *title = [IllToolTheme makeLabelWithText:kITS_IllPen font:[IllToolTheme titleFont] color:[IllToolTheme accentColor]];
        title.frame = NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, kRowHeight);
        [rows addObject:title];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Pen Mode toggle
    //------------------------------------------------------------------
    {
        NSButton *cb = [NSButton checkboxWithTitle:kITS_PenModeActive target:self action:@selector(penModeToggled:)];
        cb.font = [IllToolTheme labelFont];
        [cb setContentHuggingPriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
        cb.frame = NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, kRowHeight);
        cb.state = NSControlStateValueOff;
        _penModeCheckbox = cb;
        [rows addObject:cb];
    }

    //------------------------------------------------------------------
    //  Path Name
    //------------------------------------------------------------------
    {
        NSTextField *label = [IllToolTheme makeLabelWithText:kITS_PathName font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
        label.frame = NSMakeRect(kPadding, 0, 80, kRowHeight);
        [rows addObject:label];

        NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(kPadding + 82, 0, kPanelWidth - 2 * kPadding - 82, kRowHeight)];
        field.font = [IllToolTheme labelFont];
        field.textColor = [IllToolTheme textColor];
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
        NSTextField *label = [IllToolTheme makeLabelWithText:kITS_TargetGroup font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
        label.frame = NSMakeRect(kPadding, 0, 90, kRowHeight);
        [rows addObject:label];

        NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding + 92, 0, kPanelWidth - 2 * kPadding - 92, kRowHeight) pullsDown:NO];
        popup.font = [IllToolTheme labelFont];
        [popup addItemWithTitle:kITS_None];
        popup.target = self;
        popup.action = @selector(targetGroupChanged:);
        _targetGroupPopup = popup;
        [rows addObject:popup];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Chamfer section header
    //------------------------------------------------------------------
    {
        NSTextField *header = [IllToolTheme makeLabelWithText:kITS_Chamfer font:[IllToolTheme titleFont] color:[IllToolTheme textColor]];
        header.frame = NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, kRowHeight);
        [rows addObject:header];
    }

    //------------------------------------------------------------------
    //  Chamfer Radius slider
    //------------------------------------------------------------------
    {
        NSTextField *label = [IllToolTheme makeLabelWithText:kITS_Radius font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
        label.frame = NSMakeRect(kPadding, 0, 50, kSliderH);
        [rows addObject:label];

        NSSlider *slider = [[NSSlider alloc] initWithFrame:NSMakeRect(kPadding + 52, 0, kPanelWidth - 2 * kPadding - 92, kSliderH)];
        slider.minValue = 0;
        slider.maxValue = 20;
        slider.doubleValue = 0;
        slider.continuous = YES;
        slider.target = self;
        slider.action = @selector(chamferSliderChanged:);
        _chamferSlider = slider;
        [rows addObject:slider];

        NSTextField *valLabel = [IllToolTheme makeLabelWithText:@"0pt" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
        valLabel.frame = NSMakeRect(kPanelWidth - kPadding - 36, 0, 36, kSliderH);
        valLabel.alignment = NSTextAlignmentRight;
        _chamferValueLabel = valLabel;
        [rows addObject:valLabel];
    }

    //------------------------------------------------------------------
    //  Uniform Edges checkbox
    //------------------------------------------------------------------
    {
        NSButton *cb = [NSButton checkboxWithTitle:kITS_UniformEdges target:self action:@selector(uniformEdgesToggled:)];
        cb.font = [IllToolTheme labelFont];
        cb.frame = NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, kRowHeight);
        cb.state = NSControlStateValueOn;
        _uniformEdgesCheckbox = cb;
        [rows addObject:cb];
    }

    //------------------------------------------------------------------
    //  Preset popup
    //------------------------------------------------------------------
    {
        NSTextField *label = [IllToolTheme makeLabelWithText:kITS_PresetLabel font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
        label.frame = NSMakeRect(kPadding, 0, 50, kRowHeight);
        [rows addObject:label];

        NSPopUpButton *popup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(kPadding + 52, 0, kPanelWidth - 2 * kPadding - 52, kRowHeight) pullsDown:NO];
        popup.font = [IllToolTheme labelFont];
        [popup addItemWithTitle:kITS_PresetSharp];
        [popup addItemWithTitle:kITS_PresetSoft];
        [popup addItemWithTitle:kITS_PresetRound];
        [popup addItemWithTitle:kITS_PresetCustom];
        popup.target = self;
        popup.action = @selector(presetChanged:);
        _presetPopup = popup;
        [rows addObject:popup];
    }

    // Separator
    {
        NSBox *sep = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, 1)];
        sep.boxType = NSBoxSeparator;
        [rows addObject:sep];
    }

    //------------------------------------------------------------------
    //  Finalize / Cancel buttons
    //------------------------------------------------------------------
    {
        NSButton *finalizeBtn = [IllToolTheme makeButtonWithTitle:kITS_Finalize target:self action:@selector(finalizeClicked:)];
        finalizeBtn.frame = NSMakeRect(kPadding, 0, (kPanelWidth - 3 * kPadding) / 2, 28);
        [rows addObject:finalizeBtn];

        NSButton *cancelBtn = [IllToolTheme makeButtonWithTitle:kITS_Cancel target:self action:@selector(cancelClicked:)];
        cancelBtn.frame = NSMakeRect(kPadding + (kPanelWidth - 3 * kPadding) / 2 + kPadding, 0, (kPanelWidth - 3 * kPadding) / 2, 28);
        [rows addObject:cancelBtn];
    }

    //------------------------------------------------------------------
    //  Status label
    //------------------------------------------------------------------
    {
        NSTextField *status = [IllToolTheme makeLabelWithText:kITS_ClickDrawHelp font:[IllToolTheme labelFont] color:[IllToolTheme secondaryTextColor]];
        status.frame = NSMakeRect(kPadding, 0, kPanelWidth - 2 * kPadding, kRowHeight);
        _statusLabel = status;
        [rows addObject:status];
    }

    //------------------------------------------------------------------
    //  Layout all rows top-down
    //------------------------------------------------------------------

    // We do manual layout since we're not using Auto Layout
    CGFloat totalHeight = kPadding;
    // First pass: compute sizes and positions
    NSMutableArray<NSValue*> *yPositions = [NSMutableArray array];
    for (NSView *row in rows) {
        [yPositions addObject:[NSValue valueWithPoint:NSMakePoint(0, totalHeight)]];
        totalHeight += row.frame.size.height + 4;  // 4pt spacing between rows
    }
    totalHeight += kPadding;

    // Create flipped root view (so y=0 is at top)
    _rootViewBacking = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    _rootViewBacking.wantsLayer = YES;
    _rootViewBacking.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;

    // Add all rows (flip y coordinates since NSView is not flipped by default)
    for (NSUInteger i = 0; i < rows.count; i++) {
        NSView *row = rows[i];
        CGFloat rowY = [yPositions[i] pointValue].y;
        NSRect frame = row.frame;
        // Position from top in a flipped coordinate sense:
        // In non-flipped coords, y=0 is bottom, so we flip
        frame.origin.y = totalHeight - rowY - frame.size.height;
        frame.origin.x = row.frame.origin.x;
        if (frame.origin.x < 0.001) frame.origin.x = kPadding;
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
        _statusLabel.stringValue = kITS_EnablePenHelp;
        _statusLabel.textColor = [IllToolTheme secondaryTextColor];
    } else {
        _statusLabel.stringValue = kITS_ClickDrawHelp;
        _statusLabel.textColor = [IllToolTheme accentColor];
    }
}

@end
