#!/bin/bash
# IllTool deploy: build → copy → sign → notarize → staple
# Usage: bash plugin/tools/deploy.sh
set -euo pipefail

SDK="/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool"
SDK_SRC="$SDK/Source"
OUTPUT="$SDK/../output/mac/debug/IllTool.aip"
INSTALL=~/Developer/ai-plugins/IllTool.aip
IDENTITY="Developer ID Application: Ryder Booth (ASH39KMW4S)"

echo "=== Step 1: Copy source files to SDK ==="
rm -f "$SDK_SRC/modules/"*.cpp "$SDK_SRC/modules/"*.h
cp plugin/Source/*.cpp plugin/Source/*.h "$SDK_SRC/"
cp plugin/Source/modules/*.cpp plugin/Source/modules/*.h "$SDK_SRC/modules/"
cp plugin/Source/panels/*.mm plugin/Source/panels/*.h "$SDK_SRC/panels/"

echo "=== Step 2: Build ==="
cd "$SDK"
xcodebuild -project IllTool.xcodeproj -configuration Release -arch arm64 build 2>&1 | tail -3
cd - > /dev/null

echo "=== Step 3: Install ==="
rm -rf "$INSTALL"
cp -R "$OUTPUT" "$INSTALL"
find "$INSTALL" -name "*.cstemp" -delete

echo "=== Step 4: Codesign ==="
codesign --force --sign "$IDENTITY" --deep --options runtime --timestamp "$INSTALL"

echo "=== Step 5: Notarize ==="
cd /tmp && rm -f IllTool.zip
zip -r IllTool.zip "$INSTALL" > /dev/null
xcrun notarytool submit IllTool.zip --keychain-profile "notarytool" --wait

echo "=== Step 6: Staple ==="
xcrun stapler staple "$INSTALL"

echo "=== DONE — restart Illustrator ==="
