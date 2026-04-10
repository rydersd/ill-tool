#!/bin/bash
# Add new module files to the IllTool Xcode project pbxproj
# Run AFTER copying source files to SDK

PBXPROJ="/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/IllTool.xcodeproj/project.pbxproj"

# New files and their IDs (file ref / build file)
# Format: FILEREF_ID BUILD_ID NAME PATH
NEW_FILES=(
  "AABB00001E AABB00001F ShapeUtils.cpp Source/ShapeUtils.cpp"
  # IllToolModuleImpl.cpp removed — implementations in CleanupModule.cpp
  "AABB000022 AABB000023 CleanupModule.cpp Source/modules/CleanupModule.cpp"
  "AABB000024 AABB000025 PerspectiveModule.cpp Source/modules/PerspectiveModule.cpp"
  "AABB000026 AABB000027 SelectionModule.cpp Source/modules/SelectionModule.cpp"
  "AABB000028 AABB000029 MergeModule.cpp Source/modules/MergeModule.cpp"
  "AABB00002A AABB00002B GroupingModule.cpp Source/modules/GroupingModule.cpp"
  "AABB00002C AABB00002D BlendModule.cpp Source/modules/BlendModule.cpp"
  "AABB00002E AABB00002F ShadingModule.cpp Source/modules/ShadingModule.cpp"
  "AABB000030 AABB000031 DecomposeModule.cpp Source/modules/DecomposeModule.cpp"
)

# Backup
cp "$PBXPROJ" "${PBXPROJ}.bak"

for entry in "${NEW_FILES[@]}"; do
  read -r FREF BFILE NAME FPATH <<< "$entry"

  # Add PBXBuildFile entry (after the last AABB build file)
  sed -i '' "/AABB00001D0E2FB5A200AABB.*in Sources/a\\
\\		${BFILE}0E2FB5A200AABB /* ${NAME} in Sources */ = {isa = PBXBuildFile; fileRef = ${FREF}0E2FB5A200AABB /* ${NAME} */; };" "$PBXPROJ"

  # Add PBXFileReference entry (after the last AABB file ref)
  sed -i '' "/AABB00001C0E2FB5A200AABB.*IllToolDecompose.cpp.*PBXFileReference/a\\
\\		${FREF}0E2FB5A200AABB /* ${NAME} */ = {isa = PBXFileReference; fileEncoding = 4; lastKnownFileType = sourcecode.cpp.cpp; name = ${NAME}; path = ${FPATH}; sourceTree = \"<group>\"; };" "$PBXPROJ"

  # Add to group children (after IllToolDecompose.cpp in the group)
  sed -i '' "/AABB00001C0E2FB5A200AABB.*IllToolDecompose.cpp.*,$/a\\
\\				${FREF}0E2FB5A200AABB /* ${NAME} */," "$PBXPROJ"

  # Add to sources build phase (after IllToolDecompose.cpp in Sources)
  sed -i '' "/AABB00001D0E2FB5A200AABB.*IllToolDecompose.cpp in Sources/a\\
\\				${BFILE}0E2FB5A200AABB /* ${NAME} in Sources */," "$PBXPROJ"

  echo "Added: $NAME ($FPATH)"
done

echo "pbxproj updated. Verify with: xcodebuild -project ... -list"
