// IllTool-UI.ai — UI Skin File Generator
// Run in Illustrator: File > Scripts > Other Script > select this file
// Creates named art objects for cursors, handles, and icons.
// Save as ~/Developer/ai-plugins/IllTool-UI.ai

function rgb(r,g,b) {
    var c = new RGBColor();
    c.red = r; c.green = g; c.blue = b;
    return c;
}

// Create document
var doc = app.documents.add(DocumentColorSpace.RGB, 800, 600);
doc.defaultFillColor = new NoColor();

// Rename default layer
doc.layers[0].name = "Cursors";
var handlesLayer = doc.layers.add();
handlesLayer.name = "Handles";
var labelsLayer = doc.layers.add();
labelsLayer.name = "Labels";

var cursorsLayer = doc.layers.getByName("Cursors");

// ============================================================
//  CURSORS
// ============================================================

// --- Pick A: arrow pointer + blue "A" badge ---
var gA = cursorsLayer.groupItems.add();
gA.name = "cursor-pick-a";

var arrowA = gA.pathItems.add();
arrowA.setEntirePath([[20,520],[20,380],[70,430],[110,340],[140,360],[100,450],[160,450]]);
arrowA.closed = true;
arrowA.filled = true;
arrowA.fillColor = rgb(0,0,0);
arrowA.stroked = true;
arrowA.strokeColor = rgb(255,255,255);
arrowA.strokeWidth = 2;
arrowA.name = "arrow";

var badgeA = gA.pathItems.ellipse(560, 130, 56, 56);
badgeA.filled = true;
badgeA.fillColor = rgb(72, 184, 224);
badgeA.stroked = true;
badgeA.strokeColor = rgb(255,255,255);
badgeA.strokeWidth = 2;
badgeA.name = "badge";

var tA = gA.textFrames.add();
tA.contents = "A";
tA.position = [144, 552];
tA.textRange.characterAttributes.size = 36;
tA.textRange.characterAttributes.fillColor = rgb(255,255,255);
tA.name = "label";

// --- Pick B: arrow pointer + orange "B" badge ---
var gB = cursorsLayer.groupItems.add();
gB.name = "cursor-pick-b";

var arrowB = gB.pathItems.add();
arrowB.setEntirePath([[250,520],[250,380],[300,430],[340,340],[370,360],[330,450],[390,450]]);
arrowB.closed = true;
arrowB.filled = true;
arrowB.fillColor = rgb(0,0,0);
arrowB.stroked = true;
arrowB.strokeColor = rgb(255,255,255);
arrowB.strokeWidth = 2;
arrowB.name = "arrow";

var badgeB = gB.pathItems.ellipse(560, 360, 56, 56);
badgeB.filled = true;
badgeB.fillColor = rgb(224, 120, 72);
badgeB.stroked = true;
badgeB.strokeColor = rgb(255,255,255);
badgeB.strokeWidth = 2;
badgeB.name = "badge";

var tB = gB.textFrames.add();
tB.contents = "B";
tB.position = [374, 552];
tB.textRange.characterAttributes.size = 36;
tB.textRange.characterAttributes.fillColor = rgb(255,255,255);
tB.name = "label";

// --- Lasso cursor: arrow + dotted polygon tail ---
var gL = cursorsLayer.groupItems.add();
gL.name = "cursor-lasso";

var arrowL = gL.pathItems.add();
arrowL.setEntirePath([[480,520],[480,380],[530,430],[570,340],[600,360],[560,450],[620,450]]);
arrowL.closed = true;
arrowL.filled = true;
arrowL.fillColor = rgb(0,0,0);
arrowL.stroked = true;
arrowL.strokeColor = rgb(255,255,255);
arrowL.strokeWidth = 2;
arrowL.name = "arrow";

var polyL = gL.pathItems.add();
polyL.setEntirePath([[560,420],[590,350],[640,370],[630,320],[580,330]]);
polyL.closed = false;
polyL.filled = false;
polyL.stroked = true;
polyL.strokeColor = rgb(136,136,136);
polyL.strokeWidth = 1;
polyL.strokeDashes = [4,3];
polyL.name = "polygon-tail";

// --- Eyedropper cursor ---
var gE = cursorsLayer.groupItems.add();
gE.name = "cursor-eyedropper";

var eyeBody = gE.pathItems.add();
eyeBody.setEntirePath([[710,520],[730,480],[750,460],[740,440],[720,460],[700,480]]);
eyeBody.closed = true;
eyeBody.filled = true;
eyeBody.fillColor = rgb(60,60,60);
eyeBody.stroked = true;
eyeBody.strokeColor = rgb(255,255,255);
eyeBody.strokeWidth = 1.5;
eyeBody.name = "body";

