//========================================================================================
//
//  IllTool — Ill Layers Panel Controller (Objective-C++)
//
//  Programmatic Cocoa layout with NSOutlineView for the layer tree.
//  Polls BridgeGetLayerTreeJSON() for updates, parses JSON on a background
//  thread, and swaps the tree data on main.  Visibility/lock toggles,
//  inline rename, drag-and-drop reorder, add layer, auto-organize,
//  and preset save/load all enqueue PluginOps through the bridge.
//
//  No XIB — all NSViews built in code.
//
//========================================================================================

#import "LayerPanelController.h"
#import "IllToolTheme.h"
#import "IllToolStrings.h"
#import "HttpBridge.h"
#import <cstdio>
#import <cmath>


// Pasteboard type for drag-and-drop reorder
static NSString * const kLayerNodePBType = @"com.illtool.layernode";

// Forward declarations — IllLayerOutlineView defined after LayerNode and LayerPanelController
@class IllLayerOutlineView;

//========================================================================================
//  LayerNode — lightweight data model for NSOutlineView
//========================================================================================

@interface LayerNode : NSObject
@property (nonatomic, assign) int  nodeID;
@property (nonatomic, assign) int  nodeType;   // 0=layer, 1=group, 2=path, 3=collapsed
@property (nonatomic, copy)   NSString *name;
@property (nonatomic, assign) BOOL visible;
@property (nonatomic, assign) BOOL locked;
@property (nonatomic, assign) BOOL isSelected;
@property (nonatomic, assign) float colorR, colorG, colorB;
@property (nonatomic, assign) int  unnamedCount;
@property (nonatomic, strong) NSMutableArray<LayerNode *> *children;
@end

@implementation LayerNode
- (instancetype)init {
    self = [super init];
    if (self) {
        _children = [NSMutableArray new];
        _visible  = YES;
        _name     = @"";
    }
    return self;
}
- (void)dealloc {
    [_children release];
    [_name release];
    [super dealloc];
}
@end


//========================================================================================
//  LayerPanelController — private interface
//========================================================================================

@interface LayerPanelController ()

@property (nonatomic, strong) NSView *rootViewBacking;

// Outline view & scroll
@property (nonatomic, strong) NSOutlineView *outlineView;
@property (nonatomic, strong) NSScrollView  *scrollView;

// Toolbar controls
@property (nonatomic, strong) NSPopUpButton *presetPopup;

// Status bar
@property (nonatomic, strong) NSTextField *statusLabel;

// Swipe-to-toggle state: hold mouse and drag across eye/lock columns
@property (nonatomic, assign) BOOL swipeActive;
@property (nonatomic, assign) int  swipeColumn;   // 0=eye, 1=lock
@property (nonatomic, assign) BOOL swipeTargetState;  // the state we're setting
@property (nonatomic, strong) NSMutableSet<NSNumber *> *swipedNodeIDs;

// Drag hover auto-expand state
@property (nonatomic, strong) NSTimer *dragHoverTimer;
@property (nonatomic, assign) id dragHoverItem;

// Data
@property (nonatomic, strong) NSMutableArray<LayerNode *> *treeData;

// Timer
@property (nonatomic, strong) NSTimer *pollTimer;

// Guard against overlapping background parses
@property (nonatomic, assign) BOOL parseInFlight;

// Track expanded node IDs to preserve state across reloads
@property (nonatomic, strong) NSMutableSet<NSNumber *> *expandedNodeIDs;
@property (nonatomic, assign) BOOL firstLoad;

@end


//========================================================================================
//  IllLayerOutlineView — subclass for keyboard shortcuts + swipe-to-toggle
//========================================================================================

@interface IllLayerOutlineView : NSOutlineView
@property (nonatomic, assign) LayerPanelController *layerController;
@end

@implementation IllLayerOutlineView

- (void)mouseDown:(NSEvent *)event
{
    NSPoint loc = [self convertPoint:event.locationInWindow fromView:nil];
    NSInteger row = [self rowAtPoint:loc];

    // Check if click is in eye column (x < 20) or lock column (20 <= x < 40)
    // Account for indentation
    CGFloat indent = 0;
    if (row >= 0) {
        NSInteger level = [self levelForRow:row];
        indent = level * self.indentationPerLevel + 16;  // 16 for disclosure triangle
    }
    CGFloat localX = loc.x - indent;

    if (row >= 0 && localX >= 0 && localX < 40) {
        int col = (localX < 20) ? 0 : 1;  // 0=eye, 1=lock
        LayerNode *node = [self itemAtRow:row];
        if (node && node.nodeType != 3) {
            BOOL targetState = (col == 0) ? !node.visible : !node.locked;
            self.layerController.swipeActive = YES;
            self.layerController.swipeColumn = col;
            self.layerController.swipeTargetState = targetState;
            self.layerController.swipedNodeIDs = [NSMutableSet new];
            [self.layerController.swipedNodeIDs addObject:@(node.nodeID)];

            PluginOp op;
            op.type = (col == 0) ? OpType::LayerSetVisible : OpType::LayerSetLocked;
            op.intParam = node.nodeID;
            op.boolParam1 = targetState;
            BridgeEnqueueOp(op);
        }
        return;
    }

    [super mouseDown:event];
}

