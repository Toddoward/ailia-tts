// Ailia TTS v3 - Content Script
// Captures Muse AI's streaming text and forwards to the TTS server.
const VERSION = '3.0.0';
console.log(`[ailia-tts] content v${VERSION} loaded`);

let currentTurnId = null;
let lastText = '';
let observer = null;

function findAssistantMessages() {
  // Multiple selector strategies, most specific first
  const strategies = [
    '[data-hatch-markdown-streaming="true"]',
    '[data-testid*="assistant"]',
    'div[class*="assistant"]',
  ];
  for (const sel of strategies) {
    const els = document.querySelectorAll(sel);
    if (els.length > 0) return els;
  }
  return [];
}

function extractText(el) {
  // Exclude code blocks
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let text = '';
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentElement;
    if (parent && (parent.closest('pre') || parent.closest('code'))) continue;
    text += node.textContent;
  }
  return text;
}

function sendMessage(msg) {
  chrome.runtime.sendMessage({ ...msg, source: 'content' }).catch(() => {});
}

function startTurn() {
  currentTurnId = 'turn_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
  lastText = '';
  sendMessage({ type: 'turn_start', turnId: currentTurnId });
  console.log(`[ailia-tts] turn start: ${currentTurnId}`);
}

function sendDelta(fullText) {
  if (fullText === lastText) return;
  // Simple diff: send only new text
  let newText = fullText;
  if (fullText.startsWith(lastText)) {
    newText = fullText.slice(lastText.length);
  } else {
    // Text changed unexpectedly; resync
    sendMessage({ type: 'text_delta', turnId: currentTurnId, text: fullText, resync: true });
    lastText = fullText;
    return;
  }
  if (newText) {
    sendMessage({ type: 'text_delta', turnId: currentTurnId, text: newText });
    lastText = fullText;
  }
}

function endTurn() {
  if (!currentTurnId) return;
  sendMessage({ type: 'turn_end', turnId: currentTurnId });
  console.log(`[ailia-tts] turn end: ${currentTurnId}`);
  currentTurnId = null;
  lastText = '';
}

function checkForStreaming() {
  const messages = findAssistantMessages();
  let found = false;
  for (const el of messages) {
    const streaming = el.getAttribute('data-hatch-markdown-streaming') === 'true';
    if (streaming) {
      found = true;
      if (!currentTurnId) startTurn();
      const text = extractText(el);
      sendDelta(text);
      // Mark this element as tracked
      el.dataset.ailiaTracked = '1';
    }
  }
  // If we had a turn but no streaming element found, the turn ended
  if (currentTurnId && !found) {
    // Double-check: look for tracked elements that are no longer streaming
    const tracked = document.querySelectorAll('[data-ailia-tracked="1"]');
    let stillActive = false;
    for (const el of tracked) {
      if (el.getAttribute('data-hatch-markdown-streaming') === 'true') {
        stillActive = true;
        break;
      }
    }
    if (!stillActive) endTurn();
  }
}

function init() {
  observer = new MutationObserver(() => checkForStreaming());
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  checkForStreaming();
  console.log('[ailia-tts] content script ready');
}

// Cancel on navigation
window.addEventListener('beforeunload', () => {
  if (currentTurnId) {
    sendMessage({ type: 'cancel', turnId: currentTurnId });
  }
});

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