// ============================================================
//  HANDLES
// ============================================================

// --- Bounding box handle (circle, white fill, dark stroke) ---
var gBBox = handlesLayer.groupItems.add();
gBBox.name = "handle-bbox";
var hBBox = gBBox.pathItems.ellipse(270, 50, 16, 16);
hBBox.filled = true;
hBBox.fillColor = rgb(255,255,255);
hBBox.stroked = true;
hBBox.strokeColor = rgb(51,51,51);
hBBox.strokeWidth = 1;

// --- Anchor handle (square, white fill, dark stroke) ---
var gAnch = handlesLayer.groupItems.add();
gAnch.name = "handle-anchor";
var hAnch = gAnch.pathItems.rectangle(270, 100, 14, 14);
hAnch.filled = true;
hAnch.fillColor = rgb(255,255,255);
hAnch.stroked = true;
hAnch.strokeColor = rgb(51,51,51);
hAnch.strokeWidth = 1;

// --- VP1 handle (circle, red) ---
var gVP1 = handlesLayer.groupItems.add();
gVP1.name = "handle-vp1";
var hVP1 = gVP1.pathItems.ellipse(270, 150, 20, 20);
hVP1.filled = true;
hVP1.fillColor = rgb(255, 77, 77);
hVP1.stroked = true;
hVP1.strokeColor = rgb(204, 0, 0);
hVP1.strokeWidth = 1;

// --- VP2 handle (circle, green) ---
var gVP2 = handlesLayer.groupItems.add();
gVP2.name = "handle-vp2";
var hVP2 = gVP2.pathItems.ellipse(270, 200, 20, 20);
hVP2.filled = true;
hVP2.fillColor = rgb(77, 204, 77);
hVP2.stroked = true;
hVP2.strokeColor = rgb(0, 153, 0);
hVP2.strokeWidth = 1;

// --- VP3 handle (circle, blue) ---
var gVP3 = handlesLayer.groupItems.add();
gVP3.name = "handle-vp3";
var hVP3 = gVP3.pathItems.ellipse(270, 250, 20, 20);
hVP3.filled = true;
hVP3.fillColor = rgb(77, 128, 255);
hVP3.stroked = true;
hVP3.strokeColor = rgb(0, 51, 204);
hVP3.strokeWidth = 1;

// --- Active handle (orange glow for selected/active state) ---
var gActive = handlesLayer.groupItems.add();
gActive.name = "handle-active";
var hActive = gActive.pathItems.ellipse(270, 310, 18, 18);
hActive.filled = true;
hActive.fillColor = rgb(255, 165, 0);
hActive.stroked = true;
hActive.strokeColor = rgb(200, 100, 0);
hActive.strokeWidth = 1.5;

// --- Hover handle (slightly larger, subtle highlight) ---
var gHover = handlesLayer.groupItems.add();
gHover.name = "handle-hover";
var hHover = gHover.pathItems.ellipse(270, 360, 20, 20);
hHover.filled = true;
hHover.fillColor = rgb(230, 240, 255);
hHover.stroked = true;
hHover.strokeColor = rgb(100, 150, 220);
hHover.strokeWidth = 1;

// ============================================================
//  LABELS
// ============================================================

var labelData = [
    ["cursor-pick-a", 40, 570],
    ["cursor-pick-b", 270, 570],
    ["cursor-lasso", 500, 570],
    ["cursor-eyedropper", 700, 570],
    ["handle-bbox", 46, 300],
    ["handle-anchor", 96, 300],
    ["handle-vp1", 148, 300],
    ["handle-vp2", 198, 300],
    ["handle-vp3", 248, 300],
    ["handle-active", 308, 300],
    ["handle-hover", 358, 300]
];

for (var i = 0; i < labelData.length; i++) {
    var lbl = labelsLayer.textFrames.add();
    lbl.contents = labelData[i][0];
    lbl.position = [labelData[i][1], labelData[i][2]];
    lbl.textRange.characterAttributes.size = 8;
    lbl.textRange.characterAttributes.fillColor = rgb(128,128,128);
    lbl.name = "label-" + labelData[i][0];
}

// Save instructions
alert("IllTool-UI.ai created!\\n\\nSave as:\\n~/Developer/ai-plugins/IllTool-UI.ai\\n\\nElements: 4 cursors, 7 handles, 11 labels");
