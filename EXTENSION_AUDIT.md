# Extension v3 Status Audit (2026-10-04)

## Summary
Extension v0.2.6 is in a **broken, non-loadable state**.

## Missing Files (Critical)
1. **extension/src/popup.html** - Referenced in manifest.json as `default_popup`, DOES NOT EXIST
   - Impact: Chrome will fail to load the extension or show broken popup
   
2. **extension/src/popup.js** - Companion to popup.html, DOES NOT EXIST
   
3. **extension/icons/** - Directory DOES NOT EXIST
   - icon128.png, icon48.png missing
   - Impact: Extension will show default icon (minor)

## Existing Files
- extension/src/background.js (v0.2.6) - EXISTS, routes messages to offscreen
- extension/src/content.js (v0.2.6) - EXISTS, captures Muse DOM text
- extension/src/offscreen.html - EXISTS
- extension/src/offscreen.js (v0.2.6) - EXISTS, WebSocket + audio playback
- extension/manifest.json (v0.2.6) - EXISTS, references missing popup.html

## Test Handler Status
- **background.js**: No `test_audio` / `test_text` message handlers
- **offscreen.js**: No test handlers (needs full review)
- **server/tts_server.py**: No test handlers (v3 uses turn_start/text_delta protocol)

The v0.2.5 popup test features (from commit 0234b59) were deleted in v3 rebuild
(commit 632a182) and not restored.

## Content Script Status
- content.js uses selector strategies for Muse DOM capture
- Strategies: `[data-hatch-markdown-streaming="true"]`, `[data-testid*="assistant"]`, etc.
- **Not verified** against actual Muse DOM (per project notes: "실제 Muse DOM capture도 아직 검증되지 않았다")

## Required Actions (Deferred)
1. Restore popup.html/popup.js from Lim's local files (not in repo)
2. Restore icons/ from Lim's local files (not in repo)
3. OR: Remove popup reference from manifest.json if popup not needed for v3
4. Implement test handlers OR document websocket_test.py as the test method
5. Verify content.js selectors against real Muse DOM

## Recommendation
Given that websocket_test.py is now the primary test tool (per user instruction),
the popup test UI may be optional. However, the manifest MUST NOT reference
non-existent files. Either restore the popup files or remove the reference.
