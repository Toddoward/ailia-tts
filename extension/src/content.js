// Ailia TTS — content script v0.2.0 (localhost streaming mode)
// Watches Muse chat DOM for streaming assistant responses,
// forwards raw text deltas to background for bi-streaming TTS.
// No sentence chunking — the TTS server handles streaming.

(() => {
  'use strict';

  const VERSION = '0.2.0';
  function log(...args) { console.log('[ailia-tts][content]', ...args); }

  log(`content script v${VERSION} loaded on`, location.href);

  // --- Text sanitization (light) -----------------------------------------
  // Only strip emojis; keep everything else for the TTS server.
  const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}]/gu;

  function sanitizeText(text) {
    return text.replace(EMOJI_RE, '').trim();
  }

  // --- Streaming detection -----------------------------------------------
  function isAssistantBubble(el) {
    const cls = el.className || '';
    if (typeof cls === 'string' && cls.includes('hatch-agent-bubble-bg')) return true;
    const style = el.getAttribute('style') || '';
    if (style.includes('hatch-agent-bubble-bg')) return true;
    return false;
  }

  function findStreamingBubble() {
    const streamingEls = document.querySelectorAll('[data-hatch-markdown-streaming="true"]');
    for (const se of streamingEls) {
      let el = se;
      while (el && el !== document.body) {
        if (el.classList && el.classList.contains('hatch-chat-groupable-bubble')) {
          if (isAssistantBubble(el)) return el;
          break;
        }
        el = el.parentElement;
      }
    }
    return null;
  }

  let turnCounter = 0;
  function turnId(el) {
    if (!el._ailiaTurnId) el._ailiaTurnId = `turn-${++turnCounter}-${Date.now()}`;
    return el._ailiaTurnId;
  }

  // Extract speakable text, excluding code blocks.
  function extractText(el) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        let p = node.parentElement;
        while (p && p !== el) {
          const tag = p.tagName;
          if (tag === 'PRE' || tag === 'CODE') return NodeFilter.FILTER_REJECT;
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const parts = [];
    let n;
    while ((n = walker.nextNode())) {
      const t = n.textContent.trim();
      if (t) parts.push(t);
    }
    return sanitizeText(parts.join(' ').replace(/\s+/g, ' '));
  }

  function forward(type, payload) {
    chrome.runtime.sendMessage({ source: 'ailia-tts-content', type, ...payload });
  }

  // --- Turn tracking with text delta streaming ---------------------------
  let currentTurnId = null;
  let sentText = '';  // text already forwarded for current turn
  let settleTimer = null;
  let streamingBubble = null;

  function onStreamingText(turnEl) {
    const id = turnId(turnEl);
    const text = extractText(turnEl);
    if (!text) return;

    if (id !== currentTurnId) {
      if (currentTurnId !== null) {
        log('new turn, ending previous:', currentTurnId);
        forward('turn_end', { turnId: currentTurnId });
      }
      log('turn started:', id);
      forward('turn_start', { turnId: id });
      currentTurnId = id;
      sentText = '';
    }

    // Send only the new delta
    if (text.length > sentText.length && text.startsWith(sentText)) {
      const delta = text.slice(sentText.length);
      if (delta.trim()) {
        forward('text_delta', { turnId: id, text: delta });
        sentText = text;
      }
    } else if (!text.startsWith(sentText)) {
      // Text was edited/rewound — resync by sending full text as delta
      // (server should handle this as a reset for the turn)
      log('text resync for turn:', id);
      forward('text_delta', { turnId: id, text: text, resync: true });
      sentText = text;
    }
  }

  function onTurnDone(turnEl) {
    const id = turnId(turnEl);
    if (id !== currentTurnId) return;
    // Flush any remaining text
    const text = extractText(turnEl);
    if (text.length > sentText.length && text.startsWith(sentText)) {
      const delta = text.slice(sentText.length);
      if (delta.trim()) {
        forward('text_delta', { turnId: id, text: delta });
      }
    }
    log('turn ended:', id);
    forward('turn_end', { turnId: id });
    currentTurnId = null;
    sentText = '';
    streamingBubble = null;
  }

  function scan() {
    const bubble = findStreamingBubble();

    if (bubble) {
      if (streamingBubble !== bubble) {
        if (streamingBubble && currentTurnId !== null) {
          onTurnDone(streamingBubble);
        }
        streamingBubble = bubble;
        log('streaming started for bubble');
      }
      clearTimeout(settleTimer);
      onStreamingText(bubble);
      settleTimer = setTimeout(() => {
        const stillStreaming = bubble.querySelector('[data-hatch-markdown-streaming="true"]');
        if (!stillStreaming && streamingBubble === bubble) {
          log('streaming ended, finalizing');
          onTurnDone(bubble);
        }
      }, 1500);
    } else {
      if (streamingBubble && currentTurnId !== null) {
        log('streaming bubble gone, finalizing');
        clearTimeout(settleTimer);
        onTurnDone(streamingBubble);
      }
    }
  }

  const observer = new MutationObserver(() => scan());
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['data-hatch-markdown-streaming'],
  });

  window.addEventListener('beforeunload', () => {
    if (currentTurnId !== null) forward('cancel', { turnId: currentTurnId });
  });

  log('content script ready — streaming text deltas (no chunking)');
})();
