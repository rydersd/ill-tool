# Continuity Ledger: C++ Plugin Loading

## Goal
Get the IllTool C++ Illustrator plugin to load and execute in Adobe Illustrator 2026.

## Key Discovery
- Illustrator 2026 loads the plugin binary into memory (confirmed via `vmmap`/`lsof`) but **blocks it from initializing** (SafeMode system)
- The "Plugin issues detected" warning is NOT cosmetic — the plugin is dlopen'd but PluginMain never executes
- Adobe's own SDK Annotator sample shows the SAME behavior with ad-hoc signing
- **All working third-party plugins (Astute) are notarized with Developer ID**
- Illustrator has `com.apple.security.cs.disable-library-validation = true` — so it's not macOS blocking, it's Illustrator's own SafeMode checking notarization status

## Blocker
Apple notarization fails with HTTP 403: "A required agreement is missing or has expired." User signed an agreement on developer.apple.com today but it hasn't propagated. Likely resolves within 24h.

## What Works
- [x] Official Adobe Illustrator 2026 SDK downloaded to `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/`
- [x] SDK Annotator sample builds cleanly with xcodebuild
- [x] IllTool plugin built from cloned Annotator sample — proper SDK Plugin base class, PiPL via create_pipl.py
- [x] Developer ID Application cert created (Ryder Booth, ASH39KMW4S)
- [x] Plugin binary loads in memory (confirmed via lsof)
- [x] Additional Plug-ins Folder set up at `~/Developer/ai-plugins`
- [x] All CEP panels removed (user wants everything rebuilt in C++)

## Current State
- [→] Waiting for Apple agreement propagation to enable notarization
- Next: notarize → staple → restart Illustrator → tool should appear

## Once Notarization Works — Run These Commands
```bash
# 1. Sign with Developer ID
codesign --force --sign "Developer ID Application: Ryder Booth (ASH39KMW4S)" --deep --options runtime \
  '/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/samplecode/output/mac/release/IllTool.aip'

# 2. Zip for submission
cd '/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/samplecode/output/mac/release/'
zip -r /tmp/IllTool.zip IllTool.aip

# 3. Submit for notarization
xcrun notarytool submit /tmp/IllTool.zip \
  --apple-id "ryder@rydersdesign.com" \
  --team-id "ASH39KMW4S" \
  --password "tjki-awei-bnuk-wmty" \
  --wait

# 4. Staple the notarization ticket
xcrun stapler staple \
  '/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/samplecode/output/mac/release/IllTool.aip'

# 5. Copy to dev plugins folder
cp -R '/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/samplecode/output/mac/release/IllTool.aip' \
  ~/Developer/ai-plugins/IllTool.aip

# 6. Clear caches and restart Illustrator
rm -f ~/Library/Preferences/Adobe\ Illustrator\ 30\ Settings/en_US/aggressivePlugincache_v2.bin
rm -f ~/Library/Preferences/Adobe\ Illustrator\ 30\ Settings/en_US/AggressiveDelayLoad-Plug-in\ Cache
```

## Remaining After Plugin Loads
- [ ] Add HTTP bridge (port 8787) to IllToolPlugin for CEP/external communication
- [ ] Verify annotator draws on canvas (test circle)
- [ ] Verify custom tool appears in toolbox and receives mouse events
- [ ] Add LLM client (Claude API via NSURLSession)
- [ ] Build panel UI (replaces removed CEP panels)
- [ ] Wire overlays: simplification handles, bounding box, cluster visualization, merge preview
- [ ] Icon: filled square SVG for toolbox

## Working Set
- SDK project: `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK/samplecode/IllTool/`
- Build output: `samplecode/output/mac/release/IllTool.aip`
- Xcode project: `IllTool.xcodeproj` (renamed from Annotator)
- Dev plugins folder: `~/Developer/ai-plugins/`
- Build command: `xcodebuild -project '.../IllTool.xcodeproj' -configuration release -arch arm64 build`
- Old CMake plugin (deprecated): `/Users/ryders/Developer/GitHub/ill_tool/plugin/` — superseded by SDK-based build