- (void)mouseDragged:(NSEvent *)event
{
    if (!self.layerController.swipeActive) {
        [super mouseDragged:event];
        return;
    }

    NSPoint loc = [self convertPoint:event.locationInWindow fromView:nil];
    NSInteger row = [self rowAtPoint:loc];
    if (row < 0) return;

    LayerNode *node = [self itemAtRow:row];
    if (!node || node.nodeType == 3) return;

    if ([self.layerController.swipedNodeIDs containsObject:@(node.nodeID)]) return;
    [self.layerController.swipedNodeIDs addObject:@(node.nodeID)];

    PluginOp op;
    op.type = (self.layerController.swipeColumn == 0) ? OpType::LayerSetVisible : OpType::LayerSetLocked;
    op.intParam = node.nodeID;
    op.boolParam1 = self.layerController.swipeTargetState;
    BridgeEnqueueOp(op);
}

- (void)mouseUp:(NSEvent *)event
{
    if (self.layerController.swipeActive) {
        self.layerController.swipeActive = NO;
        self.layerController.swipedNodeIDs = nil;
        return;
    }
    [super mouseUp:event];
}

- (void)keyDown:(NSEvent *)event
{
    BOOL cmd = (event.modifierFlags & NSEventModifierFlagCommand) != 0;
    NSString *chars = event.characters;

    // Cmd+G → group selected
    if (cmd && [chars isEqualToString:@"g"]) {
        if (self.layerController) {
            [self.layerController performSelector:@selector(onGroupSelected:) withObject:nil];
        }
        return;
    }

    // Cmd+H → toggle visibility of selected
    if (cmd && [chars isEqualToString:@"h"]) {
        if (self.selectedRow >= 0 && self.layerController) {
            [self.layerController performSelector:@selector(onToggleVisibilitySelected:) withObject:nil];
        }
        return;
    }

    // Cmd+L → toggle lock of selected
    if (cmd && [chars isEqualToString:@"l"]) {
        if (self.selectedRow >= 0 && self.layerController) {
            [self.layerController performSelector:@selector(onToggleLockSelected:) withObject:nil];
        }
        return;
    }

    // Tab / Shift+Tab → navigate
    if (event.keyCode == 48) {
        NSInteger row = self.selectedRow;
        if (event.modifierFlags & NSEventModifierFlagShift) {
            if (row > 0) {
                [self selectRowIndexes:[NSIndexSet indexSetWithIndex:row - 1] byExtendingSelection:NO];
                [self scrollRowToVisible:row - 1];
            }
        } else {
            if (row < self.numberOfRows - 1) {
                [self selectRowIndexes:[NSIndexSet indexSetWithIndex:row + 1] byExtendingSelection:NO];
                [self scrollRowToVisible:row + 1];
            }
        }
        return;
    }

    // Cmd+] → move up in stack
    if (cmd && [chars isEqualToString:@"]"]) {
        if (self.selectedRow >= 0 && self.layerController)
            [self.layerController performSelector:@selector(onMoveUp:) withObject:nil];
        return;
    }

    // Cmd+[ → move down in stack
    if (cmd && [chars isEqualToString:@"["]) {
        if (self.selectedRow >= 0 && self.layerController)
            [self.layerController performSelector:@selector(onMoveDown:) withObject:nil];
        return;
    }

    // Cmd+R → rename selected
    if (cmd && [chars isEqualToString:@"r"]) {
        if (self.selectedRow >= 0) {
            NSView *rowView = [self viewAtColumn:0 row:self.selectedRow makeIfNecessary:NO];
            if (rowView) {
                for (NSView *sub in rowView.subviews) {
                    if ([sub isKindOfClass:[NSTextField class]] && [(NSTextField *)sub isEditable]) {
                        [self.window makeFirstResponder:(NSTextField *)sub];
                        break;
                    }
                }
            }
        }
        return;
    }

    // Delete/Backspace → delete selected
    if (event.keyCode == 51 || event.keyCode == 117) {
        if (self.selectedRow >= 0 && self.layerController)
            [self.layerController performSelector:@selector(onDeleteSelected:) withObject:nil];
        return;
    }

    [super keyDown:event];
}

@end


//========================================================================================
//  LayerPanelController — implementation
//========================================================================================

@implementation LayerPanelController

- (void)dealloc
{
    // Timers are not retained by us (scheduledTimerWithTimeInterval: returns
    // autoreleased; the run loop holds the only strong reference).
    // Invalidate to remove from run loop and break the target reference.
    [_pollTimer invalidate];
    _pollTimer = nil;

    [_dragHoverTimer invalidate];
    _dragHoverTimer = nil;

    // Release alloc'd ivars (views created via alloc/init)
    [_outlineView release];
    [_scrollView release];
    [_presetPopup release];
    // _statusLabel is autoreleased (from makeLabelWithText:), retained only by superview

    [_swipedNodeIDs release];
    [_treeData release];
    [_expandedNodeIDs release];

    // Release root view last — it is the superview that retains statusLabel,
    // buttons, and other autoreleased subviews
    [_rootViewBacking release];

    [super dealloc];
}

- (NSView *)rootView
{
    return _rootViewBacking;
}

//----------------------------------------------------------------------------------------
//  init — build the entire view hierarchy programmatically
//----------------------------------------------------------------------------------------

