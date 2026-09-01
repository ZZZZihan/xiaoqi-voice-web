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
- Automatic half-duplex call mode: click once, speak naturally, pause to submit, hear the reply, and continue without clicking again.
- Browser voice input records locally and prefers backend STT when it is ready; browser speech recognition remains available for endpointing and transcript fallback.
- Raspberry Pi voice input records on the server with `arecord`, then uses backend STT.
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
- `VOICE_WEB_PI_PLAYBACK_COMMAND`: optional local audio playback command for Raspberry Pi speaker output. When unset, the backend tries common players such as `ffplay`, `mpv`, `cvlc`, `play`, `paplay`, `aplay`, and `afplay`.
- `VOICE_WEB_PI_PLAYBACK_DEVICE`: optional manual ALSA playback override. When unset, the backend auto-discovers playback hardware from `aplay -l`, preferring non-HDMI devices first and falling back to HDMI.

## Automatic Call Mode

The browser call mode is deliberately half-duplex for the first usable version:

1. `listening`: the browser microphone is open and local voice activity is measured.
2. After roughly 1.1 seconds of silence, the microphone closes and the turn enters `processing`.
3. The existing Hermes `/api/respond` or `/api/converse` path generates the answer and TTS audio.
4. `speaking`: the browser plays the whole answer with the microphone closed.
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
- `POST /api/pi-record`: record audio on the Raspberry Pi for a fixed duration, transcribe it, and generate a spoken reply. Body: `{ "session_id": "...", "duration": 30 }`.
- `POST /api/pi-record/start`: start a stoppable Raspberry Pi recording job. Body: `{ "session_id": "...", "duration": 30 }`.
- `POST /api/pi-record/{job_id}/stop`: stop an active Raspberry Pi recording job; the captured audio is then transcribed.
- `GET /api/pi-record/{job_id}`: poll a Raspberry Pi recording job until it returns `complete` or `error`.
- `POST /api/pi-playback`: play a generated `/audio/...` file on the server/Raspberry Pi speaker. Body: `{ "audio_url": "/audio/reply.ogg" }`.
- `GET /audio/{path}`: serve generated audio from Hermes audio cache.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
node --test tests/test_call_mode.js
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
11. Open the app from a secure browser context, start continuous voice mode, verify silence causes an automatic retry, and verify **结束语音** releases the microphone and restores the other controls.

## Current Acceptance Status

The Raspberry Pi currently serves the redesigned interface over trusted LAN HTTPS, but the deployed stylesheet is an earlier variant and does not include the latest local responsive fixes. Treat the current working tree as a pending release until its complete runtime file set is committed, bundled, deployed, and reverified together.

The Raspberry Pi 5 deployment at `https://pi5.local:8787/` runs the automatic half-duplex call implementation with runtime files derived from commit `50763c91ebcc26f0565b1c89159ef5297bf7df2f` plus later uncommitted interface assets. The 2026-08-31 trusted-LAN-HTTPS rollout verified the certificate chain, hostname and IP SANs, HTTPS assets, `window.isSecureContext`, microphone permission, and a live fake browser audio track without changing the model provider or secret files. A physical phone still requires explicit root-certificate installation and real microphone permission by its owner.

The complete spoken-answer loop is **not yet accepted** because a controlled Hermes request returned Xiaomi MiMo HTTP 401 `Invalid API Key`. The configured credential is `XIAOMI_API_KEY` in `/home/pi/.hermes/.env`; it must be replaced by the user or provider owner, then the service and spoken loop must be reverified. Historical May hardware evidence does not describe the currently connected devices.

See `docs/ACCEPTANCE.md` for the latest concrete checklist and command evidence.
