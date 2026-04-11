//========================================================================================
//
//  IllTool — Grouping Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for group management.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "GroupingPanelController.h"
#import "IllToolTheme.h"
#import "HttpBridge.h"
#import <cstdio>
#import <string>


static const CGFloat kPanelWidth  = 240.0;
static const CGFloat kPadding     = 8.0;
static const CGFloat kRowHeight   = 22.0;
static const CGFloat kSliderH     = 18.0;


//========================================================================================
//  GroupingPanelController
//========================================================================================

@interface GroupingPanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSTextField *groupNameField;
@property (nonatomic, strong) NSSlider *simplificationSlider;
@property (nonatomic, strong) NSTextField *simplificationValueLabel;
@property (nonatomic, strong) NSTextField *pointsCountLabel;
@property (nonatomic, strong) NSButton *detachButton;
@property (nonatomic, strong) NSButton *splitButton;

@end

@implementation GroupingPanelController

- (instancetype)init
{
    self = [super init];
    if (self) {
        [self buildUI];
    }
    return self;
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
    CGFloat totalHeight = 340.0;
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kPanelWidth, totalHeight)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    root.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.rootViewInternal = root;
    [root release];  // P2: balance alloc — strong property retains

    CGFloat y = totalHeight - kPadding;

    // --- Title ---
    NSTextField *title = [IllToolTheme makeLabelWithText:@"Grouping Tools" font:[NSFont boldSystemFontOfSize:12] color:[IllToolTheme textColor]];
    title.frame = NSMakeRect(kPadding, y - 16, kPanelWidth - 2*kPadding, 16);
    [root addSubview:title];
    y -= 24;

    // --- Group name field ---
    NSTextField *nameLbl = [IllToolTheme makeLabelWithText:@"Group Name" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    nameLbl.frame = NSMakeRect(kPadding, y - 14, 80, 14);
    [root addSubview:nameLbl];
    y -= (14 + 2);

    NSTextField *nameField = [[NSTextField alloc] initWithFrame:
        NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight)];
    nameField.font = [IllToolTheme labelFont];
    nameField.placeholderString = @"Enter group name...";
    nameField.bezelStyle = NSTextFieldSquareBezel;
    nameField.bordered = YES;
    nameField.editable = YES;
    [root addSubview:nameField];
    self.groupNameField = nameField;
    [nameField release];
    y -= (kRowHeight + kPadding);

    // --- Copy to Group button ---
    NSButton *copyBtn = [IllToolTheme makeButtonWithTitle:@"Copy to Group" target:self action:@selector(onCopyToGroup:)];
    copyBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:copyBtn];
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep1 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep1.boxType = NSBoxSeparator;
    [root addSubview:sep1];
    [sep1 release];
    y -= (1 + kPadding);

    // --- Simplification slider ---
    NSTextField *simpLbl = [IllToolTheme makeLabelWithText:@"Simplification" font:[IllToolTheme labelFont] color:[IllToolTheme textColor]];
    simpLbl.frame = NSMakeRect(kPadding, y - 14, 110, 14);
    [root addSubview:simpLbl];

    NSTextField *simpVal = [IllToolTheme makeLabelWithText:@"50" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
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
    NSTextField *ptsLbl = [IllToolTheme makeLabelWithText:@"Points: 0" font:[IllToolTheme monoFont] color:[IllToolTheme accentColor]];
    ptsLbl.frame = NSMakeRect(kPadding, y - 14, kPanelWidth - 2*kPadding, 14);
    [root addSubview:ptsLbl];
    self.pointsCountLabel = ptsLbl;
    y -= (14 + kPadding);

    // --- Confirm / Reset / Cancel row ---
    CGFloat thirdW = (kPanelWidth - 2*kPadding - 2*4) / 3.0;
    NSButton *confirmBtn = [IllToolTheme makeButtonWithTitle:@"Confirm" target:self action:@selector(onConfirm:)];
    confirmBtn.frame = NSMakeRect(kPadding, y - kRowHeight, thirdW, kRowHeight);
    [root addSubview:confirmBtn];

    NSButton *resetBtn = [IllToolTheme makeButtonWithTitle:@"Reset" target:self action:@selector(onReset:)];
    resetBtn.frame = NSMakeRect(kPadding + thirdW + 4, y - kRowHeight, thirdW, kRowHeight);
    [root addSubview:resetBtn];

    NSButton *cancelBtn = [IllToolTheme makeButtonWithTitle:@"Cancel" target:self action:@selector(onCancel:)];
    cancelBtn.frame = NSMakeRect(kPadding + 2*(thirdW + 4), y - kRowHeight, thirdW, kRowHeight);
    [root addSubview:cancelBtn];
    y -= (kRowHeight + kPadding);

    // --- Separator ---
    NSBox *sep2 = [[NSBox alloc] initWithFrame:NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, 1)];
    sep2.boxType = NSBoxSeparator;
    [root addSubview:sep2];
    [sep2 release];
    y -= (1 + kPadding);

    // --- In-group controls (hidden by default) ---
    NSButton *detachBtn = [IllToolTheme makeButtonWithTitle:@"Detach from Group" target:self action:@selector(onDetach:)];
    detachBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:detachBtn];
    self.detachButton = detachBtn;
    y -= (kRowHeight + 4);

    NSButton *splitBtn = [IllToolTheme makeButtonWithTitle:@"Split to New Group" target:self action:@selector(onSplit:)];
    splitBtn.frame = NSMakeRect(kPadding, y - kRowHeight, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:splitBtn];
    self.splitButton = splitBtn;

    // Hidden by default (shown when selection is in a group)
    [self setInGroupMode:NO];
}