- (instancetype)init
{
    self = [super init];
    if (!self) return nil;

    CGFloat panelW = kPanelWidth;
    CGFloat panelH = 520;
    CGFloat pad    = kPadding;

    _treeData = [NSMutableArray new];
    _parseInFlight = NO;
    _expandedNodeIDs = [NSMutableSet new];
    _firstLoad = YES;

    //------------------------------------------------------------------
    //  Root view
    //------------------------------------------------------------------
    NSView *root = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, panelW, panelH)];
    root.wantsLayer = YES;
    root.layer.backgroundColor = [IllToolTheme panelBackground].CGColor;
    root.autoresizesSubviews = YES;

    // Layout from top (flipped y: NSView origin is bottom-left, so we
    // calculate from panelH downward and set origin accordingly).
    CGFloat y = panelH;

    //------------------------------------------------------------------
    //  Title — compact, right at top
    //------------------------------------------------------------------
    y -= 20;
    NSTextField *title = [IllToolTheme makeLabelWithText:kITS_IllLayers
                                                   font:[IllToolTheme titleFont]
                                                  color:[IllToolTheme accentColor]];
    title.frame = NSMakeRect(pad, y, panelW - 2 * pad, 16);
    title.autoresizingMask = NSViewMinYMargin | NSViewWidthSizable;
    [root addSubview:title];

    //------------------------------------------------------------------
    //  Toolbar row: [Preset popup] [+ Layer] [Organize]
    //------------------------------------------------------------------
    y -= 24;

    // Preset popup (left side)
    NSPopUpButton *presetPopup = [[NSPopUpButton alloc]
        initWithFrame:NSMakeRect(pad, y, 100, kRowHeight) pullsDown:NO];
    presetPopup.font = [IllToolTheme smallFont];
    [presetPopup addItemWithTitle:kITS_NoPreset];
    [presetPopup addItemWithTitle:kITS_SavePresetDots];
    presetPopup.target = self;
    presetPopup.action = @selector(onPresetSelected:);
    [root addSubview:presetPopup];
    _presetPopup = presetPopup;

    // Organize button (right side)
    CGFloat orgW = 64;
    NSButton *orgBtn = [IllToolTheme makeButtonWithTitle:kITS_Organize
                                                 target:self
                                                 action:@selector(onAutoOrganize:)];
    orgBtn.frame = NSMakeRect(panelW - pad - orgW, y, orgW, kRowHeight);
    [root addSubview:orgBtn];

    // + Layer button (to the left of Organize)
    CGFloat addW = 30;
    NSButton *addBtn = [IllToolTheme makeButtonWithTitle:@"+"
                                                 target:self
                                                 action:@selector(onAddLayer:)];
    addBtn.frame = NSMakeRect(panelW - pad - orgW - 4 - addW, y, addW, kRowHeight);
    [root addSubview:addBtn];

    //------------------------------------------------------------------
    //  NSScrollView + NSOutlineView (main content area)
    //------------------------------------------------------------------
    y -= 2;
    CGFloat statusBarH = 20;
    CGFloat treeH = y - statusBarH;

    NSScrollView *scrollView = [[NSScrollView alloc]
        initWithFrame:NSMakeRect(0, statusBarH, panelW, treeH)];
    scrollView.hasVerticalScroller = YES;
    scrollView.autohidesScrollers  = YES;
    scrollView.autoresizingMask    = NSViewWidthSizable | NSViewHeightSizable;
    scrollView.drawsBackground     = NO;

    IllLayerOutlineView *outlineView = [[IllLayerOutlineView alloc]
        initWithFrame:scrollView.bounds];
    outlineView.layerController = self;
    outlineView.dataSource  = self;
    outlineView.delegate    = self;
    outlineView.headerView  = nil;   // no column header
    outlineView.rowHeight   = kRowHeight;
    outlineView.indentationPerLevel    = 16;
    outlineView.autoresizesOutlineColumn = YES;
    outlineView.backgroundColor = [IllToolTheme panelBackground];
    outlineView.usesAlternatingRowBackgroundColors = NO;

    // Multi-select: allow Cmd+click and Shift+click
    outlineView.allowsMultipleSelection = YES;

    // Register for drag-and-drop with source-list highlighting (blue target highlight)
    [outlineView registerForDraggedTypes:@[kLayerNodePBType]];
    outlineView.draggingDestinationFeedbackStyle =
        NSTableViewDraggingDestinationFeedbackStyleSourceList;

    // Single column — fills the width
    NSTableColumn *col = [[[NSTableColumn alloc] initWithIdentifier:@"main"] autorelease];
    col.width = panelW - 20;
    col.resizingMask = NSTableColumnAutoresizingMask;
    [outlineView addTableColumn:col];
    outlineView.outlineTableColumn = col;

    scrollView.documentView = outlineView;
    [root addSubview:scrollView];

    _outlineView = outlineView;
    _scrollView  = scrollView;

    //------------------------------------------------------------------
    //  Status bar
    //------------------------------------------------------------------
    NSTextField *statusLabel = [IllToolTheme makeLabelWithText:@""
                                                         font:[IllToolTheme smallFont]
                                                        color:[IllToolTheme secondaryTextColor]];
    statusLabel.frame = NSMakeRect(pad, 2, panelW - 2 * pad, 16);
    [root addSubview:statusLabel];
    _statusLabel = statusLabel;

    //------------------------------------------------------------------
    //  Finish
    //------------------------------------------------------------------
    _rootViewBacking = root;

    // Fire an initial tree scan so we have data right away
    {
        PluginOp op;
        op.type = OpType::LayerScanTree;
        BridgeEnqueueOp(op);
    }

    // Start poll timer — checks bridge dirty flag for tree updates
    _pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.5
                                                 target:self
                                               selector:@selector(pollTreeState:)
                                               userInfo:nil
                                                repeats:YES];

    fprintf(stderr, "[LayerPanel] Initialized with NSOutlineView\n");
    return self;
}


