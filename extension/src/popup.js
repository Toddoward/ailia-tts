// Ailia TTS — popup settings logic (v0.2.6 localhost mode)
const $ = (id) => document.getElementById(id);
const DEFAULT_URL = 'ws://127.0.0.1:18766';

async function load() {
  const s = await chrome.storage.sync.get({
    ttsServerUrl: DEFAULT_URL,
    voice: 'ailia',
    enabled: true,
  });
  $('ttsServerUrl').value = s.ttsServerUrl;
  $('voice').value = s.voice;
  $('enabled').checked = s.enabled;
  updateStatus(s);
}

function updateStatus(s) {
  const el = $('status');
  if (!s.enabled) {
    el.textContent = 'TTS가 꺼져 있습니다.';
    el.className = 'status';
  } else if (s.ttsServerUrl) {
    el.textContent = '✅ 로컬 서버 모드: ' + s.ttsServerUrl;
    el.className = 'status ok';
  } else {
    el.textContent = '⚠️ 서버 URL을 입력하세요.';
    el.className = 'status';
  }
}

$('save').addEventListener('click', async () => {
  const s = {
    ttsServerUrl: $('ttsServerUrl').value.trim().replace(/\/$/, '') || DEFAULT_URL,
    voice: $('voice').value,
    enabled: $('enabled').checked,
  };
  await chrome.storage.sync.set(s);
  updateStatus(s);
  const prev = $('status').textContent;
  $('status').textContent = '💾 저장됨. ' + prev;
});

$('test').addEventListener('click', async () => {
  const url = $('ttsServerUrl').value.trim() || DEFAULT_URL;
  const el = $('status');
  el.textContent = '🔄 연결 테스트 중...';
  el.className = 'status';
  try {
    const ws = new WebSocket(url);
    const timeout = setTimeout(() => {
      try { ws.close(); } catch (_) { }
      el.textContent = '❌ 연결 실패 (시간 초과). 서버가 실행 중인지 확인하세요.';
      el.className = 'status err';
    }, 5000);
    ws.onopen = () => {
      clearTimeout(timeout);
      el.textContent = '✅ 서버 연결 성공!';
      el.className = 'status ok';
      ws.close();
    };
    ws.onerror = () => {
      clearTimeout(timeout);
      el.textContent = '❌ 연결 실패. 서버가 실행 중인지 확인하세요.';
      el.className = 'status err';
    };
  } catch (e) {
    el.textContent = '❌ 오류: ' + e.message;
    el.className = 'status err';
  }
});

$('enabled').addEventListener('change', async () => {
  const s = await chrome.storage.sync.get({ ttsServerUrl: DEFAULT_URL, voice: 'ailia', enabled: true });
  s.enabled = $('enabled').checked;
  updateStatus(s);
});

// --- Streaming tests -------------------------------------------------------

function showTestStatus(text, ok) {
  const el = $('testStatus');
  el.style.display = 'block';
  el.textContent = text;
  el.className = 'status ' + (ok === true ? 'ok' : ok === false ? 'err' : '');
}

$('testAudio').addEventListener('click', async () => {
  const text = $('testText').value.trim();
  showTestStatus('🔊 서버에 오디오 생성 요청 중...');
  try {
    const res = await chrome.runtime.sendMessage({
      source: 'ailia-tts-popup',
      type: 'test_audio',
      text: text || undefined,
    });
    if (res && res.ok) {
      showTestStatus('🔊 서버가 합성 중... 잠시 후 재생됩니다.', null);
    } else {
      showTestStatus('❌ 요청 실패: ' + ((res && res.error) || 'unknown'), false);
    }
  } catch (e) {
    showTestStatus('❌ 오류: ' + e.message, false);
  }
});

$('testText').addEventListener('click', async () => {
  const text = $('testText').value.trim() || '안녕하세요, 주인님! 에일리아 음성 테스트 중이에요.';
  showTestStatus('📝 텍스트 스트리밍 전송 중... (서버 로그 확인)');
  try {
    const res = await chrome.runtime.sendMessage({
      source: 'ailia-tts-popup',
      type: 'test_text',
      text,
    });
    if (res && res.ok) {
      showTestStatus('📝 전송 완료! 서버 로그에서 수신을 확인하세요.', true);
    } else {
      showTestStatus('❌ 요청 실패: ' + ((res && res.error) || 'unknown'), false);
    }
  } catch (e) {
    showTestStatus('❌ 오류: ' + e.message, false);
  }
});

load();
