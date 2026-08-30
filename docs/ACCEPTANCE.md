# Acceptance Checklist

Date: 2026-05-04
Target: Raspberry Pi at `192.168.0.87`, app path `/home/pi/.hermes/voice-web`, HTTPS port `8787`.

## Objective

Make Hermes Voice Web good enough to stand as an independent developer project: documented, runnable, testable, deployable, verified end to end, and able to offer both browser-side and Raspberry Pi-side recording options.

## Artifact Checklist

- `server.py`: FastAPI backend with health, sessions, text chat, XiaoQi/Soul study-assistant prompt identity, transcript response, audio upload, stoppable Raspberry Pi `arecord` capture jobs, cached in-process local STT, audio serving, Hermes integration, TTS, guarded subprocess STT timeouts, and Pi-side audio playback for generated replies.
- `index.html`: Single-page console with sessions, text composer, browser/Pi playback toggle, separate browser/Pi voice controls, shared stop control, health panel, responsive layout, and audio playback.
- `requirements.txt`: Runtime Python dependencies.
- `requirements-dev.txt`: Test dependencies.
- `scripts/run-voice-web.sh`: Portable run script with Hermes env detection and optional TLS certs.
- `scripts/install-user-service.sh`: User systemd installer for unattended startup.
- `tests/test_server.py`: Regression tests for sessions, chat persistence, prompt identity, TTS audio URLs, Pi playback, Pi recording status/endpoint/stop behavior, inline local STT routing, STT health readiness, and audio path traversal rejection.
- `README.md`: Install, run, deploy, configure, test, and troubleshoot documentation.

## Verification Evidence

- Local compile: `python3 -m py_compile server.py` passed.
- Frontend parse: extracted inline script from `index.html` and parsed it with Node successfully.
- Local tests: `python3 -m pytest -q` passed, `15 passed`.
- Remote compile: `/home/pi/.hermes/hermes-agent/venv/bin/python -m py_compile server.py` passed.
- Remote health: `GET /health` returned `ok: true`.
- Remote Hermes CLI: `/home/pi/.hermes/hermes-agent/venv/bin/hermes`.
- Remote chat provider: `xiaomi / mimo-v2.5-pro`.
- Remote STT: `provider=local`, `ready=true`, cached `model.bin` size `145217532`.
- Remote STT runtime after optimization: `runtime=inline-cache`, `model_loaded=true`, `local_model_path=/home/pi/.cache/huggingface/hub/models--Systran--faster-whisper-base/snapshots/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`.
- Remote TTS: `provider=edge`, `voice=zh-CN-XiaoxiaoNeural`, `ready=true`.
- Remote Pi recording health: `pi_record.available=true`, selected device `plughw:CARD=Device,DEV=0`, `rate=16000`, `channels=1`.
- Remote Pi capture device: `arecord -l` shows `USB PnP Sound Device`, card `Device`, device `0`.
- Remote Pi WAV capture: `arecord -D plughw:CARD=Device,DEV=0 -f S16_LE -r 16000 -c 1 -d 2` produced a `64044` byte RIFF/WAVE file.
- Pi recording stop API: `POST /api/pi-record/start` starts a job, `POST /api/pi-record/{job_id}/stop` signals the active `arecord` process, honors stop requests that arrive before `arecord` is attached to the job, and `GET /api/pi-record/{job_id}` exposes recording/processing/complete/error states for the frontend stop button.
- Remote Pi stop verification: a 30 second job was stopped after 2 seconds; status moved from `recording` to `processing`, `stop_requested=true`, `elapsed=2`, and `pgrep -a arecord` returned no active recorder process.
- Text API: `POST /api/chat` returned `OK` and persisted a session.
- Transcript-to-speech API: `POST /api/respond` returned `服务运行正常，随时可以对话。` and generated `/audio/tts_20260504_102520.ogg`.
- Audio serving: `GET /audio/tts_20260504_102520.ogg` returned an Ogg Opus audio file.
- Upload conversation API: `POST /api/converse` with the generated Ogg file returned HTTP 200, transcript `服務運行正常,隨時可以對話。`, reply `好的，收到。服务正常就好，有什么需要随时说。`, and generated `/audio/tts_20260504_102836.ogg`.
- Upload conversation API after inline-cache optimization: `POST /api/converse` with `/home/pi/.hermes/audio_cache/tts_20260504_102520.ogg` returned HTTP 200 in `13.82s`, transcript `服務運行正常,隨時可以對話。`, and generated `/audio/tts_20260504_151959.ogg`.
- Pi recording API: `POST /api/pi-record` performed a 2 second server-side recording and reached STT; because no one spoke into the microphone during the check, it returned controlled HTTP 400 `No speech was transcribed`.
- Remote process check: exactly one `uvicorn server:app --host 0.0.0.0 --port 8787` process is listening.

## Residual Risks

- Backend local STT is CPU-bound and still slow on the Raspberry Pi, especially the first transcription after restart. The web process now keeps the local faster-whisper model loaded for later recordings, with subprocess fallback retained for compatibility.
- Pi-side recording cannot be fully validated through chat/TTS without real speech at the microphone; the deployed endpoint was validated through recording, STT invocation, and controlled empty-speech handling.
- This repository directory is not currently a git repository, so commit hygiene and history-level review cannot be performed here.
- Remote pytest is not installed in the Hermes venv; full tests were run locally, while the remote runtime was validated by compile and API checks.