//========================================================================================
//  Poll timer — check bridge for tree updates, parse JSON on background thread
//========================================================================================

- (void)pollTreeState:(NSTimer *)timer
{
    if (_parseInFlight) return;

    bool dirty = BridgeGetLayerTreeDirty();
    if (!dirty) return;

    BridgeSetLayerTreeDirty(false);
    _parseInFlight = YES;

    // Grab the JSON string (mutex-protected, fast copy)
    std::string jsonStr = BridgeGetLayerTreeJSON();
    if (jsonStr.empty()) {
        _parseInFlight = NO;
        return;
    }

    NSString *jsonNS = [NSString stringWithUTF8String:jsonStr.c_str()];

    // Parse on a background thread to keep the panel responsive
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSData *data = [jsonNS dataUsingEncoding:NSUTF8StringEncoding];
        NSError *error = nil;
        NSArray *jsonArray = [NSJSONSerialization JSONObjectWithData:data
                                                            options:0
                                                              error:&error];

        if (error || ![jsonArray isKindOfClass:[NSArray class]]) {
            fprintf(stderr, "[LayerPanel] JSON parse error: %s\n",
                    error ? [[error localizedDescription] UTF8String] : "not an array");
            dispatch_async(dispatch_get_main_queue(), ^{
                self->_parseInFlight = NO;
            });
            return;
        }

        // Build LayerNode tree from the parsed JSON
        // newTree is +1 from alloc.  dispatch_async copies the block to the
        // heap, which retains captured objects (+1 → +2).  After the block
        // runs, the block releases its reference (→ +1).  The surviving +1
        // is transferred to _treeData via direct ivar assignment below.
        NSMutableArray<LayerNode *> *newTree = [[NSMutableArray alloc] init];
        for (NSDictionary *nodeDict in jsonArray) {
            [newTree addObject:[self parseNodeFromDict:nodeDict]];
        }

        // Swap data and reload on main thread
        dispatch_async(dispatch_get_main_queue(), ^{
            // Save current expansion state before reload
            if (!self->_firstLoad) {
                [self saveExpansionState];
            }

            [self->_treeData release];
            self->_treeData = newTree;  // transfer ownership (+1 from alloc)
            [self->_outlineView reloadData];

            if (self->_firstLoad) {
                // First load: expand all top-level layers by default
                for (LayerNode *node in self->_treeData) {
                    [self->_outlineView expandItem:node];
                    [self->_expandedNodeIDs addObject:@(node.nodeID)];
                }
                self->_firstLoad = NO;
            } else {
                // Restore expansion state
                [self restoreExpansionState];
            }

            [self updateStatusLabel];

            // Check for AI suggestion
            std::string suggestion = BridgeGetLayerSuggestion();
            if (!suggestion.empty()) {
                fprintf(stderr, "[LayerPanel] Suggestion: %s\n", suggestion.c_str());
            }

            self->_parseInFlight = NO;
        });
    });
}

//----------------------------------------------------------------------------------------
//  Recursive JSON -> LayerNode builder
//----------------------------------------------------------------------------------------

- (LayerNode *)parseNodeFromDict:(NSDictionary *)dict
{
    LayerNode *node = [[[LayerNode alloc] init] autorelease];
    node.nodeID     = [dict[@"id"] intValue];
    node.nodeType   = [dict[@"type"] intValue];
    node.name       = dict[@"name"] ?: @"";
    node.visible    = [dict[@"visible"] boolValue];
    node.locked     = [dict[@"locked"] boolValue];
    node.isSelected = [dict[@"selected"] boolValue];
    node.unnamedCount = [dict[@"unnamed"] intValue];

    NSArray *colorArr = dict[@"color"];
    if ([colorArr isKindOfClass:[NSArray class]] && colorArr.count >= 3) {
        node.colorR = [colorArr[0] floatValue];
        node.colorG = [colorArr[1] floatValue];
        node.colorB = [colorArr[2] floatValue];
    }

    NSArray *children = dict[@"children"];
    if ([children isKindOfClass:[NSArray class]]) {
        for (NSDictionary *childDict in children) {
            [node.children addObject:[self parseNodeFromDict:childDict]];
        }
    }

    return node;
}


//========================================================================================
//  NSOutlineView Data Source
//========================================================================================

- (NSInteger)outlineView:(NSOutlineView *)outlineView numberOfChildrenOfItem:(id)item
{
    if (!item) return (NSInteger)_treeData.count;
    return (NSInteger)((LayerNode *)item).children.count;
}

- (id)outlineView:(NSOutlineView *)outlineView child:(NSInteger)index ofItem:(id)item
{
    if (!item) return _treeData[index];
    return ((LayerNode *)item).children[index];
}

- (BOOL)outlineView:(NSOutlineView *)outlineView isItemExpandable:(id)item
{
    return ((LayerNode *)item).children.count > 0;
}


