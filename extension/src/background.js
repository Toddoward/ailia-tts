// Ailia TTS v3 - Background Service Worker
// Routes messages between content script, popup, and offscreen document.
const VERSION = '0.2.6';
console.log(`[ailia-tts] background v${VERSION}`);

let creatingOffscreen = null;

async function ensureOffscreen() {
  if (creatingOffscreen) return creatingOffscreen;
  creatingOffscreen = (async () => {
    const exists = await chrome.offscreen.hasDocument();
    if (!exists) {
      await chrome.offscreen.createDocument({
        url: 'src/offscreen.html',
        reasons: ['AUDIO_PLAYBACK', 'WEBSOCKET'],
        justification: 'TTS audio playback and WebSocket connection',
      });
    }
    creatingOffscreen = null;
  })();
  return creatingOffscreen;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Route everything to offscreen
  ensureOffscreen().then(() => {
    chrome.runtime.sendMessage({ ...msg, _routed: true }).catch(() => {});
  });
  return false;
});

// Keep service worker alive for offscreen
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === 'keepalive') {
    port.onDisconnect.addListener(() => {});
  }
});

self.addEventListener('install', () => self.skipWaiting());
