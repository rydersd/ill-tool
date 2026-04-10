//========================================================================================
//
//  IllTool — Surface Extraction Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout for click-to-extract surface boundaries.
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "SurfacePanelController.h"
#include "IllToolPlugin.h"
#import "HttpBridge.h"
#import <cstdio>

// Theme constants and helpers inherited from TransformPanelController.mm
// (compiled in same translation unit via IllToolPanels.mm includes)
static NSColor* ITGreenColor()    { return [NSColor colorWithRed:0.40 green:0.80 blue:0.40 alpha:1.0]; }
// kSliderH defined in TracePanelController.mm (same translation unit)

//========================================================================================
//  FlippedView
//========================================================================================

@interface SurfaceFlippedView : NSView
@end

@implementation SurfaceFlippedView
- (BOOL)isFlipped { return YES; }
@end

//========================================================================================
//  SurfacePanelController
//========================================================================================

@interface SurfacePanelController ()

@property (nonatomic, strong) NSView *rootViewInternal;

// Controls
@property (nonatomic, strong) NSButton *extractToggle;
@property (nonatomic, strong) NSSlider *sensitivitySlider;
@property (nonatomic, strong) NSTextField *sensitivityLabel;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTextField *surfaceTypeLabel;
@property (nonatomic, strong) NSTimer *statusTimer;

@end

@implementation SurfacePanelController

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    CGFloat y = kPadding;

    SurfaceFlippedView *root = [[SurfaceFlippedView alloc] initWithFrame:
                                NSMakeRect(0, 0, kPanelWidth, 240)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = ITBGColor().CGColor;

    // Section title
    NSTextField *title = MakeLabel(@"Surface Extraction", ITLabelFont(), ITAccentColor());
    title.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    title.font = [NSFont boldSystemFontOfSize:12];
    [root addSubview:title];
    y += kRowHeight + 4;

    // Extract mode toggle button
    self.extractToggle = [NSButton checkboxWithTitle:@"Click-to-Extract Mode"
                                             target:self
                                             action:@selector(extractToggled:)];
    self.extractToggle.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [self.extractToggle setFont:ITLabelFont()];
    [root addSubview:self.extractToggle];
    y += kRowHeight + 8;

    // Sensitivity slider
    NSTextField *sensTitleLabel = MakeLabel(@"Sensitivity:", ITLabelFont(), ITTextColor());
    sensTitleLabel.frame = NSMakeRect(kPadding, y, 80, kRowHeight);
    [root addSubview:sensTitleLabel];

    self.sensitivityLabel = MakeLabel(@"50%", ITLabelFont(), ITDimColor());
    self.sensitivityLabel.frame = NSMakeRect(kPanelWidth - kPadding - 40, y, 40, kRowHeight);
    self.sensitivityLabel.alignment = NSTextAlignmentRight;
    [root addSubview:self.sensitivityLabel];
    y += kRowHeight;

    self.sensitivitySlider = [[NSSlider alloc] initWithFrame:
                              NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kSliderH)];
    self.sensitivitySlider.minValue = 0;
    self.sensitivitySlider.maxValue = 100;
    self.sensitivitySlider.intValue = 50;
    self.sensitivitySlider.target = self;
    self.sensitivitySlider.action = @selector(sensitivityChanged:);
    [root addSubview:self.sensitivitySlider];
    y += kSliderH + 12;

    // Surface type display
    self.surfaceTypeLabel = MakeLabel(@"Surface: ---", ITLabelFont(), ITGreenColor());
    self.surfaceTypeLabel.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight);
    [root addSubview:self.surfaceTypeLabel];
    y += kRowHeight + 4;

    // Status label
    self.statusLabel = MakeLabel(@"Enable extract mode, then click on reference", ITLabelFont(), ITDimColor());
    self.statusLabel.frame = NSMakeRect(kPadding, y, kPanelWidth - 2*kPadding, kRowHeight * 2);
    self.statusLabel.maximumNumberOfLines = 2;
    [root addSubview:self.statusLabel];
    y += kRowHeight * 2 + kPadding;

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

- (void)extractToggled:(id)sender
{
    bool enable = (self.extractToggle.state == NSControlStateValueOn);
    BridgeRequestSurfaceExtractToggle(enable);
    fprintf(stderr, "[SurfacePanel] Extract mode %s\n", enable ? "ON" : "OFF");
}

- (void)sensitivityChanged:(id)sender
{
    double val = self.sensitivitySlider.doubleValue / 100.0;
    BridgeSetExtractionSensitivity(val);
    self.sensitivityLabel.stringValue = [NSString stringWithFormat:@"%.0f%%",
                                         self.sensitivitySlider.doubleValue];
}

//----------------------------------------------------------------------------------------
//  Status polling
//----------------------------------------------------------------------------------------

- (void)updateStatus
{
    std::string status = BridgeGetExtractionStatus();
    if (!status.empty()) {
        self.statusLabel.stringValue = [NSString stringWithUTF8String:status.c_str()];
    }

    // Update surface type from bridge
    int surfType = BridgeGetSurfaceType();
    double conf = BridgeGetSurfaceConfidence();
    if (surfType >= 0) {
        const char* names[] = {"flat", "cylindrical", "convex", "concave", "saddle", "angular"};
        const char* name = (surfType < 6) ? names[surfType] : "unknown";
        self.surfaceTypeLabel.stringValue = [NSString stringWithFormat:@"Surface: %s (%.0f%%)",
                                             name, conf * 100];
    }

    // Sync toggle state with bridge
    bool active = BridgeGetSurfaceExtractMode();
    self.extractToggle.state = active ? NSControlStateValueOn : NSControlStateValueOff;
}

@end