//========================================================================================
//  NSOutlineView Delegate — custom cell views
//========================================================================================

- (NSView *)outlineView:(NSOutlineView *)outlineView
     viewForTableColumn:(NSTableColumn *)tableColumn
                   item:(id)item
{
    LayerNode *node = (LayerNode *)item;
    CGFloat cellW = outlineView.frame.size.width;

    NSView *cellView = [[[NSView alloc] initWithFrame:NSMakeRect(0, 0, cellW, kRowHeight)] autorelease];

    CGFloat x = 0;

    //------------------------------------------------------------------
    //  Eye icon (visibility toggle)
    //------------------------------------------------------------------
    {
        NSString *symbolName = node.visible ? @"eye.fill" : @"eye.slash";
        NSImage *img = [NSImage imageWithSystemSymbolName:symbolName
                                accessibilityDescription:@"Visibility"];
        NSImageView *eyeIcon = [NSImageView imageViewWithImage:img];
        eyeIcon.frame = NSMakeRect(x, 2, 18, 18);
        eyeIcon.contentTintColor = node.visible
            ? [IllToolTheme textColor]
            : [IllToolTheme secondaryTextColor];
        [cellView addSubview:eyeIcon];
        x += 20;
    }

    //------------------------------------------------------------------
    //  Lock icon
    //------------------------------------------------------------------
    {
        NSString *lockSymbol = node.locked ? @"lock.fill" : @"lock.open";
        NSImage *lockImg = [NSImage imageWithSystemSymbolName:lockSymbol
                                    accessibilityDescription:@"Lock"];
        NSImageView *lockIcon = [NSImageView imageViewWithImage:lockImg];
        lockIcon.frame = NSMakeRect(x, 2, 18, 18);
        lockIcon.contentTintColor = node.locked
            ? [IllToolTheme accentColor]
            : [IllToolTheme secondaryTextColor];
        [cellView addSubview:lockIcon];
        x += 20;
    }

    //------------------------------------------------------------------
    //  Name label (editable on double-click for non-collapsed nodes)
    //------------------------------------------------------------------
    {
        NSFont  *font;
        NSColor *color;

        if (node.nodeType == 3) {
            // Collapsed placeholder — dim italic
            NSFontDescriptor *desc = [[IllToolTheme smallFont].fontDescriptor
                fontDescriptorWithSymbolicTraits:NSFontDescriptorTraitItalic];
            font  = [NSFont fontWithDescriptor:desc size:10];
            if (!font) font = [IllToolTheme smallFont];  // fallback
            color = [IllToolTheme secondaryTextColor];
        } else {
            font  = (node.nodeType == 0) ? [IllToolTheme titleFont]
                                         : [IllToolTheme labelFont];
            color = node.isSelected ? [IllToolTheme accentColor]
                                    : [IllToolTheme textColor];
        }

        CGFloat nameLabelW = cellW - x - 24;  // leave room for color dot
        NSTextField *nameLabel = [IllToolTheme makeLabelWithText:node.name
                                                           font:font
                                                          color:color];
        nameLabel.frame = NSMakeRect(x, 1, nameLabelW, 20);

        // Editable on double-click (except collapsed placeholders)
        if (node.nodeType != 3) {
            nameLabel.editable  = YES;
            nameLabel.bordered  = NO;
            nameLabel.drawsBackground = NO;
            nameLabel.delegate  = self;
            nameLabel.tag       = node.nodeID;
        }

        [cellView addSubview:nameLabel];
    }

    //------------------------------------------------------------------
    //  Color dot (layers only, nodeType == 0)
    //------------------------------------------------------------------
    if (node.nodeType == 0) {
        NSView *dot = [[[NSView alloc]
            initWithFrame:NSMakeRect(cellW - 22, 7, 8, 8)] autorelease];
        dot.wantsLayer = YES;
        dot.layer.backgroundColor = [NSColor colorWithRed:node.colorR
                                                    green:node.colorG
                                                     blue:node.colorB
                                                    alpha:1.0].CGColor;
        dot.layer.cornerRadius = 4;
        [cellView addSubview:dot];
    }

    return cellView;
}

//========================================================================================
//  Selection change — log the selected node
//========================================================================================

- (void)outlineViewSelectionDidChange:(NSNotification *)notification
{
    NSIndexSet *selectedRows = _outlineView.selectedRowIndexes;
    if (selectedRows.count == 0) return;

    // For single selection, select the node in Illustrator
    if (selectedRows.count == 1) {
        NSInteger row = selectedRows.firstIndex;
        LayerNode *node = [_outlineView itemAtRow:row];
        if (!node || node.nodeType == 3) return;

        PluginOp op;
        op.type = OpType::LayerSelectNode;
        op.intParam = node.nodeID;
        BridgeEnqueueOp(op);

        fprintf(stderr, "[LayerPanel] Selected node %d: %s\n",
                node.nodeID, node.name.UTF8String);
    } else {
        fprintf(stderr, "[LayerPanel] Multi-selected %lu items\n",
                (unsigned long)selectedRows.count);
    }
}


//========================================================================================
//  Inline rename — NSTextFieldDelegate
//========================================================================================

