// Ailia TTS — offscreen document for audio playback (MV3 requirement)
// Buffers chunks by (turnId, seq) and plays in sequence order.
// Supports stop (on cancel / new turn).

// Per-turn buffers: turnId -> { expectedSeq, buffer: Map(seq -> item), playing }
const turns = new Map();
let currentAudio = null;
let activeTurnId = null;

// Notify background that we're ready to receive audio.
chrome.runtime.sendMessage({ source: 'ailia-tts-offscreen', type: 'offscreenReady' });
console.log('[ailia-tts] offscreen audio ready, sent ready signal');

function b64ToBlob(b64, mime) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

function getTurn(turnId) {
  if (!turns.has(turnId)) {
    turns.set(turnId, { expectedSeq: 0, buffer: new Map(), playing: false });
  }
  return turns.get(turnId);
}

async function pumpTurn(turnId) {
  const turn = turns.get(turnId);
  if (!turn || turn.playing) return;
  // Only play if this is the active turn (or no active turn)
  if (activeTurnId && activeTurnId !== turnId) return;

  const item = turn.buffer.get(turn.expectedSeq);
  if (!item) return; // wait for next seq

  turn.buffer.delete(turn.expectedSeq);
  turn.expectedSeq++;
  turn.playing = true;
  activeTurnId = turnId;

  currentAudio = new Audio();
  const mime = 'audio/wav';
  currentAudio.src = URL.createObjectURL(b64ToBlob(item.audio, mime));

  currentAudio.onended = () => {
    URL.revokeObjectURL(currentAudio.src);
    currentAudio = null;
    turn.playing = false;
    // Clean up finished turn
    if (turn.buffer.size === 0 && turn.expectedSeq > 0) {
      // Keep turn for a bit in case late chunks arrive
    }
    if (activeTurnId === turnId) activeTurnId = null;
    // Try next in this turn, or next turn
    pumpTurn(turnId);
    for (const [tid] of turns) {
      if (tid !== turnId) pumpTurn(tid);
    }
  };
  currentAudio.onerror = () => {
    console.error('[ailia-tts][audio] playback error for turn:', turnId, 'seq:', item.seq);
    currentAudio = null;
    turn.playing = false;
    if (activeTurnId === turnId) activeTurnId = null;
    pumpTurn(turnId);
  };
  try {
    console.log(`[ailia-tts][audio] playing turn ${turnId} seq ${item.seq}`);
    await currentAudio.play();
  } catch (e) {
    console.error('[ailia-tts][audio] play() failed:', e);
    turn.playing = false;
    if (activeTurnId === turnId) activeTurnId = null;
    pumpTurn(turnId);
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.source !== 'ailia-tts-bg') return;

  if (msg.type === 'playAudio') {
    const seq = msg.seq ?? 0;
    console.log(`[ailia-tts][audio] received turn ${msg.turnId} seq ${seq} (${(msg.audio || '').length} chars)`);
    const turn = getTurn(msg.turnId);
    // Dedupe
    if (seq < turn.expectedSeq || turn.buffer.has(seq)) {
      console.log(`[ailia-tts][audio] duplicate/old seq ${seq}, skipping`);
      return;
    }
    turn.buffer.set(seq, { audio: msg.audio, format: msg.format, seq });
    // Bound buffer
    if (turn.buffer.size > 30) {
      const oldest = Math.min(...turn.buffer.keys());
      turn.buffer.delete(oldest);
    }
    pumpTurn(msg.turnId);
  }

  if (msg.type === 'stopAudio') {
    console.log('[ailia-tts][audio] stop requested for turn:', msg.turnId);
    turns.delete(msg.turnId);
    if (activeTurnId === msg.turnId && currentAudio) {
      currentAudio.pause();
      URL.revokeObjectURL(currentAudio.src);
      currentAudio = null;
      activeTurnId = null;
    }
    // Try next turn
    for (const [tid] of turns) pumpTurn(tid);
  }
});

console.log('[ailia-tts] offscreen audio ready, sent ready signal');
