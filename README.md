# Hermes Voice Web

Hermes Voice Web is a small self-hosted web console for a Raspberry Pi running Hermes. It provides text chat, browser or backend speech-to-text, spoken replies, session history, and health diagnostics from a single FastAPI app.

## Features

- Chinese-first chat UI with persistent sessions.
- Default assistant identity is `生活助手小七`, tuned as Soul's student-focused life and study assistant.
- Text chat with optional TTS playback.
- Real-time weather lookup for chat and voice requests using Open-Meteo.
- Daily briefing for "今日简报 / 早安 / 今天怎么样" with weather plus Raspberry Pi service status.
- Local reminders and todos for "提醒我..." / "我的提醒", stored on the Raspberry Pi and included in daily briefings.
- Two voice input options: browser microphone recording and Raspberry Pi microphone recording.
- Automatic half-duplex call mode with explicit input and output routing: browser microphone or XiaoQi's Raspberry Pi microphone, then browser speaker or XiaoQi's Raspberry Pi speaker.
- Browser voice input records locally and prefers backend STT when it is ready; browser speech recognition remains available for endpointing and transcript fallback.
- Raspberry Pi voice input records on the server with `arecord`, then uses backend STT.
- In Raspberry Pi call mode, DeepSeek replies stream into punctuation-aware sentence segments: the first sentence can start playing while the rest of a long answer is still generated and synthesised.
- Edge TTS playback from Hermes audio cache.
- Reply playback target toggle: play generated replies in the browser or on the Raspberry Pi speaker.
- Health panel for Hermes CLI, model provider, STT, TTS, and session storage.
- Safe backend behavior: long STT and Hermes calls run off the event loop with timeouts.
- Faster local STT path: the web process can keep the local faster-whisper model loaded instead of reloading it for every recording.
- No database dependency; sessions and reminders are stored in JSON under `~/.hermes/voice-web/`.

## Requirements

- Python 3.11+
- Hermes agent installed at `~/.hermes/hermes-agent`
- Hermes CLI available from the agent venv or `PATH`
- FastAPI runtime dependencies from `requirements.txt`
- For backend STT: a configured Hermes STT provider, or cached local faster-whisper model files
- For Raspberry Pi recording: ALSA `arecord` and a working capture device such as a USB microphone. The service auto-detects capture hardware from `arecord -l`.

Install only the web runtime:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

On the Raspberry Pi, the app normally uses Hermes' own venv:

```bash
HERMES_HOME=/home/pi/.hermes \
HERMES_AGENT=/home/pi/.hermes/hermes-agent \
scripts/run-voice-web.sh
```

With HTTPS certs in `certs/key.pem` and `certs/cert.pem`, the script enables TLS automatically. The current trusted LAN deployment is reachable at:

```text
https://pi5.local:8787/
```

The current-IP fallback is `https://192.168.5.12:8787/`. HTTPS provides transport encryption and the browser secure context required for microphone access; it does not add application authentication, so this service must remain limited to a trusted LAN and must not be exposed to the public internet.

Install as a user systemd service on the Pi:

```bash
cd /home/pi/.hermes/voice-web
scripts/install-user-service.sh
```

## Configuration

Environment variables:

- `HERMES_HOME`: Hermes home directory, default `~/.hermes`.
- `HERMES_AGENT`: Hermes agent checkout, default `$HERMES_HOME/hermes-agent`.
- `VOICE_WEB_HOST`: bind host, default `0.0.0.0`.
- `VOICE_WEB_PORT`: bind port, default `8787`.
- `VOICE_WEB_HERMES_TIMEOUT`: Hermes chat timeout in seconds, default `300`.
- `VOICE_WEB_STT_TIMEOUT`: backend STT timeout in seconds, default `180`.
- `VOICE_WEB_INLINE_LOCAL_STT`: use an in-process cached faster-whisper model for `stt.provider: local`, default `true`.
- `VOICE_WEB_STT_SUBPROCESS_FALLBACK`: fall back to the Hermes transcription subprocess if inline local STT cannot load, default `true`.
- `VOICE_WEB_PRELOAD_LOCAL_STT`: start loading the local faster-whisper model in the background when the server starts, default `true`.
- `VOICE_WEB_MAX_MESSAGE_CHARS`: maximum user message length, default `12000`.
- `VOICE_WEB_MAX_HISTORY_MESSAGES`: prompt history window, default `18`.
- `VOICE_WEB_MAX_SESSIONS`: retained sessions, default `100`.
- `VOICE_WEB_MAX_REMINDERS`: retained local reminders, default `200`.
- `VOICE_WEB_DEFAULT_WEATHER_LOCATION`: optional default city for weather questions that do not mention a city. When unset, the assistant asks for a city.
- `VOICE_WEB_WEATHER_TIMEOUT`: Open-Meteo request timeout in seconds, default `8`.
- `VOICE_WEB_ASSISTANT_NAME`: assistant persona name, default `生活助手小七`.
- `VOICE_WEB_USER_NAME`: primary user name, default `Soul`.
- `VOICE_WEB_USER_PROFILE`: primary user profile injected into prompts, default `学生，需要你帮助完成学习上的事情，也可以协助日常安排。`.
- `VOICE_WEB_MIN_LOCAL_STT_MODEL_BYTES`: minimum local STT `model.bin` size treated as ready.
- `VOICE_WEB_PI_RECORD_DEVICE`: optional manual ALSA capture override. When unset, the backend auto-discovers real capture hardware from `arecord -l`.
- `VOICE_WEB_PI_RECORD_RATE`: WAV recording sample rate, default `16000`.
- `VOICE_WEB_PI_RECORD_CHANNELS`: WAV recording channels, default `1`.
- `VOICE_WEB_PI_VAD_ENABLED`: enable Raspberry Pi microphone silence endpointing, default `true`.
- `VOICE_WEB_PI_VAD_SILENCE_SECONDS`: silence after detected speech that closes the turn, default `1.0`.
- `VOICE_WEB_PI_VAD_NO_SPEECH_SECONDS`: maximum wait for speech before closing an empty turn, default `5.0`.
- `VOICE_WEB_PI_VAD_MIN_SPEECH_SECONDS`: sustained voice activity required to mark speech, default `0.3` (long enough to reject short USB/room transients without losing normal short phrases).
- `VOICE_WEB_PI_VAD_MIN_RMS`: minimum normalized RMS trigger for Pi voice activity, default `0.0052` (calibrated for XiaoQi's low-gain USB microphone).
- `VOICE_WEB_PI_VAD_NOISE_MULTIPLIER`: adaptive speech trigger relative to the measured noise floor, default `1.6`.
- `VOICE_WEB_PI_VAD_RELEASE_MULTIPLIER`: post-speech release threshold relative to the measured noise floor, default `1.35`.
- `VOICE_WEB_STREAMING_VOICE_ENABLED`: enable first-sentence streaming for Raspberry Pi call turns when DeepSeek is active, default `true`.
- `VOICE_WEB_STREAMING_FIRST_SEGMENT_CHARS`: maximum first segment length when no earlier sentence boundary is available, default `48`.
- `VOICE_WEB_STREAMING_SEGMENT_CHARS`: maximum later segment length when no earlier sentence boundary is available, default `88`.
- `VOICE_WEB_PI_PLAYBACK_COMMAND`: optional local audio playback command for Raspberry Pi speaker output. When unset, the backend tries common players such as `ffplay`, `mpv`, `cvlc`, `play`, `paplay`, `aplay`, and `afplay`.
- `VOICE_WEB_PI_PLAYBACK_DEVICE`: optional manual ALSA playback override. When unset, the backend auto-discovers playback hardware from `aplay -l`, preferring non-HDMI devices first and falling back to HDMI.
- `VOICE_WEB_PI_PLAYBACK_TIMEOUT`: maximum seconds a half-duplex call waits for Raspberry Pi speaker playback to finish, default `180`.

## Automatic Call Mode

The call mode is deliberately half-duplex for the first usable version. The selected route is preserved when a call starts; starting a call must never silently reset input or output to the browser.

1. `listening`: the selected input opens. Browser input uses local voice activity detection; Raspberry Pi input starts a server-side `arecord` job with adaptive energy endpointing and a bounded 5–8 second maximum turn.
2. Browser input closes after roughly 1.1 seconds of silence. Raspberry Pi input closes after 1 second of silence following detected speech, or after its maximum bound; an empty Pi turn closes after 5 seconds by default. The turn then enters `processing`.
3. Browser-input turns continue through the existing Hermes `/api/respond` or `/api/converse` path. Raspberry Pi-input turns request streaming: when DeepSeek is active, the backend generates punctuation-aware sentence segments and starts TTS as soon as the first segment is ready. If direct streaming is unavailable, the turn falls back to the existing full-answer Hermes path.
4. `speaking`: the selected output plays ready segments in order while later segments are still generated. Long answers are not truncated; the complete answer and all segment metadata are saved after generation. The microphone remains closed, and Raspberry Pi playback waits for each segment to finish before the next listening turn begins.
5. When playback ends, the controller returns to `listening` automatically.

No-speech turns restart listening without consuming the error budget. Three consecutive network, model, transcription, or playback failures end the call; microphone permission failures end it immediately. `call-mode.js` owns this state machine and exposes a small dependency-injected interface, while `index.html` provides the browser microphone, Hermes API, playback, and UI adapters.

Browser microphone access requires a secure context. The Raspberry Pi now serves the phone-facing application through dedicated LAN HTTPS at:

```text
https://pi5.local:8787/
```

The current-IP fallback is `https://192.168.5.12:8787/`. A phone must first install and fully trust `docs/trusted-https/xiaoqi-local-ca.cer`; do not bypass a browser certificate warning. Full phone setup, certificate fingerprints, expiry, verification, and one-command rollback are documented in `docs/TRUSTED_HTTPS.md`.

The former `http://localhost` SSH-tunnel workaround is no longer the primary path: port `8787` now speaks TLS and the certificate identifies `pi5.local`/the LAN IP, not `localhost`. Use the direct trusted LAN URL for phone and tablet access.

This version does not include a wake word, full-duplex echo cancellation, or barge-in while XiaoQi is speaking. Those are later-stage latency and audio-pipeline improvements, not hidden claims of the basic mode.

To inspect Pi capture devices:

```bash
arecord -l
arecord -L
```

If auto-discovery is not desired, set a capture device explicitly:

```bash
VOICE_WEB_PI_RECORD_DEVICE=plughw:CARD=Device,DEV=0
```

## Local STT Cache

If Hermes uses `stt.provider: local`, the web health endpoint marks STT ready only when a usable faster-whisper `model.bin` exists under the Hugging Face cache. The web app keeps the model in memory after it loads, so the first transcription after restart is still the slowest, while later recordings avoid the repeated model-load cost. In restricted networks, download through a reachable mirror first, for example:

```bash
HF_ENDPOINT=https://hf-mirror.com \
HF_HUB_DISABLE_XET=1 \
/home/pi/.hermes/hermes-agent/venv/bin/python -c 'from huggingface_hub import snapshot_download; print(snapshot_download("Systran/faster-whisper-base"))'
```

If `snapshot_download` stalls on large Xet files, use a resumable or range-capable downloader and place `model.bin` into the same Hugging Face cache snapshot.

## API

- `GET /health`: runtime and capability diagnostics.
- `GET /api/sessions`: list session summaries.
- `POST /api/sessions`: create a session.
- `GET /api/sessions/{id}`: load a session.
- `PATCH /api/sessions/{id}`: rename a session.
- `DELETE /api/sessions/{id}`: delete a session.
- `GET /api/reminders`: list open reminders. Add `?include_done=true` to include completed items.
- `POST /api/reminders`: create a reminder. Body: `{ "text": "交作业", "due_text": "明天 09:00" }`.
- `PATCH /api/reminders/{id}`: update or complete a reminder. Body: `{ "done": true }`.
- `DELETE /api/reminders/{id}`: delete a reminder.
- `POST /api/chat`: send text. Body: `{ "session_id": "...", "message": "...", "speak": false }`.
- `POST /api/respond`: submit an already-transcribed voice message.
- `GET /api/weather?location=上海`: query Open-Meteo directly and return the structured weather context used by chat.
- `GET /api/briefing?location=天津`: return the structured daily briefing context used by chat.
- `POST /api/converse`: upload audio for backend STT.
- `POST /api/pi-record`: record audio on the Raspberry Pi with silence endpointing up to the requested maximum duration, transcribe it, and generate a spoken reply. Body: `{ "session_id": "...", "duration": 30 }`.
- `POST /api/pi-record/start`: start a stoppable Raspberry Pi recording job. Body: `{ "session_id": "...", "duration": 30, "stream": true }`; call mode enables streaming while the manual record button leaves it off.
- `POST /api/pi-record/{job_id}/stop`: stop an active Raspberry Pi recording job; the captured audio is then transcribed.
- `GET /api/pi-record/{job_id}`: poll a Raspberry Pi recording job through `recording`, `processing`, `streaming`, and finally `complete`, `cancelled`, or `error`. Ready sentence audio appears incrementally in `segments`.
- `POST /api/pi-playback`: play a generated `/audio/...` file on the server/Raspberry Pi speaker. Body: `{ "audio_url": "/audio/reply.ogg", "wait": false }`. Call mode sends `wait: true` to preserve half-duplex behavior.
- `GET /audio/{path}`: serve generated audio from Hermes audio cache.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
node --test tests/test_call_mode.js tests/test_pi_streaming.js
```

The tests mock Hermes chat/TTS where needed, so they validate the web app without calling external model providers.

To prepare a checksummed deployment bundle locally without contacting or changing the Raspberry Pi:

```bash
scripts/build-deployment-bundle.sh
```

The command writes a timestamped directory, tar archive, and archive checksum under `dist/`. The bundle contains the runtime files, both service scripts, `README.md`, `BUILD-INFO.txt`, and `SHA256SUMS` for offline verification.

## Deployment Checklist

1. Copy `app.css`, `ui-motion.js`, `call-mode.js`, `server.py`, `requirements.txt`, and `scripts/run-voice-web.sh` first. Do not replace `index.html` yet; the running process does not know the new asset routes until restart.
2. Confirm Hermes agent is installed and `HERMES_HOME` / `HERMES_AGENT` point to it.
3. For an existing installation, run `systemctl --user restart hermes-voice-web.service`, then require `systemctl --user is-active hermes-voice-web.service` to return `active`. Do not rely on `enable --now` to restart an already-active service.
4. Copy `index.html` last, then verify `/`, `/app.css`, and `/ui-motion.js` return 200 with the expected MIME types, `Cache-Control: no-store`, and the deployed file hashes.
5. Open `/health` and verify:
   - `ok: true`
   - Hermes CLI path is present
   - `tools.tts_tool: true`
   - STT is ready, or browser STT is available for the target browser
6. Send a text chat request and confirm a saved session.
7. Send "提醒我明天上午九点交作业" and confirm `/api/reminders` shows the new local reminder.
8. Submit `/api/respond` and confirm an audio URL.
9. Submit `/api/converse` when backend STT is expected to work.
10. Confirm `arecord -l` sees a microphone, then use the `智能助手录音` button or `POST /api/pi-record`.
11. Open the app from a secure browser context and verify all four route combinations remain selected after starting: browser/browser, browser/XiaoQi speaker, XiaoQi microphone/browser, and XiaoQi microphone/XiaoQi speaker. Verify browser silence retry, Raspberry Pi bounded-turn capture, half-duplex playback completion, and **结束语音** cleanup separately.

## Current Acceptance Status

The 2026-09-07 local source acceptance covers Pi silence endpointing, DeepSeek streaming, and the cleanup fixes found during review, based on commit `c7f7ec7848a376c5d08a0f4403bdbe4ff57e79a5`. All 63 Python tests and 20 call-mode/page-adapter tests passed, along with compilation, script parsing, and diff hygiene checks. Empty automatic recordings are rejected at recorder EOF; failed streaming turns are stopped and allowed to finish before automatic retry. If cleanup cannot settle within its bounds, the call ends with a clear error. See `docs/ACCEPTANCE.md` for exact tested-file hashes, review closure, and the host dependency-environment caveat.

This is source acceptance for GitHub publication. No deployment, live Pi connection, provider request, or service change was performed. Before the corrective changes, the local runtime matched the archived 2026-09-03 rollout, which recorded calibrated Pi silence endpointing, DeepSeek streaming, and a physical USB microphone/M83 speaker loop. Those physical results are historical and do not establish the Pi's current runtime or acceptance of these local fixes.

If ffmpeg is unavailable or segment concatenation fails, history audio replay uses the first segment; live playback and saved full text/segment metadata remain complete. Full history replay in that failure case remains a known limitation.

The 2026-08-31 trusted-LAN-HTTPS rollout verified the certificate chain, hostname and IP SANs, HTTPS assets, `window.isSecureContext`, microphone permission, and a live fake browser audio track. On 2026-09-01 the phone owner completed the remaining physical-device acceptance with no certificate warning: two consecutive real spoken turns were recognized and answered audibly, and ending voice mode removed the phone's microphone indicator.

On 2026-09-01 the Hermes provider was migrated from Xiaomi MiMo to `zai / glm-5.1` using the GLM China Coding Plan endpoint. A direct Hermes request, `/api/chat`, `/api/respond`, and a synthetic-audio `/api/converse` request succeeded; the latter verified Volcengine STT -> GLM -> Edge TTS and returned a valid Ogg reply. Diagnostic sessions and generated audio were removed. The complete application release from source commit `47f337d0b5ab40376b0474d73af72a8c2490c5e0` was checksummed and deployed that day. These dated GLM and phone-acceptance records predate the September 3 Pi streaming work.

See `docs/ACCEPTANCE.md` for the latest concrete checklist and command evidence.