- (void)controlTextDidEndEditing:(NSNotification *)notification
{
    NSTextField *field = notification.object;
    int nodeID = (int)field.tag;
    NSString *newName = field.stringValue;

    if (!newName || newName.length == 0) return;

    PluginOp op;
    op.type     = OpType::LayerRename;
    op.intParam = nodeID;
    op.strParam = std::string([newName UTF8String]);
    BridgeEnqueueOp(op);

    fprintf(stderr, "[LayerPanel] Rename node %d -> '%s'\n",
            nodeID, [newName UTF8String]);
}


//========================================================================================
//  Visibility / Lock toggle actions
//========================================================================================

- (void)toggleVisibility:(NSButton *)sender
{
    int nodeID = (int)sender.tag;
    LayerNode *node = [self findNodeByID:nodeID];
    if (!node) return;

    PluginOp op;
    op.type      = OpType::LayerSetVisible;
    op.intParam  = nodeID;
    op.boolParam1 = !node.visible;
    BridgeEnqueueOp(op);

    fprintf(stderr, "[LayerPanel] Toggle visibility node %d -> %s\n",
            nodeID, node.visible ? "hidden" : "visible");
}

- (void)toggleLock:(NSButton *)sender
{
    int nodeID = (int)sender.tag;
    LayerNode *node = [self findNodeByID:nodeID];
    if (!node) return;

    PluginOp op;
    op.type      = OpType::LayerSetLocked;
    op.intParam  = nodeID;
    op.boolParam1 = !node.locked;
    BridgeEnqueueOp(op);

    fprintf(stderr, "[LayerPanel] Toggle lock node %d -> %s\n",
            nodeID, node.locked ? "unlocked" : "locked");
}


//========================================================================================
//  Node lookup (recursive)
//========================================================================================

- (LayerNode *)findNodeByID:(int)nodeID
{
    return [self findNodeByID:nodeID inArray:_treeData];
}

- (LayerNode *)findNodeByID:(int)nodeID inArray:(NSArray<LayerNode *> *)nodes
{
    for (LayerNode *node in nodes) {
        if (node.nodeID == nodeID) return node;
        LayerNode *found = [self findNodeByID:nodeID inArray:node.children];
        if (found) return found;
    }
    return nil;
}


//========================================================================================
//  Toolbar button actions
//========================================================================================

- (void)onAddLayer:(id)sender
{
    PluginOp op;
    op.type    = OpType::LayerCreate;
    op.strParam = std::string([kITS_NewLayer UTF8String]);
    BridgeEnqueueOp(op);
    fprintf(stderr, "[LayerPanel] Add layer\n");
}

- (void)onAutoOrganize:(id)sender
{
    PluginOp op;
    op.type = OpType::LayerAutoOrganize;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[LayerPanel] Auto-organize\n");
}

- (void)onGroupSelected:(id)sender
{
    // Group all selected items via Cmd+G
    NSIndexSet *selectedRows = _outlineView.selectedRowIndexes;
    if (selectedRows.count < 1) return;

    // First, select them all in Illustrator (multi-select).
    // The first SelectNode clears existing selection (addToSelection=false),
    // subsequent ones add to it (addToSelection=true).
    __block BOOL isFirst = YES;
    [selectedRows enumerateIndexesUsingBlock:^(NSUInteger idx, BOOL *stop) {
        LayerNode *node = [self->_outlineView itemAtRow:idx];
        if (node && node.nodeType != 3) {
            PluginOp selOp;
            selOp.type = OpType::LayerSelectNode;
            selOp.intParam = node.nodeID;
            selOp.boolParam1 = !isFirst;  // addToSelection for 2nd+ items
            BridgeEnqueueOp(selOp);
            isFirst = NO;
        }
    }];

    // Then group them
    PluginOp op;
    op.type = OpType::LayerGroupSelected;
    op.strParam = std::string([kITS_Group UTF8String]);
    BridgeEnqueueOp(op);
    fprintf(stderr, "[LayerPanel] Group %lu selected items\n", (unsigned long)selectedRows.count);
}

- (void)onToggleVisibilitySelected:(id)sender
{
    NSIndexSet *rows = _outlineView.selectedRowIndexes;
    // Determine target state from first selected item
    LayerNode *first = [_outlineView itemAtRow:rows.firstIndex];
    if (!first || first.nodeType == 3) return;
    BOOL targetState = !first.visible;

    [rows enumerateIndexesUsingBlock:^(NSUInteger idx, BOOL *stop) {
        LayerNode *node = [self->_outlineView itemAtRow:idx];
        if (!node || node.nodeType == 3) return;
        PluginOp op;
        op.type = OpType::LayerSetVisible;
        op.intParam = node.nodeID;
        op.boolParam1 = targetState;
        BridgeEnqueueOp(op);
    }];
    fprintf(stderr, "[LayerPanel] Cmd+H toggle visibility %lu items → %s\n",
            (unsigned long)rows.count, targetState ? "visible" : "hidden");
}

- (void)onToggleLockSelected:(id)sender
{
    NSIndexSet *rows = _outlineView.selectedRowIndexes;
    LayerNode *first = [_outlineView itemAtRow:rows.firstIndex];
    if (!first || first.nodeType == 3) return;
    BOOL targetState = !first.locked;

    [rows enumerateIndexesUsingBlock:^(NSUInteger idx, BOOL *stop) {
        LayerNode *node = [self->_outlineView itemAtRow:idx];
        if (!node || node.nodeType == 3) return;
        PluginOp op;
        op.type = OpType::LayerSetLocked;
        op.intParam = node.nodeID;
        op.boolParam1 = targetState;
        BridgeEnqueueOp(op);
    }];
    fprintf(stderr, "[LayerPanel] Cmd+L toggle lock %lu items → %s\n",
            (unsigned long)rows.count, targetState ? "locked" : "unlocked");
}