//----------------------------------------------------------------------------------------
//  Actions
//----------------------------------------------------------------------------------------

- (void)onCopyToGroup:(id)sender
{
    NSString *name = self.groupNameField.stringValue;
    if (name.length == 0) {
        name = @"Untitled Group";
    }
    std::string groupName(name.UTF8String);
    fprintf(stderr, "[IllTool Panel] Copy to Group: '%s' — queuing via bridge\n", groupName.c_str());
    BridgeRequestCopyToGroup(groupName);
}

- (void)onSimplificationChanged:(NSSlider *)sender
{
    int value = (int)sender.integerValue;
    self.simplificationValueLabel.stringValue = [NSString stringWithFormat:@"%d", value];
    fprintf(stderr, "[IllTool Panel] Grouping Simplification: %d\n", value);
}

- (void)onConfirm:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Grouping Confirm — queuing working apply via bridge\n");
    // Reuse existing working mode apply — deleteOriginals=true by default for grouping confirm
    BridgeRequestWorkingApply(true);
}

- (void)onReset:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Grouping Reset — queuing working cancel + re-enter\n");
    // Cancel reverts to originals (undo within working mode)
    BridgeRequestWorkingCancel();
}

- (void)onCancel:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Grouping Cancel — queuing working cancel via bridge\n");
    BridgeRequestWorkingCancel();
}

- (void)onDetach:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Detach from Group — queuing via bridge\n");
    BridgeRequestDetach();
}

- (void)onSplit:(id)sender
{
    fprintf(stderr, "[IllTool Panel] Split to New Group — queuing via bridge\n");
    BridgeRequestSplit();
}

//----------------------------------------------------------------------------------------
//  Public methods
//----------------------------------------------------------------------------------------

- (void)updatePointsCount:(NSInteger)count
{
    self.pointsCountLabel.stringValue = [NSString stringWithFormat:@"Points: %ld", (long)count];
}

- (void)setInGroupMode:(BOOL)inGroup
{
    self.detachButton.hidden = !inGroup;
    self.splitButton.hidden = !inGroup;
}

- (void)dealloc
{
    self.rootViewInternal = nil;
    self.groupNameField = nil;
    self.simplificationSlider = nil;
    self.simplificationValueLabel = nil;
    self.pointsCountLabel = nil;
    self.detachButton = nil;
    self.splitButton = nil;
    [super dealloc];
}

@end
