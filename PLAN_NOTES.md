# TTS Performance Investigation Notes

## Step 1: CosyVoice API Investigation

### Question
Does `inference_zero_shot(text, prompt_text, prompt_wav, stream=True)` re-process
prompt.wav on every call, or is there a way to pre-process the prompt once?

### Investigation Method
- Clone official CosyVoice repo (shallow) to examine API
- Look at AutoModel.inference_zero_shot implementation
- Check for lower-level APIs that accept pre-processed prompt features

### Status: In progress

### Findings (2026-10-04)

**CONFIRMED: Prompt WAV is re-processed on every call.**

`cosyvoice/cli/cosyvoice.py:91-101` - `inference_zero_shot`:
```python
for i in tqdm(self.frontend.text_normalize(tts_text, split=True, ...)):
    model_input = self.frontend.frontend_zero_shot(i, prompt_text, prompt_wav, ...)
    for model_output in self.model.tts(**model_input, ...):
```

`cosyvoice/cli/frontend.py:168` - `frontend_zero_shot`:
```python
prompt_text_token, ... = self._extract_text_token(prompt_text)
speech_feat, ... = self._extract_speech_feat(prompt_wav)      # WAV re-read!
speech_token, ... = self._extract_speech_token(prompt_wav)    # WAV re-read!
embedding = self._extract_spk_embedding(prompt_wav)           # WAV re-read!
```

**Every synthesis call re-extracts from prompt.wav:**
1. `_extract_speech_feat` - mel spectrogram features
2. `_extract_speech_token` - discrete speech tokens  
3. `_extract_spk_embedding` - speaker embedding (Resemblyzer/CampPlus)

**Optimization path:**
Pre-compute prompt features once at startup via frontend methods directly,
then for each synthesis only compute tts_text tokens and merge with cached
prompt features, calling `self.model.tts(**model_input)` directly instead
of going through `inference_zero_shot`.

This bypasses the official high-level API but uses the same lower-level
components. Risk: depends on internal API stability.

### Status: Investigation complete. Proceeding to implementation.