- (void)onMoveUp:(id)sender
{
    NSInteger row = _outlineView.selectedRow;
    if (row < 0) return;
    LayerNode *node = [_outlineView itemAtRow:row];
    if (!node || node.nodeType == 3) return;

    // Find the sibling above to reorder relative to
    if (row > 0) {
        LayerNode *above = [_outlineView itemAtRow:row - 1];
        if (above) {
            PluginOp op;
            op.type = OpType::LayerReorder;
            op.intParam = node.nodeID;
            op.param1 = (double)above.nodeID;
            op.boolParam1 = true;  // place above
            BridgeEnqueueOp(op);
            fprintf(stderr, "[LayerPanel] Move up node %d above %d\n", node.nodeID, above.nodeID);
        }
    }
}

- (void)onMoveDown:(id)sender
{
    NSInteger row = _outlineView.selectedRow;
    if (row < 0) return;
    LayerNode *node = [_outlineView itemAtRow:row];
    if (!node || node.nodeType == 3) return;

    if (row < _outlineView.numberOfRows - 1) {
        LayerNode *below = [_outlineView itemAtRow:row + 1];
        if (below) {
            PluginOp op;
            op.type = OpType::LayerReorder;
            op.intParam = node.nodeID;
            op.param1 = (double)below.nodeID;
            op.boolParam1 = false;  // place below
            BridgeEnqueueOp(op);
            fprintf(stderr, "[LayerPanel] Move down node %d below %d\n", node.nodeID, below.nodeID);
        }
    }
}

- (void)onDeleteSelected:(id)sender
{
    NSInteger row = _outlineView.selectedRow;
    if (row < 0) return;
    LayerNode *node = [_outlineView itemAtRow:row];
    if (!node || node.nodeType == 3) return;

    PluginOp op;
    op.type = OpType::LayerDelete;
    op.intParam = node.nodeID;
    BridgeEnqueueOp(op);
    fprintf(stderr, "[LayerPanel] Delete node %d\n", node.nodeID);
}

- (void)onPresetSelected:(NSPopUpButton *)sender
{
    NSString *selected = sender.titleOfSelectedItem;

    if ([selected isEqualToString:kITS_SavePresetDots]) {
        // Show save dialog
        NSAlert *alert = [[[NSAlert alloc] init] autorelease];
        alert.messageText = kITS_SaveLayerPreset;
        alert.informativeText = kITS_EnterPresetName;
        [alert addButtonWithTitle:kITS_Save];
        [alert addButtonWithTitle:kITS_Cancel];

        NSTextField *input = [[[NSTextField alloc]
            initWithFrame:NSMakeRect(0, 0, 200, 24)] autorelease];
        input.stringValue = kITS_MyPreset;
        alert.accessoryView = input;

        if ([alert runModal] == NSAlertFirstButtonReturn) {
            PluginOp op;
            op.type    = OpType::LayerPresetSave;
            op.strParam = std::string([input.stringValue UTF8String]);
            BridgeEnqueueOp(op);
            fprintf(stderr, "[LayerPanel] Save preset: '%s'\n",
                    [input.stringValue UTF8String]);
        }

        // Reset selection back to first item
        [sender selectItemAtIndex:0];
        return;
    }

    if (![selected isEqualToString:kITS_NoPreset]) {
        PluginOp op;
        op.type    = OpType::LayerPresetLoad;
        op.strParam = std::string([selected UTF8String]);
        BridgeEnqueueOp(op);
        fprintf(stderr, "[LayerPanel] Load preset: '%s'\n", [selected UTF8String]);
    }
}


//========================================================================================
//  Drag and Drop — NSOutlineView data source methods
//========================================================================================

- (id<NSPasteboardWriting>)outlineView:(NSOutlineView *)outlineView
               pasteboardWriterForItem:(id)item
{
    LayerNode *node = (LayerNode *)item;
    if (node.nodeType == 3) return nil;  // can't drag collapsed placeholder

    NSPasteboardItem *pbItem = [[[NSPasteboardItem alloc] init] autorelease];
    [pbItem setString:[NSString stringWithFormat:@"%d", node.nodeID]
              forType:kLayerNodePBType];
    return pbItem;
}

- (NSDragOperation)outlineView:(NSOutlineView *)outlineView
                  validateDrop:(id<NSDraggingInfo>)info
                  proposedItem:(id)item
            proposedChildIndex:(NSInteger)index
{
    // Don't allow drop onto collapsed placeholders
    if (item && ((LayerNode *)item).nodeType == 3) return NSDragOperationNone;

    // Auto-expand: when hovering over an expandable item for 2 seconds, expand it
    if (item != _dragHoverItem) {
        // Hovering over a new item — reset timer
        [_dragHoverTimer invalidate];
        _dragHoverTimer = nil;
        _dragHoverItem = item;

        if (item && [outlineView isExpandable:item] && ![outlineView isItemExpanded:item]) {
            _dragHoverTimer = [NSTimer scheduledTimerWithTimeInterval:2.0
                                                              target:self
                                                            selector:@selector(dragHoverExpand:)
                                                            userInfo:item
                                                             repeats:NO];
        }
    }

    return NSDragOperationMove;
}

- (void)dragHoverExpand:(NSTimer *)timer
{
    id item = timer.userInfo;
    if (item) {
        [_outlineView expandItem:item];
        [_expandedNodeIDs addObject:@(((LayerNode *)item).nodeID)];
        fprintf(stderr, "[LayerPanel] Auto-expanded hover target: %s\n",
                ((LayerNode *)item).name.UTF8String);
    }
    _dragHoverTimer = nil;
    _dragHoverItem = nil;
}

- (BOOL)outlineView:(NSOutlineView *)outlineView
         acceptDrop:(id<NSDraggingInfo>)info
               item:(id)item
         childIndex:(NSInteger)index
{
    // Clean up hover timer
    [_dragHoverTimer invalidate];
    _dragHoverTimer = nil;
    _dragHoverItem = nil;

    NSArray<NSPasteboardItem *> *pbItems = info.draggingPasteboard.pasteboardItems;
    if (!pbItems || pbItems.count == 0) return NO;

    LayerNode *targetNode = (LayerNode *)item;
    int dstID = targetNode ? targetNode.nodeID : 0;  // 0 = root level

    int moved = 0;
    for (NSPasteboardItem *pbItem in pbItems) {
        NSString *srcIDStr = [pbItem stringForType:kLayerNodePBType];
        if (!srcIDStr) continue;

        int srcID = [srcIDStr intValue];

        PluginOp op;
        op.type      = OpType::LayerReorder;
        op.intParam  = srcID;
        op.param1    = (double)dstID;
        op.param2    = (double)index;
        op.boolParam1 = (index == 0);
        BridgeEnqueueOp(op);
        moved++;
    }

    fprintf(stderr, "[LayerPanel] Reorder %d items -> parent %d at index %ld\n",
            moved, dstID, (long)index);
    return (moved > 0);
}


//========================================================================================
//  Status bar update
//========================================================================================

//========================================================================================
//  Expansion state management
//========================================================================================

- (void)saveExpansionState
{
    [_expandedNodeIDs removeAllObjects];
    [self saveExpansionStateForNodes:_treeData];
}

- (void)saveExpansionStateForNodes:(NSArray<LayerNode *> *)nodes
{
    for (LayerNode *node in nodes) {
        if ([_outlineView isItemExpanded:node]) {
            [_expandedNodeIDs addObject:@(node.nodeID)];
        }
        if (node.children.count > 0) {
            [self saveExpansionStateForNodes:node.children];
        }
    }
}

- (void)restoreExpansionState
{
    [self restoreExpansionStateForNodes:_treeData];
}

- (void)restoreExpansionStateForNodes:(NSArray<LayerNode *> *)nodes
{
    for (LayerNode *node in nodes) {
        if ([_expandedNodeIDs containsObject:@(node.nodeID)]) {
            [_outlineView expandItem:node];
        }
        if (node.children.count > 0) {
            [self restoreExpansionStateForNodes:node.children];
        }
    }
}

- (void)collapseAll
{
    [_expandedNodeIDs removeAllObjects];
    [_outlineView collapseItem:nil collapseChildren:YES];
}

// NSOutlineView delegate: Option+click on disclosure triangle collapses/expands all
- (void)outlineViewItemWillCollapse:(NSNotification *)notification
{
    NSEvent *event = [NSApp currentEvent];
    if (event && (event.modifierFlags & NSEventModifierFlagOption)) {
        // Option+collapse: collapse everything
        dispatch_async(dispatch_get_main_queue(), ^{
            [self collapseAll];
        });
    }
}

- (void)outlineViewItemWillExpand:(NSNotification *)notification
{
    NSEvent *event = [NSApp currentEvent];
    if (event && (event.modifierFlags & NSEventModifierFlagOption)) {
        // Option+expand: expand everything
        dispatch_async(dispatch_get_main_queue(), ^{
            [self expandAll];
        });
    }
}

- (void)expandAll
{
    [_outlineView expandItem:nil expandChildren:YES];
    // Record all expandable node IDs
    [self saveExpansionState];
}

// Track manual expand/collapse to keep expandedNodeIDs current
- (void)outlineViewItemDidExpand:(NSNotification *)notification
{
    LayerNode *node = notification.userInfo[@"NSObject"];
    if (node) [_expandedNodeIDs addObject:@(node.nodeID)];
}

- (void)outlineViewItemDidCollapse:(NSNotification *)notification
{
    LayerNode *node = notification.userInfo[@"NSObject"];
    if (node) [_expandedNodeIDs removeObject:@(node.nodeID)];
}


//========================================================================================
//  Status bar update
//========================================================================================

- (void)updateStatusLabel
{
    int layerCount  = 0;
    int objectCount = 0;
    for (LayerNode *node in _treeData) {
        layerCount++;
        objectCount += [self countObjects:node];
    }
    _statusLabel.stringValue = [NSString stringWithFormat:kITS_LayerCountFmt,
                                layerCount, objectCount];
}

- (int)countObjects:(LayerNode *)node
{
    int count = (node.nodeType == 2) ? 1 : 0;  // paths are objects
    count += node.unnamedCount;                  // collapsed unnamed items
    for (LayerNode *child in node.children) {
        count += [self countObjects:child];
    }
    return count;
}

@end
